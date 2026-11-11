"""Cell selections checked against the question and assembled from stored values."""

from dataclasses import replace
from decimal import Decimal
import json
from typing import Any

from pydantic import ValidationError
import pytest

from app.agent.cell_answers import (
    StaleCellError,
    StoredCell,
    cell_digest,
    review_cell_selection,
)
from app.agent.types import CellSelectionAnswer
from app.figures.answers import UNIT_UNVERIFIED_ANSWER_KO, UNIT_UNVERIFIED_RATIONALE_KO
from app.figures.items import ITEMS
from app.figures.vocabulary import PHRASE_ITEMS, items_named
from app.retrieval.tables import cell_ref_chunk

SOURCE = "a" * 64
STABLE = "k" * 64
RESOLVER = "r" * 64


def identity(chunk_id: int) -> dict[str, Any]:
    """Return one retrieved chunk's complete source identity."""
    return {
        "chunk_id": chunk_id,
        "doc_id": "TESTCO-FY2024",
        "citation": "TestCo FY2024 · Item 8",
        "start_char": 0,
        "end_char": 100,
        "source_sha256": SOURCE,
    }


def stored(ref: str = "2024:r1c1", value: str = "25785", **cell: Any) -> StoredCell:
    """Return one stored revenue cell for FY2024 in USD millions, changed where asked."""
    record = {
        "ref": ref,
        "row_label": "Net revenue",
        "column_header": "2024",
        "raw_text": f"$ {value}",
        "item": "revenue",
        "fiscal_years": [2024],
        "scale": "1000000",
        "currency": "USD",
        "percent": False,
        "status": "known",
        "complete": True,
        **cell,
    }
    return StoredCell(ref, cell_ref_chunk(ref), record, STABLE, RESOLVER, Decimal(value))


def ledger_of(*cells: StoredCell) -> dict[str, dict[str, Any]]:
    """Record cells as this question's fetches returned them."""
    return {
        cell.ref: {
            "chunk_id": cell.chunk_id,
            "stable_key": cell.stable_key,
            "resolver_identity": cell.resolver_identity,
            "digest": cell_digest(cell.cell),
        }
        for cell in cells
    }


def proposal(*selections: tuple[str, str, int], **changes: Any) -> CellSelectionAnswer:
    """Build a selected proposal, or another combination through ``changes``."""
    return CellSelectionAnswer.model_validate_json(
        json.dumps(
            {
                "contract_version": "cell-v1",
                "label": "SUPPORTED",
                "reason": "selected",
                "selections": [
                    {"cell_id": ref, "claimed_item": item, "claimed_fiscal_year": year}
                    for ref, item, year in selections
                ],
                "unresolved_chunk_ids": [],
                **changes,
            }
        )
    )


def review(answer: CellSelectionAnswer, *cells: StoredCell, fetched=None, **context: Any):
    """Review one proposal against the cells fetched and stored for chunk 2024."""
    return review_cell_selection(
        answer,
        ledger=ledger_of(*(fetched if fetched is not None else cells)),
        evidence=context.get("evidence", {2024: identity(2024)}),
        stored={cell.ref: cell for cell in cells},
        requested_items=context.get("items", frozenset({"revenue"})),
        requested_years=context.get("years", (2024,)),
        searched=context.get("searched", True),
        locale=context.get("locale", "en"),
    )


def test_a_matching_cell_is_answered_from_its_stored_value_in_each_language():
    """Write the stored value with its scale and currency; the model writes no amount."""
    choice = proposal(("2024:r1c1", "revenue", 2024))
    english = review(choice, stored())
    korean = review(choice, stored(), locale="ko")
    assert english.report is not None and korean.report is not None
    assert english.report.label == "SUPPORTED"
    assert english.report.answer == "FY2024 Net revenue: 25,785 million USD."
    assert korean.report.answer == "2024 회계연도 매출: 25,785 백만 USD."
    assert [citation.chunk_id for citation in english.report.citations] == [2024]


def test_sign_and_written_decimals_survive_assembly():
    """Keep a loss negative and every written decimal, without rounding the scale away."""
    loss = stored(
        value="-1641.50", raw_text="(1,641.50)", item="net income", row_label="Net income (loss)"
    )
    result = review(
        proposal(("2024:r1c1", "net income", 2024)), loss, items=frozenset({"net income"})
    )
    assert result.report is not None
    assert result.report.answer == "FY2024 Net income: -1,641.50 million USD."


def test_a_wrong_row_or_year_claim_is_returned_for_correction():
    """Return a claim whose item or year differs from the cell, accepting nothing."""
    wrong_item = review(proposal(("2024:r1c1", "net income", 2024)), stored())
    wrong_year = review(proposal(("2024:r1c1", "revenue", 2023)), stored())
    assert wrong_item.report is None and wrong_item.problem == (
        "cell 2024:r1c1 is revenue, not net income"
    )
    assert wrong_year.report is None and "fiscal 2024, not 2023" in (wrong_year.problem or "")


def test_a_cell_of_an_item_the_question_does_not_ask_for_is_refused():
    """Never let a correctly claimed but unasked item answer the question."""
    result = review(
        proposal(("2024:r1c1", "net income", 2024)),
        stored(item="net income"),
    )
    assert result.problem == "cell 2024:r1c1 is net income; the question asks for revenue"


def test_another_known_period_is_a_period_mismatch_not_an_answer():
    """Report the cell's own period when every selected cell is outside the request."""
    result = review(
        proposal(("2024:r1c2", "revenue", 2023)), stored("2024:r1c2", fiscal_years=[2023])
    )
    assert result.report is not None and result.report.label == "PERIOD_MISMATCH"
    assert result.period_mismatch is not None
    assert result.period_mismatch.evidenced_fiscal_years == (2023,)
    assert "25,785" not in result.report.answer
    assert "25785" not in result.report.answer


def test_a_period_mismatch_states_only_what_the_selection_shows_in_each_language():
    """Say the selected cells are for another year; never that the evidence lacks the asked one."""
    choice = proposal(("2024:r1c2", "revenue", 2023))
    cell = stored("2024:r1c2", fiscal_years=[2023])
    english, korean = review(choice, cell), review(choice, cell, locale="ko")
    assert english.report is not None and korean.report is not None
    assert english.report.answer == "The selected table cells are for fiscal 2023, not fiscal 2024."
    assert (
        korean.report.answer == "선택된 표의 칸은 2024 회계연도가 아니라 2023 회계연도의 값입니다."
    )
    assert english.report.rationale == (
        "The selected cells belong to a different period than the question asks about."
    )
    assert korean.report.rationale == "선택된 칸은 질문이 묻는 기간과 다른 기간의 값입니다."


def test_not_found_before_any_search_returned_is_returned_for_a_search():
    """Never report a search that did not happen; a search with no hits is a search."""
    absent = proposal(label="NOT_IN_DOCS", reason="not_found", selections=[])
    unsearched = review(absent, evidence={}, searched=False)
    zero_hits = review(absent, evidence={})
    with_hits = review(absent)
    assert unsearched.report is None and unsearched.problem == (
        "no search has returned in this question; search the filings before reporting not_found"
    )
    for result in (zero_hits, with_hits):
        assert result.report is not None and result.report.label == "NOT_IN_DOCS"
        assert result.report.citations == ()
        assert result.report.rationale == (
            "The filings were searched in this question; "
            "the model reported no answering table cell."
        )


def test_every_korean_report_has_a_korean_rationale():
    """Write the rationale in the report's language, as the assembled answer already was."""
    unit = review(
        proposal(("2024:r1c1", "revenue", 2024)),
        stored(currency="$", status="currency_unconfirmed"),
        locale="ko",
    )
    unresolved = review(
        proposal(reason="cannot_resolve", selections=[], unresolved_chunk_ids=[2024]),
        locale="ko",
    )
    absent = review(proposal(label="NOT_IN_DOCS", reason="not_found", selections=[]), locale="ko")
    assert unit.report is not None and unit.report.answer == UNIT_UNVERIFIED_ANSWER_KO
    assert unit.report.rationale == UNIT_UNVERIFIED_RATIONALE_KO
    assert unresolved.report is not None
    assert (
        unresolved.report.answer
        == unresolved.report.rationale
        == ("인용한 근거에서 답이 되는 표의 칸을 확정하지 못해 수치를 보고하지 않습니다.")
    )
    assert absent.report is not None and absent.report.rationale == (
        "이 질문에서 공시를 검색했고 모델은 질문에 답하는 표의 칸을 찾지 못했다고 보고했습니다."
    )


def test_an_unconfirmed_currency_withholds_every_amount():
    """Withhold the answer and keep the amount out of every public field."""
    dollar = stored(currency="$", status="currency_unconfirmed")
    result = review(proposal(("2024:r1c1", "revenue", 2024)), dollar)
    assert result.report is not None and result.report.label == "UNVERIFIED"
    assert "25,785" not in result.report.answer + result.report.rationale
    assert result.unit_unverified is not None
    assert result.unit_unverified.figures == ("$ 25785",)


HELD = {"currency": "$", "status": "currency_unconfirmed"}


@pytest.mark.parametrize(
    ("cell", "claim", "items", "expected"),
    [
        (
            {"item": "total assets", "fiscal_years": [2019], "status": "scale_unknown"},
            ("net income", 2031),
            {"revenue"},
            "cell 2024:r1c1 is total assets, not net income",
        ),
        (
            {"item": None, "fiscal_years": [], **HELD},
            ("revenue", 2024),
            {"revenue"},
            "cell 2024:r1c1 has no established item, so it cannot be revenue; select another "
            "cell or report cannot_resolve for its chunk",
        ),
        (
            {"fiscal_years": [], **HELD},
            ("revenue", 2024),
            {"revenue"},
            "cell 2024:r1c1 has no single fiscal year, so it cannot be fiscal 2024; select "
            "another cell or report cannot_resolve for its chunk",
        ),
        ({**HELD}, ("revenue", 2023), {"revenue"}, "cell 2024:r1c1 is fiscal 2024, not 2023"),
        (
            {"item": "net income", **HELD},
            ("net income", 2024),
            {"revenue"},
            "cell 2024:r1c1 is net income; the question asks for revenue",
        ),
    ],
)
def test_a_held_cell_is_checked_against_its_claim_and_the_question_first(
    cell, claim, items, expected
):
    """Return a held cell that is not what was claimed or asked, as for a known cell."""
    result = review(proposal(("2024:r1c1", *claim)), stored(**cell), items=frozenset(items))
    assert result.report is None and result.problem == expected
    assert result.unit_unverified is None


def test_a_held_cell_that_matches_is_withheld_even_for_another_period():
    """Withhold a matching held cell, and let the hold outrank a period mismatch."""
    for years in ((2024,), (2023,)):
        result = review(proposal(("2024:r1c1", "revenue", 2024)), stored(**HELD), years=years)
        assert result.report is not None and result.report.label == "UNVERIFIED"
        assert result.unit_unverified is not None and result.period_mismatch is None
    known, held = stored(), stored("2024:r1c2", item="net income", **HELD)
    both = review(
        proposal(("2024:r1c1", "revenue", 2024), ("2024:r1c2", "net income", 2024)),
        known,
        held,
        items=frozenset({"revenue", "net income"}),
    )
    assert both.report is not None and both.report.label == "UNVERIFIED"
    assert both.unit_unverified is not None and both.unit_unverified.figures == ("$ 25785",)
    assert [check["decision"] for check in both.checks] == ["held", "held"]


def test_two_cells_for_one_item_and_year_are_returned_for_correction():
    """Refuse two amounts for the same item and year instead of reporting both."""
    other = stored("2025:r1c1", value="99999")
    result = review_cell_selection(
        proposal(("2024:r1c1", "revenue", 2024), ("2025:r1c1", "revenue", 2024)),
        ledger=ledger_of(stored(), other),
        evidence={2024: identity(2024), 2025: identity(2025)},
        stored={"2024:r1c1": stored(), "2025:r1c1": other},
        requested_items=frozenset({"revenue"}),
        requested_years=(2024,),
        searched=True,
    )
    assert result.report is None and result.problem == (
        "cells 2024:r1c1 and 2025:r1c1 both answer revenue for fiscal 2024; select one cell "
        "for each item and fiscal year"
    )


def test_cells_for_different_years_or_items_are_still_answered_together():
    """Keep reporting one cell per item and year, in selection order."""
    years = review(
        proposal(("2024:r1c1", "revenue", 2024), ("2024:r1c2", "revenue", 2023)),
        stored(),
        stored("2024:r1c2", value="22680", fiscal_years=[2023]),
        years=(2023, 2024),
    )
    items = review(
        proposal(("2024:r1c1", "revenue", 2024), ("2024:r2c1", "net income", 2024)),
        stored(),
        stored("2024:r2c1", value="1641", item="net income", row_label="Net income"),
        items=frozenset({"revenue", "net income"}),
    )
    assert years.report is not None and years.report.answer == (
        "FY2024 Net revenue: 25,785 million USD. FY2023 Net revenue: 22,680 million USD."
    )
    assert items.report is not None and items.report.answer == (
        "FY2024 Net revenue: 25,785 million USD. FY2024 Net income: 1,641 million USD."
    )


def test_a_cell_of_an_unasked_year_beside_an_asked_one_is_returned_for_correction():
    """Refuse an unasked year like an unasked item once another cell answers the asked year."""
    older = stored("2024:r1c2", value="22680", fiscal_years=[2023])
    held_older = stored("2024:r1c2", value="22680", fiscal_years=[2023], **HELD)
    two_years = proposal(("2024:r1c1", "revenue", 2024), ("2024:r1c2", "revenue", 2023))
    known = review(two_years, stored(), older)
    held = review(two_years, stored(), held_older)
    wider = review(
        proposal(("2024:r1c1", "revenue", 2024), ("2024:r1c2", "revenue", 2022)),
        stored(),
        stored("2024:r1c2", fiscal_years=[2022]),
        years=(2023, 2024),
    )
    problem = "cell 2024:r1c2 is fiscal 2023; the question asks for fiscal 2024"
    assert known.report is None and known.problem == problem
    assert held.report is None and held.problem == problem and held.unit_unverified is None
    assert wider.problem == "cell 2024:r1c2 is fiscal 2022; the question asks for fiscal 2023, 2024"


def test_years_the_question_asks_for_or_does_not_restrict_are_still_answered():
    """Answer every asked year, any year of an undated question, and hold an asked held cell."""
    older = stored("2024:r1c2", value="22680", fiscal_years=[2023])
    two_years = proposal(("2024:r1c1", "revenue", 2024), ("2024:r1c2", "revenue", 2023))
    undated = review(two_years, stored(), older, years=())
    assert undated.report is not None and undated.report.label == "SUPPORTED"
    assert "FY2023 Net revenue: 22,680 million USD." in undated.report.answer
    asked_held = review(
        two_years,
        stored(**HELD),
        older,
        years=(2023, 2024),
    )
    assert asked_held.report is not None and asked_held.report.label == "UNVERIFIED"
    assert asked_held.unit_unverified is not None
    assert asked_held.unit_unverified.figures == ("$ 25785",)
    only_older = review(proposal(("2024:r1c2", "revenue", 2023)), older)
    assert only_older.report is not None and only_older.report.label == "PERIOD_MISMATCH"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (
            {"percent": True, "value": "49", "item": "gross profit", "row_label": "Gross margin"},
            "cell 2024:r1c1 is a percentage, not the amount of gross profit; select the "
            "amount's cell or report cannot_resolve for its chunk",
        ),
        (
            {"complete": False, "item": "gross profit"},
            "cell 2024:r1c1 is only partly in its chunk's text, so it is not one established "
            "amount; select another cell or report cannot_resolve for its chunk",
        ),
        (
            {"percent": True, "value": "49", "item": "gross profit", **HELD},
            "cell 2024:r1c1 is a percentage, not the amount of gross profit; select the "
            "amount's cell or report cannot_resolve for its chunk",
        ),
    ],
)
def test_a_percentage_or_partial_cell_is_not_an_amount(cell, expected):
    """Never state a percentage or a partly cited cell as an item's amount."""
    result = review(
        proposal(("2024:r1c1", "gross profit", 2024)),
        stored(**cell),
        items=frozenset({"gross profit"}),
    )
    assert result.report is None and result.problem == expected


def test_a_cell_not_fetched_in_this_question_is_refused():
    """Knowing a ref is not enough: the cell must have been fetched in this question."""
    result = review(proposal(("2024:r1c1", "revenue", 2024)), stored(), fetched=())
    assert result.problem == (
        "cell 2024:r1c1 was not returned by a fetch in this question; fetch its chunk"
    )


def test_a_cell_whose_stored_content_changed_is_a_system_failure():
    """Stop instead of answering from a cell that changed after it was fetched."""
    with pytest.raises(StaleCellError, match="2024:r1c1"):
        review(
            proposal(("2024:r1c1", "revenue", 2024)),
            stored(value="99999"),
            fetched=(stored(),),
        )


def test_a_changed_source_version_alone_is_a_system_failure():
    """Stop when only the stored resolver identity or stable key changed after the fetch."""
    for change in ({"resolver_identity": "s" * 64}, {"stable_key": "j" * 64}):
        fetched = stored()
        now = replace(fetched, **change)
        with pytest.raises(StaleCellError, match="2024:r1c1"):
            review(proposal(("2024:r1c1", "revenue", 2024)), now, fetched=(fetched,))


def test_a_cell_selected_twice_is_returned_for_correction():
    """Refuse the same ref listed twice before reading anything about it."""
    result = review(
        proposal(("2024:r1c1", "revenue", 2024), ("2024:r1c1", "revenue", 2024)), stored()
    )
    assert result.report is None and result.problem == "each cell may be selected once"


def test_an_unresolved_chunk_not_retrieved_in_this_question_is_refused():
    """Cite only chunks this question retrieved when reporting cannot_resolve."""
    result = review(proposal(reason="cannot_resolve", selections=[], unresolved_chunk_ids=[999]))
    assert result.report is None
    assert result.problem == "chunk 999 was not retrieved in this question"


def test_an_undated_question_needs_a_cell_for_each_item():
    """Without a requested year, require some selected cell for every requested item."""
    result = review(
        proposal(("2024:r1c1", "revenue", 2024)),
        stored(),
        items=frozenset({"revenue", "net income"}),
        years=(),
    )
    answered = review(proposal(("2024:r1c1", "revenue", 2024)), stored(), years=())
    assert result.problem == "no selected cell answers net income"
    assert answered.report is not None and answered.report.label == "SUPPORTED"


def test_a_missing_requested_combination_is_returned_for_correction():
    """Require a cell for every requested item and year once one requested year is met."""
    result = review(proposal(("2024:r1c1", "revenue", 2024)), stored(), years=(2023, 2024))
    assert result.problem == "no selected cell answers revenue for fiscal 2023"


def test_a_question_without_a_recognized_item_is_withheld():
    """Withhold rather than guess which row the question meant."""
    result = review(proposal(("2024:r1c1", "revenue", 2024)), stored(), items=frozenset())
    korean = review(
        proposal(("2024:r1c1", "revenue", 2024)), stored(), items=frozenset(), locale="ko"
    )
    assert result.report is not None and result.report.label == "UNVERIFIED"
    assert result.report.answer == (
        "The application could not read which item the question asks for, so the selected "
        "table cells could not be matched to it and no figure is reported."
    )
    assert korean.report is not None and korean.report.answer == (
        "질문이 묻는 항목을 애플리케이션이 읽지 못해 선택된 표의 칸을 질문과 맞출 수 없으므로 "
        "수치를 보고하지 않습니다."
    )
    assert "25,785" not in result.report.answer + korean.report.answer


@pytest.mark.parametrize(
    "question",
    [
        "What was AMD's Q4 2024 revenue?",
        "What was AMD's revenue in December 2024?",
        "What was AMD's revenue for the period ended March 30, 2024?",
    ],
)
def test_a_shorter_period_question_is_never_answered_from_the_annual_cell(question):
    """Withhold, never support, the FY2024 annual cell for a quarter, month or period."""
    asked = items_named(question, issuers=("AMD",))
    choice = proposal(("2024:r1c1", "revenue", 2024))
    shorter = review(choice, stored(), items=asked)
    assert shorter.report is not None and shorter.report.label == "UNVERIFIED"
    assert "25,785" not in shorter.report.answer


@pytest.mark.parametrize(
    "question",
    [
        "What was AMD's 2024 revenue?",
        "What was AMD's revenue for the year ended December 28, 2024?",
        "How much revenue did AMD generate in 2024 according to its 10-K?",
    ],
)
def test_an_annual_question_is_still_answered_from_the_annual_cell(question):
    """Support the FY2024 annual cell for an annual question in its real forms."""
    asked = items_named(question, issuers=("AMD",))
    whole = review(proposal(("2024:r1c1", "revenue", 2024)), stored(), items=asked)
    assert whole.report is not None and whole.report.label == "SUPPORTED"


def test_cannot_resolve_and_not_found_are_distinct_reports():
    """Keep evidence that cannot be reduced to a cell apart from evidence that is absent."""
    unresolved = review(
        proposal(reason="cannot_resolve", selections=[], unresolved_chunk_ids=[2024])
    )
    absent = review(proposal(label="NOT_IN_DOCS", reason="not_found", selections=[]))
    assert unresolved.report is not None and unresolved.report.label == "UNVERIFIED"
    assert [c.chunk_id for c in unresolved.report.citations] == [2024]
    assert absent.report is not None and absent.report.answer == "NOT_IN_DOCS"
    mixed = review(proposal(("2024:r1c1", "revenue", 2024), reason="not_found"), stored())
    assert mixed.report is None and mixed.problem is not None


@pytest.mark.parametrize(
    "change",
    [
        {"answer": "$25,785 million"},
        {
            "selections": [
                {"cell_id": "2024:r1c1", "claimed_item": "revenue", "claimed_fiscal_year": True}
            ]
        },
        {
            "selections": [
                {"cell_id": "c1:abc", "claimed_item": "revenue", "claimed_fiscal_year": 2024}
            ]
        },
        {"contract_version": "cell-v2"},
    ],
)
def test_the_schema_has_no_place_for_an_amount_or_a_loose_value(change):
    """Reject an extra amount field, a boolean year, an unknown ref shape and version."""
    with pytest.raises(ValidationError):
        proposal(**change)


def test_every_item_has_a_korean_label():
    """Name in Korean exactly the items the figure vocabulary recognizes."""
    assert set(ITEMS) == set(PHRASE_ITEMS.values())
