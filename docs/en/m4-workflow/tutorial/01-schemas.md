# M4.1 Tutorial 1 — Establish the boundary before writing workflow code

The first ring of defense is a single **provider boundary**. Prompts go out here, output is validated here, tokens are counted here, and failure is handled here.

**Prerequisite:** M3 is complete and `uv run pytest tests/evals -q` passes.

### Why the boundary is gathered into one place

Imagine what happens without it. There are four workflow nodes, and each parses its own JSON, retries in its own way, and counts tokens however it likes.

- retry policy differs per node (one tries three times, one not at all)
- parse-failure handling differs (one raises, one returns empty)
- **the raw provider response gets discarded somewhere** — later you cannot see why it failed
- the deterministic test provider and the real OpenAI follow different contracts

So the rules gather in one place. A node only says "give me a result of this schema for this prompt," and the boundary handles validation, retries, and instrumentation.

One sentence ties this whole file together, and it is testable: a `ProviderResult` never holds both a parsed value and a refusal, and never neither. Every model written before section 4 exists to make that sentence expressible in types; `validate_result_state` at the end is where it becomes enforced code.

### Repair happens exactly once

If structured output does not match the schema, one repair prompt goes out. **Once.** If that fails, a typed refusal is returned.

Why once? Adding retries raises the success rate and **grows cost and latency linearly.** And if the model missed the schema twice in a row, a third attempt is unlikely to land — usually the prompt or the schema itself is at fault.

Unbounded retries are especially dangerous: cost can run away before a budget overrun is even detected.

The policy is not a comment — it is encoded in the types this document writes. `ProviderMetadata.retries` is constrained with `Field(ge=0, le=1)`, so a metadata value claiming two retries cannot even be constructed, and `SchemaRejected.attempts` is `Literal[2]` with a default of 2 — a schema rejection is, by type, something that only exists after the repair attempt also failed.

Even on refusal, **the raw response and metadata come back with it.** That is what makes it possible to see later what failed and why. Swallow failures quietly and there is nothing to debug with.

```
Prompt + schema + ProviderBudget → provider call → RawProviderResponse → strict parse
                                                        ↓ failure
                                            one repair prompt → final typed result
```

### What to define, what to implement, and what to inspect

This document builds one file, `app/llm/schemas.py`, in five steps. The provider implementation is the next two documents.

| Area | Learning action | What to take away |
|---|---|---|
| Value vocabulary and `StrictSchema` | **Define the settings schema** | What `strict=True` blocks on top of the field types |
| `Prompt`, `TokenPricing`, `ProviderBudget` | **Write the model declarations** | The allowance fixed before the call |
| The model validator in `AnswerDecision` | **Implement** the exclusivity rule yourself | How label and evidence are kept from contradicting |
| The three failure types | **Write the record declarations** | Why failure is kept as a value rather than a string |
| `ProviderResult` | **Implement** the invariants yourself | How success and failure are kept from both being true |

### 1. Value vocabulary and a fail-closed base

#### Create `app/llm/schemas.py` — module header

**Learning action — define the structure:** `Decimal` is imported. Cost arithmetic does not use floating point.

```python
"""Strict structured-output, budget, and provider-result schemas for M4."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator
```

#### Extend `app/llm/schemas.py` — value vocabulary

**Learning action — define the settings schema:** the first four aliases are constraints — note which invalid value each blocks. The last two are closed vocabularies: they do not constrain a value, they enumerate every value that exists.

<!-- src: app/llm/schemas.py::NonBlank,ProviderStatus -->
```python
NonBlank = Annotated[StrictStr, Field(min_length=1)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
AnswerLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]
ProviderStatus = Literal[
    "ok",
    "schema_rejected",
    "provider_refused",
    "provider_error",
    "budget_exceeded",
]
```

**What to look for in the code**

- `Annotated[StrictStr, Field(min_length=1)]` bundles a type and its constraint under one name. Every field typed `NonBlank` gets the rule without repeating the code, and changing the rule changes it everywhere at once.
- `NonNegativeDecimal` is a `Decimal` with `allow_inf_nan=False`. Handling cost as a `float` puts the 0.1 + 0.2 problem into a billing figure.
- `ProviderStatus` is a `Literal` of five values. `"provider_refused"` (the model declined) and `"provider_error"` (the call itself failed) are **different values**. Collapsing them makes a prompt problem indistinguishable from a network problem. Note the asymmetry too: only four of the five can appear on a refusal — `"ok"` is the one status that never travels with a failure value.

> **Concept — Decimal is exact only if you construct it exactly**
>
> A binary float cannot represent most decimal fractions; 0.1 + 0.2 is famously not 0.3, and the error compounds under arithmetic. Decimal stores decimal digits, so 0.1 + 0.2 is exactly 0.3 — that is why every money field in this file is Decimal-based.
>
> The trap is the constructor. Building a Decimal from a float first commits the binary error and then preserves it faithfully: Decimal(0.4) carries the float's long binary tail, while Decimal("0.4") is exactly four tenths. When a price table is written by hand, values must arrive as strings or integers, never as float literals.

Why a `Literal` and not an `Enum`? A `StrEnum` is what most Python codebases reach for, and it would work. But every M4 boundary value is frozen and must round-trip through JSON traces unchanged; a `Literal` of plain strings serializes as the string itself, compares with `==` against raw stored JSON, and needs no import at any consumer. An enum adds a class that every reader of a stored trace has to reconstruct — for a vocabulary that gains nothing from methods or iteration. Tutorial 6's workflow reason types make the same choice for the same reason.

#### Extend `app/llm/schemas.py` — `StrictSchema` and the budget

**Learning action — write the model declarations:** note the three entries in `StrictSchema`'s `model_config`.

<!-- src: app/llm/schemas.py::StrictSchema,ProviderBudget -->
```python
class StrictSchema(BaseModel):
    """Frozen fail-closed base for all M4 boundary values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Prompt(StrictSchema):
    """System and user text sent through one provider boundary."""

    system: NonBlank
    user: NonBlank

    @field_validator("system", "user", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject whitespace-only prompts without silently normalizing them."""
        if not value.strip():
            raise ValueError("prompt text must not be blank")
        return value


class TokenPricing(StrictSchema):
    """Caller-supplied provider prices in USD per million tokens."""

    input_per_million_usd: NonNegativeDecimal
    output_per_million_usd: NonNegativeDecimal

    def estimate(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Return the exact Decimal estimate for explicit token counts."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be nonnegative")
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * self.input_per_million_usd
            + Decimal(output_tokens) * self.output_per_million_usd
        ) / million


class ProviderBudget(StrictSchema):
    """Remaining cumulative token and estimated-cost allowance for one completion."""

    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    max_cost_usd: NonNegativeDecimal
    pricing: TokenPricing
```

**What to look for in the code**

- `strict=True` goes a level beyond M2.1's `Strict*` types. M2.1's `ChunkHit` config was `extra="forbid", frozen=True` — strictness there lived per field, in the `Strict*` aliases, and a plainly annotated field would silently coerce. Here the switch moves to the **whole model**, so there is no place to forget when adding a field later.
- `ProviderBudget` is built **before** the call — by the caller, never by the provider. Token and cost limits travel with the request, so how much a provider may spend is written in a value rather than in code. The provider never mutates it either: the base is frozen, so tutorial 3's repair path shrinks a per-attempt copy with `model_copy` while the caller's original survives untouched.
- `TokenPricing` lives inside the budget rather than arriving as a sibling argument. A cost ceiling is meaningless without the price table that judges it — passed separately, the two could drift, and a limit set at one price would be enforced at another. Nested, a price change makes the budget object itself differ, so costs computed at the old price never mix with the new.

> **Concept — Coercion, and where the strict switch lives**
>
> By default Pydantic runs in lax mode: the string "5" is accepted where an integer is declared and becomes 5, the integer 5 becomes the float 5.0, "true" becomes True. For web forms that is a convenience; at a boundary that accounts for money and failure states it is silent data rewriting.
>
> There are two places to turn it off. Field level: the Strict* aliases opt individual fields out, which is what M2.1 did — protection exactly where someone remembered to ask for it. Model level: strict=True in the config turns coercion off for every field the model has now and every field anyone adds later.
>
> This file does both. The model config is the primary defense; the Strict* types inside the aliases keep each alias honest even if it is ever reused on a model with a laxer config.

One more thing to notice in this block: `Prompt` carries `reject_blank_text` even though `system` and `user` are already `NonBlank`. The two gates block different strings.

> **Concept — min_length counts characters, strip detects blanks**
>
> The constraint min_length=1 rejects the empty string and nothing else. A single space has length 1 and passes; so does a tab, a newline, or forty spaces. Length is the wrong instrument for "says nothing".
>
> That is what the validator adds: value.strip() collapses whitespace-only text to empty, so the check catches every visually blank string the length rule waves through. The pair is deliberate — the alias blocks the degenerate case at zero cost everywhere, while the validator does the semantic work on the five models that carry free text.
>
> This file repeats the same validator shape five times. Read them as five copies of one gate, not as boilerplate to deduplicate — delete one and whitespace-only text walks into that model alone.

The committed test pins this section's arithmetic to a number: with prices of 2 and 10 USD per million tokens, `estimate(100, 20)` returns exactly `Decimal("0.0004")` — that is 100 × 2 / 1,000,000 + 20 × 10 / 1,000,000, every intermediate value a Decimal, so the test's equality is exact rather than approximate.

```bash
uv run pytest tests/workflow/test_01_schemas.py -k token_pricing -q
```

### 2. Keeping label and evidence from contradicting

#### Extend `app/llm/schemas.py` — relevance and answer decision

**Learning action — implement the exclusivity rule:** implement `AnswerDecision`'s model validator yourself. It is the same shape as M3.1's positive/absent rule.

<!-- src: app/llm/schemas.py::ChunkRelevance,AnswerDecision -->
```python
class ChunkRelevance(StrictSchema):
    """One source chunk graded for relevance by a structured LLM call."""

    chunk_id: PositiveInt
    relevant: StrictBool
    reason: NonBlank

    @field_validator("reason", mode="after")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        """Require an inspectable grading reason."""
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class RelevanceJudgment(StrictSchema):
    """Complete relevance grades for one retrieved candidate set."""

    grades: tuple[ChunkRelevance, ...]

    @model_validator(mode="after")
    def reject_duplicate_chunk_ids(self) -> Self:
        """Prevent one chunk from receiving contradictory duplicate grades."""
        chunk_ids = [grade.chunk_id for grade in self.grades]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("graded chunk ids must be unique")
        return self


class AnswerDecision(StrictSchema):
    """One structured evidence decision produced before workflow code guards it."""

    label: AnswerLabel
    answer: NonBlank
    citation_chunk_ids: tuple[PositiveInt, ...]
    reason: NonBlank

    @field_validator("answer", "reason", mode="after")
    @classmethod
    def reject_blank_decision_text(cls, value: str) -> str:
        """Require visible answer and decision rationale text."""
        if not value.strip():
            raise ValueError("decision text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_label_contract(self) -> Self:
        """Keep supported and absent structured states mutually exclusive."""
        if len(self.citation_chunk_ids) != len(set(self.citation_chunk_ids)):
            raise ValueError("citation chunk ids must be unique")
        if self.label == "SUPPORTED":
            if not self.citation_chunk_ids:
                raise ValueError("SUPPORTED decisions require at least one citation")
            if self.answer == "NOT_IN_DOCS":
                raise ValueError("SUPPORTED decisions require a supported answer")
        else:
            if self.answer != "NOT_IN_DOCS":
                raise ValueError("NOT_IN_DOCS decisions must use the NOT_IN_DOCS answer")
            if self.citation_chunk_ids:
                raise ValueError("NOT_IN_DOCS decisions must not contain citations")
        return self
```

**What to look for in the code**

- `SUPPORTED` with empty `citation_chunk_ids` is rejected. **A supported answer with no evidence** is the first failure M4 has to stop. The same branch rejects a second, separate contradiction: `SUPPORTED` paired with the literal answer `NOT_IN_DOCS`.
- `NOT_IN_DOCS` carrying citations is rejected. Claiming "not in the documents" while citing documents is a contradiction.
- The exclusivity rule M3.1's `GoldenCase` established on the ground-truth side is set up here on the **model-output side**. Evaluation and execution hold contracts of the same shape.
- The two model validators in this block share one signature: `@model_validator(mode="after")` returning `Self`. After-mode runs on the fully built, typed instance, so the check can read several fields at once and hand back the object itself; this file uses the signature six times, always for cross-field facts no single field can see.

### 3. Failure as a value, not a string

#### Extend `app/llm/schemas.py` — raw response and failure types

**Learning action — write the record declarations:** note which evidence each of the three failure types carries.

<!-- src: app/llm/schemas.py::RawProviderResponse,CompletionFailure -->
```python
class RawProviderResponse(StrictSchema):
    """Provider-neutral raw response used by adapters and deterministic tests."""

    output_text: StrictStr
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    request_id: StrictStr | None = None
    refusal: StrictStr | None = None

    @field_validator("request_id", "refusal", mode="after")
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        """Reject present-but-empty identifiers and refusals."""
        if value is not None and not value.strip():
            raise ValueError("optional provider text must not be blank")
        return value


class SchemaRejected(StrictSchema):
    """Typed fail-closed result after one repair attempt also fails."""

    status: Literal["schema_rejected"] = "schema_rejected"
    errors: tuple[NonBlank, ...]
    attempts: Literal[2] = 2

    @model_validator(mode="after")
    def require_errors(self) -> Self:
        """Require the final validation failure to remain inspectable."""
        if not self.errors:
            raise ValueError("schema rejection requires validation errors")
        return self


class BudgetExceeded(StrictSchema):
    """Typed refusal when a call or repair cannot continue within its budget."""

    status: Literal["budget_exceeded"] = "budget_exceeded"
    which: Literal["input_tokens", "output_tokens", "estimated_cost_usd"]
    used: StrictInt | Decimal
    limit: StrictInt | Decimal
    attempts: Annotated[StrictInt, Field(ge=1, le=2)]

    @model_validator(mode="after")
    def validate_nonnegative_values(self) -> Self:
        """Reject nonsensical negative budget evidence."""
        if self.used < 0 or self.limit < 0:
            raise ValueError("budget evidence must be nonnegative")
        if isinstance(self.used, Decimal) and not self.used.is_finite():
            raise ValueError("used budget evidence must be finite")
        if isinstance(self.limit, Decimal) and not self.limit.is_finite():
            raise ValueError("budget limit evidence must be finite")
        return self


class ProviderRefusal(StrictSchema):
    """Typed model refusal or provider-boundary error."""

    status: Literal["provider_refused", "provider_error"]
    message: NonBlank
    attempts: Annotated[StrictInt, Field(ge=1, le=2)]

    @field_validator("message", mode="after")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        """Keep provider failures explicit and visible."""
        if not value.strip():
            raise ValueError("provider refusal message must not be blank")
        return value


type CompletionFailure = SchemaRejected | BudgetExceeded | ProviderRefusal
```

**What to look for in the code**

- `RawProviderResponse` is built **before** schema parsing — born inside `_request`, the adapter written in tutorial 3, as the last provider-neutral stop between an SDK response and our parsing. Even when parsing fails, what the model actually said survives: its `output_text` is appended to the metadata's raw-output history on every path.
- There are three failure types, each carrying only the evidence its own path can produce. `SchemaRejected` holds the final validation errors and the attempt count — not the raw output, which lives in `ProviderMetadata.raw_outputs` and is reached through the result's `metadata`. `BudgetExceeded` holds which limit was passed, the amount used, and the limit itself. `ProviderRefusal` holds the refusal reason.
- `CompletionFailure` is the union of the three. A caller handling them with `match` gets a type checker that catches the missing branch.

Why three sibling classes instead of one failure type with optional fields? A single grab-bag — `errors`, `which`, `message` all optional on one class — would reintroduce inside the failure value exactly the disease this file exists to cure: states holding the wrong combination of fields, or none at all, would construct cleanly. Three siblings mean each failure can only carry the evidence its path actually produces. The same logic keeps `raw_outputs` off `SchemaRejected`: raw output exists on every outcome including success, so its home is the metadata every result carries, not one failure branch.

> **Concept — A Literal default is a claim, not a convenience**
>
> SchemaRejected declares attempts as Literal[2] with a default of 2. That is not "the usual value" — it is a type-level assertion that this failure can only exist after exactly two attempts, because a schema rejection is by definition the state after the one repair also failed. No code path can construct one with a different count, and no test needs to check for it.
>
> BudgetExceeded makes the opposite statement with the opposite mechanism: its attempts is a strict integer constrained to 1 or 2, because a budget can die on the first call or on the repair. There the count is evidence that varies, so it is data with bounds rather than a constant.
>
> Read the two side by side and the intro's policy — repair happens exactly once — stops being prose. It is encoded once as a constant and once as a range.

> **Concept — This union is bare on purpose**
>
> All three members carry a status field typed as a one- or two-value Literal, which is exactly the shape a discriminated union wants. Yet the union declares no discriminator. The static story does not need one: a match over the three classes dispatches on the class itself, and the type checker flags a missing branch either way.
>
> A discriminator matters at runtime, when a union is parsed back from JSON. Without one, Pydantic falls back to smart-union scoring — try the members, keep the best fit — which works but produces error messages listing every member's complaints. In this module that path never runs: failure values are constructed in Python with the concrete class already chosen, and no code here parses a CompletionFailure back out of JSON.
>
> Tutorial 6 meets the same shape under the opposite constraint — its reason union does round-trip through stored JSON — and there the union declares a discriminator. Same pattern, different lifecycle, different choice.

### 4. Keeping success and failure from both being true

#### Complete `app/llm/schemas.py` — metadata and result

**Learning action — implement the invariants:** implement `ProviderResult`'s validator yourself. The relationship between `status` and `parsed`/`refusal` is the point.

<!-- src: app/llm/schemas.py::ProviderMetadata,ProviderResult -->
```python
class ProviderMetadata(StrictSchema):
    """Trace-ready provider identity, usage, latency, raw output, and retry data."""

    provider: NonBlank
    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    estimated_cost_usd: NonNegativeDecimal
    request_time_ms: Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
    retries: Annotated[StrictInt, Field(ge=0, le=1)]
    request_ids: tuple[StrictStr, ...]
    llm_output: StrictStr
    raw_outputs: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def validate_attempt_metadata(self) -> Self:
        """Keep final output and retry count consistent with captured attempts."""
        if any(not value.strip() for value in (self.provider, self.model_name, self.api_url)):
            raise ValueError("provider identity fields must not be blank")
        if any(not request_id.strip() for request_id in self.request_ids):
            raise ValueError("request ids must not be blank")
        if not self.raw_outputs:
            raise ValueError("provider metadata requires at least one raw output")
        if len(self.raw_outputs) != self.retries + 1:
            raise ValueError("raw output count must equal retries plus one")
        if self.llm_output != self.raw_outputs[-1]:
            raise ValueError("llm_output must equal the final raw output")
        if len(self.request_ids) > len(self.raw_outputs):
            raise ValueError("request ids cannot outnumber provider attempts")
        return self


class ProviderResult[OutputT: BaseModel](StrictSchema):
    """Typed successful output or typed refusal with trace-ready metadata."""

    status: ProviderStatus
    parsed: OutputT | None
    refusal: CompletionFailure | None
    metadata: ProviderMetadata

    @model_validator(mode="after")
    def validate_result_state(self) -> Self:
        """Require exactly one success output or matching typed refusal."""
        if self.status == "ok":
            if self.parsed is None or self.refusal is not None:
                raise ValueError("successful provider results require only parsed output")
        else:
            if self.parsed is not None or self.refusal is None:
                raise ValueError("failed provider results require only a typed refusal")
            if self.refusal.status != self.status:
                raise ValueError("provider result status must match refusal status")
        return self
```

**What to look for in the code**

- `ProviderResult[OutputT: BaseModel]` is generic. Nodes use different output schemas while the boundary stays single.
- With `status == "ok"` there is a `parsed` and no `refusal`. Otherwise the reverse. A state with both, or with neither, cannot be constructed.
- Even though `refusal` already knows its status, `status` is stored top-level — deliberate redundancy. Deriving it would leave `"ok"` results without one and force every trace consumer to compute it; stored, every result carries one queryable field, and the validator's last check turns the duplication from a drift risk into an enforced equality.
- `metadata` attaches to both success and failure. A failed call still spent tokens and money, so leaving it out of the totals leaks budget silently.
- `ProviderMetadata` carries retry request IDs and raw outputs under validator-pinned lifecycle invariants: the raw-output tuple's length must equal `retries + 1` — one entry per attempt, in order — its last element must equal `llm_output`, and request IDs may never outnumber attempts. Every attempt stays traceable without depending on one provider SDK.

### Focused tests and the contracts they protect

```bash
WORKFLOW_MODULE=app.llm.schemas uv run pytest tests/workflow/test_01_schemas.py -q
```

The `WORKFLOW_MODULE` override points the harness at the module you just wrote; the package-level command works once tutorial 3's `__init__.py` exists.

| Value the test breaks | Contract being protected |
|---|---|
| `SUPPORTED` with no citations | A supported answer with no evidence is never built. |
| `NOT_IN_DOCS` carrying citations | Label and evidence never contradict. |
| A result holding both `parsed` and `refusal` | Success and failure cannot both be true. |
| A cost arriving as `float` | Floating-point error never enters a billing figure. |
| An unknown extra field | A typo never passes at a boundary value. |

The suite behind that command holds 11 test functions, and the five rows above map to named tests. The first two rows are `test_supported_decision_requires_unique_citations_and_non_absent_answer` and `test_not_in_docs_decision_requires_literal_answer_and_no_citations`. The third is `test_provider_result_requires_exactly_one_output_or_matching_refusal`, which constructs the mismatched-status and the neither-value states — the both-values state dies on the same validator branch. The cost row is pinned twice: `test_token_pricing_uses_exact_decimal_arithmetic` proves the exact arithmetic, and `test_provider_budget_requires_explicit_strict_limits_and_pricing` feeds a bool where a token count belongs plus a negative cost. The extra-field row is the `extra=True` case in `test_prompt_is_strict_frozen_and_forbids_unknown_fields`. The remaining tests pin the whitespace gate, duplicate grades, the required-errors rule, negative budget evidence, and the metadata attempt invariants — every contract in this file is exercised by at least one committed test.

### What you should be able to explain now

- **What differs per node when the boundary is not gathered in one place?**
  - **Answer:** Retry policy, JSON parsing, failure handling, and token accounting can each follow a different contract.
- **Why is the repair prompt sent only once?**
  - **Answer:** Additional attempts increase cost and latency linearly, while two schema failures usually indicate that the prompt or schema needs correction.
- **Why are `provider_refused` and `provider_error` separate?**
  - **Answer:** A refusal means the model deliberately declined, while an error means the call or infrastructure failed; callers need that distinction to diagnose and respond correctly.
- **What leaks if a failed call's `metadata` is discarded?**
  - **Answer:** Its spent tokens, cost, latency, retry IDs, and raw outputs disappear from tracing, so consumed budget silently leaks out of the totals.
- **Why is cost held as a `Decimal`?**
  - **Answer:** Billing arithmetic needs exact decimal values rather than binary floating-point rounding drift.

---

[Module overview](../03-build.md) · [Next: Provider boundary →](02-provider.md)
