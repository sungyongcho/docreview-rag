# M4.1 Tutorial 2 — Splitting parsing, repair, and budget judgment into functions

Tutorial 1 made failure a value: a `ProviderResult` holds either a parsed object or a typed refusal, never both and never neither — `validate_result_state` rejects every other combination. What it left open is where those values come from. No code yet turns the string a model actually returns into one of them.

Skip this layer and every caller improvises that conversion. One node parses with a bare `json.loads` and lets `NaN` sail into a cost sum, another retries on its own schedule, a third drops the raw output that would have explained the failure — the per-node chaos tutorial 1 opened with, rebuilt one call site at a time.

This document builds the **decision logic** of the provider boundary. Not a class — seven pure module-level functions; the table below marks which ones you implement yourself. The invariant they defend fits in one testable sentence: **no code path returns a parsed value and validation errors at the same time.** `_parse_output` hands back either a model instance with an empty error tuple or `None` with at least one error string, and that exclusivity is what lets the next document's `complete()` satisfy `validate_result_state` on every exit.

The order matters. The `LLMProvider` abstract class runs 212 lines (`provider.py:152-363`), and every judgment inside it lives in these functions. Build the functions first and the class is left with **only call order.** That is also what "pure" buys here: every judgment can be tested as a plain function call — no event loop, no network, no class instance.

**Prerequisite:** Tutorial 1's `uv run pytest tests/workflow/test_01_schemas.py -q` passes.

### How far can the JSON a model returns be trusted

Structured output is still a string in the end. Three things can go wrong in parsing.

- the JSON itself is broken
- the JSON is valid but does not match the schema
- both are fine but it contains **a value outside the JSON standard** (`NaN`, `Infinity`)

The third is the quietest. Python's `json` allows `NaN` by default, so the parse succeeds, the value lands in a cost calculation or a score, and from then on every comparison against it is false. **A budget check that always passes is a budget that does not exist.** The first two failures at least announce themselves; this one leaves no signal at the parsing stage at all.

All three get their own typed, inspectable exit in `_parse_output` below, and every exit produces error strings a repair prompt can act on.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| Module header and clock alias | **Define the structure** | Why the clock is injectable |
| `_parse_output` | **Implement** the parsing guard yourself | Where non-standard JSON values are blocked |
| `_repair_prompt` | **Write the field mapping** | What the repair prompt gives the model |
| The two budget judges | **Implement** the boundary rules yourself | Why `>` and `>=` diverge |

### 1. Module header and an injectable clock

#### Create `app/llm/provider.py` — module header

**Learning action — define the structure:** `Decimal` and `ValidationError` are among the imports — cost arithmetic and schema validation live in the same file. The header you type here is the complete M4.1 form; tutorial 9 adds one more import — the SDK's strict format type — when the strict decoding path arrives.

```python
"""Async structured-output providers with one repair and fail-closed refusal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from decimal import Decimal
import json
import time
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.llm.schemas import (
    BudgetExceeded,
    CompletionFailure,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    ProviderResult,
    RawProviderResponse,
    SchemaRejected,
)
```

#### Extend `app/llm/provider.py` — clock alias

**Learning action — define the structure:** the same alias shape M3's evaluation CLI (`app/evals/retrieval_eval.py`) used for its `Clock`.

<!-- src: app/llm/provider.py::Clock -->
```python
type Clock = Callable[[], int]
```

**What to look for in the code**

- `Clock` returns integer nanoseconds. Floating-point seconds would bury a short call's latency in rounding.
- The alias exists so the clock can be injected. `complete()` reads the clock twice around each attempt to measure it; with the production default `time.perf_counter_ns` a test could only assert "some nonnegative number". The test suite injects a `TickClock` that advances exactly 1,000,000 ns per read, and the happy-path test then pins `request_time_ms == 1.0` — latency becomes a deterministic, assertable value.

### 2. Blocking values outside the JSON standard

#### Extend `app/llm/provider.py` — output parsing

**Learning action — implement the parsing guard:** implement `_json_object` and `_invalid_json_constant` yourself. Note when `parse_constant` gets called.

<!-- src: app/llm/provider.py::_json_object,_parse_output -->
```python
def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _validation_errors(error: ValidationError) -> tuple[str, ...]:
    messages = []
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"]) or "$"
        messages.append(f"{location}: {issue['msg']} [{issue['type']}]")
    return tuple(messages)


def _parse_output[OutputT: BaseModel](
    output_text: str,
    schema: type[OutputT],
) -> tuple[OutputT | None, tuple[str, ...]]:
    try:
        value = json.loads(
            output_text,
            object_pairs_hook=_json_object,
            parse_constant=_invalid_json_constant,
        )
        canonical = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        return schema.model_validate_json(canonical, strict=True), ()
    except ValidationError as error:
        return None, _validation_errors(error)
    except json.JSONDecodeError as error:
        message = f"$: {error.msg} at line {error.lineno} column {error.colno} [json_invalid]"
        return None, (message,)
    except ValueError as error:
        return None, (f"$: {error} [json_invalid]",)
```

> **Concept — Why parse, then re-serialize, then parse again**
>
> Two requirements pull in opposite directions. Duplicate keys are visible only during parsing: Python's `json.loads` exposes every key-value pair through its `object_pairs_hook` before they collapse into a dict, while Pydantic's own JSON parser keeps the last duplicate and reports nothing. Strict decoding, meanwhile, is defined against JSON text: the rules that keep `"5"` from becoming an integer are the ones `model_validate_json` applies under `strict=True`, and Pydantic applies a different, Python-object rule table when handed an already-parsed dict.
>
> Satisfying both forces the detour: parse with hooks, re-serialize canonically, validate the canonical text. "Simplifying" the tail to `schema.model_validate(value)` would still pass every test that feeds well-formed output — it would only silently change which coercions are allowed. On the `json.dumps` step, `allow_nan=False` is a second gate behind `parse_constant`: a non-finite float that arrived by any other route still cannot be serialized into the text the schema sees.

> **Concept — `NaN` is not JSON**
>
> RFC 8259, the JSON standard, has no representation for non-finite numbers. `NaN`, `Infinity`, and `-Infinity` are not JSON at all; CPython's `json` module accepts them as a documented extension. That is why "the model returned invalid JSON" offers no protection here — the parse succeeds. `parse_constant` is the hook the parser fires for exactly these three tokens and nothing else, so raising inside it turns the extension back into the error the standard says it is.

**What to look for in the code**

- `parse_constant=_invalid_json_constant` fires on `NaN`, `Infinity`, and `-Infinity`. Python's `json` **permits** all three by default, so they pass unless explicitly blocked.
- `object_pairs_hook=_json_object` rejects duplicate keys — the same defense as M3.1's loader. A model emitting the same key twice would otherwise silently keep the last.
- `_validation_errors` compresses Pydantic errors into a string tuple, joining each error's `loc` path with dots (`answer.label`) and falling back to `$` — JSONPath's name for the document root — when the top-level value itself is the problem. The tuple's life does not end here: the first attempt's tuple is what `_repair_prompt` folds into the repair prompt body, and if the second attempt also fails, the tuple that final parse produces is stored on `SchemaRejected.errors` and returned to the caller — each attempt's parse rebinds the variable, so the two tuples are not the same object.
- The three `except` clauses are ordered deliberately. `json.JSONDecodeError` subclasses `ValueError`, so the specific clause must come first — reverse the last two and every broken-JSON failure is swallowed by the bare `ValueError` clause: the dedicated clause becomes dead code, and the module no longer controls the format of its broken-JSON message. The line and column would survive — the decode error's own message carries them — but only because the standard library happens to phrase it that way, not because this module chose to.
- A non-object at the top level is **not** caught by the hooks. `object_pairs_hook` fires only on objects, so a model returning an array or a bare string passes `json.loads`, survives `json.dumps`, and is rejected by `model_validate_json` — it surfaces as a schema validation error, not on the `json_invalid` path.

The two quiet failures are pinned by a test rather than asserted. In `tests/workflow/test_02_provider.py`, `test_non_strict_json_is_repaired_instead_of_silently_interpreted` feeds exactly two payloads — a duplicate key the default parser would silently resolve to `NOT_IN_DOCS`, namely `{"label":"SUPPORTED","label":"NOT_IN_DOCS"}`, and an otherwise valid object whose `reason` is `NaN` — and asserts each one triggers a repair whose prompt carries `json_invalid`, with `retries == 1`.

### 3. What the repair prompt gives the model

#### Extend `app/llm/provider.py` — repair prompt

**Learning action — write the field mapping:** note what goes into the repair prompt.

<!-- src: app/llm/provider.py::_repair_prompt -->
```python
def _repair_prompt(prompt: Prompt, raw_output: str, errors: Sequence[str]) -> Prompt:
    details = "\n".join(f"- {error}" for error in errors)
    return Prompt(
        system=prompt.system,
        user=(
            f"{prompt.user}\n\n"
            "Your previous structured output failed validation. Repair it once and return "
            "only an object that matches the required schema.\n"
            f"Validation errors:\n{details}\n"
            f"Previous output:\n{raw_output}"
        ),
    )
```

**What to look for in the code**

- The original prompt, **the wrong output the model produced**, and **the list of validation errors** all travel together. Drop any one and the model cannot know what to fix — **without the errors it knows only that something was rejected, and the second attempt is likely to repeat the first.**
- The error list is Pydantic's paths rather than human prose (`answer.label: ...`). For a model that is the more precise form — the field to fix is named, not described.
- Only `user` changes; `system` is reused verbatim. The system prompt is the task contract, and the second attempt must solve the same task under the same rules — an attempt-specific instruction appended to `system` would quietly make the repair a different task. Everything that belongs to this attempt — the rejected output, the error report — is data, and data goes in the user turn.
- The errors travel as pre-formatted strings rather than structured objects, because a prompt is text either way and `_validation_errors` already chose the serialization. `include_url=False` and `include_input=False` are hygiene: they slim the error entries Pydantic builds, dropping the documentation link and the echoed field input from each one. That the failing output appears exactly once — in the `Previous output` block, not once per error — is guaranteed a step earlier, by the formatter itself, which reads only each error's location path, message, and type.

That all three ingredients actually arrive is proven by a test: `test_schema_failure_repairs_once_with_errors_and_remaining_budget` asserts the second prompt contains `failed validation`, the Pydantic message `Field required`, and the rejected output `{"label":"SUPPORTED"}` itself.

### 4. Where `>` and `>=` diverge

#### Extend `app/llm/provider.py` — budget judgment

**Learning action — implement the boundary rules:** put the two functions side by side and compare the operators. This is the subtlest part of the document.

<!-- src: app/llm/provider.py::_budget_failure,_repair_budget_failure -->
```python
def _budget_failure(
    budget: ProviderBudget,
    *,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: Decimal,
    attempts: int,
) -> BudgetExceeded | None:
    if input_tokens > budget.max_input_tokens:
        return BudgetExceeded(
            which="input_tokens",
            used=input_tokens,
            limit=budget.max_input_tokens,
            attempts=attempts,
        )
    if output_tokens > budget.max_output_tokens:
        return BudgetExceeded(
            which="output_tokens",
            used=output_tokens,
            limit=budget.max_output_tokens,
            attempts=attempts,
        )
    if estimated_cost_usd > budget.max_cost_usd:
        return BudgetExceeded(
            which="estimated_cost_usd",
            used=estimated_cost_usd,
            limit=budget.max_cost_usd,
            attempts=attempts,
        )
    return None


def _repair_budget_failure(
    budget: ProviderBudget,
    *,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: Decimal,
) -> BudgetExceeded | None:
    """Return why a validation repair cannot make another provider request."""
    if input_tokens >= budget.max_input_tokens:
        return BudgetExceeded(
            which="input_tokens",
            used=input_tokens,
            limit=budget.max_input_tokens,
            attempts=1,
        )
    if output_tokens >= budget.max_output_tokens:
        return BudgetExceeded(
            which="output_tokens",
            used=output_tokens,
            limit=budget.max_output_tokens,
            attempts=1,
        )
    priced = budget.pricing.input_per_million_usd > 0 or budget.pricing.output_per_million_usd > 0
    if priced and estimated_cost_usd >= budget.max_cost_usd:
        return BudgetExceeded(
            which="estimated_cost_usd",
            used=estimated_cost_usd,
            limit=budget.max_cost_usd,
            attempts=1,
        )
    return None
```

> **Concept — Post-hoc judgment vs prospective judgment**
>
> The two functions answer different questions about different moments. `_budget_failure` asks "did what already happened cost too much" — a verdict on the past, where landing exactly on the limit means the limit held. `_repair_budget_failure` asks "can one more request be afforded" — a verdict on the future, where already standing on the limit means the next request must cross it. One character of difference carries all of it: a post-hoc judge using `>=` would punish a call for staying inside its budget, and a prospective judge using `>` would authorize a request that is guaranteed to overrun.

**What to look for in the code**

- `_budget_failure` uses `>` while `_repair_budget_failure` uses `>=`. **That is deliberate.**
- `_budget_failure` judges a call that **already happened**. Spending exactly the limit is not an overrun.
- `_repair_budget_failure` asks whether **another call is possible**. Having reached the limit exactly means the next call must exceed it, so it is blocked in advance.
- Both judges return `BudgetExceeded | None` instead of raising. Tutorial 1 made failure a value; these functions produce that value or nothing, and the next document chains them as guard clauses. Raising here would put budget failures back on the exception channel — the very channel `complete()` exists to keep empty.
- The `priced` check guards only the cost judgment, and it belongs to the **budget**, not to any provider class: pricing lives on the caller-supplied `ProviderBudget.pricing`. A price table of all zeros keeps the estimate at 0, and 0 does not mean "at the cost limit" — it means cost is unmeasured. With `max_cost_usd` also 0, `0 >= 0` would block every repair forever. The token judgments need no such guard, and the types say why: `max_input_tokens` and `max_output_tokens` are `PositiveInt` and can never be zero, while `max_cost_usd` is `NonNegativeDecimal`, and zero is exactly what an unpriced budget carries.

Neither judge knows which attempt it is judging — the caller supplies the numbers. In the next document, `complete()` hands them the **original** caps together with the **cumulative** usage of every attempt so far, while the shrunken per-attempt copy it derives with `model_copy` goes to the transport, never to these judges. The test suite makes the split measurable: with a 1,000/100 budget, a first attempt that spends 10 input and 5 output tokens leaves the repair judgment comparing 10 against 1,000 — retry allowed — while the second request is handed shrunken caps of 990 and 95. The fixture's pricing — `Decimal("2")` in, `Decimal("10")` out, per million tokens — is also what makes cost assertions exact: the happy-path test pins `estimated_cost_usd == Decimal("0.0004")` for 100 input and 20 output tokens, arithmetic a float could only approximate.

Both operators are exercised at their exact boundaries. `test_repair_does_not_start_after_the_first_attempt_exhausts_budget` is the `>=` boundary run for real: a 10-token input cap, a first attempt that spends exactly 10, and a schema failure that wants to repair — `_budget_failure` finds no overrun, because `10 > 10` is false, yet `_repair_budget_failure` blocks the second call, and the result records `used == limit == 10` with exactly one prompt sent. `test_explicit_usage_and_cost_budgets_fail_closed` is the `>` boundary: caps of 9 input tokens, 4 output tokens, or `Decimal("0.00001")` in cost against a call that used 10 in, 5 out, and `Decimal("0.00007")` — each case past its limit, each returning `budget_exceeded` with `parsed is None`.

### What you should be able to explain now

- **Which three non-standard JSON values does Python's `json` permit by default?**
  - **Answer:** `NaN`, `Infinity`, and `-Infinity` — none of them legal JSON under RFC 8259 — are accepted unless `parse_constant` rejects them explicitly.
- **Why does `_parse_output` re-serialize instead of handing Pydantic the parsed dict?**
  - **Answer:** Duplicate keys are visible only through an `object_pairs_hook` on `json.loads`, and strict decoding is defined only for the JSON text `model_validate_json` receives, so the value is parsed with hooks, re-serialized canonically, and validated as text.
- **Why must the validation error list go into the repair prompt?**
  - **Answer:** The model needs the exact schema violations, together with the original prompt and rejected output, to know what to correct.
- **Why do `_budget_failure` and `_repair_budget_failure` use different operators?**
  - **Answer:** `_budget_failure` judges a completed call — a post-hoc verdict where spending exactly the limit is valid, so it uses `>`. `_repair_budget_failure` judges whether a next call can start — a prospective verdict where standing on the limit already condemns the next call, so it blocks with `>=`.
- **What happens to an unpriced budget without the `priced` check?**
  - **Answer:** An all-zero price table keeps the cost estimate at 0, and with `max_cost_usd` also 0, `0 >= 0` becomes true and every repair attempt is blocked — while the token caps are immune because `PositiveInt` keeps them nonzero.
- **Why is the clock integer nanoseconds?**
  - **Answer:** Integer nanoseconds preserve short call durations that floating-point seconds could bury in rounding.

---

[← Previous: Schemas](01-schemas.md) · [Module overview](../03-build.md) · [Next: Provider implementations →](03-provider-impl.md)
