"""The cumulative budget guard run before a workflow node is entered."""

from pydantic import ValidationError
import pytest

from app.observability.budget import pre_node_budget_guard
from app.observability.types import Budget
from tests.observability.support import step_trace


def test_pre_node_guard_allows_entry_while_every_budget_has_capacity():
    """Admit the next node while every budget still has capacity."""
    result = pre_node_budget_guard(
        run_id="run-allowed",
        node="check",
        budget=Budget(
            max_iterations=3,
            max_input_tokens=101,
            max_output_tokens=21,
            max_wall_clock_s=2.0,
        ),
        elapsed_seconds=1.0,
        system_prompt="Ground every claim.",
        node_path=["retrieve", "grade"],
        steps=[step_trace()],
    )

    assert result is None


@pytest.mark.parametrize(
    ("budget_overrides", "elapsed_seconds", "expected_resource"),
    [
        ({"max_iterations": 2}, 1.0, "iterations"),
        ({"max_input_tokens": 100}, 1.0, "input_tokens"),
        ({"max_output_tokens": 20}, 1.0, "output_tokens"),
        ({"max_wall_clock_s": 1.0}, 1.0, "wall_clock_s"),
    ],
)
def test_pre_node_guard_returns_structured_budget_exceeded_refusal(
    budget_overrides,
    elapsed_seconds,
    expected_resource,
):
    """Refuse the next node with structured evidence of the exhausted budget."""
    values = {
        "max_iterations": 3,
        "max_input_tokens": 101,
        "max_output_tokens": 21,
        "max_wall_clock_s": 2.0,
    }
    values.update(budget_overrides)

    result = pre_node_budget_guard(
        run_id="run-refused",
        node="check",
        budget=Budget(**values),
        elapsed_seconds=elapsed_seconds,
        system_prompt="Ground every claim.",
        node_path=["retrieve", "grade"],
        steps=[step_trace()],
    )

    assert result is not None
    assert result.status == "budget_exceeded"
    assert result.node_path == ("retrieve", "grade")
    assert result.report == {
        "reason": {
            "code": "budget_exceeded",
            "resource": expected_resource,
            "limit": values[f"max_{expected_resource}"],
            "observed": {
                "iterations": 2,
                "input_tokens": 100,
                "output_tokens": 20,
                "wall_clock_s": elapsed_seconds,
            }[expected_resource],
            "blocked_node": "check",
        }
    }


@pytest.mark.parametrize(
    ("budget", "expected_resource", "limit"),
    [
        (Budget(max_iterations=3, max_wall_clock_s=2.0), "iterations", 3),
        (Budget(max_iterations=10, max_wall_clock_s=1.0), "wall_clock_s", 1.0),
    ],
    ids=["iterations", "wall_clock"],
)
def test_pre_node_guard_never_refuses_the_report_node_on_pacing_budgets(
    budget,
    expected_resource,
    limit,
):
    """Admit the pure report node on a spent pacing budget while the first node stays paced.

    The report node sends nothing, so refusing it saves no time or money; it would only
    discard the answer the run already paid for.
    """

    def guard(node):
        """Ask the guard for one node after three entered nodes and one second elapsed."""
        return pre_node_budget_guard(
            run_id="run-report",
            node=node,
            budget=budget,
            elapsed_seconds=1.0,
            system_prompt="Ground every claim.",
            node_path=["retrieve", "grade", "check"],
            steps=[step_trace()],
        )

    assert guard("report") is None
    refused = guard("retrieve")
    assert refused is not None
    assert refused.report == {
        "reason": {
            "code": "budget_exceeded",
            "resource": expected_resource,
            "limit": limit,
            "observed": limit,
            "blocked_node": "retrieve",
        }
    }


def test_zero_budget_refuses_the_first_node_and_negative_budgets_are_invalid():
    """Refuse the first node on a zero budget and reject a negative one outright."""
    budget = Budget(
        max_iterations=0,
        max_input_tokens=0,
        max_output_tokens=0,
        max_wall_clock_s=0.0,
    )

    result = pre_node_budget_guard(
        run_id="run-zero",
        node="retrieve",
        budget=budget,
        elapsed_seconds=0.0,
        system_prompt="Ground every claim.",
        node_path=[],
        steps=[],
    )

    assert result is not None
    assert result.status == "budget_exceeded"
    assert result.report["reason"]["resource"] == "iterations"
    with pytest.raises(ValidationError):
        Budget(max_input_tokens=-1)
    with pytest.raises(ValidationError):
        Budget(max_iterations=True)
    with pytest.raises(ValidationError):
        Budget(max_wall_clock_s=float("inf"))
