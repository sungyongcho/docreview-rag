"""Fiscal years named or described relative to the question date."""

from datetime import date

import pytest

from app.query.periods import names_fiscal_year, question_fiscal_years, without_fiscal_years

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


@pytest.mark.parametrize(
    ("query", "years"),
    [
        ("FY24 revenue?", (2024,)),
        ("What was revenue in FY'24?", (2024,)),
        ("fiscal year 24 revenue", (2024,)),
        ("FY24 and FY23 revenue", (2023, 2024)),
        ("FY24-FY25 revenue", (2024, 2025)),
        ("FY99 revenue", (2099,)),
        ("revenue in FY2024, 2023 and 2022", (2022, 2023, 2024)),
    ],
)
def test_question_years_read_explicit_fiscal_identifiers_like_headers_and_answers(query, years):
    """A two-digit fiscal identifier asks for 2000-2099, as the shared period forms read it."""
    assert question_fiscal_years(query, TODAY) == years


@pytest.mark.parametrize(
    ("query", "years"),
    [
        ("NVIDIA revenue for FY2024 ended January 26, 2025", (2024,)),
        ("NVIDIA revenue for FY'24 (ending 2025-01-26)", (2024,)),
        ("revenue for fiscal 2025 (ended January 26, 2025) and 2023", (2023, 2025)),
        ("revenue for the fiscal year ended January 26, 2025", (2025,)),
        ("FY24 revenue against 2025 guidance", (2024, 2025)),
    ],
)
def test_an_identified_annual_ending_asks_for_its_fiscal_year_only(query, years):
    """The end date of an ending with a fiscal identifier is not a second requested year."""
    assert question_fiscal_years(query, TODAY) == years


@pytest.mark.parametrize(
    "query",
    ["What does the fiscal year 10-K say about risks?", "What are the top 24 risks?", "24년 매출"],
)
def test_form_numbers_and_bare_short_numbers_ask_for_no_year(query):
    """Only an explicit fiscal identifier gives a two-digit number a century."""
    assert question_fiscal_years(query, TODAY) == ()


@pytest.mark.parametrize(
    ("text", "rest"),
    [
        ("NVDA data center revenue 2023", "NVDA data center revenue "),
        ("삼성전자 2024년 매출", "삼성전자  매출"),
        ("AMD revenue last year", "AMD revenue "),
        ("FY24 and FY'23 revenue", " and  revenue"),
        ("NVIDIA revenue for FY2024 ended January 26, 2025", "NVIDIA revenue for "),
    ],
)
def test_every_year_form_the_reader_accepts_can_be_removed(text, rest):
    """A superseded turn loses its years in whichever form it named them."""
    assert names_fiscal_year(text)
    assert without_fiscal_years(text) == rest
    assert question_fiscal_years(rest, TODAY) == ()


@pytest.mark.parametrize("text", ["What are NVIDIA's main risks?", "top 24 risks"])
def test_text_without_a_year_is_left_as_written(text):
    """Text that names no fiscal year is neither changed nor treated as naming one."""
    assert not names_fiscal_year(text)
    assert without_fiscal_years(text) == text
