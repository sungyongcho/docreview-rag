"""The cumulative budget guard run before a workflow node is entered."""

import pytest

from app.observability.budget import pre_node_budget_guard
from app.observability.types import Budget
from tests.observability.support import step_trace


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
