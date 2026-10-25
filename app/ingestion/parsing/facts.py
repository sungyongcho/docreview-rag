"""Read the machine-readable facts a filing declares for its own figures.

An inline XBRL filing (SEC) tags each reported number with its concept, period
context, unit and scale; a DART report tags the cells of its financial statements
with a concept (``ACODE``) and a context (``ACONTEXT``) that names the fiscal year
and the consolidated or separate statement. The HTML normalizer unwraps these tags,
so they are read here from the raw source, each fact keeping the source span of
its tag so a table cell can find the facts inside its own span.

Nothing is inferred beyond what the filing states. A fiscal year is given only to
an annual period or a fiscal-year-end instant, anchored to the document's own
fiscal year; any other period, an unreadable context or a DART context whose year
contradicts its relative position keeps no fiscal year.
"""

from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import html
import json
import re
from typing import Literal

from app.ingestion.sources.models import DocumentReference

type FactSource = Literal["ixbrl", "dart"]
type Dimension = tuple[str, str]

# A fiscal year of 52 or 53 weeks, or a calendar year, measured in days.
_ANNUAL_DAYS = range(350, 381)
# Years between two fiscal year ends average about 364.4 days for 52/53-week years
# and 365.25 for calendar years; a year end within this many days of a whole number of
# such years from the document's own year end is that many fiscal years earlier.
_YEAR_DAYS = 364.8
_YEAR_END_TOLERANCE = 10

_NS = r"(?:[\w.-]+:)?"
_ATTRIBUTE = re.compile(r'([\w:.-]+)\s*=\s*"([^"]*)"')
_TAGS = re.compile(r"<[^>]+>")
_CONTEXT = re.compile(rf"<{_NS}context\b([^>]*)>(.*?)</{_NS}context>", re.S | re.I)
_DATE = re.compile(rf"<{_NS}(startDate|endDate|instant)>\s*([^<\s]+)\s*<", re.I)
_EXPLICIT = re.compile(
    rf'<{_NS}explicitMember\b[^>]*\bdimension="([^"]+)"[^>]*>\s*([^<]+?)\s*<', re.I
)
_TYPED = re.compile(
    rf'<{_NS}typedMember\b[^>]*\bdimension="([^"]+)"[^>]*>(.*?)</{_NS}typedMember>', re.S | re.I
)
_UNIT = re.compile(rf"<{_NS}unit\b([^>]*)>(.*?)</{_NS}unit>", re.S | re.I)
_NUMERATOR = re.compile(rf"<{_NS}unitNumerator>(.*?)</{_NS}unitNumerator>", re.S | re.I)
_DENOMINATOR = re.compile(rf"<{_NS}unitDenominator>(.*?)</{_NS}unitDenominator>", re.S | re.I)
_MEASURE = re.compile(rf"<{_NS}measure>\s*([^<\s]+)\s*<", re.I)
_NON_FRACTION = re.compile(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", re.S | re.I)
_DART_CELL = re.compile(r"<(T[EDHU])\b([^>]*\bACONTEXT=\"[^\"]*\"[^>]*)>(.*?)</\1>", re.S)
# "CFY2024dFY": current fiscal year 2024, a duration; "PFY2023eFY": the prior year's end.
_DART_CONTEXT = re.compile(
    r"(?P<relative>C|P|BP|BBP)FY(?P<year>\d{4})(?P<kind>[de])FY(?:_(?P<dims>.+))?"
)
_DART_OFFSETS = {"C": 0, "P": 1, "BP": 2, "BBP": 3}


@dataclass(frozen=True, slots=True)
class FactContext:
    """The period and dimensional scope one filing context declares.

    ``period_start``/``period_end`` bound a duration and ``instant`` names a point in
    time; DART contexts state only a fiscal year, so their dates stay ``None``.
    ``dimensions`` are (axis, member) pairs; an undimensioned context has none.
    """

    context_id: str
    period_start: date | None
    period_end: date | None
    instant: date | None
    fiscal_year: int | None
    dimensions: tuple[Dimension, ...]


@dataclass(frozen=True, slots=True)
class FactUnit:
    """One inline XBRL unit: its measures, and the denominator of a ratio unit."""

    unit_id: str
    numerator: str
    denominator: str | None


@dataclass(frozen=True, slots=True)
class SourceFact:
    """One tagged number and the source span of its tag.

    ``scale`` is the inline XBRL power of ten the displayed number is multiplied by
    (``None`` for DART, whose cells state no scale); ``decimals`` is the stated
    precision, never a scale.
    """

    start_char: int
    end_char: int
    concept: str
    context_id: str
    unit_id: str | None
    scale: int | None
    sign: str | None
    decimals: str | None
    text: str


@dataclass(frozen=True, slots=True)
class FilingFacts:
    """Every context, unit and tagged number of one filing, facts in source order."""

    source: FactSource | None = None
    contexts: tuple[FactContext, ...] = ()
    units: tuple[FactUnit, ...] = ()
    facts: tuple[SourceFact, ...] = ()

    def fingerprint(self) -> str:
        """Return a digest of every context, unit and fact, for parse identity."""
        payload = json.dumps(asdict(self), default=date.isoformat, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def within(self, start: int, end: int) -> tuple[SourceFact, ...]:
        """Return the facts whose tag starts inside the half-open source span."""
        first = bisect_left(self.facts, start, key=lambda fact: fact.start_char)
        last = bisect_left(self.facts, end, key=lambda fact: fact.start_char)
        return self.facts[first:last]


def _text(markup: str) -> str:
    """Return the visible text of a markup fragment, whitespace collapsed."""
    return " ".join(html.unescape(_TAGS.sub(" ", markup)).split())


def _date(value: str | None) -> date | None:
    """Parse one XBRL date, or None when it is absent or not a plain date."""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _fiscal_year(day: date, document: DocumentReference) -> int | None:
    """Name the fiscal year that ends on ``day``, counted back from the document's.

    Returns None unless ``day`` falls within a few days of a whole number of fiscal
    years before (or after) the document's own fiscal year end.
    """
    days = (document.report_period - day).days
    years = round(days / _YEAR_DAYS)
    if abs(days - years * _YEAR_DAYS) > _YEAR_END_TOLERANCE:
        return None
    return document.fiscal_year - years


def _sec_context(attributes: str, body: str, document: DocumentReference) -> FactContext | None:
    """Read one ``xbrli:context``; None when it has no id."""
    context_id = dict(_ATTRIBUTE.findall(attributes)).get("id")
    if not context_id:
        return None
    dates = {name.lower(): _date(value) for name, value in _DATE.findall(body)}
    start, end, instant = dates.get("startdate"), dates.get("enddate"), dates.get("instant")
    fiscal_year = None
    if instant is not None:
        fiscal_year = _fiscal_year(instant, document)
    elif start is not None and end is not None and (end - start).days in _ANNUAL_DAYS:
        fiscal_year = _fiscal_year(end, document)
    dimensions = [(axis, member) for axis, member in _EXPLICIT.findall(body)]
    dimensions += [(axis, f"typed:{_text(member)}") for axis, member in _TYPED.findall(body)]
    return FactContext(context_id, start, end, instant, fiscal_year, tuple(sorted(dimensions)))


def _sec_unit(attributes: str, body: str) -> FactUnit | None:
    """Read one ``xbrli:unit``; product measures are joined with ``*``."""
    unit_id = dict(_ATTRIBUTE.findall(attributes)).get("id")
    if not unit_id:
        return None
    numerator, denominator = _NUMERATOR.search(body), _DENOMINATOR.search(body)
    if numerator is not None and denominator is not None:
        return FactUnit(
            unit_id,
            "*".join(_MEASURE.findall(numerator.group(1))),
            "*".join(_MEASURE.findall(denominator.group(1))),
        )
    return FactUnit(unit_id, "*".join(_MEASURE.findall(body)), None)


def sec_facts(raw: str, document: DocumentReference) -> FilingFacts:
    """Read the contexts, units and ``ix:nonFraction`` facts of one inline XBRL filing.

    A filing without inline XBRL yields empty facts. Nil facts carry no number and a
    fact that encloses another fact cannot be tied to one figure, so both are left out.
    """
    contexts = tuple(
        context
        for attributes, body in _CONTEXT.findall(raw)
        if (context := _sec_context(attributes, body, document)) is not None
    )
    units = tuple(
        unit for attributes, body in _UNIT.findall(raw) if (unit := _sec_unit(attributes, body))
    )
    facts: list[SourceFact] = []
    for match in _NON_FRACTION.finditer(raw):
        attributes = dict(_ATTRIBUTE.findall(match.group(1)))
        inner = match.group(2)
        if attributes.get("xsi:nil") == "true" or "<ix:nonfraction" in inner.lower():
            continue
        concept, context_id = attributes.get("name"), attributes.get("contextRef")
        if not concept or not context_id:
            continue
        scale = attributes.get("scale", "0")
        facts.append(
            SourceFact(
                match.start(),
                match.end(),
                concept,
                context_id,
                attributes.get("unitRef"),
                int(scale) if re.fullmatch(r"-?\d+", scale) else None,
                attributes.get("sign"),
                attributes.get("decimals"),
                _text(inner),
            )
        )
    if not facts:
        return FilingFacts()
    return FilingFacts("ixbrl", contexts, units, tuple(facts))


def _dart_dimensions(names: str) -> tuple[Dimension, ...] | None:
    """Split ``ifrs-full_FooAxis_ifrs-full_BarMember...`` into (axis, member) pairs."""
    tokens = names.split("_")
    if len(tokens) % 4:
        return None
    qualified = [f"{tokens[i]}:{tokens[i + 1]}" for i in range(0, len(tokens), 2)]
    pairs = list(zip(qualified[::2], qualified[1::2], strict=True))
    if not all(axis.endswith("Axis") and member.endswith("Member") for axis, member in pairs):
        return None
    return tuple(sorted(pairs))


def _dart_context(context_id: str, document: DocumentReference) -> FactContext:
    """Read one DART context id; an unreadable one keeps no year and an opaque scope."""
    match = _DART_CONTEXT.fullmatch(context_id)
    if match is None:
        return FactContext(context_id, None, None, None, None, (("unparsed", context_id),))
    year = int(match.group("year"))
    consistent = document.fiscal_year - _DART_OFFSETS[match.group("relative")] == year
    dims = match.group("dims")
    dimensions = _dart_dimensions(dims) if dims else ()
    return FactContext(
        context_id,
        None,
        None,
        None,
        year if consistent else None,
        dimensions if dimensions is not None else (("unparsed", dims or ""),),
    )


def dart_facts(raw: str, document: DocumentReference) -> FilingFacts:
    """Read the tagged cells of one DART report and the contexts they name."""
    facts: list[SourceFact] = []
    context_ids: dict[str, None] = {}
    for match in _DART_CELL.finditer(raw):
        attributes = dict(_ATTRIBUTE.findall(match.group(2)))
        concept, context_id = attributes.get("ACODE"), attributes.get("ACONTEXT")
        if not concept or not context_id:
            continue
        context_ids.setdefault(context_id)
        facts.append(
            SourceFact(
                match.start(),
                match.end(),
                concept,
                context_id,
                None,
                None,
                None,
                attributes.get("ADECIMAL"),
                _text(match.group(3)),
            )
        )
    if not facts:
        return FilingFacts()
    contexts = tuple(_dart_context(context_id, document) for context_id in sorted(context_ids))
    return FilingFacts("dart", contexts, (), tuple(facts))
