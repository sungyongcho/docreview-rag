# M4.2 Tutorial 5 — Budget guard, trace conversion, and safe persistence

The observability types are ready. Now build the three files that fill and defend them. Tutorial 4 defined the models and left three seams open: `StepTrace` has no producer, nothing decides when a run must stop, and `RunReport` has no path into the database.

Each open seam is a concrete failure in tutorial 8's runner. Without the guard, a run that keeps spending has no ceiling — the budget fields exist but nothing reads them. Without the trace adapter, the mapping from provider result to trace has to live in code that knows both types: either `app/observability` starts importing `app.llm`, or every caller re-implements the field mapping by hand. Without redaction, an API key that slipped into a prompt is stored in plaintext the moment the report is persisted.

The invariant this document builds toward: every run ends as a `RunReport`, and no unredacted secret ever exists inside a `Run` or `Trace` instance — not even transiently.

**Prerequisite:** `observability/types.py` and `cost.py` from tutorial 4 are written. Their tests run at the end of this document.

### Reaching the limit is already exceeding it

The budget guard uses `>=` rather than `>`. Landing **exactly on** the limit still blocks the next node.

The reason is the same as M4.1's `_repair_budget_failure`. The guard judges "is there room to run the next node," not "how much has been spent." Filling the limit exactly leaves zero room.

The failure `>` would allow is concrete: a node entered with exactly zero remaining tokens still issues its request, and that request can only overrun the limit — the overrun is guaranteed, and it is already paid for by the time any later check looks. `>=` refuses entry instead. This guard is prevention; a post-hoc check would be accounting.

There is one side effect. **A budget of 0 becomes a valid configuration.** It refuses from the first node deterministically, so "what happens with a zero budget" is not undefined behavior.

### Traces are received through protocols

`step_trace_from_provider_result` does not import `ProviderResult`. Two `Protocol` declarations describe only the shape it needs.

The point is to keep `app/observability` from depending on `app/llm`. Observability has to attach to any provider boundary — a different LLM layer later reuses this file unchanged.

The claim is stronger than one function's import list, and it is checkable in one command from the repo root:

```bash
grep -rn "app.llm" app/observability/
```

It prints nothing. Not just this one function but the whole `app/observability` package carries no reference to `app.llm`. The dependency flows one way, and this document's tests never import the provider layer either.

### A key inside a trace ends up in the database

`llm_output` is the raw string the model produced. If an API key slipped into the prompt, or the model echoed a header back, **that key travels in the trace into the database.**

So redaction happens immediately before persistence. Not in logging but at the **storage boundary** — deleting after storage is already too late.

Why not a logging filter, the usual answer? Because a filter guards only the code paths that log through it: the database write is a different path, and every future producer of traces would have to remember to install the filter. The storage boundary is a chokepoint — every persisted byte passes through `report_to_records`, so one seam covers every producer, present and future.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `pre_node_budget_guard` | **Implement** the decision rule yourself | How `>=` makes a zero budget valid |
| The two `Protocol`s | **Review the design decision** | Accepting a type without inverting the dependency |
| `step_trace_from_provider_result` | **Write the field mapping** | Where a provider result becomes a trace |
| `redact_sensitive_text` | **Implement** the redaction rules yourself | Removing credentials without erasing ordinary text |
| `persist_run_report` | **Inspect call order** | Why redaction must precede storage |

### 1. How `>=` makes a zero budget valid

#### Create `app/observability/budget.py` — module header

**Learning action — define the structure:** note that this file holds exactly one function.

```python
"""The single cumulative budget guard used before workflow node entry."""

from __future__ import annotations

from typing import Literal

from app.observability.types import (
    Budget,
    RunReport,
    StepTrace,
    WorkflowNode,
    build_run_report,
    validate_elapsed_seconds,
)

BudgetResource = Literal["iterations", "input_tokens", "output_tokens", "wall_clock_s"]

```

#### Complete `app/observability/budget.py` — the budget guard

**Learning action — implement the decision rule:** implement the structure of building `observed` and `limits` and comparing them yourself.

<!-- src: app/observability/budget.py::pre_node_budget_guard -->
```python
def pre_node_budget_guard(
    *,
    run_id: str,
    node: WorkflowNode,
    budget: Budget,
    elapsed_seconds: float,
    system_prompt: str,
    node_path: tuple[WorkflowNode, ...] | list[WorkflowNode],
    steps: tuple[StepTrace, ...] | list[StepTrace],
) -> RunReport | None:
    """Return a structured refusal when any cumulative hard limit is exhausted.

    This is the only budget-enforcement point: call it immediately before a node.
    Equality blocks entry because no capacity remains, which also makes a zero budget
    a valid configuration that deterministically refuses the first node.
    """
    elapsed = validate_elapsed_seconds(elapsed_seconds)
    trace_values = tuple(steps)
    observed: dict[BudgetResource, int | float] = {
        "iterations": len(node_path),
        "input_tokens": sum(trace.input_tokens for trace in trace_values),
        "output_tokens": sum(trace.output_tokens for trace in trace_values),
        "wall_clock_s": elapsed,
    }
    limits: dict[BudgetResource, int | float] = {
        "iterations": budget.max_iterations,
        "input_tokens": budget.max_input_tokens,
        "output_tokens": budget.max_output_tokens,
        "wall_clock_s": budget.max_wall_clock_s,
    }

    exhausted: BudgetResource | None = next(
        (resource for resource in limits if observed[resource] >= limits[resource]),
        None,
    )
    if exhausted is None:
        return None

    return build_run_report(
        run_id=run_id,
        status="budget_exceeded",
        total_time_seconds=elapsed,
        system_prompt=system_prompt,
        node_path=node_path,
        steps=trace_values,
        report={
            "reason": {
                "code": "budget_exceeded",
                "resource": exhausted,
                "limit": limits[exhausted],
                "observed": observed[exhausted],
                "blocked_node": node,
            }
        },
    )
```

**What to look for in the code**

- `observed` and `limits` are two dictionaries with the same keys, but the runtime protection is **one-directional**: the comprehension iterates `limits` and indexes `observed`, so a resource added to `limits` alone raises `KeyError` loudly, while one added to `observed` alone is silently never compared. What actually keeps the two aligned is the `BudgetResource` Literal — a misspelled or unknown key fails the type check before the code ever runs.
- `next((... for resource in limits if ...), None)` finds the **first** exhausted resource. It does not collect them all because only one goes into the report.
- `>=` makes a zero budget a valid configuration. The first node is refused deterministically.
- The return type is `RunReport | None`. Being a value rather than an exception lets a caller fall into the terminal path naturally with `if report:`.

> **Concept — Dictionary order is the precedence rule**
>
> A Python dict iterates in insertion order, so the generator expression checks resources in exactly the order the limits literal writes them: iterations, then input tokens, then output tokens, then wall clock. When several resources are exhausted at once, the report names the first in that order — the zero-budget test exhausts all four simultaneously and always reads back the iterations reason. Reordering the literal would change what stored reports say. The order is observable behavior encoded in a dict literal, not a formatting accident.

Why return a report rather than raise a typed exception? Because a blocked run is not an error to recover from — it is one of the run's normal endings, and it must carry the same complete shape as every other ending. An exception would force each caller to catch it and rebuild that report; returning `RunReport | None` makes "every terminal state is a `RunReport`" structural rather than a convention.

The report the guard returns is terminal, not advisory: the caller returns it as the run's final report and the blocked node never executes — tutorial 8 wires every node behind exactly this guard-and-return. The refusal also keeps "entered" and "attempted" apart. In `tests/workflow/test_03_observability.py`, blocking entry to `check` after two completed nodes leaves `node_path` at `("retrieve", "grade")`, while the blocked node appears only inside `report["reason"]` as `"blocked_node": "check"` — the path records what ran, the reason records what was refused, and iteration counts stay honest.

### 2. Not inverting the dependency

#### Create `app/observability/trace.py` — module header

**Learning action — define the structure:** `app.llm` is absent from the import list.

```python
"""Adapters from provider results into strict observability traces."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Protocol

from pydantic import BaseModel

from app.observability.types import StepTrace, WorkflowNode

```

#### Extend `app/observability/trace.py` — structural types

**Learning action — review the design decision:** note how `Protocol` differs from nominal inheritance.

<!-- src: app/observability/trace.py::ProviderMetadataLike,ProviderResultLike -->
```python
class ProviderMetadataLike(Protocol):
    """Minimum trace-ready metadata required from an LLM provider boundary."""

    model_name: str
    api_url: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    llm_output: str
    retries: int


class ProviderResultLike(Protocol):
    """Minimum typed provider result needed to retain a refusal reason."""

    status: str
    metadata: ProviderMetadataLike
    refusal: object | None
```

**What to look for in the code**

- `Protocol` is a **structural** type. `ProviderResult` never declares that it inherits this protocol — matching the shape is enough.
- That is what keeps `app/observability` unaware of `app/llm`. The dependency flows one way.

> **Concept — Structural typing ends at the type checker**
>
> A structural match is verified where the code is type-checked, not where it runs. These two protocols are not declared runtime-checkable, and the conversion function performs no runtime type check on its argument — it simply reads the attributes it declared and lets whatever comes out flow onward. The runtime gate sits one layer down on purpose: the values still have to pass the strict validators on the trace model itself. The protocol keeps the dependency arrow pointing the right way; the model keeps the data honest. Two layers, two different failure times.

The test file demonstrates the structural claim directly: `test_provider_refusal_mapping_keeps_trace_metadata_and_typed_reason` never imports the provider either — it feeds plain `SimpleNamespace` objects, and they satisfy `ProviderResultLike` because only the shape is read.

#### Complete `app/observability/trace.py` — trace conversion

**Learning action — write the field mapping:** match each provider metadata field to its trace field.

<!-- src: app/observability/trace.py::_jsonable_refusal,step_trace_from_provider_result -->
```python
def _jsonable_refusal(refusal: object) -> dict[str, Any]:
    if isinstance(refusal, BaseModel):
        return refusal.model_dump(mode="json")
    if isinstance(refusal, Mapping):
        return dict(refusal)
    return {"message": str(refusal)}


def step_trace_from_provider_result(
    result: ProviderResultLike,
    *,
    step: int,
    node: WorkflowNode,
) -> StepTrace:
    """Map trace-ready provider metadata and typed refusal state without importing it."""
    metadata = result.metadata
    error = None
    if result.status != "ok":
        failure = (
            _jsonable_refusal(result.refusal)
            if result.refusal is not None
            else {"message": "provider returned a non-ok result without refusal details"}
        )
        error = json.dumps(
            {"status": result.status, "refusal": failure},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return StepTrace(
        step=step,
        node=node,
        model_name=metadata.model_name,
        api_url=metadata.api_url,
        input_tokens=metadata.input_tokens,
        output_tokens=metadata.output_tokens,
        request_time_ms=metadata.request_time_ms,
        llm_output=metadata.llm_output,
        retries=metadata.retries,
        error=error,
    )
```

**What to look for in the code**

- `_jsonable_refusal` converts a refusal value into a **JSON-able Python object** — a plain dict — not yet into JSON text. The failure types are Pydantic models and cannot be stored as they are; the serialization to a string happens in the caller's `json.dumps` call.
- That `json.dumps` call passes `sort_keys=True` and `separators=(",", ":")`, so the flattening is canonical: two identical failures produce byte-identical strings. The test pins the exact bytes — `{"refusal":{"errors":["label is required"],"status":"schema_rejected"},"status":"schema_rejected"}` — keys sorted at every depth, no whitespace, which is what lets stored errors be grouped or deduplicated by plain string equality later.
- Both success and failure produce a trace. The `error` field's presence distinguishes them. `error` is born `None` on the success path; on failure it is a flattened JSON **string**, not a structure — a deliberate flattening so the whole refusal fits a single text column. It lands in `Trace.error` in section 4, redacted on the way.

### 3. Removing credentials without erasing ordinary text

#### Create `app/observability/persistence.py` — module header and patterns

**Learning action — define the structure:** note which shape each of the three regexes catches.

```python
"""Secret-safe mapping and transaction-neutral workflow persistence seams."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Trace
from app.observability.types import JsonValue, RunReport
```

<!-- src: app/observability/persistence.py::REDACTED,_SECRET_ASSIGNMENT -->
```python
REDACTED = "[REDACTED]"
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|password|secret|access[_-]?token)\b\s*[:=]\s*)"
    r"([^\s,;]+)"
)
```

**What to look for in the code**

- There are three patterns: the OpenAI key shape, a `Bearer` token, and an **assignment form** like `api_key: ...`. The last catches the widest.
- `_SECRET_ASSIGNMENT` has two capture groups: group 1 is the key name plus separator, group 2 is the value. The replacement `rf"\1{REDACTED}"` writes group 1 back and never references group 2 — the value disappears by omission, and the key name survives. What was redacted has to remain visible in a log.

> **Concept — Capture groups and backreferences**
>
> Parentheses in a regular expression capture the text they match, numbered from 1 in the order of the opening parentheses. In a replacement string, a backreference like `\1` pastes back what group 1 captured, so a substitution can keep part of the match verbatim while dropping the rest. The `(?i)` prefix makes the whole pattern case-insensitive, which is why the assignment vocabulary matches whether a header writes the key name in upper or lower case.

> **Concept — Substitution, not deletion**
>
> Redaction here replaces a secret with a visible marker instead of deleting it. The difference matters when someone reads the stored trace later: with substitution they can tell that something was removed and what kind of thing it was; with deletion, a redacted value and a value that never existed look identical, and an investigation cannot tell "the model leaked a key and we scrubbed it" apart from "no key was ever there". The marker is part of the audit trail.

Why three explicit shapes rather than a general high-entropy detector? Because this system stores long hex strings on purpose: every citation carries a 64-hex `source_sha256`, and redaction walks the very JSON those live in. An entropy heuristic that errs toward redaction would erase our own provenance; one that errs the other way misses keys, and neither failure is visible when it happens. Three closed shapes plus caller-supplied `secret_values` keep the rules auditable — what gets removed is exactly what the patterns say, nothing more.

#### Extend `app/observability/persistence.py` — redaction

**Learning action — implement the redaction rules:** work out why `secret_values` is sorted longest-first.

<!-- src: app/observability/persistence.py::redact_sensitive_text,_sanitize_json -->
```python
def redact_sensitive_text(text: str, *, secret_values: Iterable[str] = ()) -> str:
    """Preserve ordinary text while removing explicit and recognizable credentials."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    secrets: list[str] = []
    for secret in secret_values:
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret_values must contain nonempty strings")
        secrets.append(secret)
    redacted = text
    for secret in sorted(set(secrets), key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTED)
    redacted = _OPENAI_KEY.sub(REDACTED, redacted)
    redacted = _BEARER_TOKEN.sub(rf"\1{REDACTED}", redacted)
    return _SECRET_ASSIGNMENT.sub(rf"\1{REDACTED}", redacted)


def _sanitize_json(value: JsonValue, *, secret_values: tuple[str, ...]) -> JsonValue:
    if isinstance(value, str):
        return redact_sensitive_text(value, secret_values=secret_values)
    if isinstance(value, Mapping):
        return {
            redact_sensitive_text(str(key), secret_values=secret_values): _sanitize_json(
                child,
                secret_values=secret_values,
            )
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_json(child, secret_values=secret_values) for child in value]
    return value
```

**What to look for in the code**

- `sorted(set(secrets), key=len, reverse=True)` substitutes **longer secrets first**. A shorter one replaced first would erase part of a longer secret and leave the remainder.
- `secret_values` is typed `Iterable[str]` and is materialized into a list during validation. An iterable may be a one-shot generator, and the values are needed again for the sorted substitution pass — validating and substituting off the same generator would find it already exhausted.
- `_sanitize_json` redacts dictionary **keys** as well. Sometimes a token appears in a key name.
- The recursion walks the whole nested structure — but note which structure: `StepTrace` has no loose JSON field. The arbitrary-depth value is `RunReport.report`, and `_sanitize_json` exists for exactly that one loosely typed field.

The three patterns and the longest-first rule can be watched rather than believed. From the repo root:

```bash
uv run python -c "
from app.observability.persistence import redact_sensitive_text as r
print(r('send Bearer abc.def-123 now'))
print(r('api_key=sk-test, user=alice'))
print(r('pair abcdef123 abcdef', secret_values=['abcdef', 'abcdef123']))
"
```

```text
send Bearer [REDACTED] now
api_key=[REDACTED], user=alice
pair [REDACTED] [REDACTED]
```

Line by line: the `Bearer` keyword survives and only the token after it is gone; the key name and `user=alice` survive because the assignment vocabulary is closed, while the value is gone; and with both overlapping secrets supplied, longest-first substitution leaves no residue — substituting the shorter first would have left the tail `123` of the longer secret standing.

### 4. Redaction precedes storage

#### Complete `app/observability/persistence.py` — record conversion and storage

**Learning action — inspect call order:** note where `report_to_records` invokes redaction.

<!-- src: app/observability/persistence.py::report_to_records,persist_run_report -->
```python
def report_to_records(
    report: RunReport,
    *,
    secret_values: Iterable[str] = (),
) -> tuple[Run, tuple[Trace, ...]]:
    """Map a strict report to secret-safe ORM records without database I/O."""
    if not isinstance(report, RunReport):
        raise ValueError("report must be a RunReport")
    secrets = tuple(secret_values)
    run = Run(
        run_id=report.run_id,
        status=report.status,
        iterations=report.iterations,
        total_requests=report.total_requests,
        total_input_tokens=report.total_input_tokens,
        total_output_tokens=report.total_output_tokens,
        total_time_seconds=report.total_time_seconds,
        system_prompt=redact_sensitive_text(
            report.system_prompt,
            secret_values=secrets,
        ),
        node_path=list(report.node_path),
        report=_sanitize_json(report.report, secret_values=secrets),
    )
    traces = tuple(
        Trace(
            run_id=report.run_id,
            step=trace.step,
            node=trace.node,
            model_name=trace.model_name,
            api_url=redact_sensitive_text(trace.api_url, secret_values=secrets),
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
            request_time_ms=trace.request_time_ms,
            llm_output=redact_sensitive_text(trace.llm_output, secret_values=secrets),
            retries=trace.retries,
            error=(
                redact_sensitive_text(trace.error, secret_values=secrets)
                if trace.error is not None
                else None
            ),
        )
        for trace in report.steps
    )
    return run, traces


async def persist_run_report(
    session: AsyncSession,
    report: RunReport,
    *,
    secret_values: Iterable[str] = (),
) -> Run:
    """Flush one run and its traces without committing the caller's transaction."""
    run, traces = report_to_records(report, secret_values=secret_values)
    session.add(run)
    session.add_all(traces)
    await session.flush()
    return run
```

**What to look for in the code**

- Redaction happens inside `report_to_records`, **before** the ORM objects are built. There is no moment when an unredacted value sits inside a `Run` or `Trace` instance — which is also why redaction is a transformation applied to constructor arguments rather than a method on the record: a cleanup method can be forgotten, but here the secret-bearing string never exists in the object at any instant.
- The mapping redacts exactly the free-text fields: `system_prompt`, `report`, `api_url`, `llm_output`, and `error`. `model_name` passes through untouched because it comes from our own configuration's closed vocabulary — no outside text flows into it — while a URL can carry credentials in its query string: the redaction test feeds an `api_url` ending in `?api_key=...` and asserts the stored value is clean.
- `node_path=list(report.node_path)` converts the report's tuple for the JSON column. The mapping test reads back `run.node_path == ["retrieve", "grade"]` — same order, same content, different container.
- `persist_run_report` only flushes. As with M3.3's `persist_eval_result`, the caller commits.
- `secret_values` arrives as an argument. Nothing is read from settings, so this file does not depend on `app.config`.

> **Concept — Flush versus commit**
>
> A flush sends the pending INSERT statements to the database inside the caller's still-open transaction; the rows exist for that transaction and database-generated primary keys come back, but nothing is durable yet — a later rollback undoes everything the flush wrote. Commit is the durability decision, and it belongs to whoever owns the transaction. A seam that only flushes composes: the caller can persist a run report atomically with its own rows, or discard both together, and a test can drive the whole seam with a fake session and no database at all.

Why is `secret_values` a parameter instead of being read from `Settings`? Reading settings here would be more convenient — and it would create the import this package spent three files avoiding: the configuration object is where the real API key lives, so touching it couples observability to `app.config` and hides the redaction list from the call site. As a parameter, the caller states exactly which values are secret, and the tests exercise redaction with fabricated secrets and no configuration at all.

Follow `secret_values` through the function: it enters from the caller, is pinned once into a tuple at the top of `report_to_records`, and is then threaded explicitly into all five redaction sites. The repetition is deliberately mechanical — each site is a free-text column, and a site missed here is a leak no type checker can see, which is exactly why the parameter passing looks so repetitive.

#### Create `app/observability/__init__.py` — public API

**Learning action — define the structure:** the surface M4.2 publishes.

```python
"""Public contracts for M4 workflow observability and budget enforcement."""

from app.observability.budget import BudgetResource, pre_node_budget_guard
from app.observability.cost import (
    MODEL_PRICES,
    ModelPrice,
    UnknownModelPriceError,
    estimate_cost_usd,
    estimate_trace_cost_usd,
)
from app.observability.persistence import (
    REDACTED,
    persist_run_report,
    redact_sensitive_text,
    report_to_records,
)
from app.observability.trace import step_trace_from_provider_result
from app.observability.types import (
    Budget,
    JsonObject,
    RunReport,
    RunStatus,
    StepTrace,
    WorkflowNode,
    build_run_report,
)

__all__ = [
    "MODEL_PRICES",
    "REDACTED",
    "Budget",
    "BudgetResource",
    "JsonObject",
    "ModelPrice",
    "RunReport",
    "RunStatus",
    "StepTrace",
    "UnknownModelPriceError",
    "WorkflowNode",
    "build_run_report",
    "estimate_cost_usd",
    "estimate_trace_cost_usd",
    "persist_run_report",
    "pre_node_budget_guard",
    "redact_sensitive_text",
    "report_to_records",
    "step_trace_from_provider_result",
]
```

### Focused tests and the contracts they protect

```bash
uv run pytest tests/workflow/test_03_observability.py -q
```

The file holds 13 test functions in 389 lines and covers tutorial 4's models together with this document's three files — the `_trace` and `_report` fixtures at the top build one canonical trace and one canonical report, and every contract below is exercised against them. Three are worth reading in full: `test_zero_budget_refuses_the_first_node_and_negative_budgets_are_invalid` for the guard's edge, `test_persistence_mapping_preserves_provenance_and_redacts_secrets` for the whole redaction path through one report, and `test_persistence_flushes_without_committing_or_live_services`, which drives `persist_run_report` with a hand-written recording session — no database, no I/O, exactly what a flush-only seam makes possible.

| Value the test breaks | Contract being protected |
|---|---|
| Usage landing exactly on the limit | Zero remaining room blocks the next node. |
| A zero-budget configuration | The first node is refused deterministically. |
| A total that disagrees with the traces | Aggregates are always derived from traces. |
| An API key inside `llm_output` | No credential is stored in the database. |
| Overlapping secret strings | A longer secret is never partially erased. |

### What you should be able to explain now

- **Which configuration becomes valid because the guard uses `>=` instead of `>`?**
  - **Answer:** A zero budget becomes valid and deterministically blocks execution before the first node; with all four resources exhausted at once, the refusal names `iterations` — the first key in the limits literal.
- **Which dependency direction does using `Protocol` preserve?**
  - **Answer:** `app.observability` depends only on the structural shape it needs and remains unaware of `app.llm`; provider results satisfy that shape without inheriting from it.
- **Why are secret strings substituted longest-first?**
  - **Answer:** Replacing a shorter overlapping secret first could remove only part of a longer one and leave its remainder exposed.
- **What breaks if redaction moves after ORM object construction?**
  - **Answer:** Unredacted secrets would already exist inside `Run` or `Trace` objects, so the guarantee that sensitive values never cross the storage boundary would be lost.
- **Why does `persist_run_report` not commit?**
  - **Answer:** The caller owns the transaction and decides when this write should commit atomically with any surrounding work; the function only flushes.

---

[← Previous: Observability types](04-observability-types.md) · [Module overview](../03-build.md) · [Next: Workflow types →](06-workflow-types.md)
