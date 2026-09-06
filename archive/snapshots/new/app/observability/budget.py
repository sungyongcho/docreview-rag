"""The single cumulative budget guard used before workflow node entry."""

from __future__ import annotations

from typing import Literal

from app.observability.types import (
    Budget,
    RunReport,
    StepTrace,
    WorkflowNode,
    build_run_report,
    validate_elapsed_seconds,
)

BudgetResource = Literal["iterations", "input_tokens", "output_tokens", "wall_clock_s"]


def pre_node_budget_guard(
    *,
    run_id: str,
    node: WorkflowNode,
    budget: Budget,
    elapsed_seconds: float,
    system_prompt: str,
    node_path: tuple[WorkflowNode, ...] | list[WorkflowNode],
    steps: tuple[StepTrace, ...] | list[StepTrace],
) -> RunReport | None:
    """Return a structured refusal when any cumulative hard limit is exhausted.

    This is the only budget-enforcement point: call it immediately before a node.
    Equality blocks entry because no capacity remains, which also makes a zero budget
    a valid configuration that deterministically refuses the first node.
    """
    elapsed = validate_elapsed_seconds(elapsed_seconds)
    trace_values = tuple(steps)
    observed: dict[BudgetResource, int | float] = {
        "iterations": len(node_path),
        "input_tokens": sum(trace.input_tokens for trace in trace_values),
        "output_tokens": sum(trace.output_tokens for trace in trace_values),
        "wall_clock_s": elapsed,
    }
    limits: dict[BudgetResource, int | float] = {
        "iterations": budget.max_iterations,
        "input_tokens": budget.max_input_tokens,
        "output_tokens": budget.max_output_tokens,
        "wall_clock_s": budget.max_wall_clock_s,
    }

    exhausted: BudgetResource | None = next(
        (resource for resource in limits if observed[resource] >= limits[resource]),
        None,
    )
    if exhausted is None:
        return None

    return build_run_report(
        run_id=run_id,
        status="budget_exceeded",
        total_time_seconds=elapsed,
        system_prompt=system_prompt,
        node_path=node_path,
        steps=trace_values,
        report={
            "reason": {
                "code": "budget_exceeded",
                "resource": exhausted,
                "limit": limits[exhausted],
                "observed": observed[exhausted],
                "blocked_node": node,
            }
        },
    )
