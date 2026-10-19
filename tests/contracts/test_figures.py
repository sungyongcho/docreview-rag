"""Answer figures checked against the period of the cited evidence."""

from dataclasses import asdict

import pytest

from app.contracts.figures import EvidenceText, check_figures, figures
from app.ingestion.chunking import chunk_filing
from app.ingestion.parsing.models import Block
from tests.ingestion.chunk.support import build_filing

# AMD FY2024 consolidated statement of operations, as the filing lays it out.
INCOME_TABLE = (
    "<table><tr><td>(In millions)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Net income</td><td>1,641</td><td>854</td></tr></table>"
)


def table_evidence(html: str = INCOME_TABLE) -> EvidenceText:
    """Chunk one table through the real chunker and read it as cited evidence."""
    block = Block("table", "", html=html, source_pos=0, end_pos=len(html))
    filing = build_filing([block])
    filing.source_length = len(html)
    (chunk,) = chunk_filing(filing)
    assert chunk.table_fragment is not None
    return EvidenceText(1, chunk.body, chunk.context_header, asdict(chunk.table_fragment))


def prose_evidence(body: str) -> EvidenceText:
    """Read one narrative chunk as cited evidence."""
    return EvidenceText(2, body, "AMD FY2024 · Item 7")


def test_a_figure_from_the_requested_period_column_is_verified():
    """Accept 2024 revenue read from the December 28, 2024 column."""
    result = check_figures("2024 revenue was $25,785 million.", [table_evidence()], [2024])
    assert result.verdict == "verified"
    assert result.checks[0].evidenced_years == (2024,)


def test_a_figure_from_a_comparative_column_is_a_period_mismatch():
    """Reject 22,680 as 2024 revenue: the 10-K reports it in the 2023 column."""
    result = check_figures("2024 revenue was $22,680 million.", [table_evidence()], [2024])
    assert result.verdict == "period_mismatch"
    assert (result.checks[0].figure, result.checks[0].evidenced_years) == ("22,680", (2023,))


def test_a_figure_missing_from_the_evidence_is_unverified():
    """Reject a figure no cited cell or text states."""
    result = check_figures("2024 revenue was $26,000 million.", [table_evidence()], [2024])
    assert result.verdict == "unverified"


def test_without_a_requested_period_any_cited_figure_is_verified():
    """Check only presence when the question names no period."""
    result = check_figures("Revenue was $22,680 million.", [table_evidence()], [])
    assert result.verdict == "verified"


def test_a_prose_figure_cannot_prove_a_requested_period():
    """Refuse a running-text figure when the question asks for a period."""
    prose = prose_evidence("Net revenue increased 14% compared with the prior year.")
    assert check_figures("Revenue grew 14%.", [prose], [2024]).verdict == "unverified"
    assert check_figures("Revenue grew 14%.", [prose], []).verdict == "verified"


def test_losses_match_by_magnitude():
    """Match "a loss of 33" to a filing's parenthesized (33)."""
    html = INCOME_TABLE.replace("854", "(33)")
    result = check_figures("The 2023 net loss was 33 million.", [table_evidence(html)], [2023])
    assert result.verdict == "verified"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Revenue was $25,785 million in fiscal 2024.", ("25,785",)),
        ("FY2024 Item 7 of the 10-K, Q4 results.", ()),
        ("As of December 28, 2024 and 2024.12.31, revenue was 1,641.", ("1,641",)),
        ("2024년 12월 31일 기준 매출은 25,785백만원, 1분기 제56기", ("25,785",)),
        ("영업이익률 14.5%", ("14.5",)),
    ],
)
def test_identifiers_dates_and_years_are_not_figures(text, expected):
    """Leave years, dates, item numbers and periods out of the figures to check."""
    assert figures(text) == expected
