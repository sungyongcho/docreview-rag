"""Review a written answer: its citations, then its figures against the cited evidence.

:func:`judge_figures` is the one place that turns the figure check into a judgement,
for every path: a figure the cited evidence does not confirm makes the answer absent
or returns it to the model (``unverified_figures`` in :mod:`app.review.policy`), an
uncertain unit, currency or direction withholds it, a figure of another period reports
that period, and otherwise the answer stands.

The agent paths propose a written ``final_answer`` and review it with
:func:`review_written_answer`: it must cite only identities a tool returned in this
question (:func:`validate_final_answer`), and a ``SUPPORTED`` answer then has its cited
evidence read as stored now and its figures judged (:func:`judge_written_answer`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from app.contracts.answers import AgentAnswer, AgentReportAnswer
from app.contracts.evidence import EvidenceCitation
from app.contracts.figures import FiguresUnverified, FiguresWithheld, PeriodMismatch
from app.figures.answers import EvidenceText, FiguresResult, check_figures
from app.llm.decoding import validation_errors
from app.review.evidence import EvidenceReader
from app.review.final_answer import EvidenceReadError, FinalReview, as_report
from app.review.policy import AnswerPolicy
from app.review.reports import (
    QualifiedReport,
    figures_unverified_report,
    period_mismatch_report,
    withheld_report,
)
from app.tools.registry import parse_arguments, safe_runtime_error

type Locale = Literal["en", "ko"]


@dataclass(frozen=True, slots=True)
class FigureJudgement:
    """What the figure check makes of one ``SUPPORTED`` written answer.

    ``verdict`` is ``accepted``, ``withheld``, ``period_mismatch``, ``not_in_docs`` or
    ``returned``. Each qualified verdict carries its typed record; ``returned`` also
    carries ``problem``, the text that tells the model what to correct.
    """

    verdict: Literal["accepted", "withheld", "period_mismatch", "not_in_docs", "returned"]
    period_mismatch: PeriodMismatch | None = None
    withheld: FiguresWithheld | None = None
    unverified: FiguresUnverified | None = None
    problem: str | None = None


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


def judge_figures(
    answer: str,
    evidence: Sequence[EvidenceText],
    requested_fiscal_years: Sequence[int],
    *,
    policy: AnswerPolicy,
) -> FigureJudgement:
    """Check the figures of a ``SUPPORTED`` answer against its cited evidence and judge them.

    Parameters
    ----------
    answer : str
        The answer text whose figures are checked.
    evidence : Sequence[EvidenceText]
        The cited evidence as the path read it.
    requested_fiscal_years : Sequence[int]
        Fiscal years the question asks about.
    policy : AnswerPolicy
        The path's policy; ``unverified_figures`` decides an unconfirmed figure.

    Returns
    -------
    FigureJudgement
        The judgement with its typed record. An uncertain unit outranks an unconfirmed
        figure, which outranks another period (see ``FiguresResult.verdict``).
    """
    figures = check_figures(answer, evidence, requested_fiscal_years)
    if figures.verdict == "withheld":
        return FigureJudgement(
            "withheld",
            withheld=FiguresWithheld(
                causes=figures.causes,
                figures=tuple(c.figure for c in figures.checks if c.verdict == "withheld"),
            ),
        )
    if figures.verdict == "unverified":
        unverified = FiguresUnverified(
            figures=tuple(c.figure for c in figures.checks if c.verdict == "unverified")
        )
        if policy.unverified_figures == "return_to_model":
            return FigureJudgement(
                "returned",
                unverified=unverified,
                problem=figures_problem(figures, requested_fiscal_years),
            )
        return FigureJudgement("not_in_docs", unverified=unverified)
    if figures.verdict == "period_mismatch":
        mismatched = [c for c in figures.checks if c.verdict == "period_mismatch"]
        return FigureJudgement(
            "period_mismatch",
            period_mismatch=PeriodMismatch(
                requested_fiscal_years=tuple(requested_fiscal_years),
                evidenced_fiscal_years=tuple(
                    sorted({year for check in mismatched for year in check.evidenced_years})
                ),
                figures=tuple(check.figure for check in mismatched),
            ),
        )
    return FigureJudgement("accepted")


def validate_final_answer(
    arguments_json: str,
    evidence: Mapping[int, EvidenceCitation],
) -> tuple[AgentAnswer | None, str]:
    """Validate one final answer against every immutable identity the question observed.

    Parameters
    ----------
    arguments_json : str
        The raw JSON arguments of the ``final_answer`` call.
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
        answer = AgentAnswer.model_validate(parse_arguments(arguments_json), strict=False)
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


def _report(
    qualified: QualifiedReport, citations: tuple[EvidenceCitation, ...]
) -> AgentReportAnswer:
    """Give a report the application wrote the citations it keeps."""
    return AgentReportAnswer(
        label=qualified.label,
        answer=qualified.answer,
        citations=citations,
        rationale=qualified.rationale,
    )


def judge_written_answer(
    answer: AgentAnswer,
    texts: Mapping[int, EvidenceText],
    requested_fiscal_years: Sequence[int],
    *,
    locale: Locale,
    policy: AnswerPolicy,
) -> FinalReview:
    """Judge an identity-checked ``SUPPORTED`` answer's figures and write its report.

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
    policy : AnswerPolicy
        The path's policy, read by :func:`judge_figures`.

    Returns
    -------
    FinalReview
        The accepted answer, a qualified report with its record, or the problem the
        model must correct.
    """
    cited = tuple(citation.chunk_id for citation in answer.citations)
    judged = judge_figures(
        answer.answer,
        [texts[chunk_id] for chunk_id in cited if chunk_id in texts],
        requested_fiscal_years,
        policy=policy,
    )
    match judged.verdict:
        case "returned":
            return FinalReview(problem=judged.problem)
        case "not_in_docs":
            return FinalReview(_report(figures_unverified_report(locale=locale), ()))
        case "withheld":
            assert judged.withheld is not None
            report = _report(withheld_report(judged.withheld, locale=locale), answer.citations)
            return FinalReview(report, withheld=judged.withheld)
        case "period_mismatch":
            assert judged.period_mismatch is not None
            qualified = period_mismatch_report(judged.period_mismatch, locale=locale)
            return FinalReview(
                _report(qualified, answer.citations), period_mismatch=judged.period_mismatch
            )
        case "accepted":
            return FinalReview(as_report(answer))


async def review_written_answer(
    arguments_json: str,
    evidence: Mapping[int, EvidenceCitation],
    *,
    evidence_reader: EvidenceReader | None,
    requested_fiscal_years: Sequence[int],
    locale: Locale,
    policy: AnswerPolicy,
    passthrough: tuple[type[Exception], ...] = (),
) -> FinalReview:
    """Review one lone written ``final_answer`` call, the same way on both agent paths.

    Identity comes first, against the question's evidence ledger; only a ``SUPPORTED``
    answer with matching citations has its cited evidence read and its figures judged.
    A valid ``NOT_IN_DOCS`` is accepted as it is.

    Parameters
    ----------
    arguments_json : str
        The raw JSON arguments of the ``final_answer`` call.
    evidence : Mapping[int, EvidenceCitation]
        Identities returned by tools in this question, by chunk id.
    evidence_reader : EvidenceReader | None
        Reads the cited chunks as stored now. Without it no figure can be confirmed, so
        an answer that states figures is judged unconfirmed.
    requested_fiscal_years : Sequence[int]
        Fiscal years the question asks about.
    locale : Literal["en", "ko"]
        Resolved application language for the reports the review writes.
    policy : AnswerPolicy
        The calling path's policy.
    passthrough : tuple[type[Exception], ...]
        Exceptions from the reader that are the caller's control flow, raised unchanged.

    Raises
    ------
    EvidenceReadError
        If the cited evidence cannot be read, so the answer is never judged without it.
    """
    answer, problem = validate_final_answer(arguments_json, evidence)
    if answer is None:
        return FinalReview(problem=problem)
    if answer.label != "SUPPORTED":
        return FinalReview(as_report(answer))
    cited = tuple(citation.chunk_id for citation in answer.citations)
    try:
        texts = await evidence_reader(cited) if evidence_reader is not None else {}
    except passthrough:
        raise
    except Exception as error:
        raise EvidenceReadError(safe_runtime_error(error, "cited evidence read")) from error
    return judge_written_answer(answer, texts, requested_fiscal_years, locale=locale, policy=policy)
