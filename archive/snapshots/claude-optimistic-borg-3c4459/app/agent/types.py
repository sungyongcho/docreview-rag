"""Strict value objects for the M9 tool-calling agent."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr
from pydantic.functional_validators import model_validator

from app.llm.schemas import (
    AnswerLabel,
    NonBlank,
    NonNegativeDecimal,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    StrictSchema,
)
from app.retrieval.types import SourceSha256

type AgentStatus = Literal["ok", "budget_exceeded", "provider_error"]


class AgentBudget(StrictSchema):
    """Hard limits one agent run may never exceed.

    The limits are cumulative across every iteration of a run, so a model that
    burns tokens exploring cannot spend what the final answer would need.
    """

    max_iterations: Annotated[StrictInt, Field(gt=0, le=64)] = 8
    max_total_input_tokens: PositiveInt = 60_000
    max_total_output_tokens: PositiveInt = 8_000
    max_total_cost_usd: NonNegativeDecimal = Decimal("0.25")


class ToolCall(StrictSchema):
    """One tool invocation requested by the model, with raw JSON arguments."""

    call_id: NonBlank
    name: NonBlank
    arguments_json: StrictStr


class Observation(StrictSchema):
    """The explicit result the loop feeds back for one tool call.

    Errors are observations too: a failed call must come back as a typed
    message the model can read, never as a silently dropped step.
    """

    call_id: NonBlank
    name: NonBlank
    output_json: StrictStr = ""
    error: NonBlank | None = None

    @model_validator(mode="after")
    def require_output_or_error(self) -> Self:
        """Keep successful output and typed failure mutually exclusive."""
        if self.error is None and not self.output_json:
            raise ValueError("observations require output_json or an error")
        if self.error is not None and self.output_json:
            raise ValueError("failed observations must not also carry output")
        return self


class StepUsage(StrictSchema):
    """Provider accounting for one agent iteration."""

    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt = 0
    cache_write_input_tokens: NonNegativeInt = 0
    reasoning_tokens: NonNegativeInt = 0
    estimated_cost_usd: NonNegativeDecimal = Decimal("0")
    request_time_ms: NonNegativeFloat
    retries: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_usage_details(self) -> Self:
        """Keep detailed token counters within their provider totals."""
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ValueError("detailed input tokens must not exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens must not exceed output_tokens")
        return self


class AgentStep(StrictSchema):
    """One Thought → Tool → Observation iteration with full provenance."""

    step: PositiveInt
    output_text: StrictStr
    tool_calls: tuple[ToolCall, ...]
    observations: tuple[Observation, ...]
    usage: StepUsage

    @model_validator(mode="after")
    def observations_match_calls(self) -> Self:
        """Reject ambiguous calls and observations that do not match their call."""
        call_ids = [call.call_id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call ids must be unique within one step")
        calls_by_id = {call.call_id: call for call in self.tool_calls}
        observation_ids = [observation.call_id for observation in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation call ids must be unique within one step")
        for observation in self.observations:
            call = calls_by_id.get(observation.call_id)
            if call is None:
                raise ValueError("observation call_id does not match any tool call")
            if observation.name != call.name:
                raise ValueError("observation name does not match its tool call")
        return self


class AgentCitation(StrictSchema):
    """Complete immutable identity of one retrieved chunk supporting the answer."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    citation: NonBlank
    start_char: NonNegativeInt
    end_char: PositiveInt
    source_sha256: SourceSha256

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Require a nonempty half-open source interval."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


class AgentAnswer(StrictSchema):
    """The structured final answer with the M4 label and citation contract."""

    label: AnswerLabel
    answer: NonBlank
    citations: tuple[AgentCitation, ...]
    rationale: NonBlank

    @model_validator(mode="after")
    def validate_label_contract(self) -> Self:
        """Keep supported and absent answers mutually exclusive."""
        chunk_ids = [citation.chunk_id for citation in self.citations]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("citation chunk ids must be unique")
        if self.label == "SUPPORTED":
            if not self.citations:
                raise ValueError("SUPPORTED answers require at least one citation")
            if self.answer == "NOT_IN_DOCS":
                raise ValueError("SUPPORTED answers require a supported answer")
        else:
            if self.answer != "NOT_IN_DOCS":
                raise ValueError(
                    'NOT_IN_DOCS answers must use exactly the string "NOT_IN_DOCS" as the answer'
                )
            if self.citations:
                raise ValueError("NOT_IN_DOCS answers must not carry citations")
        return self


class AgentResult(StrictSchema):
    """One terminal agent run: an answer or a typed failure, never both."""

    status: AgentStatus
    answer: AgentAnswer | None
    failure: NonBlank | None
    iterations: NonNegativeInt
    total_input_tokens: NonNegativeInt
    total_output_tokens: NonNegativeInt
    total_cached_input_tokens: NonNegativeInt = 0
    total_cache_write_input_tokens: NonNegativeInt = 0
    total_reasoning_tokens: NonNegativeInt = 0
    total_estimated_cost_usd: NonNegativeDecimal = Decimal("0")
    total_time_seconds: NonNegativeFloat
    steps: tuple[AgentStep, ...]

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Keep success and failure states mutually exclusive."""
        if self.status == "ok":
            if self.answer is None or self.failure is not None:
                raise ValueError("successful runs require an answer and no failure")
        else:
            if self.answer is not None or self.failure is None:
                raise ValueError("failed runs require a failure and no answer")
        return self
