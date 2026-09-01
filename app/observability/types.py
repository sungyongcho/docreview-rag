"""Strict value objects for workflow traces, reports, and budgets."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import math
from types import MappingProxyType
from typing import Annotated, Final, Literal, Self

from pydantic import Field, JsonValue, StrictFloat, StrictInt, StrictStr
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
BudgetResource = Literal["iterations", "input_tokens", "output_tokens", "wall_clock_s"]
JsonObject = dict[str, JsonValue]

# Single definition of the run-id grammar. The API response schema and the route path
# parameters validate against this same pattern, so a persisted run id can never be
# accepted by one boundary and rejected by another.
RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
RunId = Annotated[StrictStr, Field(pattern=RUN_ID_PATTERN)]

_PACING_RESOURCES: tuple[BudgetResource, ...] = ("iterations", "wall_clock_s")
_PROVIDER_RESOURCES: tuple[BudgetResource, ...] = (
    "iterations",
    "input_tokens",
    "output_tokens",
    "wall_clock_s",
)

# A node is refused only on the resources it can actually consume. `retrieve` and
# `report` issue no provider call, so blocking them on token exhaustion cannot prevent
# any spend — it only discards work the run has already paid for. Declaring the draw per
# node means a fifth node must state its resource class instead of silently inheriting
# the wrong one.
NODE_BUDGET_RESOURCES: Final[Mapping[WorkflowNode, tuple[BudgetResource, ...]]] = MappingProxyType(
    {
        "retrieve": _PACING_RESOURCES,
        "grade": _PROVIDER_RESOURCES,
        "check": _PROVIDER_RESOURCES,
        "report": _PACING_RESOURCES,
    }
)


class StepTrace(StrictSchema):
    """One raw, traceable workflow step before persistence redaction."""

    step: PositiveInt
    node: WorkflowNode
    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt = 0
    cache_write_input_tokens: NonNegativeInt = 0
    reasoning_tokens: NonNegativeInt = 0
    estimated_cost_usd: NonNegativeDecimal
    request_time_ms: NonNegativeFloat
    llm_output: StrictStr
    retries: NonNegativeInt
    error: NonBlank | None = None

    @model_validator(mode="after")
    def validate_usage_details(self) -> Self:
        """Keep detailed token counters within their provider totals."""
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ValueError("detailed input tokens must not exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens must not exceed output_tokens")
        return self


class RunReport(StrictSchema):
    """One complete or structured-failure workflow run."""

    run_id: RunId
    status: RunStatus
    iterations: NonNegativeInt
    total_requests: NonNegativeInt
    total_input_tokens: NonNegativeInt
    total_output_tokens: NonNegativeInt
    total_cached_input_tokens: NonNegativeInt = 0
    total_cache_write_input_tokens: NonNegativeInt = 0
    total_reasoning_tokens: NonNegativeInt = 0
    total_estimated_cost_usd: NonNegativeDecimal = Decimal("0")
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


class BudgetLimitFailure(StrictSchema):
    """A workflow node blocked by one exhausted cumulative resource.

    Owned here, next to the budget guard that produces it, so the refusal payload and
    the schema consumers validate against cannot drift apart.
    """

    code: Literal["budget_exceeded"] = "budget_exceeded"
    resource: BudgetResource
    limit: StrictInt | StrictFloat
    observed: StrictInt | StrictFloat
    blocked_node: WorkflowNode

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        """Keep budget evidence finite and nonnegative."""
        if any(
            isinstance(value, float) and not math.isfinite(value)
            for value in (self.limit, self.observed)
        ):
            raise ValueError("budget values must be finite")
        if self.limit < 0 or self.observed < 0:
            raise ValueError("budget values must be nonnegative")
        return self


def derived_totals(
    *,
    node_path: tuple[WorkflowNode, ...] | list[WorkflowNode],
    steps: tuple[StepTrace, ...] | list[StepTrace],
) -> dict[str, int | Decimal]:
    """Return the cumulative counters implied by the entered nodes and raw traces.

    The keys are ``RunReport`` field names, so this is the single definition both the
    report builder and the report validator derive their totals from.
    """
    return {
        "iterations": len(node_path),
        "total_requests": sum(1 + trace.retries for trace in steps),
        "total_input_tokens": sum(trace.input_tokens for trace in steps),
        "total_output_tokens": sum(trace.output_tokens for trace in steps),
        "total_cached_input_tokens": sum(trace.cached_input_tokens for trace in steps),
        "total_cache_write_input_tokens": sum(trace.cache_write_input_tokens for trace in steps),
        "total_reasoning_tokens": sum(trace.reasoning_tokens for trace in steps),
        "total_estimated_cost_usd": sum(
            (trace.estimated_cost_usd for trace in steps),
            Decimal("0"),
        ),
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
        total_cached_input_tokens=totals["total_cached_input_tokens"],
        total_cache_write_input_tokens=totals["total_cache_write_input_tokens"],
        total_reasoning_tokens=totals["total_reasoning_tokens"],
        total_estimated_cost_usd=totals["total_estimated_cost_usd"],
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
