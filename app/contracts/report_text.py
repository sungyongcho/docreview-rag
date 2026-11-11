"""Localized application reports limited to the evidence each check established."""

from collections.abc import Sequence
from typing import Literal


def period_mismatch_text(
    requested: Sequence[int],
    evidenced: Sequence[int],
    figures: Sequence[str] = (),
    *,
    locale: Literal["en", "ko"] = "en",
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
            f"답변에 적힌 {amounts}은(는) 요청한 {asked} 회계연도가 아니라 "
            f"{found} 회계연도의 값으로 확인됐습니다."
        )
    return (
        f"The stated figures {amounts} were found for fiscal {found}, "
        f"not the requested fiscal {asked}."
    )


def period_mismatch_rationale(
    *, locale: Literal["en", "ko"] = "en", selection: bool = False
) -> str:
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
