"""Strict structured-output, budget, and provider-result schemas for M4."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)
from pydantic.functional_validators import model_validator


def _reject_blank(value: str) -> str:
    """Reject text that is present but carries no visible character."""
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


NonBlank = Annotated[StrictStr, Field(min_length=1), AfterValidator(_reject_blank)]

#: Longest grade rationale kept: about twenty words, so five grades cost far less than the
#: 600-token local output allowance the grade and check calls share.
GRADE_REASON_MAX_CHARS = 160


def _truncate_reason(value: object) -> object:
    """Cut an over-long rationale at its last word boundary instead of rejecting it.

    Constrained decoders honour the schema's ``maxLength``; providers that ignore it would
    otherwise turn a wordy but correct grade into a schema failure and a repair round.
    """
    if isinstance(value, str) and len(value) > GRADE_REASON_MAX_CHARS:
        head = value[:GRADE_REASON_MAX_CHARS]
        cut = head.rfind(" ")
        return (head[:cut] if cut > GRADE_REASON_MAX_CHARS // 2 else head).rstrip()
    return value


BoundedReason = Annotated[
    StrictStr,
    BeforeValidator(_truncate_reason),
    Field(min_length=1, max_length=GRADE_REASON_MAX_CHARS),
    AfterValidator(_reject_blank),
]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
AnswerLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]
ProviderStatus = Literal[
    "ok",
    "schema_rejected",
    "provider_refused",
    "provider_error",
    "budget_exceeded",
]


class StrictSchema(BaseModel):
    """Frozen fail-closed base for all M4 boundary values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Prompt(StrictSchema):
    """System and user text sent through one provider boundary."""

    system: NonBlank
    user: NonBlank


class TokenPricing(StrictSchema):
    """Provider prices in USD per million detailed token categories."""

    input_per_million_usd: NonNegativeDecimal
    output_per_million_usd: NonNegativeDecimal
    cached_input_per_million_usd: NonNegativeDecimal | None = None
    cache_write_input_per_million_usd: NonNegativeDecimal | None = None

    def estimate(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        cached_input_tokens: int = 0,
        cache_write_input_tokens: int = 0,
    ) -> Decimal:
        """Return the exact cost estimate for explicit token counts.

        Parameters
        ----------
        input_tokens : int
            Nonnegative input-token count.
        output_tokens : int
            Nonnegative output-token count.

        Returns
        -------
        Decimal
            Estimated USD cost without binary floating-point rounding.

        Raises
        ------
        ValueError
            If either token count is negative.
        """
        if any(
            value < 0
            for value in (
                input_tokens,
                output_tokens,
                cached_input_tokens,
                cache_write_input_tokens,
            )
        ):
            raise ValueError("token counts must be nonnegative")
        detailed_input = cached_input_tokens + cache_write_input_tokens
        if detailed_input > input_tokens:
            raise ValueError("detailed input tokens must not exceed input_tokens")
        regular_input_tokens = input_tokens - detailed_input
        cached_price = (
            self.input_per_million_usd
            if self.cached_input_per_million_usd is None
            else self.cached_input_per_million_usd
        )
        cache_write_price = (
            self.input_per_million_usd
            if self.cache_write_input_per_million_usd is None
            else self.cache_write_input_per_million_usd
        )
        million = Decimal(1_000_000)
        return (
            Decimal(regular_input_tokens) * self.input_per_million_usd
            + Decimal(cached_input_tokens) * cached_price
            + Decimal(cache_write_input_tokens) * cache_write_price
            + Decimal(output_tokens) * self.output_per_million_usd
        ) / million


class ProviderBudget(StrictSchema):
    """Remaining cumulative token and estimated-cost allowance for one completion."""

    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    max_cost_usd: NonNegativeDecimal
    pricing: TokenPricing

    def exhausted_by(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        cache_write_input_tokens: int = 0,
        attempts: int,
        inclusive: bool = False,
        schema_errors: tuple[str, ...] = (),
    ) -> BudgetExceeded | None:
        """Return the first hard limit the accumulated usage has reached.

        Parameters
        ----------
        input_tokens : int
            Accumulated input-token usage.
        output_tokens : int
            Accumulated output-token usage.
        attempts : int
            Number of provider requests the evidence represents.
        inclusive : bool
            Treat a limit reached exactly as exhausted. A completed attempt is judged
            exclusively, because spending the whole allowance is allowed; asking whether
            another request may start is judged inclusively, because the next request
            needs capacity left over.
        schema_errors : tuple[str, ...]
            Validation failure that a blocked repair would have addressed.

        Returns
        -------
        BudgetExceeded | None
            Typed evidence for the first exhausted limit, otherwise ``None``.

        Notes
        -----
        This is the single definition of provider-budget exhaustion. Both the provider
        boundary and the workflow's pre-call gate ask it, so neither can drift into
        admitting a call the other would refuse. A zero-priced provider never exhausts a
        zero cost ceiling, so the inclusive cost boundary applies only when at least one
        token price is positive.
        """
        spent = self.pricing.estimate(
            input_tokens,
            output_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
        )

        def reached(used: int | Decimal, limit: int | Decimal) -> bool:
            """Compare one usage against its limit on the requested boundary."""
            return used >= limit if inclusive else used > limit

        def failure(
            which: Literal["input_tokens", "output_tokens", "estimated_cost_usd"],
            used: int | Decimal,
            limit: int | Decimal,
        ) -> BudgetExceeded:
            """Build the typed evidence for one exhausted limit."""
            return BudgetExceeded(
                which=which,
                used=used,
                limit=limit,
                attempts=attempts,
                schema_errors=schema_errors,
            )

        if reached(input_tokens, self.max_input_tokens):
            return failure("input_tokens", input_tokens, self.max_input_tokens)
        if reached(output_tokens, self.max_output_tokens):
            return failure("output_tokens", output_tokens, self.max_output_tokens)
        priced = self.pricing.input_per_million_usd > 0 or self.pricing.output_per_million_usd > 0
        if (priced or not inclusive) and reached(spent, self.max_cost_usd):
            return failure("estimated_cost_usd", spent, self.max_cost_usd)
        return None


class ChunkRelevance(StrictSchema):
    """One source chunk graded for relevance by a structured LLM call."""

    chunk_id: PositiveInt
    relevant: StrictBool
    reason: BoundedReason


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


class LocalModelTiming(StrictSchema):
    """Optional authoritative Ollama metrics for one received provider attempt."""

    attempt: PositiveInt = 1
    total_duration_ms: NonNegativeFloat | None = None
    load_duration_ms: NonNegativeFloat | None = None
    prompt_eval_duration_ms: NonNegativeFloat | None = None
    eval_duration_ms: NonNegativeFloat | None = None
    prompt_eval_count: NonNegativeInt | None = None
    eval_count: NonNegativeInt | None = None


class RawProviderResponse(StrictSchema):
    """Provider-neutral raw response used by adapters and deterministic tests."""

    output_text: StrictStr
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt = 0
    cache_write_input_tokens: NonNegativeInt = 0
    reasoning_tokens: NonNegativeInt = 0
    request_id: NonBlank | None = None
    refusal: NonBlank | None = None
    local_timing: LocalModelTiming | None = None

    @model_validator(mode="after")
    def validate_usage_details(self) -> Self:
        """Keep provider detail counters within their authoritative totals."""
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ValueError("detailed input tokens must not exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens must not exceed output_tokens")
        return self


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
    """Typed refusal when a call or repair cannot continue within its budget.

    ``schema_errors`` carries the validation failure of the attempt whose repair the
    budget blocked. A budget that runs out before anything failed validation leaves it
    empty; without it a repair blocked at the exact boundary would report only that the
    budget stopped, never that the output was also unusable.
    """

    status: Literal["budget_exceeded"] = "budget_exceeded"
    which: Literal["input_tokens", "output_tokens", "estimated_cost_usd"]
    used: StrictInt | Decimal
    limit: StrictInt | Decimal
    #: Requests actually sent before the refusal; zero when the first attempt was refused
    #: from its projected size and nothing reached the provider.
    attempts: Annotated[StrictInt, Field(ge=0, le=2)]
    schema_errors: tuple[NonBlank, ...] = ()
    #: Estimated size of the request that was refused before it was sent. ``used`` stays
    #: actual usage, so an estimate never inflates reported accounting.
    projected_input_tokens: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_nonnegative_values(self) -> Self:
        """Reject nonsensical negative budget evidence and misplaced projections."""
        if self.used < 0 or self.limit < 0:
            raise ValueError("budget evidence must be nonnegative")
        if self.projected_input_tokens is not None and self.which != "input_tokens":
            raise ValueError("a projected prompt size applies to the input token budget only")
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


type CompletionFailure = SchemaRejected | BudgetExceeded | ProviderRefusal


class ProviderMetadata(StrictSchema):
    """Trace-ready provider identity, usage, latency, raw output, and retry data."""

    provider: NonBlank
    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt = 0
    cache_write_input_tokens: NonNegativeInt = 0
    reasoning_tokens: NonNegativeInt = 0
    estimated_cost_usd: NonNegativeDecimal
    request_time_ms: NonNegativeFloat
    retries: Annotated[StrictInt, Field(ge=0, le=1)]
    request_ids: tuple[NonBlank, ...]
    llm_output: StrictStr
    raw_outputs: tuple[StrictStr, ...]
    local_timings: tuple[LocalModelTiming, ...] = ()
    #: Requests actually sent to the provider: one per raw output, or zero when the only
    #: attempt was refused before the call. Defaults to the captured attempts.
    requests: NonNegativeInt
    #: Set when the final attempt was refused before the call from its projected size.
    projected_input_tokens: NonNegativeInt | None = None

    @model_validator(mode="before")
    @classmethod
    def default_requests(cls, data: object) -> object:
        """Count one request per captured raw output unless the caller states otherwise."""
        if isinstance(data, dict) and data.get("requests") is None:
            outputs = data.get("raw_outputs")
            data = {**data, "requests": len(outputs) if isinstance(outputs, tuple | list) else 1}
        return data

    @model_validator(mode="after")
    def validate_attempt_metadata(self) -> Self:
        """Keep final output, retry count and sent requests consistent with captured attempts."""
        if self.requests == 0:
            if self.raw_outputs or self.retries or self.request_ids or self.llm_output:
                raise ValueError("a refusal before any request carries no provider output")
            if self.input_tokens or self.output_tokens:
                raise ValueError("a refusal before any request carries no usage")
            return self
        if not self.raw_outputs:
            raise ValueError("provider metadata requires at least one raw output")
        if len(self.raw_outputs) != self.retries + 1 or self.requests != len(self.raw_outputs):
            raise ValueError("raw output count must equal retries plus one and sent requests")
        if self.llm_output != self.raw_outputs[-1]:
            raise ValueError("llm_output must equal the final raw output")
        if len(self.request_ids) > len(self.raw_outputs):
            raise ValueError("request ids cannot outnumber provider attempts")
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ValueError("detailed input tokens must not exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens must not exceed output_tokens")
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
