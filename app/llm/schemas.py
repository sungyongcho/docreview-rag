"""Strict structured-output, budget, and provider-result schemas for M4."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
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


class StrictSchema(BaseModel):
    """Frozen fail-closed base for all M4 boundary values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Prompt(StrictSchema):
    """System and user text sent through one provider boundary."""

    system: NonBlank
    user: NonBlank


class TokenPricing(StrictSchema):
    """Caller-supplied provider prices in USD per million tokens."""

    input_per_million_usd: NonNegativeDecimal
    output_per_million_usd: NonNegativeDecimal

    def estimate(self, input_tokens: int, output_tokens: int) -> Decimal:
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


class ChunkRelevance(StrictSchema):
    """One source chunk graded for relevance by a structured LLM call."""

    chunk_id: PositiveInt
    relevant: StrictBool
    reason: NonBlank


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


class RawProviderResponse(StrictSchema):
    """Provider-neutral raw response used by adapters and deterministic tests."""

    output_text: StrictStr
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    request_id: NonBlank | None = None
    refusal: NonBlank | None = None


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
    attempts: Annotated[StrictInt, Field(ge=1, le=2)]
    schema_errors: tuple[NonBlank, ...] = ()

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


type CompletionFailure = SchemaRejected | BudgetExceeded | ProviderRefusal


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
    request_ids: tuple[NonBlank, ...]
    llm_output: StrictStr
    raw_outputs: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def validate_attempt_metadata(self) -> Self:
        """Keep final output and retry count consistent with captured attempts."""
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
