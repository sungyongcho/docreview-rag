"""Strict value objects for the M9 tool-calling agent."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import model_validator

type AgentStatus = Literal["ok", "no_answer", "budget_exceeded", "provider_error"]

NonBlank = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
NonnegativeFloat = Annotated[StrictFloat, Field(ge=0)]


class StrictAgentModel(BaseModel):
    """Frozen fail-closed base for every M9 boundary value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AgentBudget(StrictAgentModel):
    """Hard limits one agent run may never exceed.

    The limits are cumulative across every iteration of a run, so a model that
    burns tokens exploring cannot spend what the final answer would need.
    """

    max_iterations: Annotated[StrictInt, Field(gt=0, le=64)] = 8
    max_total_input_tokens: PositiveInt = 60_000
    max_total_output_tokens: PositiveInt = 8_000


class ToolCall(StrictAgentModel):
    """One tool invocation requested by the model, with raw JSON arguments."""

    call_id: NonBlank
    name: NonBlank
    arguments_json: StrictStr


class Observation(StrictAgentModel):
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


class StepUsage(StrictAgentModel):
    """Provider accounting for one agent iteration."""

    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    request_time_ms: NonnegativeFloat
    retries: NonnegativeInt = 0


class AgentStep(StrictAgentModel):
    """One Thought → Tool → Observation iteration with full provenance."""

    step: PositiveInt
    output_text: StrictStr
    tool_calls: tuple[ToolCall, ...]
    observations: tuple[Observation, ...]
    usage: StepUsage

    @model_validator(mode="after")
    def observations_match_calls(self) -> Self:
        """Reject observations that answer a call this step never made."""
        call_ids = {call.call_id for call in self.tool_calls}
        for observation in self.observations:
            if observation.call_id not in call_ids:
                raise ValueError("observation call_id does not match any tool call")
        return self


class AgentCitation(StrictAgentModel):
    """One retrieved chunk the final answer stands on."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    citation: NonBlank


class AgentAnswer(StrictAgentModel):
    """The structured final answer with the M4 label and citation contract."""

    label: Literal["SUPPORTED", "NOT_IN_DOCS"]
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
                raise ValueError("NOT_IN_DOCS answers must use the NOT_IN_DOCS answer")
            if self.citations:
                raise ValueError("NOT_IN_DOCS answers must not carry citations")
        return self


class AgentResult(StrictAgentModel):
    """One terminal agent run: an answer or a typed failure, never both."""

    status: AgentStatus
    answer: AgentAnswer | None
    failure: NonBlank | None
    iterations: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
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
