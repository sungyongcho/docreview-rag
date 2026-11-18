"""Review a model's table cell selection and assemble the answer from the stored cells.

The model proposes only cell refs with the item and fiscal year it claims for each; it
never writes an amount. :func:`review_cell_answer` validates the proposal and re-reads
the selected cells to catch changed sources; :func:`review_cell_selection` checks the
proposal against the cells fetched in this question, the question's items and periods
and each cell's established unit and currency, and then writes the answer in English or
Korean from the stored values, keeping sign, decimals and the table scale. A missing
unit or currency withholds the answer; another known period is reported as a period
mismatch; anything the model can correct is returned to it. Only the prebuilt agent
offers this mode (``cell_answers`` in :mod:`app.review.policy`).
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal

from pydantic import ValidationError

from app.contracts.answers import AgentReportAnswer, CellSelection, CellSelectionAnswer
from app.contracts.evidence import EvidenceCitation
from app.contracts.figures import FiguresWithheld, PeriodMismatch, ordered_causes
from app.figures.items import ITEMS
from app.figures.tables import WITHHOLDING_CAUSES
from app.llm.decoding import validation_errors
from app.review.evidence import CellReader, StoredCell
from app.review.final_answer import EvidenceReadError, FinalReview
from app.review.ledger import cell_digest
from app.review.reports import QualifiedReport, period_mismatch_report, withheld_report
from app.tools.registry import safe_runtime_error

type Locale = Literal["en", "ko"]

_SCALES_EN = {0: "", 3: "thousand", 6: "million", 9: "billion", 12: "trillion"}
_SCALES_KO = {0: "", 3: "천", 4: "만", 6: "백만", 8: "억", 9: "십억", 12: "조"}

# Each report's answer and rationale are written in the report's language.
# True also when the search returned no hits: nothing is claimed about retrieved chunks.
NOT_FOUND = {
    "en": (
        "The filings were searched in this question; the model reported no answering table cell."
    ),
    "ko": "이 질문에서 공시를 검색했고 모델은 질문에 답하는 표의 칸을 찾지 못했다고 보고했습니다.",
}
CANNOT_RESOLVE = {
    "en": (
        "No answering table cell was established from the cited evidence, so no figure is reported."
    ),
    "ko": ("인용한 근거에서 답이 되는 표의 칸을 확정하지 못해 수치를 보고하지 않습니다."),
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
ASSEMBLED = {
    "en": (
        "Assembled by the application from the selected table cells after checking their "
        "item, fiscal year, unit and currency."
    ),
    "ko": "선택된 표의 칸을 항목·회계연도·단위·통화로 확인한 뒤 애플리케이션이 작성했습니다.",
}


class StaleCellError(RuntimeError):
    """A selected cell's stored content or source version changed within the question."""


def _scale_words(scale: Decimal, locale: Locale) -> str | None:
    """Name a power-of-ten table scale, or None when it has no plain name."""
    exponent = scale.normalize().as_tuple()
    if exponent.digits != (1,) or not isinstance(exponent.exponent, int):
        return None
    return (_SCALES_KO if locale == "ko" else _SCALES_EN).get(exponent.exponent)


def _amount(cell: StoredCell, locale: Locale) -> str:
    """Write a stored amount with its sign, written decimals, scale and currency.

    Only an accepted cell reaches this; ``_cell_problem`` returns every percentage.
    """
    assert cell.value is not None
    number = f"{cell.value:,}"
    scale = Decimal(cell.cell["scale"])
    words = _scale_words(scale, locale)
    unit = words if words is not None else f"× {scale:f}"
    return " ".join(part for part in (number, unit, cell.cell["currency"]) if part)


def _line(cell: StoredCell, locale: Locale) -> str:
    """State one selected cell as one sentence of the answer."""
    (year,) = cell.cell["fiscal_years"]
    definition = ITEMS[cell.cell["item"]]
    label = definition.label_en
    if locale == "ko":
        label = definition.label_ko
        return f"{year} 회계연도 {label}: {_amount(cell, locale)}."
    return f"FY{year} {label}: {_amount(cell, locale)}."


def _citations(
    chunk_ids: Sequence[int], evidence: Mapping[int, Mapping[str, Any]]
) -> tuple[EvidenceCitation, ...]:
    """Cite each chunk once, in order, with the identity this question recorded."""
    return tuple(
        EvidenceCitation.model_validate(evidence[chunk_id]) for chunk_id in dict.fromkeys(chunk_ids)
    )


def _report(
    qualified: QualifiedReport, citations: tuple[EvidenceCitation, ...]
) -> AgentReportAnswer:
    """Give a report the application wrote the citations of its selected cells."""
    return AgentReportAnswer(
        label=qualified.label,
        answer=qualified.answer,
        citations=citations,
        rationale=qualified.rationale,
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
    matches no claim. Any other status, a cell only partly in its chunk's text and a
    percentage are not one established amount of an item.
    """
    status, item, years = cell.cell["status"], cell.cell["item"], cell.cell["fiscal_years"]
    if status != "known" and status not in WITHHOLDING_CAUSES:
        return (
            f"cell {cell.ref} is {status}; it is not one established amount, "
            "so report cannot_resolve for its chunk instead"
        )
    if cell.cell["complete"] is not True:
        return (
            f"cell {cell.ref} is only partly in its chunk's text, so it is not one "
            "established amount; select another cell or report cannot_resolve for its chunk"
        )
    if cell.cell["percent"]:
        return (
            f"cell {cell.ref} is a percentage, not the amount of {selection.claimed_item}; "
            "select the amount's cell or report cannot_resolve for its chunk"
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
    searched: bool,
    locale: Locale,
) -> FinalReview:
    """Decide on one cell-selecting final answer.

    Parameters
    ----------
    proposal : CellSelectionAnswer
        The model's validated proposal.
    ledger : Mapping[str, Mapping[str, Any]]
        Cells fetched in this question, by ref, as the question's ledger recorded them.
    evidence : Mapping[int, Mapping[str, Any]]
        Source identities retrieved in this question, by chunk id.
    stored : Mapping[str, StoredCell]
        The selected cells as stored now, read after the proposal.
    requested_items, requested_years : frozenset[str], Sequence[int]
        What the question asks for, read from the question by the application.
    searched : bool
        Whether a retrieval tool call returned a result in this question, even one
        with no hits; ``not_found`` is refused until one has.
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
        return FinalReview(problem=problem)
    if proposal.reason == "not_found":
        if not searched:
            return FinalReview(
                problem="no search has returned in this question; search the filings before "
                "reporting not_found"
            )
        return FinalReview(
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
            return FinalReview(problem=f"chunk {unknown[0]} was not retrieved in this question")
        return FinalReview(
            AgentReportAnswer(
                label="UNVERIFIED",
                answer=CANNOT_RESOLVE[locale],
                citations=_citations(proposal.unresolved_chunk_ids, evidence),
                rationale=CANNOT_RESOLVE[locale],
            )
        )

    refs = [selection.cell_id for selection in proposal.selections]
    if len(set(refs)) != len(refs):
        return FinalReview(problem="each cell may be selected once")
    missing = next((ref for ref in refs if ref not in ledger), None)
    if missing is not None:
        return FinalReview(
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
            return FinalReview(problem=problem)
    first: dict[tuple[str, int], str] = {}
    for cell in cells:
        pair = (cell.cell["item"], cell.cell["fiscal_years"][0])
        if pair in first:
            return FinalReview(
                problem=f"cells {first[pair]} and {cell.ref} both answer {pair[0]} for fiscal "
                f"{pair[1]}; select one cell for each item and fiscal year"
            )
        first[pair] = cell.ref
    if not requested_items:
        return FinalReview(
            AgentReportAnswer(
                label="UNVERIFIED",
                answer=QUESTION_ITEM_UNREAD[locale],
                citations=_citations(chunk_ids, evidence),
                rationale=QUESTION_ITEM_UNREAD[locale],
            ),
            cell_checks=tuple(_check(cell, "question item unknown") for cell in cells),
        )
    off_item = next((cell for cell in cells if cell.cell["item"] not in requested_items), None)
    if off_item is not None:
        asked = ", ".join(sorted(requested_items))
        return FinalReview(
            problem=f"cell {off_item.ref} is {off_item.cell['item']}; the question asks for {asked}"
        )
    # Like an unasked item, a cell of an unasked year is returned once another selected
    # cell is of an asked year; when none is, the selection is a period mismatch below.
    years = {cell.cell["fiscal_years"][0] for cell in cells}
    requested = set(requested_years)
    if years & requested:
        off_year = next(
            (cell for cell in cells if cell.cell["fiscal_years"][0] not in requested), None
        )
        if off_year is not None:
            asked = ", ".join(str(year) for year in sorted(requested))
            return FinalReview(
                problem=f"cell {off_year.ref} is fiscal {off_year.cell['fiscal_years'][0]}; "
                f"the question asks for fiscal {asked}"
            )
    # A unit hold withholds the whole answer, but only once the held cell is what the
    # model claimed and of the asked item and, when any selected cell is of an asked
    # year, of an asked year. It outranks a period mismatch, so with no selected cell
    # of an asked year a held cell still withholds rather than names another period.
    held = [cell for cell in cells if cell.cell["status"] in WITHHOLDING_CAUSES]
    if held:
        withheld = FiguresWithheld(
            causes=ordered_causes(WITHHOLDING_CAUSES[cell.cell["status"]] for cell in held),
            figures=tuple(cell.cell["raw_text"] for cell in held),
        )
        return FinalReview(
            _report(withheld_report(withheld, locale=locale), _citations(chunk_ids, evidence)),
            withheld=withheld,
            cell_checks=tuple(_check(cell, "held") for cell in cells),
        )
    if requested and not years & requested:
        mismatch = PeriodMismatch(
            requested_fiscal_years=tuple(sorted(requested)),
            evidenced_fiscal_years=tuple(sorted(years)),
            figures=tuple(cell.cell["raw_text"] for cell in cells),
        )
        qualified = period_mismatch_report(mismatch, locale=locale, selection=True)
        return FinalReview(
            _report(qualified, _citations(chunk_ids, evidence)),
            period_mismatch=mismatch,
            cell_checks=tuple(_check(cell, "other period") for cell in cells),
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
        return FinalReview(problem=f"no selected cell answers {item}{period}")
    return FinalReview(
        AgentReportAnswer(
            label="SUPPORTED",
            answer=" ".join(_line(cell, locale) for cell in cells),
            citations=_citations(chunk_ids, evidence),
            rationale=ASSEMBLED[locale],
        ),
        cell_checks=tuple(_check(cell, "accepted") for cell in cells),
    )


async def review_cell_answer(
    arguments_json: str,
    *,
    ledger: Mapping[str, Mapping[str, Any]],
    evidence: Mapping[int, Mapping[str, Any]],
    cell_reader: CellReader | None,
    requested_items: frozenset[str],
    requested_years: Sequence[int],
    searched: bool,
    locale: Locale,
    passthrough: tuple[type[Exception], ...] = (),
) -> FinalReview:
    """Review one lone cell-selecting ``final_answer`` call.

    The proposal is validated strictly, the selected cells are read again as stored now
    and :func:`review_cell_selection` decides. A ref this question did not fetch is
    refused by that review, so it is never read: only fetched cells are read again.

    Parameters
    ----------
    arguments_json : str
        The raw JSON arguments of the ``final_answer`` call.
    ledger, evidence : Mapping[str, Mapping[str, Any]], Mapping[int, Mapping[str, Any]]
        Cells fetched and source identities retrieved in this question.
    cell_reader : CellReader | None
        Reads the selected cells as stored now; required.
    requested_items, requested_years : frozenset[str], Sequence[int]
        What the question asks for, read from the question by the application.
    searched : bool
        Whether a retrieval tool call returned a result in this question.
    locale : Locale
        Language the answer is written in.
    passthrough : tuple[type[Exception], ...]
        Exceptions that are the caller's control flow, raised unchanged.

    Raises
    ------
    EvidenceReadError
        If no reader is configured, the stored cells cannot be read or a selected cell
        changed since it was fetched (:class:`StaleCellError`), which the model cannot
        correct.
    """
    try:
        proposal = CellSelectionAnswer.model_validate_json(arguments_json, strict=True)
    except ValidationError as error:
        return FinalReview(problem=f"invalid final_answer: {'; '.join(validation_errors(error))}")
    refs = tuple(selection.cell_id for selection in proposal.selections)
    try:
        if cell_reader is None:
            raise RuntimeError("no stored cell reader is configured")
        fetched = bool(refs) and all(ref in ledger for ref in refs)
        stored = await cell_reader(refs) if fetched else {}
        return review_cell_selection(
            proposal,
            ledger=ledger,
            evidence=evidence,
            stored=stored,
            requested_items=requested_items,
            requested_years=requested_years,
            searched=searched,
            locale=locale,
        )
    except passthrough:
        raise
    except Exception as error:
        raise EvidenceReadError(safe_runtime_error(error, "stored cell read")) from error
