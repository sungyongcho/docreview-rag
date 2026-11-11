"""Cell selections checked against the question and assembled from stored values."""

from decimal import Decimal
import json
from typing import Any

from pydantic import ValidationError
import pytest

from app.agent.cell_answers import (
    _ITEM_LABELS_KO,
    StaleCellError,
    StoredCell,
    cell_digest,
    review_cell_selection,
)
from app.agent.types import CellSelectionAnswer
from app.figures.vocabulary import PHRASE_ITEMS
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
        evidence={2024: identity(2024)},
        stored={cell.ref: cell for cell in cells},
        requested_items=context.get("items", frozenset({"revenue"})),
        requested_years=context.get("years", (2024,)),
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
    assert result.report.answer == "FY2024 Net income (loss): -1,641.50 million USD."


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
    assert unit.report is not None and unit.report.answer == unit.report.rationale == (
        "인용한 표에 이 항목이 있지만 해당 칸의 단위나 통화를 확정하지 못해 "
        "수치를 보고하지 않습니다."
    )
    assert unresolved.report is not None
    assert (
        unresolved.report.answer
        == unresolved.report.rationale
        == (
            "인용한 근거는 질문과 관련 있지만 답이 되는 표의 칸 하나를 확정하지 못해 "
            "수치를 보고하지 않습니다."
        )
    )
    assert absent.report is not None and absent.report.rationale == (
        "이 질문에서 검색한 근거에서 질문에 답하는 표의 칸을 찾지 못했습니다."
    )


def test_an_unconfirmed_currency_withholds_every_amount():
    """Withhold the answer and keep the amount out of every public field."""
    dollar = stored(currency="$", status="currency_unconfirmed")
    result = review(proposal(("2024:r1c1", "revenue", 2024)), dollar)
    assert result.report is not None and result.report.label == "UNVERIFIED"
    assert "25,785" not in result.report.answer + result.report.rationale
    assert result.unit_unverified is not None
    assert result.unit_unverified.figures == ("$ 25785",)


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
    assert set(_ITEM_LABELS_KO) == set(PHRASE_ITEMS.values())
