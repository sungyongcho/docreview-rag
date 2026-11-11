"""Fiscal years a question asks about, including relative wording."""

from datetime import UTC, date, datetime
import re

from app.figures.periods import annual_fiscal_year_spans, fiscal_year_spans

YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

_YEAR_WORD = re.compile(rf"{YEAR_RE.pattern}년?")

# Relative wording resolves against the calendar date the question is asked on.
RELATIVE_YEARS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (-2, re.compile(r"재작년|전전년|two years ago|the year before last", re.IGNORECASE)),
    (
        -1,
        re.compile(
            r"작년|지난\s?해|전년|(?:last|previous|prior)\s+(?:fiscal\s+)?year", re.IGNORECASE
        ),
    ),
    (
        0,
        re.compile(
            r"올해|금년|this\s+(?:fiscal\s+)?year|current\s+(?:fiscal\s+)?year", re.IGNORECASE
        ),
    ),
)


def utc_today() -> date:
    """Return today's UTC calendar date."""
    return datetime.now(UTC).date()


def question_fiscal_years(query: str, today: date) -> tuple[int, ...]:
    """Return the sorted fiscal years a question names or describes relative to ``today``.

    Explicit fiscal-year identifiers are read by the shared period forms, so "FY24"
    is 2024 here as it is in a header and an answer. An annual ending that carries
    such an identifier is dated by it: the calendar year of its end date
    ("FY2024 ended January 26, 2025") is not a second requested year. "재작년" is
    matched before "작년" and its span removed, so one phrase never yields two years.
    """
    owned = [(start, end) for start, end, _ in annual_fiscal_year_spans(query)]
    years = {year for _, _, year in fiscal_year_spans(query)}
    years.update(
        int(match.group(0))
        for match in YEAR_RE.finditer(query)
        if not any(start <= match.start() < end for start, end in owned)
    )
    remaining = query
    for offset, pattern in RELATIVE_YEARS:
        if pattern.search(remaining):
            years.add(today.year + offset)
            remaining = pattern.sub(" ", remaining)
    return tuple(sorted(years))


def names_fiscal_year(text: str) -> bool:
    """Whether the text names a fiscal year in any form ``question_fiscal_years`` reads."""
    return without_fiscal_years(text) != text


def without_fiscal_years(text: str) -> str:
    """Remove every fiscal-year expression ``question_fiscal_years`` reads.

    A follow-up that names its own year supersedes the years of the turn it continues,
    whichever form either turn used.
    """
    for spans in (annual_fiscal_year_spans, fiscal_year_spans):
        for start, end, _ in reversed(spans(text)):
            text = text[:start] + text[end:]
    text = _YEAR_WORD.sub("", text)
    for _, pattern in RELATIVE_YEARS:
        text = pattern.sub("", text)
    return text
