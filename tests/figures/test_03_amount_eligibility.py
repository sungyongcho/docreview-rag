"""Selection and written answers share one complete monetary evidence boundary."""

import pytest

from app.figures.answers import EvidenceText, check_figures
from app.figures.tables import interpret_table_cell, read_table_cells
from tests.figures.support import fact, fragment_evidence, linked, reading


@pytest.mark.parametrize(
    "changes",
    [
        {"years": frozenset()},
        {"years": frozenset({2023, 2024})},
        {"scope": "?"},
        {"scope": "axis=member"},
        {"measure": "other"},
        {"measure": "per_share"},
        {"percent": True},
        {"item": None},
        {"overrides": ("incomplete",)},
        {"overrides": ("multiple",)},
    ],
)
@pytest.mark.parametrize("year", [False, True])
def test_ineligible_cells_neither_confirm_nor_create_period_mismatches(changes, year):
    """Refuse structurally unread cells with or without a stated/requested year."""
    cell = reading(**changes)
    claim = ("FY2025 " if year else "") + "revenue was USD 1,234 million."
    assert not cell.evidence_eligible
    assert (
        check_figures(
            claim, [EvidenceText(1, claim, claim, [cell])], [2025] if year else []
        ).verdict
        == "unverified"
    )


@pytest.mark.parametrize("text", ["1,234 5,678", "1,234 1,234", "1,2341", "1,234(1)"])
def test_multiplicity_and_footnote_digits_do_not_leave_a_candidate_amount(text):
    """Preserve occurrence count even when the numbers have identical magnitudes."""
    ev = fragment_evidence("Revenue", text)
    assert ev.table_cells and not ev.table_cells[0].evidence_eligible
    assert interpret_table_cell(text, ev.table_cells).status == "conflicting"
    assert check_figures("Revenue was USD 1,234 million.", [ev], []).verdict == "unverified"


@pytest.mark.parametrize(
    "numerator,denominator",
    [
        ("xbrli:shares", None),
        ("xbrli:pure", None),
        ("unknown:widgets", None),
        ("iso4217:USD", "xbrli:shares"),
        ("iso4217:USD", "unknown:ratio"),
    ],
)
def test_non_amount_tags_never_borrow_a_tables_monetary_note(numerator, denominator):
    """A row named revenue cannot turn a share, ratio or per-share tag into revenue."""
    fragment = {
        "header_cells": [{"column": 1, "text": "2024"}],
        "caption_sources": [linked("(In millions of U.S. dollars)")],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": "1,234"}]},
        ],
    }
    cells = read_table_cells(
        fragment, {(1, 1): (fact(text="1,234", numerator=numerator, denominator=denominator),)}
    )
    assert not cells[0].evidence_eligible
    assert interpret_table_cell("1,234", cells).status == "not_monetary"
    assert (
        check_figures(
            "FY2024 revenue was USD 1,234 million.", [EvidenceText(1, "", "", cells)], [2024]
        ).verdict
        == "unverified"
    )


@pytest.mark.parametrize(
    "changes,verdict",
    [
        ({}, "verified"),
        ({"scale": None}, "withheld"),
        ({"currency": None}, "withheld"),
        ({"overrides": ("direction",)}, "withheld"),
        ({"years": frozenset({2023})}, "period_mismatch"),
    ],
)
def test_ordinary_amounts_and_unit_only_holds_survive(changes, verdict):
    """Retain annual amounts, deliberate unit/direction holds and real year mismatches."""
    cell = reading(**changes)
    assert cell.evidence_eligible
    assert (
        check_figures(
            "FY2024 revenue was USD 1,234 million.", [EvidenceText(1, "", "", [cell])], [2024]
        ).verdict
        == verdict
    )


def test_a_table_body_or_context_cannot_smuggle_in_a_prose_claim():
    """No table claim falls back to narrative when its canonical cells are ineligible."""
    claim = "Revenue was USD 1,234 million."
    assert check_figures(claim, [EvidenceText(1, claim, claim, [])], []).verdict == "unverified"
    assert check_figures(claim, [EvidenceText(1, claim, "", None)], []).verdict == "verified"


@pytest.mark.parametrize("notation", ["▲1,234", "(1,234)", "△1,234", "1,234"])
@pytest.mark.parametrize("sign,expected", [("-", -1234), ("+", 1234)])
def test_one_matching_monetary_tag_establishes_the_sign(notation, sign, expected):
    """Consume a tag's resolved sign in interpretation, persistence and comparison."""
    from decimal import Decimal

    from app.db.models import TableSourceCell
    from app.ingestion.persistence import reading_columns
    from app.retrieval.tables import _reading

    ev = fragment_evidence("Revenue", notation)
    assert ev.table_cells is not None
    fragment = {
        "header_cells": [{"column": 1, "text": "2024"}],
        "caption_sources": [linked("(In millions of U.S. dollars)")],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": notation}]},
        ],
    }
    (cell,) = read_table_cells(fragment, {(1, 1): (fact(text="1,234", sign=sign),)})
    assert cell.values == {Decimal(expected)}
    assert "direction" not in cell.overrides
    assert interpret_table_cell(notation, [cell]).value == expected
    source = TableSourceCell(grid_row=1, grid_column=1, **reading_columns(cell))
    assert _reading(source) == cell
    for claimed in (expected, -expected):
        claim = f"FY2024 revenue was USD {claimed:,} million."
        assert check_figures(claim, [EvidenceText(1, "", "", [cell])], [2024]).verdict == (
            "verified" if claimed == expected else "unverified"
        )


@pytest.mark.parametrize("prefix", ["FY'24", "fiscal 24", "FY'500", "fiscal 99999"])
def test_an_identifier_shaped_amount_with_a_unit_does_not_disappear(prefix):
    """Even new fiscal spellings keep a unit-bearing amount in the figure check."""
    from app.figures.answers import _claims

    claims = _claims(f"Revenue was {prefix} million USD.", answer=True)
    assert claims and claims[0].figure.value is not None


@pytest.mark.parametrize("period", ["for the year", "for the fiscal year", "for the prior year"])
def test_a_period_stated_without_a_year_number_cannot_borrow_running_text(period):
    """Narrative confirms only claims that ask for and state no period at all."""
    evidence = [EvidenceText(1, "Revenue was USD 1,234 million.", "")]
    assert (
        check_figures(f"Revenue {period} was USD 1,234 million.", evidence, []).verdict
        == "unverified"
    )
    assert check_figures("Revenue was USD 1,234 million.", evidence, []).verdict == "verified"


@pytest.mark.parametrize(
    "suffix,verdict", [("in FY2024", "verified"), ("in May 2024", "unverified")]
)
def test_grounded_issuer_words_are_not_claim_periods(suffix, verdict):
    """A month in the grounded issuer name is identity; a separately stated month is period."""
    from app.figures.vocabulary import items_named

    question = f"What was May Industries revenue {suffix}?"
    assert bool(items_named(question, issuers=("May Industries",))) is (verdict == "verified")
    evidence = [EvidenceText(1, "", "May Industries FY2024 · Item 7", [reading()])]
    answer = f"May Industries revenue {suffix} was USD 1,234 million."
    assert check_figures(answer, evidence, [2024]).verdict == verdict


@pytest.mark.parametrize(
    "form",
    [
        "fiscal 2024 (ended December 28, 2024)",
        "fiscal 2024 ended December 28, 2024",
        "fiscal year 2024 (ended Dec. 28, 2024)",
        "FY2024, which ended on December 28, 2024",
        "52 weeks ended December 28, 2024",
        "53-week fiscal year ended 12/28/2024",
        "twelve months ended December 28, 2024",
        "the year ended 12/28/2024",
        "fiscal 2024, a 52-week period",
        "52-week fiscal year 2024",
        "annual period 2024",
        "2024.01.01 ~ 2024.12.31",
    ],
)
def test_annual_ending_forms_confirm_only_the_matching_year(form):
    """Whole-year forms are understood without manufacturing a fiscal-year mapping."""
    claim = f"Revenue for {form} was USD 1,234 million."
    for year, expected in [(2024, "verified"), (2023, "period_mismatch")]:
        evidence = [EvidenceText(1, "", "", [reading(years=frozenset({year}))])]
        assert check_figures(claim, evidence, [2024]).verdict == expected


@pytest.mark.parametrize(
    "form",
    [
        "2024년 12월 28일로 종료된 회계연도",
        "2024년 12월 28일 종료 회계연도",
        "2024년 12월 28일에 종료되는 사업연도",
        "2024.12.28 종료 사업연도",
        "2024년 1월 1일부터 2024년 12월 31일까지",
    ],
)
def test_korean_annual_forms_share_the_question_and_answer_reading(form):
    """Korean endings and valid full-year ranges preserve annual revenue identity."""
    from app.figures.vocabulary import items_named

    assert items_named(f"AMD의 {form} 매출은?", issuers=("AMD",)) == {"revenue"}
    claim = f"{form}의 순매출은 1,234백만 달러입니다."
    assert (
        check_figures(claim, [EvidenceText(1, "", "", [reading()])], [2024]).verdict == "verified"
    )


@pytest.mark.parametrize("amount", ["1,234", "999,999"])
def test_an_unread_comparison_period_withholds_every_figure_without_a_false_mismatch(amount):
    """Any unread period qualifies the whole sentence, even its otherwise annual figure."""
    claim = (
        f"Net revenue was USD 1,234 million for 2024 compared to USD {amount} million "
        "for the prior year period."
    )
    result = check_figures(claim, [EvidenceText(1, "", "", [reading()])], [2024])
    assert [c.verdict for c in result.checks] == ["unverified", "unverified"]


@pytest.mark.parametrize("form", ["52 weeks", "12 months", "year ended 12/28/2024"])
def test_a_unit_after_an_annual_identifier_keeps_its_number_visible(form):
    """A fiscal-form number bearing a monetary unit must never disappear as a date."""
    from app.figures.answers import _claims

    claims = _claims(f"Revenue was {form} million USD.", answer=True)
    assert claims and claims[0].figure.value is not None


def test_a_calendar_end_without_an_explicit_fy_keeps_its_literal_year():
    """An end date in 2025 names 2025; no issuer-specific fiscal calendar is inferred."""
    from app.figures.answers import _claims

    claim = "Revenue for fiscal year ending January 26, 2025 was USD 1,234 million."
    assert _claims(claim, answer=True)[0].year == 2025
    assert (
        check_figures(claim, [EvidenceText(1, "", "", [reading()])], [2024]).verdict
        == "period_mismatch"
    )


def test_cross_calendar_explicit_fy_is_annual_but_answer_year_conflict_still_withholds():
    """Pin the answer-reader integration needed outside this bundle's write boundary."""
    from app.figures.answers import _claims

    claim = "Revenue for FY2024 ended January 26, 2025 was USD 1,234 million."
    parsed = _claims(claim, answer=True)[0]
    assert parsed.period == "annual" and parsed.dated_ambiguously
    assert (
        check_figures(claim, [EvidenceText(1, "", "", [reading()])], [2024]).verdict == "unverified"
    )


@pytest.mark.parametrize("currency", ["USD", "$", "BHD"])
@pytest.mark.parametrize("form", ["52 weeks", "12 months", "53-week fiscal year"])
def test_currency_before_an_annual_identifier_keeps_the_amount_visible(currency, form):
    """Shared annual blanking cannot erase a currency-bearing identifier-shaped amount."""
    from app.figures.answers import _claims

    claims = _claims(f"Revenue was {currency} {form}.", answer=True)
    assert claims and claims[0].figure.value is not None
