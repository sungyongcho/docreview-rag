"""Uncertainty must always carry one or more closed, canonical causes."""

import json

import pytest

from app.agent.types import AgentWithheld
from app.figures.answers import FigureCheck
from app.figures.currency import same_currency
from app.figures.withholding import UncertainComparison
from app.workflow.types import FiguresWithheld, WorkflowReport


@pytest.mark.parametrize("causes", [(), ("unknown",)])
def test_comparisons_and_figures_cannot_withhold_without_a_known_cause(causes):
    """Fail closed before an untyped withholding can reach an application report."""
    with pytest.raises(ValueError):
        UncertainComparison(causes)
    with pytest.raises(ValueError):
        FigureCheck("25", "withheld", causes=causes)


def test_a_confirmed_figure_cannot_carry_a_withholding_cause():
    """Causes belong only to the comparison that actually withholds."""
    with pytest.raises(ValueError):
        FigureCheck("25", "verified", causes=("currency",))
    assert same_currency("USD", "$") == UncertainComparison(("currency",))
    assert same_currency("$", "USD") == "match"
    assert same_currency("EUR", "USD") == "no"


@pytest.mark.parametrize("schema", [AgentWithheld, FiguresWithheld])
def test_wire_causes_are_required_closed_nonempty_and_canonical(schema):
    """JSON records reject absent/unknown causes and normalize duplicates and ordering."""
    for payload in (
        {"figures": ["25"]},
        {"figures": ["25"], "causes": []},
        {"figures": ["25"], "causes": ["unknown"]},
    ):
        with pytest.raises(ValueError):
            schema.model_validate_json(json.dumps(payload))
    record = schema.model_validate_json(
        json.dumps({"figures": ["25"], "causes": ["direction", "scale", "currency", "scale"]})
    )
    assert record.causes == ("scale", "currency", "direction")
    assert schema.model_validate_json(record.model_dump_json()) == record


def test_the_previous_reason_code_is_rejected():
    """A retired undeployed wire reason has no alias or legacy reader."""
    with pytest.raises(ValueError):
        WorkflowReport.model_validate_json(
            json.dumps(
                {
                    "label": "NOT_IN_DOCS",
                    "answer": "NOT_IN_DOCS",
                    "citations": [],
                    "rationale": "No match",
                    "reasons": [{"code": "figures_unit_unverified", "figures": ["25"]}],
                }
            )
        )
