"""Figures found in text, without identifiers, dates or bare years."""

import pytest

from app.figures.text import figures


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Revenue was $25,785 million in fiscal 2024.", ("25,785",)),
        ("FY2024 Item 7 of the 10-K, Q4 results.", ()),
        ("As of December 28, 2024 and 2024.12.31, revenue was 1,641.", ("1,641",)),
        ("2024년 12월 31일 기준 매출은 25,785백만원, 1분기 제56기", ("25,785",)),
        ("영업이익률 14.5%", ("14.5",)),
        ("$25.8B and 25.8bn", ("25.8", "25.8")),
        ("3M and 10K filers, Series B, 5G", ()),
        ("Revenue was $25,785bil or 25.8x.", ("25,785", "25.8")),
        ("In 2024, revenue was 25,785, then 1,641.", ("25,785", "1,641")),
        ("Revenue was $99999xyz, $2024mn, $2024 million and 2024%.", ("99999",) + ("2024",) * 3),
        ("USD25,785, 25,785USD, ₩300, 300원 and 25 usd", ("25,785", "25,785", "300", "300", "25")),
    ],
)
def test_identifiers_dates_and_years_are_not_figures(text, expected):
    """Leave years, dates and identifiers out, but keep figures glued to unknown units."""
    assert figures(text) == expected


def test_explicit_identifier_shapes_stay_out_of_the_check():
    """Leave 3M, 10K, 5G, Series B, ordinals and FY/Q/date/Item references out."""
    answer = (
        "In the 3rd year, 3M and 10K filers with 5G and Series B, per FY2024 Q4 "
        "Item 7 as of December 28, 2024, reported net revenue of $25,785 million."
    )
    assert figures(answer) == ("25,785",)


def test_real_dates_and_period_references_stay_out_of_the_check():
    """Leave FY, quarter, Item and calendar dates out even beside currency words."""
    assert figures("FY2024 Q4 results in USD, Item 7, as of December 28, 2024 and 2024.") == ()
