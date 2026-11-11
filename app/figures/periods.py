"""Classify fiscal periods before any reader blanks identifiers or calendar dates.

Identifier grammars stay with their readers. This module owns the shared distinction
between a fiscal year, a shorter period, a calendar date and no stated period.
"""

import re
from typing import Literal

MONTH_NAMES = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
PERIOD_WORDS = re.compile(
    r"\b(?:months?|weeks?|quarter(?:s|ly)?|q\s*[1-4](?:\d{2})?|[1-4]q(?:\d{2})?|h\s*[12](?:\d{2})?|[12]h(?:\d{2})?|half(?:[\s-]year)?"
    r"|ytd|year[\s-]to[\s-]date|to[\s-]date|interim|periods?|semi[\s-]?annual)\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b"
    r"|분\s*기|반\s*기|개월|누적|누계|기\s*초|기간|(?<!\d)\d{1,2}\s*월",
    re.IGNORECASE,
)

type PeriodKind = Literal["annual", "subannual", "date", "none"]

_YEAR = re.compile(
    r"(?<!\d)(?:19|20)\d{2}(?!\d)|\bfy\s*\d{2,4}\b|회계연도|사업연도|당기|전기|제\s*\d+\s*기|\b(?:annual|fiscal|year)\b",
    re.I,
)
_DATE = re.compile(
    MONTH_NAMES + r"\b|(?<!\d)(?:19|20)\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}"
    r"|(?<!\d)\d{1,2}/\d{1,2}/(?:19|20)\d{2}|(?<!\d)\d{1,2}\s*월",
    re.I,
)
ANNUAL_END = re.compile(
    r"(?<![\w-])(?:fiscal\s+)?year\s+end(?:ed|ing)\s+(?:on\s+)?(?:"
    + MONTH_NAMES
    + r"\.?\s+\d{1,2},?\s+((?:19|20)\d{2})(?!\w)"
    r"|((?:19|20)\d{2})[./-]\d{1,2}[./-]\d{1,2}(?!\w))",
    re.I,
)
_FULL_DURATION = re.compile(
    r"\b(?:twelve|12)[\s-]+months?\b|\b(?:52|53|fifty[\s-]two|fifty[\s-]three)[\s-]+weeks?\b", re.I
)


def classify_period(text: str) -> PeriodKind:
    """Read the period before identifiers disappear; a nonannual qualifier wins.

    Only an explicit fiscal-year-end form can consume a prose date. Header readers
    separately retain their existing grammar for bare column-end date identifiers.
    """
    text = normalize_fiscal_years(text)
    annual = ANNUAL_END.search(text) is not None or _FULL_DURATION.search(text) is not None
    rest = ANNUAL_END.sub(" ", text)
    if _FULL_DURATION.search(rest):
        # A full duration's end date is a fiscal-year-end form, too.
        rest = re.sub(
            r"\b(?:ended|ending)\s+" + MONTH_NAMES + r"\.?\s+\d{1,2},?\s+(?:19|20)\d{2}",
            " ",
            rest,
            flags=re.I,
        )
        rest = _FULL_DURATION.sub(" ", rest)
    if _DATE.search(rest):
        return "date"
    if PERIOD_WORDS.search(rest):
        return "subannual"
    return "annual" if annual or _YEAR.search(rest) else "none"


_FISCAL_YEAR = re.compile(
    r"(?<![\w-])(?:fy\s*['’]?\s*|fiscal\s+(?:year\s+)?)"
    r"(?P<year>(?:19|20)\d{2}|\d{2})(?!\w|[,.]\d)",
    re.I,
)


def fiscal_year_spans(text: str) -> list[tuple[int, int, int]]:
    """Read explicit FY/fiscal identifiers; two-digit years always mean 2000–2099.

    The century is fixed, never inferred from the clock or a nearby cell. Callers
    retain their own identifier-versus-amount grammar before consuming these spans.
    """
    return [
        (m.start(), m.end(), int(m["year"]) + (2000 if len(m["year"]) == 2 else 0))
        for m in _FISCAL_YEAR.finditer(text)
    ]


def normalize_fiscal_years(text: str) -> str:
    """Expand only explicit fiscal-year identifiers, preserving ordinary short numbers."""
    for start, end, year in reversed(fiscal_year_spans(text)):
        text = text[:start] + f"FY{year}" + text[end:]
    return text
