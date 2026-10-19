"""Check that every figure an answer states comes from the right period of its evidence.

Citation checks prove which chunks an answer cites, not that its numbers come from
them. This module finds each figure of an answer in the cited evidence. A figure found
in a table data cell takes that cell's column period from the column headers (or the
table's only captioned year). It passes when that period is one the question asks
for, and is a period mismatch when it belongs only to other periods. With no requested
period, being in the evidence is enough. A figure found only in running text, or not
at all, cannot be verified.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

# A figure: digits with optional thousands separators and decimals, optionally signed.
_NUMBER = re.compile(r"[(△▲-]?\d[\d,]*(?:\.\d+)?\)?")
# Identifiers and calendar dates carry digits but state no figure.
_NOT_FIGURES = re.compile(
    r"\b(?:FY|Q|H)\s?\d+|\b\d+[QH]\b|\d+-[A-Z]\b|"
    r"\b(?:Item|Note|Part|Exhibit|Section)s?\s+\d+[A-Z]?(?:\.\d+)*|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|"
    r"\d{4}\s?[./-]\s?\d{1,2}\s?[./-]\s?\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|"
    r"\d{4}\s?년(?:\s?\d{1,2}\s?월)?(?:\s?\d{1,2}\s?일)?|\d{1,2}\s?월\s?\d{1,2}\s?일|"
    r"\d\s?분기|제\s?\d+\s?기",
    re.IGNORECASE,
)
_BARE_YEAR = re.compile(r"(?:19|20)\d{2}")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

type Verdict = Literal["verified", "period_mismatch", "unverified"]


@dataclass(frozen=True, slots=True)
class EvidenceText:
    """One cited chunk as the checker reads it.

    ``table_fragment`` is the stored fragment of a table chunk: its data cells,
    header cells and captions with their source grid coordinates.
    """

    chunk_id: int
    body: str
    context_header: str
    table_fragment: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class FigureCheck:
    """The outcome for one figure stated in the answer."""

    figure: str
    verdict: Verdict
    evidenced_years: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class FiguresResult:
    """The outcome for a whole answer."""

    checks: tuple[FigureCheck, ...]

    @property
    def verdict(self) -> Verdict:
        """Fail on any unverified figure, then on any period mismatch."""
        verdicts = {check.verdict for check in self.checks}
        if "unverified" in verdicts:
            return "unverified"
        return "period_mismatch" if "period_mismatch" in verdicts else "verified"


def _value(text: str) -> Decimal | None:
    """Return the magnitude a figure denotes, ignoring sign, currency and separators.

    Filings write losses as ``(1,234)`` or ``△1,234`` while answers write "a loss of
    1,234", so the comparison is between magnitudes.
    """
    digits = re.sub(r"[^\d.]", "", text)
    try:
        return abs(Decimal(digits)) if digits else None
    except InvalidOperation:
        return None


def figures(text: str) -> tuple[str, ...]:
    """Return the figures a text states, without identifiers, dates or bare years."""
    cleaned = _NOT_FIGURES.sub(" ", text)
    found = []
    for match in _NUMBER.finditer(cleaned):
        token = match.group(0)
        start, end = match.span()
        if (start and cleaned[start - 1].isascii() and cleaned[start - 1].isalpha()) or (
            end < len(cleaned) and cleaned[end].isascii() and cleaned[end].isalpha()
        ):
            continue
        if _BARE_YEAR.fullmatch(token.strip("()△▲-")):
            continue
        found.append(token)
    return tuple(found)


def _values(text: str) -> set[Decimal]:
    """Return the magnitudes of every figure a text states."""
    return {value for figure in figures(text) if (value := _value(figure)) is not None}


def _entries(container: Mapping[str, object] | object, key: str) -> list[Mapping[str, object]]:
    """Return the JSON objects stored in one list field of a stored fragment."""
    value = container.get(key, ()) if isinstance(container, Mapping) else ()
    if not isinstance(value, list | tuple):
        return []
    return [entry for entry in value if isinstance(entry, Mapping)]


def _int(value: object) -> int:
    """Read one stored integer coordinate."""
    if not isinstance(value, int):
        raise ValueError("table fragment coordinates must be integers")
    return value


def _column_years(
    source: Mapping[str, object],
    headers: Sequence[Mapping[str, object]],
    caption_years: set[int],
) -> set[int]:
    """Return the years the headers above one data cell's columns name."""
    start = _int(source["column"])
    end = start + _int(source.get("colspan", 1))
    years: set[int] = set()
    for header in headers:
        first = _int(header["column"])
        if first < end and start < first + _int(header.get("colspan", 1)):
            years.update(int(year) for year in _YEAR.findall(str(header.get("text", ""))))
    if not years and len(caption_years) == 1:
        return set(caption_years)
    return years


def _table_cells(fragment: Mapping[str, object]) -> list[tuple[set[Decimal], set[int]]]:
    """Return each data cell's figures and column years in one stored fragment."""
    headers = _entries(fragment, "header_cells")
    caption_years = {
        int(year)
        for caption in _entries(fragment, "caption_sources")
        for year in _YEAR.findall(str(caption.get("text", "")))
    }
    cells = []
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            values = _values(str(source.get("text", "")))
            if values:
                cells.append((values, _column_years(source, headers, caption_years)))
    return cells


def check_figures(
    answer: str, evidence: Sequence[EvidenceText], requested_years: Sequence[int]
) -> FiguresResult:
    """Check every figure of ``answer`` against the cited evidence and requested periods."""
    requested = set(requested_years)
    cells = [
        cell
        for item in evidence
        if item.table_fragment is not None
        for cell in _table_cells(item.table_fragment)
    ]
    data_values = {value for values, _ in cells for value in values}
    labels = {
        value
        for item in evidence
        for value in _values(item.context_header)
        | (_values(item.body) - data_values if item.table_fragment is not None else set())
    }
    prose = {
        value for item in evidence if item.table_fragment is None for value in _values(item.body)
    }
    checks = []
    for figure in dict.fromkeys(figures(answer)):
        value = _value(figure)
        matched = [years for values, years in cells if value in values]
        if matched:
            evidenced = set().union(*matched)
            if not requested or any(years & requested for years in matched):
                checks.append(FigureCheck(figure, "verified", tuple(sorted(evidenced))))
            elif all(matched):
                checks.append(FigureCheck(figure, "period_mismatch", tuple(sorted(evidenced))))
            else:
                checks.append(FigureCheck(figure, "unverified", tuple(sorted(evidenced))))
        elif value in labels:
            checks.append(FigureCheck(figure, "verified"))
        elif value in prose and not requested:
            checks.append(FigureCheck(figure, "verified"))
        else:
            checks.append(FigureCheck(figure, "unverified"))
    return FiguresResult(tuple(checks))
