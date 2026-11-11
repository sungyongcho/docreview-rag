"""The written final-answer policy shared by ``run_agent`` and :class:`ReviewGate`.

A written ``final_answer`` stands alone in its turn, cites only identities the run
observed, and, when ``SUPPORTED``, has its figures checked against the cited evidence:
it is accepted, reported as a period mismatch, withheld as ``UNVERIFIED`` or returned
to the model with the problem it can act on.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import functools
from typing import Any, Literal

from pydantic import ValidationError

from app.agent.tools.registry import FINAL_ANSWER_NAME, parse_arguments
from app.agent.types import (
    AgentAnswer,
    AgentPeriodMismatch,
    AgentReportAnswer,
    AgentUnitUnverified,
    ToolCall,
)
from app.contracts.evidence import EvidenceCitation
from app.contracts.report_text import period_mismatch_rationale, period_mismatch_text
from app.figures.answers import (
    UNIT_UNVERIFIED_ANSWER,
    UNIT_UNVERIFIED_ANSWER_KO,
    UNIT_UNVERIFIED_RATIONALE,
    UNIT_UNVERIFIED_RATIONALE_KO,
    EvidenceText,
    FiguresResult,
    check_figures,
)
from app.llm.decoding import strict_response_format, validation_errors

type EvidenceReader = Callable[[tuple[int, ...]], Awaitable[Mapping[int, EvidenceText]]]

# The rejection run_agent sends for a turn that pairs final_answer with other calls.
FINAL_NOT_ALONE = "final_answer must be the only tool call in its provider turn"


@functools.cache
def final_answer_spec() -> dict[str, Any]:
    """Return the strict function spec for the loop-owned final_answer tool.

    The spec is a pure function of :class:`AgentAnswer`, so it is generated once
    per process instead of once per run.
    """
    payload = strict_response_format(AgentAnswer)
    return {
        "type": "function",
        "name": FINAL_ANSWER_NAME,
        "description": "Finish the run with a structured, citation-checked answer.",
        "parameters": payload["schema"],
        "strict": True,
    }


def validate_final_answer(
    call: ToolCall,
    evidence: Mapping[int, EvidenceCitation],
) -> tuple[AgentAnswer | None, str]:
    """Validate one final answer against every immutable identity the run observed.

    Parameters
    ----------
    call : ToolCall
        The loop-owned ``final_answer`` call.
    evidence : Mapping[int, EvidenceCitation]
        Complete source identities returned by successful tool observations.

    Returns
    -------
    tuple[AgentAnswer | None, str]
        Accepted answer and an empty problem, or no answer and a rejection whose
        field-level detail the model can act on. The detail is rendered from the
        model's own arguments, so passing it back leaks nothing.
    """
    try:
        answer = AgentAnswer.model_validate(parse_arguments(call.arguments_json), strict=False)
    except ValidationError as error:
        details = "; ".join(validation_errors(error))
        return None, f"invalid final_answer: {details}"
    except ValueError as error:
        return None, f"invalid final_answer: {error}"
    missing = tuple(
        citation.chunk_id for citation in answer.citations if citation.chunk_id not in evidence
    )
    if missing:
        cited = ", ".join(str(chunk_id) for chunk_id in missing)
        return None, (
            f"final_answer cites chunk ids no tool returned in this run: {cited}. "
            "Cite only retrieved evidence or answer NOT_IN_DOCS."
        )
    mismatched = tuple(
        citation.chunk_id
        for citation in answer.citations
        if evidence[citation.chunk_id] != citation
    )
    if mismatched:
        cited = ", ".join(str(chunk_id) for chunk_id in mismatched)
        return None, f"final_answer citation identity does not match retrieved evidence: {cited}."
    return answer, ""


def figures_problem(figures: FiguresResult, requested: Sequence[int]) -> str:
    """Tell the model which figures its cited evidence could not confirm, and for which item."""
    unverified = ", ".join(
        f"{c.figure} ({c.item or 'no recognized item'})"
        for c in figures.checks
        if c.verdict == "unverified"
    )
    period = ", ".join(str(year) for year in requested) or "any period"
    return (
        f"final_answer states figures its cited evidence does not confirm for {period}: "
        f"{unverified}. Name each figure's financial item in its own clause (for example "
        "revenue or net income) and state the value of that item's row in a cited table "
        "cell of the requested period, with its unit and the currency the evidence states. "
        "A scale may be converted (25,785 million as 25.8 billion) and rounded to its last "
        "digit when at least three significant digits remain; a currency is never "
        "converted, and computed values are not confirmed. Otherwise answer NOT_IN_DOCS."
    )


def period_mismatch_report(
    answer: AgentAnswer,
    figures: FiguresResult,
    requested: Sequence[int],
    *,
    locale: Literal["en", "ko"] = "en",
) -> tuple[AgentReportAnswer, AgentPeriodMismatch]:
    """Report the cited figures' own period instead of the answer that misdated them."""
    mismatched = [c for c in figures.checks if c.verdict == "period_mismatch"]
    mismatch = AgentPeriodMismatch(
        requested_fiscal_years=tuple(requested),
        evidenced_fiscal_years=tuple(
            sorted({year for check in mismatched for year in check.evidenced_years})
        ),
        figures=tuple(check.figure for check in mismatched),
    )
    report = AgentReportAnswer(
        label="PERIOD_MISMATCH",
        answer=period_mismatch_text(
            mismatch.requested_fiscal_years,
            mismatch.evidenced_fiscal_years,
            mismatch.figures,
            locale=locale,
        ),
        citations=answer.citations,
        rationale=period_mismatch_rationale(locale=locale),
    )
    return report, mismatch


def unit_unverified_report(
    answer: AgentAnswer, figures: FiguresResult, *, locale: Literal["en", "ko"] = "en"
) -> tuple[AgentReportAnswer, AgentUnitUnverified]:
    """Withhold figures whose evidence unit or direction is uncertain, keeping the citations.

    The report states no number: the withheld figures travel only in the typed
    ``AgentUnitUnverified`` record, so nothing unconfirmed is presented as fact.
    """
    held = AgentUnitUnverified(
        figures=tuple(c.figure for c in figures.checks if c.verdict == "unit_unverified")
    )
    report = AgentReportAnswer(
        label="UNVERIFIED",
        answer=UNIT_UNVERIFIED_ANSWER_KO if locale == "ko" else UNIT_UNVERIFIED_ANSWER,
        citations=answer.citations,
        rationale=UNIT_UNVERIFIED_RATIONALE_KO if locale == "ko" else UNIT_UNVERIFIED_RATIONALE,
    )
    return report, held


def as_report(answer: AgentAnswer) -> AgentReportAnswer:
    """Widen an accepted model answer to the report type, as ``run_agent`` does."""
    return AgentReportAnswer.model_validate(answer.model_dump())


@dataclass(frozen=True, slots=True)
class WrittenAnswerJudgement:
    """What the figure check makes of one ``SUPPORTED`` written answer.

    ``report`` is the answer to end the run on, or None when the answer goes back to
    the model with ``problem``. ``period_mismatch`` and ``unit_unverified`` are the
    typed records of a report the check qualifies; a plain accepted answer has neither.
    """

    report: AgentReportAnswer | None
    problem: str = ""
    period_mismatch: AgentPeriodMismatch | None = None
    unit_unverified: AgentUnitUnverified | None = None


def judge_written_answer(
    answer: AgentAnswer,
    texts: Mapping[int, EvidenceText],
    requested_fiscal_years: Sequence[int],
    *,
    locale: Literal["en", "ko"] = "en",
) -> WrittenAnswerJudgement:
    """Check a ``SUPPORTED`` answer's figures against its cited evidence and judge it.

    Parameters
    ----------
    answer : AgentAnswer
        An identity-checked ``SUPPORTED`` answer.
    texts : Mapping[int, EvidenceText]
        The cited evidence the caller read; a cited chunk missing from it gives the
        check nothing to confirm.
    requested_fiscal_years : Sequence[int]
        Fiscal years the question asks about.

    locale : Literal["en", "ko"]
        Resolved application language; no language is inferred from the answer.

    Returns
    -------
    WrittenAnswerJudgement
        An unconfirmed figure returns the answer to the model; an uncertain unit
        withholds it; another period reports that period; otherwise it is accepted.
    """
    cited = tuple(citation.chunk_id for citation in answer.citations)
    figures = check_figures(
        answer.answer,
        [texts[chunk_id] for chunk_id in cited if chunk_id in texts],
        requested_fiscal_years,
    )
    if figures.verdict == "unverified":
        return WrittenAnswerJudgement(None, figures_problem(figures, requested_fiscal_years))
    if figures.verdict == "unit_unverified":
        report, held = unit_unverified_report(answer, figures, locale=locale)
        return WrittenAnswerJudgement(report, unit_unverified=held)
    if figures.verdict == "period_mismatch":
        report, mismatch = period_mismatch_report(
            answer, figures, requested_fiscal_years, locale=locale
        )
        return WrittenAnswerJudgement(report, period_mismatch=mismatch)
    return WrittenAnswerJudgement(as_report(answer))
