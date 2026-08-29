"""Strict value objects for workflow traces, reports, and budgets."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StrictStr
from pydantic.functional_validators import field_validator, model_validator

from app.llm.schemas import (
    NonBlank,
    NonNegativeDecimal,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    StrictSchema,
)

WorkflowNode = Literal["retrieve", "grade", "check", "report"]
RunStatus = Literal["ok", "budget_exceeded", "schema_rejected", "error"]
JsonObject = dict[str, JsonValue]

RunId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]


class StepTrace(StrictSchema):
    """One raw, traceable workflow step before persistence redaction."""

    step: PositiveInt
    node: WorkflowNode
    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    estimated_cost_usd: NonNegativeDecimal
    request_time_ms: NonNegativeFloat
    llm_output: StrictStr
    retries: NonNegativeInt
    error: NonBlank | None = None


class RunReport(StrictSchema):
    """One complete or structured-failure workflow run."""

    run_id: RunId
    status: RunStatus
    iterations: NonNegativeInt
    total_requests: NonNegativeInt
    total_input_tokens: NonNegativeInt
    total_output_tokens: NonNegativeInt
    total_time_seconds: NonNegativeFloat
    system_prompt: NonBlank
    node_path: tuple[WorkflowNode, ...]
    report: JsonObject | None
    steps: tuple[StepTrace, ...]

    @field_validator("report", mode="after")
    @classmethod
    def reject_nonfinite_json(cls, value: JsonObject | None) -> JsonObject | None:
        """Keep the report compatible with strict PostgreSQL JSONB serialization."""

        def validate(child: object) -> None:
            """Reject any non-finite number anywhere in the nested report."""
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
        for name, expected in derived_totals(node_path=self.node_path, steps=self.steps).items():
            if getattr(self, name) != expected:
                raise ValueError(f"{name} must equal the total derived from node_path and steps")
        return self


class Budget(StrictSchema):
    """Hard cumulative limits checked immediately before entering a node."""

    max_iterations: NonNegativeInt = 6
    max_input_tokens: NonNegativeInt = 60_000
    max_output_tokens: NonNegativeInt = 4_000
    max_wall_clock_s: NonNegativeFloat = 120.0


def derived_totals(
    *,
    node_path: tuple[WorkflowNode, ...] | list[WorkflowNode],
    steps: tuple[StepTrace, ...] | list[StepTrace],
) -> dict[str, int]:
    """Return the cumulative counters implied by the entered nodes and raw traces.

    The keys are ``RunReport`` field names, so this is the single definition both the
    report builder and the report validator derive their totals from.
    """
    return {
        "iterations": len(node_path),
        "total_requests": sum(1 + trace.retries for trace in steps),
        "total_input_tokens": sum(trace.input_tokens for trace in steps),
        "total_output_tokens": sum(trace.output_tokens for trace in steps),
    }


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
    """Build a report whose cumulative counters derive from raw traces.

    Parameters
    ----------
    run_id : str
        Stable workflow-run identifier.
    status : RunStatus
        Final success or structured-failure status.
    total_time_seconds : float
        Nonnegative elapsed workflow time.
    system_prompt : str
        Prompt provenance retained with the run.
    node_path : tuple[WorkflowNode, ...] | list[WorkflowNode]
        Entered nodes in execution order.
    steps : tuple[StepTrace, ...] | list[StepTrace]
        Provider traces in contiguous step order.
    report : JsonObject | None
        Final guarded output or structured failure payload.

    Returns
    -------
    RunReport
        Strict report with all counters derived from ``node_path`` and ``steps``.
    """
    trace_values = tuple(steps)
    totals = derived_totals(node_path=node_path, steps=trace_values)
    return RunReport(
        run_id=run_id,
        status=status,
        iterations=totals["iterations"],
        total_requests=totals["total_requests"],
        total_input_tokens=totals["total_input_tokens"],
        total_output_tokens=totals["total_output_tokens"],
        total_time_seconds=total_time_seconds,
        system_prompt=system_prompt,
        node_path=tuple(node_path),
        report=report,
        steps=trace_values,
    )


def validate_elapsed_seconds(value: object) -> float:
    """Validate an externally measured monotonic duration without coercion.

    Parameters
    ----------
    value : object
        Candidate duration supplied by an external clock.

    Returns
    -------
    float
        Finite nonnegative duration.

    Raises
    ------
    ValueError
        If the value is not a float or is negative or non-finite.
    """
    if isinstance(value, bool) or not isinstance(value, float):
        raise ValueError("elapsed_seconds must be a finite nonnegative float")
    if not math.isfinite(value) or value < 0:
        raise ValueError("elapsed_seconds must be a finite nonnegative float")
    return value
