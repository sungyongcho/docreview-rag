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
        ({"scale": None}, "unit_unverified"),
        ({"currency": None}, "unit_unverified"),
        ({"overrides": ("direction",)}, "unit_unverified"),
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
    from app.figures.periods import classify_period
    from app.figures.vocabulary import items_named

    assert (classify_period(phrase) == "annual") is annual
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
