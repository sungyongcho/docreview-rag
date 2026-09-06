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
