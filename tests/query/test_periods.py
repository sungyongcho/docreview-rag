"""Fiscal years named or described relative to the question date."""

from datetime import date

import pytest

from app.query.periods import question_fiscal_years

TODAY = date(2026, 10, 19)


@pytest.mark.parametrize(
    ("query", "years"),
    [
        ("NVIDIA revenue in 2024", (2024,)),
        ("2023년과 2024년 매출 비교", (2023, 2024)),
        ("AMD revenue last year", (2025,)),
        ("AMD revenue in the prior fiscal year", (2025,)),
        ("삼성전자 작년 매출", (2025,)),
        ("삼성전자 지난해 영업이익", (2025,)),
        ("올해 매출은 전년 대비 얼마나 늘었나", (2025, 2026)),
        ("재작년 매출", (2024,)),
        ("revenue two years ago", (2024,)),
        ("What are NVIDIA's main risks?", ()),
    ],
)
def test_question_years_include_relative_wording(query, years):
    """Resolve explicit years and relative wording against the question date."""
    assert question_fiscal_years(query, TODAY) == years
