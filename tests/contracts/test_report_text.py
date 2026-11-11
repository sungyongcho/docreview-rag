"""Application sentences and report entry points require a resolved language."""

import inspect

import pytest

from app.agent.cell_answers import review_cell_selection
from app.agent.final_answer import judge_written_answer, period_mismatch_report, withheld_report
from app.agent.loop import run_agent
from app.agent.review_middleware import ReviewContext
from app.contracts.report_text import period_mismatch_rationale, period_mismatch_text, withheld_text


@pytest.mark.parametrize(
    "producer",
    [
        review_cell_selection,
        judge_written_answer,
        period_mismatch_report,
        withheld_report,
        run_agent,
        ReviewContext,
        period_mismatch_text,
        period_mismatch_rationale,
        withheld_text,
    ],
)
def test_locale_is_a_required_keyword(producer):
    """New callers cannot silently pick English for a Korean question."""
    parameter = inspect.signature(producer).parameters["locale"]
    assert parameter.kind == inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


@pytest.mark.parametrize("locale", ["en", "ko"])
def test_sentences_name_only_the_actual_cause_and_never_report_the_figure(locale):
    """Single and mixed causes stay distinct in both the answer and the rationale."""
    names = (
        {"scale": "단위", "currency": "통화", "direction": "손익 방향"}
        if locale == "ko"
        else {
            "scale": "unit",
            "currency": "currency",
            "direction": "gain/loss direction",
        }
    )
    for cause, name in names.items():
        for text in withheld_text((cause,), locale=locale):
            assert name in text
            assert all(other not in text for key, other in names.items() if key != cause)
            assert not any(c.isdigit() for c in text)
    assert withheld_text(
        ("direction", "scale", "currency", "scale"), locale=locale
    ) == withheld_text(("scale", "currency", "direction"), locale=locale)
    with pytest.raises(ValueError):
        withheld_text((), locale=locale)
