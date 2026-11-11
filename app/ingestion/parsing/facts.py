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
type StatementKind = Literal[
    "balance_sheet",
    "income",
    "comprehensive_income",
    "cash_flow",
    "equity",
    "notes",
    "summary",
    "statement",
]
type StatementScope = Literal["consolidated", "separate"]

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
# A declared period: tags may sit between its words ("사업연도</TD><TD>2024년 ...").
_GAP = r"(?:\s|<[^>]*>)*"
_YMD = rf"(\d{{4}}){_GAP}[.년]{_GAP}(\d{{1,2}}){_GAP}[.월]{_GAP}(\d{{1,2}}){_GAP}일?"
# The cover's "사업연도 2024년 01월 01일 부터 2024년 12월 31일 까지".
_COVER = re.compile(rf"사업연도{_GAP}{_YMD}{_GAP}부터{_GAP}{_YMD}{_GAP}까지")
# A statement heading's "제 56 기 2024.01.01 부터 2024.12.31 까지" (or "(... ~ ...)").
_ORDINAL = re.compile(
    rf"제{_GAP}(\d+){_GAP}기{_GAP}\(?{_GAP}{_YMD}{_GAP}\.?{_GAP}(?:부터|~){_GAP}{_YMD}"
)
# A DART report's standard section codes for its financial statements, by the
# statement kind and entity scope each declares; "1. 요약재무정보" holds both scopes.
_SECTION_STATEMENTS: dict[str, tuple[StatementKind, StatementScope | None]] = {
    "D-0-3-1-0": ("summary", None),
    "D-0-3-2-0": ("statement", "consolidated"),
    "D-0-3-3-0": ("notes", "consolidated"),
    "D-0-3-4-0": ("statement", "separate"),
    "D-0-3-5-0": ("notes", "separate"),
}
# A table group's statement class: "{XBRL}BS_C", "{XBRL}IS2", "{XBRL}NT_S_D851105".
_GROUP_CLASS = re.compile(r"\{XBRL\}(?P<kind>BS|IS|CF|EF|NT)(?:_(?P<scope>[CS]))?(?P<variant>\d)?")
_GROUP_KINDS: dict[str, StatementKind] = {
    "BS": "balance_sheet",
    "CF": "cash_flow",
    "EF": "equity",
    "NT": "notes",
}
# The income statement classes: IS1 is a single statement of comprehensive income.
_INCOME_KINDS: dict[str | None, StatementKind] = {
    "1": "comprehensive_income",
    "2": "income",
    "3": "comprehensive_income",
}
_SECTION = re.compile(r"<SECTION-2\b[^>]*>(.*?)</SECTION-2>", re.S)
_SECTION_CODE = re.compile(r'<TITLE\b[^>]*\bAASSOCNOTE="(D-0-3-\d-0)"')
_GROUP = re.compile(r"<TABLE-GROUP\b([^>]*)>.*?</TABLE-GROUP>", re.S)
# The headings the report form prescribes inside "1. 요약재무정보". A heading stands as a
# whole paragraph or title, at most behind its enumerator ("가. 요약연결재무정보"); a
# paragraph that only mentions one ("나. 요약별도재무정보 (연결 기준은 가.
# 요약연결재무정보 참조)") declares nothing and ends the heading before it.
_BLOCK = re.compile(r"<(P|TITLE)\b[^>]*>(.*?)</\1>", re.S)
_SUMMARY_HEADING = re.compile(
    r"(?:(?:[가-하]|\d+)[.)]|\(\d+\))?\s*(?P<heading>요약\s*(?P<scope>연결|별도)\s*재무\s*정보)"
)
# Prior-period words and how many fiscal years before the reporting year they name.
_PRIOR_TERMS = (("전기", 1), ("전전기", 2))


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
class PeriodTerm:
    """A period word a DART report defines by declaring its dates.

    ``term`` is ``당기``, ``전기``, ``전전기`` or ``제N기``; the declaration it rests
    on is at ``start_char``/``end_char`` in the source.
    """

    term: str
    fiscal_year: int
    period_start: date
    period_end: date
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class StatementDeclaration:
    """What a DART report declares about the tables inside one span of its source.

    ``kind`` and ``scope`` are None where the declaration states neither; ``basis``
    quotes the declaration (a section code, a table group class or a heading).
    """

    start_char: int
    end_char: int
    kind: StatementKind | None
    scope: StatementScope | None
    basis: str


@dataclass(frozen=True, slots=True)
class FilingFacts:
    """Every context, unit, tagged number and declared period term of one filing.

    Facts are in source order.
    """

    source: FactSource | None = None
    contexts: tuple[FactContext, ...] = ()
    units: tuple[FactUnit, ...] = ()
    facts: tuple[SourceFact, ...] = ()
    period_terms: tuple[PeriodTerm, ...] = ()
    statements: tuple[StatementDeclaration, ...] = ()
    # Whether the filing's form presents several entity scopes (a DART report has
    # consolidated and separate statements), so a table's scope must be declared.
    scope_declared: bool = False

    def fingerprint(self) -> str:
        """Return a digest of every context, unit and fact, for parse identity."""
        payload = json.dumps(asdict(self), default=date.isoformat, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def within(self, start: int, end: int) -> tuple[SourceFact, ...]:
        """Return the facts whose tag starts inside the half-open source span."""
        first = bisect_left(self.facts, start, key=lambda fact: fact.start_char)
        last = bisect_left(self.facts, end, key=lambda fact: fact.start_char)
        return self.facts[first:last]

    def declarations_at(self, position: int) -> tuple[StatementDeclaration, ...]:
        """Return the statement declarations whose span holds one source position."""
        return tuple(
            declaration
            for declaration in self.statements
            if declaration.start_char <= position < declaration.end_char
        )


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


def _declared(match: re.Match[str], first: int) -> tuple[date, date] | None:
    """Return the annual period a declaration states from group ``first`` on, if any."""
    try:
        start = date(*(int(match.group(first + i)) for i in range(3)))
        end = date(*(int(match.group(first + 3 + i)) for i in range(3)))
    except ValueError:
        return None
    return (start, end) if (end - start).days in _ANNUAL_DAYS else None


def dart_period_terms(raw: str, document: DocumentReference) -> tuple[PeriodTerm, ...]:
    """Read the period words one DART report defines by its own declarations.

    ``당기`` is the cover's business year, when the cover declares exactly one that
    ends on the document's report period. ``제N기`` is the one annual period the report
    declares for that ordinal, named counting back from the document's fiscal year;
    an ordinal declared with two periods is left out. ``전기`` and ``전전기`` are one
    and two fiscal years before ``당기``, defined only when the report declares a
    period for that year. Nothing is defined without the cover.
    """
    covers: dict[tuple[date, date], re.Match[str]] = {}
    for match in _COVER.finditer(raw):
        if (period := _declared(match, 1)) is not None:
            covers.setdefault(period, match)
    if len(covers) != 1:
        return ()
    ((start, end), cover), *_ = covers.items()
    if end != document.report_period:
        return ()
    declared: dict[int, dict[tuple[date, date], re.Match[str]]] = {}
    for match in _ORDINAL.finditer(raw):
        if (period := _declared(match, 2)) is not None:
            declared.setdefault(int(match.group(1)), {}).setdefault(period, match)
    terms = [PeriodTerm("당기", document.fiscal_year, start, end, cover.start(), cover.end())]
    by_year: dict[int, PeriodTerm] = {document.fiscal_year: terms[0]}
    for number, periods in sorted(declared.items()):
        if len(periods) != 1:
            continue
        ((period_start, period_end), match), *_ = periods.items()
        fiscal_year = _fiscal_year(period_end, document)
        if fiscal_year is None:
            continue
        term = PeriodTerm(
            f"제{number}기", fiscal_year, period_start, period_end, match.start(), match.end()
        )
        terms.append(term)
        by_year.setdefault(fiscal_year, term)
    for word, back in _PRIOR_TERMS:
        if (found := by_year.get(document.fiscal_year - back)) is not None:
            terms.append(
                PeriodTerm(
                    word,
                    found.fiscal_year,
                    found.period_start,
                    found.period_end,
                    found.start_char,
                    found.end_char,
                )
            )
    return tuple(terms)


def dart_statements(raw: str) -> tuple[StatementDeclaration, ...]:
    """Read where a DART report declares its statements, in source order.

    Each financial section with a standard code declares its span; each table group
    with a statement class declares its kind and, with a ``_C``/``_S`` suffix, its
    scope; inside "1. 요약재무정보" each prescribed heading ("요약연결재무정보",
    "요약별도재무정보") that stands as a whole paragraph or title declares the scope
    from itself to the next paragraph naming one.
    """
    declarations: list[StatementDeclaration] = []
    for section in _SECTION.finditer(raw):
        code = _SECTION_CODE.search(section.group(1))
        if code is None or code.group(1) not in _SECTION_STATEMENTS:
            continue
        kind, scope = _SECTION_STATEMENTS[code.group(1)]
        start, end = section.start(), section.end()
        declarations.append(
            StatementDeclaration(start, end, kind, scope, f"section {code.group(1)}")
        )
        if kind != "summary":
            continue
        headings = [
            (block.start(), _SUMMARY_HEADING.fullmatch(text))
            for block in _BLOCK.finditer(raw, start, end)
            if _SUMMARY_HEADING.search(text := _text(block.group(2).replace("&cr;", " ")))
        ]
        for (position, heading), following in zip(headings, [*headings[1:], None], strict=True):
            if heading is None:
                continue
            declarations.append(
                StatementDeclaration(
                    position,
                    end if following is None else following[0],
                    "summary",
                    "consolidated" if heading.group("scope") == "연결" else "separate",
                    f"heading {heading.group('heading')}",
                )
            )
    for group in _GROUP.finditer(raw):
        label = dict(_ATTRIBUTE.findall(group.group(1))).get("ACLASS", "")
        match = _GROUP_CLASS.match(label)
        if match is None:
            continue
        name = match.group("kind")
        kind = _INCOME_KINDS.get(match.group("variant")) if name == "IS" else _GROUP_KINDS[name]
        suffix = match.group("scope")
        declarations.append(
            StatementDeclaration(
                group.start(),
                group.end(),
                kind,
                None if suffix is None else "consolidated" if suffix == "C" else "separate",
                f"class {label}",
            )
        )
    return tuple(sorted(declarations, key=lambda declaration: declaration.start_char))


def dart_facts(raw: str, document: DocumentReference) -> FilingFacts:
    """Read one DART report's tagged cells, their contexts, its terms and statements.

    A DART report presents consolidated and separate statements, so its facts always
    say a table's scope must be declared, even when the report tags nothing.
    """
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
    contexts = tuple(_dart_context(context_id, document) for context_id in sorted(context_ids))
    return FilingFacts(
        "dart",
        contexts,
        (),
        tuple(facts),
        dart_period_terms(raw, document),
        dart_statements(raw),
        scope_declared=True,
    )
