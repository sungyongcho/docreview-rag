"""Fiscal years a question asks about, including relative wording."""

from datetime import UTC, date, datetime
import re

YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

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

    "재작년" is matched before "작년" and its span removed, so one phrase never yields
    two years.
    """
    years = {int(year) for year in YEAR_RE.findall(query)}
    remaining = query
    for offset, pattern in RELATIVE_YEARS:
        if pattern.search(remaining):
            years.add(today.year + offset)
            remaining = pattern.sub(" ", remaining)
    return tuple(sorted(years))
