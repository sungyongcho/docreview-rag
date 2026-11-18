"""The reports the application writes itself when a check qualifies an answer.

Every path reports a qualified answer with the same sentences, built here from the
typed record of :mod:`app.contracts.figures`: :func:`withheld_report` for figures whose
unit, currency or direction is uncertain, :func:`period_mismatch_report` for figures of
another fiscal period and :func:`figures_unverified_report` for an answer reported as
absent because its figures were not confirmed. The sentences state only what the check
established, in the resolved application language, never a withheld figure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.contracts.figures import (
    FiguresWithheld,
    PeriodMismatch,
    WithholdingCause,
    ordered_causes,
)

type Locale = Literal["en", "ko"]


@dataclass(frozen=True, slots=True)
class QualifiedReport:
    """The label, answer and rationale of a report the application writes itself.

    The caller adds the citations: a withheld or period-mismatch report keeps the
    answer's citations, and an absent one cites nothing.
    """

    label: Literal["NOT_IN_DOCS", "PERIOD_MISMATCH", "UNVERIFIED"]
    answer: str
    rationale: str


def period_mismatch_text(
    requested: Sequence[int],
    evidenced: Sequence[int],
    figures: Sequence[str] = (),
    *,
    locale: Locale,
    selection: bool = False,
) -> str:
    """Describe only the mismatched written figures or selected cells, never filing absence."""
    asked = ", ".join(str(year) for year in requested)
    found = ", ".join(str(year) for year in evidenced)
    if selection:
        if locale == "ko":
            return f"선택된 표의 칸은 {asked} 회계연도가 아니라 {found} 회계연도의 값입니다."
        return f"The selected table cells are for fiscal {found}, not fiscal {asked}."
    amounts = ", ".join(figures)
    if locale == "ko":
        return (
            f"답변에 적힌 수치({amounts})는 요청한 {asked} 회계연도가 아니라 "
            f"{found} 회계연도의 값으로 확인됐습니다."
        )
    return (
        f"The stated figures {amounts} were found for fiscal {found}, "
        f"not the requested fiscal {asked}."
    )


def period_mismatch_rationale(*, locale: Locale, selection: bool = False) -> str:
    """Explain the mismatched subset without claiming that every answer figure is misdated."""
    if selection:
        return (
            "선택된 칸은 질문이 묻는 기간과 다른 기간의 값입니다."
            if locale == "ko"
            else "The selected cells belong to a different period than the question asks about."
        )
    return (
        "이 보고서에서 표시한 수치는 다른 회계기간의 값과 일치했습니다."
        if locale == "ko"
        else "The figures flagged in this report matched a different fiscal period."
    )


def withheld_text(causes: Sequence[WithholdingCause], *, locale: Locale) -> tuple[str, str]:
    """Build the withholding answer and rationale from only the established causes.

    Scale includes whether the figure is a percentage, matching ``scale_unknown``
    in the cell reader. No sentence asserts a particular missing declaration or
    attributes the uncertainty to a side that the comparison did not establish.
    """
    ordered = ordered_causes(causes)
    if not ordered:
        raise ValueError("a withholding report requires a cause")
    if locale == "ko":
        names = {"scale": "단위", "currency": "통화", "direction": "손익 방향"}
        detail = "·".join(names[cause] for cause in ordered)
        # The object particle follows the last listed noun.
        particle = "을" if ordered[-1] == "direction" else "를"
        return (
            f"인용 근거에 해당 항목은 있지만 수치의 {detail}{particle} 확인할 수 없어 "
            "수치를 보고하지 않습니다.",
            f"검사에서 인용 근거로 수치를 보고하는 데 필요한 {detail}{particle} "
            "확정하지 못했습니다.",
        )
    names = {
        "scale": "unit",
        "currency": "currency",
        "direction": "gain/loss direction",
    }
    labels = [names[cause] for cause in ordered]
    detail = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
    return (
        f"The cited evidence names this item, but the {detail} of its figures could not be "
        "confirmed, so no figure is reported.",
        f"The check did not establish the {detail} needed to report a figure "
        "from the cited evidence.",
    )


def withheld_report(held: FiguresWithheld, *, locale: Locale) -> QualifiedReport:
    """Report ``UNVERIFIED`` for withheld figures, stating no number.

    The withheld figures travel only in the typed record, so nothing unconfirmed is
    presented as fact.
    """
    answer, rationale = withheld_text(held.causes, locale=locale)
    return QualifiedReport("UNVERIFIED", answer, rationale)


def period_mismatch_report(
    mismatch: PeriodMismatch, *, locale: Locale, selection: bool = False
) -> QualifiedReport:
    """Report the period the mismatched figures, or selected cells, belong to instead.

    ``selection`` words the report for selected table cells, whose figures the model
    never wrote, instead of for figures stated in a written answer.
    """
    answer = period_mismatch_text(
        mismatch.requested_fiscal_years,
        mismatch.evidenced_fiscal_years,
        () if selection else mismatch.figures,
        locale=locale,
        selection=selection,
    )
    return QualifiedReport(
        "PERIOD_MISMATCH", answer, period_mismatch_rationale(locale=locale, selection=selection)
    )


def figures_unverified_report(*, locale: Locale) -> QualifiedReport:
    """Report a written answer as absent because its figures were not confirmed.

    Only a path whose policy reports unconfirmed figures as ``NOT_IN_DOCS`` writes this
    report (``unverified_figures`` in :mod:`app.review.policy`).
    """
    rationale = (
        "답변의 수치를 인용 근거에서 요청한 기간의 값으로 확인하지 못했습니다."
        if locale == "ko"
        else "The answer stated figures its cited evidence could not confirm for the "
        "requested period."
    )
    return QualifiedReport("NOT_IN_DOCS", "NOT_IN_DOCS", rationale)
