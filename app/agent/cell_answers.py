"""Check a model's table cell selection and assemble the answer from the stored cells.

The model proposes only cell refs with the item and fiscal year it claims for each; it
never writes an amount. This module checks the proposal against the cells fetched in
this question, re-reads them to catch changed sources, checks the question's items and
periods and each cell's established unit and currency, and then writes the answer in
English or Korean from the stored values, keeping sign, decimals and the table scale.
A missing unit or currency withholds the answer; another known period is reported as
a period mismatch; anything the model can correct is returned to it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
from typing import Any, Literal

from app.agent.types import (
    AgentPeriodMismatch,
    AgentReportAnswer,
    AgentUnitUnverified,
    CellSelection,
    CellSelectionAnswer,
)
from app.canonical_json import canonical_json
from app.contracts.evidence import EvidenceCitation

type Locale = Literal["en", "ko"]

# Statuses whose missing unit or currency withholds the whole answer.
UNIT_HOLDS = frozenset({"scale_unknown", "currency_unconfirmed"})

_ITEM_LABELS_KO = {
    "revenue": "매출",
    "cost of revenue": "매출원가",
    "gross profit": "매출총이익",
    "operating income": "영업이익",
    "net income": "순이익",
    "earnings per share": "주당이익",
    "basic earnings per share": "기본주당이익",
    "diluted earnings per share": "희석주당이익",
    "research and development": "연구개발비",
    "sales and marketing": "판매 및 마케팅비",
    "selling, general and administrative": "판매비와관리비",
    "income tax": "법인세",
    "accounts receivable": "매출채권",
    "total assets": "자산총계",
    "total liabilities": "부채총계",
    "total equity": "자본총계",
    "cash and cash equivalents": "현금및현금성자산",
}
_SCALES_EN = {0: "", 3: "thousand", 6: "million", 9: "billion", 12: "trillion"}
_SCALES_KO = {0: "", 3: "천", 4: "만", 6: "백만", 8: "억", 9: "십억", 12: "조"}

# Each report's answer and rationale are written in the report's language.
NOT_FOUND = {
    "en": (
        "The evidence retrieved in this question was searched and no table cell answering "
        "the question was found."
    ),
    "ko": "이 질문에서 검색한 근거에서 질문에 답하는 표의 칸을 찾지 못했습니다.",
}
CANNOT_RESOLVE = {
    "en": (
        "The cited evidence relates to the question, but no single table cell could be "
        "established as the answer, so no figure is reported."
    ),
    "ko": (
        "인용한 근거는 질문과 관련 있지만 답이 되는 표의 칸 하나를 확정하지 못해 "
        "수치를 보고하지 않습니다."
    ),
}
QUESTION_ITEM_UNREAD = {
    "en": (
        "The application could not read which item the question asks for, so the selected "
        "table cells could not be matched to it and no figure is reported."
    ),
    "ko": (
        "질문이 묻는 항목을 애플리케이션이 읽지 못해 선택된 표의 칸을 질문과 맞출 수 없으므로 "
        "수치를 보고하지 않습니다."
    ),
}
UNIT_HELD = {
    "en": (
        "The cited table names this item, but the unit or currency of its cell could not "
        "be confirmed, so no figure is reported."
    ),
    "ko": (
        "인용한 표에 이 항목이 있지만 해당 칸의 단위나 통화를 확정하지 못해 "
        "수치를 보고하지 않습니다."
    ),
}
PERIOD_MISMATCH = {
    "en": "The selected cells belong to a different period than the question asks about.",
    "ko": "선택된 칸은 질문이 묻는 기간과 다른 기간의 값입니다.",
}
ASSEMBLED = {
    "en": (
        "Assembled by the application from the selected table cells after checking their "
        "item, fiscal year, unit and currency."
    ),
    "ko": "선택된 표의 칸을 항목·회계연도·단위·통화로 확인한 뒤 애플리케이션이 작성했습니다.",
}


@dataclass(frozen=True, slots=True)
class StoredCell:
    """One fetched cell as stored now: its catalog record, source version and value."""

    ref: str
    chunk_id: int
    cell: Mapping[str, Any]
    stable_key: str
    resolver_identity: str
    value: Decimal | None


class StaleCellError(RuntimeError):
    """A selected cell's stored content or source version changed within the question."""


@dataclass(frozen=True, slots=True)
class CellVerdict:
    """The decision on one proposal: an accepted or qualified report, or a problem.

    ``report`` is None exactly when ``problem`` is set; ``checks`` are the private
    per-cell records kept in graph state, never shown to the model or the public.
    """

    report: AgentReportAnswer | None = None
    problem: str | None = None
    period_mismatch: AgentPeriodMismatch | None = None
    unit_unverified: AgentUnitUnverified | None = None
    checks: tuple[dict[str, Any], ...] = field(default=())


def cell_digest(cell: Mapping[str, Any]) -> str:
    """Identify one catalog cell's content, as the question's ledger records it."""
    return hashlib.sha256(canonical_json(dict(cell)).encode()).hexdigest()


def _scale_words(scale: Decimal, locale: Locale) -> str | None:
    """Name a power-of-ten table scale, or None when it has no plain name."""
    exponent = scale.normalize().as_tuple()
    if exponent.digits != (1,) or not isinstance(exponent.exponent, int):
        return None
    return (_SCALES_KO if locale == "ko" else _SCALES_EN).get(exponent.exponent)


def _amount(cell: StoredCell, locale: Locale) -> str:
    """Write a stored value with its sign, written decimals, scale and currency."""
    assert cell.value is not None
    number = f"{cell.value:,}"
    if cell.cell["percent"]:
        return f"{number}%"
    scale = Decimal(cell.cell["scale"])
    words = _scale_words(scale, locale)
    unit = words if words is not None else f"× {scale:f}"
    return " ".join(part for part in (number, unit, cell.cell["currency"]) if part)


def _line(cell: StoredCell, locale: Locale) -> str:
    """State one selected cell as one sentence of the answer."""
    (year,) = cell.cell["fiscal_years"]
    label = cell.cell["row_label"] or cell.cell["item"]
    if locale == "ko":
        label = _ITEM_LABELS_KO.get(cell.cell["item"], label)
        return f"{year} 회계연도 {label}: {_amount(cell, locale)}."
    return f"FY{year} {label}: {_amount(cell, locale)}."


def _citations(
    chunk_ids: Sequence[int], evidence: Mapping[int, Mapping[str, Any]]
) -> tuple[EvidenceCitation, ...]:
    """Cite each chunk once, in order, with the identity this question recorded."""
    return tuple(
        EvidenceCitation.model_validate(evidence[chunk_id]) for chunk_id in dict.fromkeys(chunk_ids)
    )


def _check(cell: StoredCell, decision: str) -> dict[str, Any]:
    """Record one cell's facts and the decision taken on it, as JSON values."""
    return {
        "ref": cell.ref,
        "status": cell.cell["status"],
        "item": cell.cell["item"],
        "fiscal_years": list(cell.cell["fiscal_years"]),
        "value": None if cell.value is None else str(cell.value),
        "decision": decision,
    }


def _combination_problem(proposal: CellSelectionAnswer) -> str | None:
    """Reject a label, reason and list combination the contract does not allow."""
    selected, unresolved = proposal.selections, proposal.unresolved_chunk_ids
    if proposal.label == "SUPPORTED" and proposal.reason == "selected":
        return (
            None
            if selected and not unresolved
            else ("a selected answer needs at least one selection and no unresolved chunks")
        )
    if proposal.label == "SUPPORTED" and proposal.reason == "cannot_resolve":
        return (
            None
            if unresolved and not selected
            else ("cannot_resolve needs unresolved_chunk_ids and no selections")
        )
    if proposal.label == "NOT_IN_DOCS" and proposal.reason == "not_found":
        return (
            None
            if not selected and not unresolved
            else ("not_found needs empty selections and unresolved_chunk_ids")
        )
    return f"label {proposal.label} cannot have reason {proposal.reason}"


def _cell_problem(selection: CellSelection, cell: StoredCell) -> str | None:
    """Return why one selected cell cannot stand for its claim, or None when it can.

    A known cell and a cell held only for its unit or currency are both checked
    against the claimed item and fiscal year; a cell with no item or no single year
    matches no claim. Any other status is not one established amount.
    """
    status, item, years = cell.cell["status"], cell.cell["item"], cell.cell["fiscal_years"]
    if status != "known" and status not in UNIT_HOLDS:
        return (
            f"cell {cell.ref} is {status}; it is not one established amount, "
            "so report cannot_resolve for its chunk instead"
        )
    if item is None:
        return (
            f"cell {cell.ref} has no established item, so it cannot be "
            f"{selection.claimed_item}; select another cell or report cannot_resolve for its "
            "chunk"
        )
    if selection.claimed_item != item:
        return f"cell {cell.ref} is {item}, not {selection.claimed_item}"
    if len(years) != 1:
        return (
            f"cell {cell.ref} has no single fiscal year, so it cannot be fiscal "
            f"{selection.claimed_fiscal_year}; select another cell or report cannot_resolve "
            "for its chunk"
        )
    if selection.claimed_fiscal_year != years[0]:
        return f"cell {cell.ref} is fiscal {years[0]}, not {selection.claimed_fiscal_year}"
    return None


def review_cell_selection(
    proposal: CellSelectionAnswer,
    *,
    ledger: Mapping[str, Mapping[str, Any]],
    evidence: Mapping[int, Mapping[str, Any]],
    stored: Mapping[str, StoredCell],
    requested_items: frozenset[str],
    requested_years: Sequence[int],
    locale: Locale = "en",
) -> CellVerdict:
    """Decide on one cell-selecting final answer.

    Parameters
    ----------
    proposal : CellSelectionAnswer
        The model's validated proposal.
    ledger : Mapping[str, Mapping[str, Any]]
        Cells fetched in this question, by ref, as :class:`ReviewGate` recorded them.
    evidence : Mapping[int, Mapping[str, Any]]
        Source identities retrieved in this question, by chunk id.
    stored : Mapping[str, StoredCell]
        The selected cells as stored now, read after the proposal.
    requested_items, requested_years : frozenset[str], Sequence[int]
        What the question asks for, read from the question by the application.
    locale : Locale
        Language the answer is written in.

    Raises
    ------
    StaleCellError
        If a selected cell's stored content or source version changed since it was
        fetched, which the model cannot correct.
    """
    problem = _combination_problem(proposal)
    if problem is not None:
        return CellVerdict(problem=problem)
    if proposal.reason == "not_found":
        if not evidence:
            return CellVerdict(
                problem="nothing was retrieved in this question; search the filings before "
                "reporting not_found"
            )
        return CellVerdict(
            AgentReportAnswer(
                label="NOT_IN_DOCS",
                answer="NOT_IN_DOCS",
                citations=(),
                rationale=NOT_FOUND[locale],
            )
        )
    if proposal.reason == "cannot_resolve":
        unknown = [
            chunk_id for chunk_id in proposal.unresolved_chunk_ids if chunk_id not in evidence
        ]
        if unknown:
            return CellVerdict(problem=f"chunk {unknown[0]} was not retrieved in this question")
        return CellVerdict(
            AgentReportAnswer(
                label="UNVERIFIED",
                answer=CANNOT_RESOLVE[locale],
                citations=_citations(proposal.unresolved_chunk_ids, evidence),
                rationale=CANNOT_RESOLVE[locale],
            )
        )

    refs = [selection.cell_id for selection in proposal.selections]
    if len(set(refs)) != len(refs):
        return CellVerdict(problem="each cell may be selected once")
    missing = next((ref for ref in refs if ref not in ledger), None)
    if missing is not None:
        return CellVerdict(
            problem=f"cell {missing} was not returned by a fetch in this question; fetch its chunk"
        )
    cells: list[StoredCell] = []
    for ref in refs:
        record, cell = ledger[ref], stored.get(ref)
        if (
            cell is None
            or cell_digest(cell.cell) != record["digest"]
            or (cell.stable_key, cell.resolver_identity)
            != (record["stable_key"], record["resolver_identity"])
        ):
            raise StaleCellError(f"stored cell {ref} changed after it was fetched")
        cells.append(cell)
    chunk_ids = [cell.chunk_id for cell in cells]
    for selection, cell in zip(proposal.selections, cells, strict=True):
        problem = _cell_problem(selection, cell)
        if problem is not None:
            return CellVerdict(problem=problem)
    if not requested_items:
        return CellVerdict(
            AgentReportAnswer(
                label="UNVERIFIED",
                answer=QUESTION_ITEM_UNREAD[locale],
                citations=_citations(chunk_ids, evidence),
                rationale=QUESTION_ITEM_UNREAD[locale],
            ),
            checks=tuple(_check(cell, "question item unknown") for cell in cells),
        )
    off_item = next((cell for cell in cells if cell.cell["item"] not in requested_items), None)
    if off_item is not None:
        asked = ", ".join(sorted(requested_items))
        return CellVerdict(
            problem=f"cell {off_item.ref} is {off_item.cell['item']}; the question asks for {asked}"
        )
    # A unit hold withholds the whole answer, but only once the held cell is what the
    # model claimed and what the question asks for; it outranks a period mismatch.
    held = [cell for cell in cells if cell.cell["status"] in UNIT_HOLDS]
    if held:
        return CellVerdict(
            AgentReportAnswer(
                label="UNVERIFIED",
                answer=UNIT_HELD[locale],
                citations=_citations(chunk_ids, evidence),
                rationale=UNIT_HELD[locale],
            ),
            unit_unverified=AgentUnitUnverified(
                figures=tuple(cell.cell["raw_text"] for cell in held)
            ),
            checks=tuple(_check(cell, "held") for cell in cells),
        )
    years = {cell.cell["fiscal_years"][0] for cell in cells}
    requested = set(requested_years)
    if requested and not years & requested:
        mismatch = AgentPeriodMismatch(
            requested_fiscal_years=tuple(sorted(requested)),
            evidenced_fiscal_years=tuple(sorted(years)),
            figures=tuple(cell.cell["raw_text"] for cell in cells),
        )
        asked = ", ".join(str(year) for year in mismatch.requested_fiscal_years)
        found = ", ".join(str(year) for year in mismatch.evidenced_fiscal_years)
        # Only the selection was checked, not whether the evidence reports the
        # asked period elsewhere, so the sentence speaks about the selection alone.
        if locale == "ko":
            answer = f"선택된 표의 칸은 {asked} 회계연도가 아니라 {found} 회계연도의 값입니다."
        else:
            answer = f"The selected table cells are for fiscal {found}, not fiscal {asked}."
        return CellVerdict(
            AgentReportAnswer(
                label="PERIOD_MISMATCH",
                answer=answer,
                citations=_citations(chunk_ids, evidence),
                rationale=PERIOD_MISMATCH[locale],
            ),
            period_mismatch=mismatch,
            checks=tuple(_check(cell, "other period") for cell in cells),
        )
    covered = {(cell.cell["item"], cell.cell["fiscal_years"][0]) for cell in cells}
    wanted = [(item, year) for item in sorted(requested_items) for year in sorted(requested)]
    gap = next((pair for pair in wanted if pair not in covered), None)
    if gap is None and not requested:
        gap = next(
            (
                (item, None)
                for item in sorted(requested_items)
                if item not in {i for i, _ in covered}
            ),
            None,
        )
    if gap is not None:
        item, year = gap
        period = "" if year is None else f" for fiscal {year}"
        return CellVerdict(problem=f"no selected cell answers {item}{period}")
    return CellVerdict(
        AgentReportAnswer(
            label="SUPPORTED",
            answer=" ".join(_line(cell, locale) for cell in cells),
            citations=_citations(chunk_ids, evidence),
            rationale=ASSEMBLED[locale],
        ),
        checks=tuple(_check(cell, "accepted") for cell in cells),
    )
