# M4.2 Tutorial 4 — Make failure visible before writing workflow code

The second ring of defense is **observability**. The order will feel odd — the workflow does not exist yet and observability comes first.

There is a reason. **Attach observability later and the failure paths get left out.**

Build the workflow first and the success path completes first. Then error handling gets added by wrapping things in `try/except`, and at that point a budget overrun or provider failure **vanishes after one log line.** Later, asked "why did this request fail?", there is nothing to answer with.

Two sentences in this document are testable invariants, and everything else serves them. First: **every terminal state produces a `RunReport`** — success, budget exhaustion, schema rejection, and error all end in the same record shape, so a "no record" outcome does not exist. Second: **every total in that report is derived from the traces beneath it**, so the report can never disagree with its own evidence.

**Prerequisite:** Tutorial 3's `uv run pytest tests/workflow/test_02_provider.py -q` passes.

### Failure is an output too

In this project, budget exhaustion and schema rejection are **not bugs but normal terminal states.**

```
ok                → completed normally
budget_exceeded   → stopped at the budget ceiling
schema_rejected   → model output did not match the schema
error             → any other failure
```

All four produce a `RunReport`. No path dies quietly. So a successful run and a failed run **can be inspected the same way.**

The same holds from a portfolio standpoint. Being able to show "when the budget is exceeded it stops like this and records like this" is an entirely different thing from simply raising an exception.

### Totals must not drift from the traces

Where does `RunReport`'s total token count come from? Not a separate counter. **It is computed from the `StepTrace` list.**

Count it separately and it drifts eventually — a node forgets to emit a trace, or a retry goes uncounted. Then the report's numbers and the trace record disagree and there is no telling which is right.

**Always derive aggregates from the underlying data.** The same principle as M1.4 making `content_tsv` a generated column.

> **Concept — A derived aggregate backed by a validator**
>
> Deriving totals in a helper function is a convention, and a convention only holds until someone bypasses the helper. This module adds a second layer: the report model re-checks every total against its own traces at construction time, so a report whose counters disagree with its steps cannot exist as an object.
>
> The two layers do different jobs. The helper makes the honest path convenient — pass traces, get correct totals. The validator makes the dishonest path impossible — a caller who builds the report directly with a wrong total gets a validation error, not a stored lie. The committed suite exercises exactly that bypass: a hand-built report claiming 999 input tokens over a 100-token trace is rejected at construction.

### The budget is checked *before* the node runs

The budget guard runs **before** executing a node, not after. It uses the tokens and time already spent to judge "is there room for the next node?" — the guard observes exactly four resources: entered nodes, input tokens, output tokens, and wall-clock seconds.

Check afterward and the money is already spent. A ceiling that is not a ceiling.

```
provider metadata + node id → StepTrace
ordered traces → cumulative token/request totals + cost → [pre-node budget guard] → RunReport
                                                              ↓
                                                    caller-owned persistence seam
```

Read the diagram carefully on one point: cost sits next to the cumulative totals, but the arrow into the guard carries only the totals. The guard never consumes cost — `Budget` has no cost field, and the only cost ceiling in the system today is the per-call one on tutorial 1's `ProviderBudget`. Section 4 returns to what cost estimation is actually for.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `StepTrace` | **Write the model declaration** | What one step must preserve |
| `RunReport` and `Budget` | **Write the model declarations** | The contract that failure also produces a report |
| `build_run_report` | **Implement** the aggregation yourself | Deriving totals from traces |
| `ModelPrice` | **Define the settings schema** | Why an unknown model is never estimated |
| `estimate_trace_cost_usd` | **Implement** the cost calculation yourself | The boundary of `Decimal` arithmetic |

### 1. What one step must preserve

#### Create `app/observability/types.py` — module header

**Learning action — define the structure:** note that this file does not import `app.llm`. That absence is a design decision, and its payoff lands in tutorial 5, where a structural `Protocol` lets provider results cross into this package without either side importing the other.

```python
"""Strict value objects for workflow traces, reports, and budgets."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

WorkflowNode = Literal["retrieve", "grade", "check", "report"]
RunStatus = Literal["ok", "budget_exceeded", "schema_rejected", "error"]
JsonObject = dict[str, JsonValue]

NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeFloat = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]

```

Two aliases in this header carry more weight than their one line suggests. `JsonValue` is Pydantic's recursive any-JSON type — strings, numbers, booleans, `None`, and lists and dicts of the same. `JsonObject = dict[str, JsonValue]` therefore reads: a JSON object whose values are valid JSON all the way down. It is the type that later lets `report` hold three differently shaped payloads while staying serializable into a strict JSONB column — though not by itself: the alias still admits non-finite floats, and what actually keeps them out of the JSONB column is the `report` field's `reject_nonfinite_json` validator, visible in the pinned fence below.

#### Extend `app/observability/types.py` — `StepTrace`

**Learning action — write the model declaration:** for each field, ask what becomes invisible without it.

<!-- src: app/observability/types.py::StepTrace -->
```python
class StepTrace(BaseModel):
    """One raw, traceable workflow step before persistence redaction."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    step: PositiveInt
    node: WorkflowNode
    model_name: Annotated[StrictStr, Field(min_length=1)]
    api_url: Annotated[StrictStr, Field(min_length=1)]
    input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    request_time_ms: NonnegativeFloat
    llm_output: StrictStr
    retries: NonnegativeInt
    error: StrictStr | None = None

    @field_validator("model_name", "api_url", mode="after")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        """Reject provider identity fields that contain only whitespace."""
        if not value.strip():
            raise ValueError("provider identity fields must not be blank")
        return value

    @field_validator("error", mode="after")
    @classmethod
    def reject_blank_error(cls, value: str | None) -> str | None:
        """Keep absence distinct from an unusable blank error message."""
        if value is not None and not value.strip():
            raise ValueError("error must be null or nonblank")
        return value
```

**What to look for in the code**

- `llm_output` is stored whole. Without a failed step's raw output there is no seeing why it failed — M4.1's `RawProviderResponse` reaches all the way here, and the arc runs one step further: tutorial 5 redacts this exact string and writes it to the database, which is where a failure investigation actually starts.
- `retries` and `error` are separate. A step that retried and succeeded is distinguishable from one that failed.
- `api_url` is present. Which endpoint was called survives, so a misconfiguration that hit the wrong environment can be found after the fact.

One more thing the code cannot show: nothing in this document ever constructs a `StepTrace`. It is born in tutorial 5, where `step_trace_from_provider_result` maps one provider result into one trace; it lives inside `RunReport.steps`; and it leaves the process only through tutorial 5's persistence seam, redacted into a `Trace` row. This file's job is to define what must survive that journey unchanged.

### 2. Failure also produces a report

#### Extend `app/observability/types.py` — `RunReport` and `Budget`

**Learning action — write the model declarations:** note the relationship between `status`'s four values and `report` being `| None`.

<!-- src: app/observability/types.py::RunReport,Budget -->
```python
class RunReport(BaseModel):
    """One complete or structured-failure workflow run."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
    status: RunStatus
    iterations: NonnegativeInt
    total_requests: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
    system_prompt: Annotated[StrictStr, Field(min_length=1)]
    node_path: tuple[WorkflowNode, ...]
    report: JsonObject | None
    steps: tuple[StepTrace, ...]

    @field_validator("system_prompt", mode="after")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        """Require the prompt provenance promised by the trace contract."""
        if not value.strip():
            raise ValueError("system_prompt must not be blank")
        return value

    @field_validator("report", mode="after")
    @classmethod
    def reject_nonfinite_json(cls, value: JsonObject | None) -> JsonObject | None:
        """Keep the report compatible with strict PostgreSQL JSONB serialization."""

        def validate(child: object) -> None:
            if isinstance(child, float) and not math.isfinite(child):
                raise ValueError("report must contain only finite JSON numbers")
            if isinstance(child, dict):
                for nested in child.values():
                    validate(nested)
            elif isinstance(child, list):
                for nested in child:
                    validate(nested)

        validate(value)
        return value

    @model_validator(mode="after")
    def validate_accumulated_totals(self) -> Self:
        """Reject reports whose cumulative counters disagree with their raw traces."""
        expected_steps = tuple(range(1, len(self.steps) + 1))
        actual_steps = tuple(trace.step for trace in self.steps)
        if actual_steps != expected_steps:
            raise ValueError("trace step numbers must be contiguous and start at 1")
        if self.iterations != len(self.node_path):
            raise ValueError("iterations must equal the number of entered nodes")
        expected_requests = sum(1 + trace.retries for trace in self.steps)
        if self.total_requests != expected_requests:
            raise ValueError("total_requests must include every trace request and retry")
        if self.total_input_tokens != sum(trace.input_tokens for trace in self.steps):
            raise ValueError("total_input_tokens must equal the trace sum")
        if self.total_output_tokens != sum(trace.output_tokens for trace in self.steps):
            raise ValueError("total_output_tokens must equal the trace sum")
        return self


class Budget(BaseModel):
    """Hard cumulative limits checked immediately before entering a node."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_iterations: NonnegativeInt = 6
    max_input_tokens: NonnegativeInt = 60_000
    max_output_tokens: NonnegativeInt = 4_000
    max_wall_clock_s: NonnegativeFloat = 120.0
```

**What to look for in the code**

- `status` has four values and all four produce a `RunReport`. No run outcome dies by exception — though be precise: the runner still raises `TypeError` for a request or provider of the wrong type and `ValueError` for a clock that does not return float seconds. Those are programming errors caught at the door, not run outcomes; tutorial 8 shows both guards. A malformed program fails loudly, a failed run reports.
- `run_id` is a pattern, not free text: it starts with a letter or digit, continues with letters, digits, `.`, `_`, `:`, or `-`, and tops out at 128 characters. The excluded characters are exactly the ones that would break a URL path segment or a filename — this identifier is designed to travel into logs, filenames, and endpoints unquoted.
- `report` is `| None`. Stopping on a budget overrun leaves no report but **the traces and totals are still there.**
- Three producers fill `report`, each with a different shape: the pre-node guard writes a structured refusal reason, the runner's failure path writes the typed failure dumped to JSON, and a completed run writes the full answer report. Three producers with three shapes is why the field is loose JSON rather than a typed model — tutorial 6 builds the typed `WorkflowReport` that occupies the success case, and this field is the union point where all three meet.
- `Budget` includes `max_wall_clock_s`. Tokens may remain while time runs out.
- The defaults are worth reading as numbers: 6 iterations, 60,000 input tokens, 4,000 output tokens, 120.0 seconds. Six against a four-node graph means the iteration ceiling is headroom, not a tuned value — nothing in the repo derives these defaults, and treating them as measured would be a mistake.
- `Budget` has no cost field. The guard enforces only what it can recompute exactly from traces and a clock; cost is an estimate derived from a price table, and its enforcement point today is the per-call provider budget from tutorial 1, not this model. Section 4 states that honestly.
- `system_prompt` is stored in the report. Editing a prompt changes results, so which prompt produced a result must travel with it for any comparison to hold.

### 3. Deriving totals from traces

#### Complete `app/observability/types.py` — assembling the report

**Learning action — implement the aggregation:** implement `build_run_report` yourself. Where the totals come from is the point.

<!-- src: app/observability/types.py::build_run_report,validate_elapsed_seconds -->
```python
def build_run_report(
    *,
    run_id: str,
    status: RunStatus,
    total_time_seconds: float,
    system_prompt: str,
    node_path: tuple[WorkflowNode, ...] | list[WorkflowNode],
    steps: tuple[StepTrace, ...] | list[StepTrace],
    report: JsonObject | None = None,
) -> RunReport:
    """Derive cumulative counters from raw traces instead of trusting callers."""
    trace_values = tuple(steps)
    return RunReport(
        run_id=run_id,
        status=status,
        iterations=len(node_path),
        total_requests=sum(1 + trace.retries for trace in trace_values),
        total_input_tokens=sum(trace.input_tokens for trace in trace_values),
        total_output_tokens=sum(trace.output_tokens for trace in trace_values),
        total_time_seconds=total_time_seconds,
        system_prompt=system_prompt,
        node_path=tuple(node_path),
        report=report,
        steps=trace_values,
    )


def validate_elapsed_seconds(value: object) -> float:
    """Validate an externally measured monotonic duration without coercion."""
    if isinstance(value, bool) or not isinstance(value, float):
        raise ValueError("elapsed_seconds must be a finite nonnegative float")
    if not math.isfinite(value) or value < 0:
        raise ValueError("elapsed_seconds must be a finite nonnegative float")
    return value
```

**What to look for in the code**

- Token totals are computed by walking `steps`. There is no separate counter, so **they cannot drift.**
- `validate_elapsed_seconds` rejects negative and non-finite values. A broken clock makes the entire budget judgment meaningless. It is a free function rather than a field validator by design: the value it checks arrives as a bare argument to the budget guard, before any report exists to hang a validator on — the guard validates the clock reading first and only then decides whether a `RunReport` is built at all.
- Step-number continuity is checked. One missing trace would quietly shrink the totals.

> **Concept — Requests, not steps**
>
> One trace is one workflow step, but one step is not one HTTP request. When the provider's repair loop from tutorial 3 retries a rejected response, the retry was a real, paid request, and the trace keeps its count. Counting one request per step would erase exactly the expensive part of the failure path.
>
> That is why the request total is the sum of one plus the retry count over all traces, rather than the number of traces. A one-step run whose single step retried once reports two requests — the step count and the request count are supposed to disagree.

The committed suite pins that case: `tests/workflow/test_03_observability.py` builds a one-step report with `retries=1` and asserts `total_requests == 2`.

> **Concept — Contiguity as a tamper check**
>
> Step numbers are 1-based and dense: a report with three traces must carry steps one, two, and three. The validator recomputes that expected sequence from the trace count alone and compares it against what the traces claim. A dropped trace does not merely shrink the totals — it leaves a numbering gap, and the gap makes the report impossible to construct.
>
> Without this rule a lost trace would be undetectable by design. The totals are derived from the surviving traces, so they would still agree with each other — perfectly, and wrongly. Continuity is the one check that catches what internally consistent arithmetic cannot.

One question remains: why store totals on the report at all if they are always derivable? Because the report does not stay in memory. Tutorial 5's `report_to_records` copies `iterations`, `total_requests`, and both token totals into columns of the persisted run row, and a monitoring query against those columns must answer "what did yesterday cost" without rehydrating every trace. The stored redundancy is deliberate, and the validator above is what makes redundancy safe.

### 4. An unknown model is never estimated

#### Create `app/observability/cost.py` — module header and price table

**Learning action — define the settings schema:** work out why `UnknownModelPriceError` is an exception.

```python
"""Deterministic token-cost estimates using versioned, explicit prices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.observability.types import StepTrace

TOKENS_PER_MILLION: Final[Decimal] = Decimal(1_000_000)

```

<!-- src: app/observability/cost.py::ModelPrice,UnknownModelPriceError -->
```python
@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD prices per one million uncached input and output tokens."""

    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.input_per_million, Decimal) or not isinstance(
            self.output_per_million, Decimal
        ):
            raise ValueError("model prices must be Decimal values")
        if not self.input_per_million.is_finite() or not self.output_per_million.is_finite():
            raise ValueError("model prices must be finite")
        if self.input_per_million < 0 or self.output_per_million < 0:
            raise ValueError("model prices must be nonnegative")


# Published launch prices are pinned so historical trace estimates never drift.
MODEL_PRICES: Final[dict[str, ModelPrice]] = {
    "gpt-4.1-mini": ModelPrice(Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-mini-2025-04-14": ModelPrice(Decimal("0.40"), Decimal("1.60")),
}


class UnknownModelPriceError(ValueError):
    """Raised when cost would otherwise be silently reported as zero."""
```

`ModelPrice` is the one plain dataclass in a package that is Pydantic everywhere else, and the inconsistency is deliberate. These prices are authored right here as module constants, never parsed from outside input, so parse-time validation machinery buys nothing; `frozen=True` with `slots=True` gives immutability and a closed attribute set with less mechanism. `__post_init__` is the dataclass counterpart of a model validator — it runs after field assignment, and the Decimal, finiteness, and sign checks live there. The obvious reuse — tutorial 1's `NonNegativeDecimal` alias — is rejected for a structural reason: that alias lives in `app.llm`, and importing it would create exactly the dependency this package was designed not to have.

`Final` guards the module constants, and it is worth being precise about what it prevents. It is a type-checker promise, not a runtime lock: rebinding `TOKENS_PER_MILLION` or `MODEL_PRICES` becomes a type error in review, but running code could still mutate the dict in place. The runtime half of the guarantee comes from `ModelPrice` itself being frozen — the values inside the table cannot be edited even where the table can.

> **Concept — Fail closed, not open**
>
> A lookup that cannot answer has two options: guess or refuse. For a cost figure, zero is the worst possible guess, because zero is indistinguishable from "nothing was spent" — the error hides inside a plausible value and every downstream consumer inherits it. Refusing makes the gap loud at the exact call site that introduced the unknown model name.
>
> The refusal type subclasses the ordinary value-error family. Callers that already treat invalid input as an error handle this case with no new code, catching it specifically stays possible, and ignoring it by accident does not.

The table's two keys are not redundancy by accident. `gpt-4.1-mini` is the floating alias and `gpt-4.1-mini-2025-04-14` is the dated snapshot, priced identically — so a deployment pinned to the dated model and one following the alias both resolve. When a future snapshot ships at different prices it gets its own row; the comment above the table promises that historical estimates never drift, and per-snapshot rows are the mechanism that keeps the promise.

**What to look for in the code**

- An unknown model name is an **exception**. It is not treated as zero, nor priced from a similar model. Be precise about what this protects today: no code in `app/` calls these estimators yet — `Budget` has no cost axis and the pre-node guard never reads cost, so cost estimation is a reporting surface, not an enforcement path. Failing closed keeps the reported figure trustworthy now, and trustworthy on the day something does enforce it; a zero estimate would instead record real spend as free and hand every consumer a plausible lie.
- Prices are per million tokens. Provider price sheets are published in that unit, which reduces transcription mistakes.

The table is checkable in one line. A full million tokens each way should cost 0.40 + 1.60 dollars exactly:

```bash
uv run python -c "from app.observability import estimate_cost_usd; print(estimate_cost_usd('gpt-4.1-mini', 1_000_000, 1_000_000))"
```

This prints `2.00` — the committed suite asserts the same value as a `Decimal`, and any other output means the price table changed.

### 5. The boundary of `Decimal` arithmetic

#### Complete `app/observability/cost.py` — cost estimation

**Learning action — implement the cost calculation:** follow where `Decimal` enters and where it leaves.

<!-- src: app/observability/cost.py::_token_count,estimate_trace_cost_usd -->
```python
def _token_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def estimate_cost_usd(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    *,
    prices: dict[str, ModelPrice] | None = None,
) -> Decimal:
    """Estimate uncached token cost exactly with decimal arithmetic.

    Unknown models fail closed because a zero estimate would weaken the budget signal.
    Callers can pass an explicit versioned table for other providers or pricing dates.
    """
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a nonblank string")
    input_count = _token_count(input_tokens, "input_tokens")
    output_count = _token_count(output_tokens, "output_tokens")
    table = MODEL_PRICES if prices is None else prices
    try:
        price = table[model_name]
    except KeyError as exc:
        raise UnknownModelPriceError(f"no pinned price for model {model_name!r}") from exc
    return (
        Decimal(input_count) * price.input_per_million
        + Decimal(output_count) * price.output_per_million
    ) / TOKENS_PER_MILLION


def estimate_trace_cost_usd(
    steps: tuple[StepTrace, ...] | list[StepTrace],
    *,
    prices: dict[str, ModelPrice] | None = None,
) -> Decimal:
    """Sum deterministic per-trace estimates without floating-point rounding."""
    total = Decimal(0)
    for trace in steps:
        if not isinstance(trace, StepTrace):
            raise ValueError("steps must contain StepTrace values")
        total += estimate_cost_usd(
            trace.model_name,
            trace.input_tokens,
            trace.output_tokens,
            prices=prices,
        )
    return total
```

**What to look for in the code**

- `_token_count` validates the counts, rejecting booleans and negatives. A `True` passing as one token makes a billing figure quietly wrong.
- The division happens between `Decimal` values. One `float` mixed in propagates error all the way to the final amount.
- `estimate_trace_cost_usd` takes a trace list and sums it. Steps may use different models, so pricing is looked up per step.

The committed suite pins the arithmetic at the smallest realistic scale too: the shared test fixture spends 100 input and 20 output tokens on `gpt-4.1-mini`, and `estimate_trace_cost_usd` over that single trace returns exactly `Decimal("0.000072")` — 100 × 0.40 / 1,000,000 plus 20 × 1.60 / 1,000,000, with no floating-point residue. Reproduce it without the harness:

```bash
uv run python -c "from app.observability import estimate_cost_usd; print(estimate_cost_usd('gpt-4.1-mini', 100, 20))"
```

Anything other than `0.000072` here means the prices or the arithmetic moved.

### What you should be able to explain now

- **Why is observability built before the workflow?**
  - **Answer:** It makes failure paths part of the design, so they cannot vanish behind a late log line or exception wrapper.
- **What does having all four terminal states produce a `RunReport` make possible?**
  - **Answer:** Successful runs, budget exhaustion, schema rejection, and errors can all be inspected through the same record shape.
- **When does a separately counted total drift?**
  - **Answer:** It drifts whenever a trace is added, removed, or changed without applying the identical update to the separate counter.
- **What is disabled by checking the budget after a node runs?**
  - **Answer:** The ceiling itself. A post-hoc check observes spend that already happened — the run still halts before the next node, but the node that just ran was never capped, so for that node the limit stopped nothing and merely reported the overrun. Checking before entry refuses the node while the resources are still unspent, which is what makes the limit a limit.
- **Which silent failure appears if an unknown model name is priced at zero?**
  - **Answer:** Real spend is recorded as zero, and because zero looks like a valid estimate, nothing downstream can tell the figure is wrong. Failing closed converts that silent corruption into a loud error at the call that introduced the model name.

---

[← Previous: Provider implementations](03-provider-impl.md) · [Module overview](../03-build.md) · [Next: Budget and persistence →](05-observability-trace.md)
