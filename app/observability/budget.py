"""The single cumulative budget guard used before workflow node entry."""

from __future__ import annotations

from app.observability.types import (
    NODE_BUDGET_RESOURCES,
    Budget,
    BudgetResource,
    RunReport,
    StepTrace,
    WorkflowNode,
    build_run_report,
    derived_totals,
    validate_elapsed_seconds,
)


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
    """Return a structured refusal when a cumulative hard limit is exhausted.

    Parameters
    ----------
    run_id : str
        Workflow run being guarded.
    node : WorkflowNode
        Node that would execute next.
    budget : Budget
        Cumulative workflow limits.
    elapsed_seconds : float
        Current monotonic runtime.
    system_prompt : str
        Prompt provenance copied into a refusal report.
    node_path : tuple[WorkflowNode, ...] | list[WorkflowNode]
        Nodes already entered.
    steps : tuple[StepTrace, ...] | list[StepTrace]
        Provider traces accumulated so far.

    Returns
    -------
    RunReport | None
        ``None`` when capacity remains, otherwise a complete refusal report.

    Raises
    ------
    ValueError
        If elapsed time or report inputs violate their strict contracts.

    Notes
    -----
    This is the only workflow-budget enforcement point and runs immediately before a
    node. Equality blocks entry because no capacity remains. Only the resources
    ``NODE_BUDGET_RESOURCES`` declares for the node are checked, so a node that issues
    no provider call is never refused for token exhaustion it cannot add to.
    """
    elapsed = validate_elapsed_seconds(elapsed_seconds)
    trace_values = tuple(steps)
    totals = derived_totals(node_path=node_path, steps=trace_values)
    observed: dict[BudgetResource, int | float] = {
        "iterations": totals["iterations"],
        "input_tokens": totals["total_input_tokens"],
        "output_tokens": totals["total_output_tokens"],
        "wall_clock_s": elapsed,
    }
    limits: dict[BudgetResource, int | float] = {
        "iterations": budget.max_iterations,
        "input_tokens": budget.max_input_tokens,
        "output_tokens": budget.max_output_tokens,
        "wall_clock_s": budget.max_wall_clock_s,
    }

    exhausted: BudgetResource | None = next(
        (
            resource
            for resource in NODE_BUDGET_RESOURCES[node]
            if observed[resource] >= limits[resource]
        ),
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
