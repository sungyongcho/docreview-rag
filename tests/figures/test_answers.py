"""Answer figures checked against cited evidence."""

import pytest

from app.figures.answers import EvidenceText, check_figures
from tests.figures.support import prose_evidence


def test_a_prose_figure_cannot_prove_a_requested_period():
    """Refuse a running-text figure when the question asks for a period."""
    prose = prose_evidence("Net revenue increased 14% compared with the prior year.")
    assert check_figures("Revenue grew 14%.", [prose], [2024]).verdict == "unverified"
    assert check_figures("Revenue grew 14%.", [prose], []).verdict == "verified"


def test_prose_and_labels_must_name_the_same_item():
    """Refuse a running-text figure stated for a different item than the answer names."""
    prose = prose_evidence("Net income increased 14% compared with the prior year.")
    assert check_figures("Revenue grew 14%.", [prose], []).verdict == "unverified"
    labelled = EvidenceText(3, "Body text.", "Net revenue of US$25,785 million · Item 8", None)
    assert check_figures("Net revenue was $25.8 billion.", [labelled], []).verdict == "verified"
    assert check_figures("Net income was $25,785 million.", [labelled], []).verdict == (
        "unverified"
    )
    unitless = EvidenceText(3, "Body text.", "Net revenue of 25,785 · Item 8", None)
    assert check_figures("Net revenue was 25,785.", [unitless], []).verdict == "unit_unverified"


@pytest.mark.parametrize(
    ("answer", "requested"),
    [
        ("2024 net income was 25,785.", [2024]),
        ("Net income was 25,785.", [2024]),
        ("Net income was 25,785 in 2024.", []),
    ],
)
def test_labels_and_running_text_cannot_confirm_a_period(answer, requested):
    """Refuse non-cell evidence whenever a period is asked or stated, even for the same item."""
    labelled = EvidenceText(7, "Net income was 25,785.", "Net income of 25,785 in 2023")
    assert check_figures(answer, [labelled], requested).verdict == "unverified"


def test_prose_fallback_needs_the_same_currency():
    """Hold or refuse running-text figures whose currency is ambiguous or different."""
    dollars = EvidenceText(3, "Body text.", "Net revenue of $25,785 million · Item 8", None)
    assert check_figures("Net revenue was $25.8 billion.", [dollars], []).verdict == (
        "unit_unverified"
    )
    assert check_figures("Net revenue was €25.8 billion.", [dollars], []).verdict == "unverified"
    won = EvidenceText(3, "Body text.", "Net revenue of 25,785 million won · Item 8", None)
    assert check_figures("Net revenue was US$25,785 million.", [won], []).verdict == "unverified"
    assert check_figures("Net revenue was ₩25,785 million.", [won], []).verdict == "verified"
