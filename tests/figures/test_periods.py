"""Shared period forms and fixed-century fiscal identifiers across readers."""

import pytest

from app.figures.answers import EvidenceText, check_figures
from app.figures.periods import classify_period, fiscal_year_spans, normalize_fiscal_years
from app.figures.tables import read_table_cells
from tests.figures.support import linked, reading


@pytest.mark.parametrize(
    "phrase,annual",
    [
        ("FY2024", True),
        ("fiscal 2024", True),
        ("2024 회계연도", True),
        ("year ended December 28, 2024", True),
        ("fiscal year ending on Dec. 28, 2024", True),
        ("Q4 2024", False),
        ("4Q24", False),
        ("fourth quarter 2024", False),
        ("H1 2024", False),
        ("1H24", False),
        ("second half 2024", False),
        ("three months ended December 28, 2024", False),
        ("nine months 2024", False),
        ("December 2024", False),
        ("2024년 12월", False),
        ("period ended March 30, 2024", False),
        ("2024년 4분기", False),
        ("2024년 상반기", False),
        ("2024년 하반기", False),
        ("2024년 9개월", False),
    ],
)
def test_three_readers_share_annual_versus_nonannual_periods(phrase, annual):
    """Question, header and answer use the same period classification before blanking."""
    from app.figures.vocabulary import items_named

    assert bool(items_named(f"What was revenue for {phrase}?")) is annual
    fragment = {
        "header_cells": [{"column": 1, "text": phrase}],
        "caption_sources": [linked("(In millions of U.S. dollars)")],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": "1,234"}]},
        ],
    }
    cell = read_table_cells(fragment)[0]
    assert (len(cell.years) == 1 and cell.scope is None) is annual
    verdict = check_figures(
        f"Revenue for {phrase} was USD 1,234 million.",
        [EvidenceText(1, "", "", [reading()])],
        [2024],
    ).verdict
    assert (verdict == "verified") is annual


@pytest.mark.parametrize(
    "phrase,year",
    [
        ("FY24", 2024),
        ("FY'24", 2024),
        ("fiscal 24", 2024),
        ("FY00", 2000),
        ("FY99", 2099),
        ("FY1999", 1999),
    ],
)
def test_short_fiscal_years_have_one_fixed_century_on_all_three_readers(phrase, year):
    """The question, header and answer never infer the century from a chosen cell."""
    from app.figures.answers import _claims
    from app.figures.vocabulary import items_named

    assert items_named(f"What was revenue in {phrase}?") == {"revenue"}
    fragment = {
        "header_cells": [{"column": 1, "text": phrase}],
        "caption_sources": [linked("(In millions of U.S. dollars)")],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": "1,234"}]},
        ],
    }
    (cell,) = read_table_cells(fragment)
    assert cell.years == {year}
    (claim,) = _claims(f"{phrase} revenue was USD 1,234 million.", answer=True)
    assert claim.year == year and claim.item == "revenue"
    assert (
        check_figures(
            f"{phrase} revenue was USD 1,234 million.", [EvidenceText(1, "", "", [cell])], [year]
        ).verdict
        == "verified"
    )


@pytest.mark.parametrize(
    "form,kind",
    [
        ("fiscal 2024 (ended December 28, 2024)", "annual"),
        ("fiscal 2024 ended December 28, 2024", "annual"),
        ("fiscal year 2024 (ended Dec. 28, 2024)", "annual"),
        ("FY2024, which ended on December 28, 2024", "annual"),
        ("FY24 (ending 2025-01-26)", "annual"),
        ("fiscal year ending January 26, 2025", "annual"),
        ("52 weeks ended December 28, 2024", "annual"),
        ("53-week fiscal year ended 2025/01/26", "annual"),
        ("fifty-two week period ended Dec. 28, 2024", "annual"),
        ("twelve months ended December 28, 2024", "annual"),
        ("12-month fiscal year ending on 12/28/2024", "annual"),
        ("fiscal 2024, a 52-week period", "annual"),
        ("52-week fiscal year 2024", "annual"),
        ("annual period 2024", "annual"),
        ("2024년 12월 28일로 종료된 회계연도", "annual"),
        ("2024년 12월 28일 종료 회계연도", "annual"),
        ("2024년 12월 28일에 종료되는 사업연도", "annual"),
        ("2024년 12월 28일로 종료하는 사업연도", "annual"),
        ("2024.12.28 종료 회계연도", "annual"),
        ("2024.01.01 ~ 2024.12.31", "annual"),
        ("2023.12.31 - 2024.12.28", "annual"),
        ("2024년 1월 1일부터 2024년 12월 31일까지", "annual"),
        ("제 56 기", "annual"),
        ("사업연도", "annual"),
        ("회계연도", "annual"),
        ("보고기간", "subannual"),
        ("fiscal year period 2024", "annual"),
        ("FY2024 period", "annual"),
        ("제56기 누계(2024.01.01~2024.12.31)", "annual"),
        ("보고기간: 2024.01.01~2024.12.31", "annual"),
        ("2024년 1월 1일부터 2024년 12월 31일까지 보고기간", "annual"),
        ("보고기간: 2024.01.01~2024.06.30", "subannual"),
        ("기말", "none"),
        ("2024년 12월 28일로 종료된 3개월", "subannual"),
        ("2024년 12월 28일로 종료된 분기", "subannual"),
        ("2024년 12월 28일로 종료된 반기", "subannual"),
        ("2024년 12월 28일", "date"),
        ("three months ended December 28, 2024", "subannual"),
        ("FY2024 Q4 ended December 28, 2024", "subannual"),
        ("FY2024, a 51-week period", "subannual"),
        ("FY2024, a 54-week period", "subannual"),
        ("eleven months 2024", "subannual"),
        ("thirteen months 2024", "subannual"),
        ("for the period", "subannual"),
        ("the prior year period", "subannual"),
        ("May 2024", "date"),
        ("may 31, 2024", "date"),
        ("in May", "date"),
        ("during march", "date"),
        ("31 Dec. 2024", "date"),
        ("which may reflect demand", "none"),
        ("march forward", "none"),
        ("mar dec sept jun", "none"),
        ("decay market septemberish", "none"),
        ("FY2024 which may reflect demand", "annual"),
        ("fiscal year ended February 30, 2024", "date"),
        ("FY2024 ended 2024-13-28", "date"),
        ("2024.02.30 ~ 2025.02.28", "date"),
        ("2024.01.01 ~ 2024.06.30", "date"),
        ("2024.01.01 ~ 2024.12.16", "date"),
        ("2024.01.01 ~ 2025.01.01", "date"),
        ("2024.01.01 ~ 2024.12.29", "annual"),
        ("2024.01.01 ~ 2025.01.05", "annual"),
        ("2024.12.31 ~ 2024.01.01", "date"),
    ],
)
def test_closed_period_form_table(form, kind):
    """Read annual forms, shorter periods, bare dates and ordinary month homonyms."""
    assert classify_period(form) == kind


@pytest.mark.parametrize(
    "form,normalized,year",
    [
        ("FY24", "FY2024", 2024),
        ("FY'00", "FY2000", 2000),
        ("fiscal year 99", "FY2099", 2099),
        ("FY1999", "FY1999", 1999),
        ("fiscal 2024", "FY2024", 2024),
    ],
)
def test_fiscal_identifier_normalization_is_explicit_and_fixed(form, normalized, year):
    """Normalize only an explicit fiscal identifier and preserve its source span."""
    text = f"in {form}, revenue"
    assert normalize_fiscal_years(text) == f"in {normalized}, revenue"
    assert fiscal_year_spans(text) == [(3, 3 + len(form), year)]


@pytest.mark.parametrize(
    "text",
    ["24", "2024", "FY500", "fiscal 99999", "FY24,123", "fiscal year 10-K", "fiscal 20-F"],
)
def test_ordinary_or_malformed_numbers_are_not_fiscal_identifiers(text):
    """The fiscal normalizer never guesses a century for an amount or a filing form number."""
    assert normalize_fiscal_years(text) == text
    assert not fiscal_year_spans(text)


@pytest.mark.parametrize("header", ["FY24-FY25", "FY2024-FY2025", "FY24/FY25"])
def test_a_range_of_fiscal_identifiers_names_both_years_and_dates_no_column(header):
    """A joined pair is two years on every reader, so its column confirms no single year."""
    assert [year for _, _, year in fiscal_year_spans(header)] == [2024, 2025]
    fragment = {
        "header_cells": [{"column": 1, "text": header}],
        "caption_sources": [linked("(In millions of U.S. dollars)")],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": "1,234"}]},
        ],
    }
    (cell,) = read_table_cells(fragment)
    assert cell.years == {2024, 2025}
    for answer in (
        "FY24 revenue was USD 1,234 million.",
        f"{header} revenue was USD 1,234 million.",
    ):
        assert check_figures(answer, [EvidenceText(1, "", "", [cell])], [2024]).verdict == (
            "unverified"
        )


def test_a_hyphenated_prefix_is_not_a_fiscal_identifier():
    """Only a hyphen that follows a digit joins a second identifier."""
    assert not fiscal_year_spans("non-FY24 revenue")


@pytest.mark.parametrize(
    "form,year",
    [
        ("FY2024 ended January 26, 2025", 2024),
        ("FY'24 (ending 2025-01-26)", 2024),
        ("fiscal year ending January 26, 2025", None),
        ("January 26, 2025", None),
    ],
)
def test_only_an_explicit_fy_identifier_dates_its_annual_ending(form, year):
    """A shared span preserves the explicit fiscal year without inventing a calendar."""
    from app.figures.periods import annual_fiscal_year_spans

    assert annual_fiscal_year_spans(form) == (
        [] if year is None else [(0, len(form.rstrip(")")), year)]
    )
