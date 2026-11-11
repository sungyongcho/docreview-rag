"""Read a table's cells: their values, unit, currency, fiscal year, scope and item.

A table's unit is read from unit declarations in its own header cells or in the
caption run the chunker linked to it with source spans, every one of them fully read.
When the unit of the item's cells is absent, not fully readable or contradictory, no
unit is guessed. A scale word written in a cell ("25.8 billion") is that cell's unit
under a table in plain currency units and contradicts a table that states a scale.

A cell whose figure the filing tags as a fact (inline XBRL, or a DART ``ACONTEXT``)
takes its fiscal year and scope from the tag, and an inline XBRL fact also its
currency and scale; each fact that contradicts the text reading is recorded as an
override. A fact scoped to a dimension (a segment, a DART separate statement) is
not the item of the whole entity, so it never confirms a claim. Untagged cells keep
the text rules above, with one addition: a header that is a period word its DART
report defines by its own declarations ("당기", "제56기") names that fiscal year.
An untagged cell is the fiscal year's reported amount of the whole entity only when
every header above it is wholly understood as a year, a date, a unit declaration or
a word saying "a full fiscal year, as reported"; any other word leaves its period or
its scope not established.

A DART report presents consolidated and separate statements, so its untagged cells
are the entity's figures only in a table it declares to be a consolidated balance
sheet, income, comprehensive income or cash flow statement or its consolidated
summary; a separate statement is a scope of its own and any other table's scope is
unknown.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
import re
from typing import Literal

from app.figures.currency import (
    ANY_CURRENCY,
    CODES,
    CONFLICT,
    FAMILIES,
    UNKNOWN,
    currencies_in,
    currency_of,
    resolve,
)
from app.figures.items import ITEMS
from app.figures.periods import PERIOD_WORDS, classify_period
from app.figures.text import (
    KOREAN_SCALE,
    YEAR,
    blank,
    english_factor,
    figure_spans,
    korean_factor,
    signed,
    values,
)
from app.figures.vocabulary import PHRASE_ITEMS, SAME_ITEM_QUALIFIER, phrase_key

# Unit declarations are read with a small explicit grammar, not from any scale word in
# the text. A parenthetical declares a unit when it is up to three words, "in" and words
# without digits ("(In millions)", "(Dollars in thousands)", "(in widgets)"), or when it
# opens with "Units:". Outside parentheses, a "Units:" clause anywhere and a header cell
# that is itself one bare declaration ("In millions", "in widgets", "Dollars in
# thousands") count too; other words ("Change in revenue") declare nothing. A declaration
# counts only when all of it is understood; anything else in it (an unsupported
# exception, another unit) makes it unknown.
_PARENTHESIS = re.compile(r"[(（]([^()（）]*)[)）]")
_DECLARATION = re.compile(
    r"\s*(?:(?:[A-Za-z$.]+\s+){0,3}in\s+[A-Za-z$][A-Za-z$.,'\s-]*|units?\s*[:：][^\d]*)",
    re.IGNORECASE,
)
_BARE_DECLARATION = re.compile(
    r"\s*(?:(?:\$|us\$|dollars|amounts)\s+)?in\s+[A-Za-z$][A-Za-z$.,'\s-]*", re.IGNORECASE
)
_UNITS_CLAUSE = re.compile(r"\bunits?\s*[:：]\s*[A-Za-z$][^()\d]*", re.IGNORECASE)
_SCALE_WORD = (
    r"(?P<scale>thousands|millions|billions|trillions)"
    rf"(?:\s+of\s+(?P<of>{ANY_CURRENCY}))?"
)
# "In millions [of <currency>]", optionally led by a currency or "Amounts".
_SCALE_DECLARATION = re.compile(
    rf"\s*(?:(?P<prefix>amounts|{ANY_CURRENCY})\s+)?in\s+{_SCALE_WORD}"
    r"(?P<per_share>\s*,\s*except\s+(?:for\s+)?(?:share\s+and\s+)?per[\s-]share"
    r"(?:\s+and\s+share)?(?:\s+(?:data|amounts|information|figures))?)?\s*",
    re.IGNORECASE,
)
# "In <currency>" ("(In U.S. dollars)") declares a currency, and plain units only when no
# other note of the table states a scale; "(In millions) (In U.S. dollars)" is millions.
_PLAIN_DECLARATION = re.compile(rf"\s*in\s+(?P<currency>{ANY_CURRENCY})\s*", re.IGNORECASE)
# A currency-only declaration states no scale at all: "(USD)", "(Currency: KRW)",
# "(Expressed in U.S. dollars)".
_CURRENCY_DECLARATION = re.compile(
    r"\s*(?:(?:currency|denomination)\s*[:：]\s*|(?:expressed|presented|reported)\s+in\s+)?"
    rf"(?P<currency>{ANY_CURRENCY})\s*",
    re.IGNORECASE,
)
_UNITS_DECLARATION = re.compile(rf"\s*units?\s*[:：]\s*{_SCALE_WORD}\s*", re.IGNORECASE)
# A Korean 단위 note runs to its closing parenthesis; it lists one unit or several.
_KOREAN_UNIT_NOTE = re.compile(r"단위\s*[:：]?\s*([^)）]*)")
# The monetary unit a Korean 단위 note may state: an optional scale and a currency.
_KOREAN_NOTE = re.compile(r"(?P<scale>(?:[십백천]?[만억조])|천)?(?P<currency>.+)")
# Per-share rows of a "(In millions, except per share data)" table are in plain currency.
_PER_SHARE = re.compile(r"per\s+share|주당", re.IGNORECASE)


# One amount's digits: grouped in threes by commas, or not grouped at all. Any other
# grouping ("25,7851" with a glued footnote, "4,5,28" note numbers) is no one amount.
_GROUPED = re.compile(r"[(△▲-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?")

# An untagged column header establishes "this fiscal year's reported amount of the
# whole entity" only when all of it is understood: its years and dates, its unit
# declarations and the closed vocabulary below, which says "a full fiscal year, as
# reported" ("Year Ended December 28, 2024", "Fiscal 2024", "52 Weeks Ended", "제56기",
# "당기말", "2024년 12월말"). Any other word is not understood (see _header_residue).
_HEADER_DATES = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+\d{1,2}(?!\d)"
    r"(?:\s*,?\s*(?:19|20)\d{2}(?!\d))?"
    r"|(?<!\d)\d{1,2}/\d{1,2}/(?:19|20)\d{2}(?!\d)"
    r"|(?<!\d)(?:19|20)\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}(?!\d)"
    r"|(?<!\d)(?:19|20)\d{2}\s*년\s*\d{1,2}\s*월\s*(?:\d{1,2}\s*일|말)"
    r"|(?<!\d)(?:19|20)\d{2}\s*년(?!\s*\d{1,2}\s*월)"
    r"|(?<!\d)\d{1,2}\s*월\s*(?:\d{1,2}\s*일|말)"
    r"|\bfy\s?(?:(?:19|20)\d{2}|\d{2})\b"
    r"|(?<!\d)(?:19|20)\d{2}(?!\d)",
    re.IGNORECASE,
)
_ANNUAL_WORDS = re.compile(
    r"\b(?:twelve|12)[\s-]+months?\b|\b(?:52|53|fifty[\s-]two|fifty[\s-]three)[\s-]+weeks?\b"
    r"|\b(?:fiscal|years?|ended|ending|end|as|of|at|on|and|consolidated|reported|gaap)\b"
    r"|제\s*\d+\s*기|회계\s*연도|사업\s*연도|전\s*전\s*기|당\s*기|전\s*기|기\s*말|현\s*재|연\s*결|말",
    re.IGNORECASE,
)
# Characters that carry no meaning of their own in a header, and DART's line break.
_HEADER_PUNCTUATION = re.compile(r"(?:&cr;?|[\s,.:;()（）\[\]&~–—-])+")
# A declared duration ("2024.01.01~2024.12.31"): a full year of one, with "누계"
# (cumulative) beside it, names the fiscal year; a shorter one is a period of its own.
_DATE = r"((?:19|20)\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})"
_RANGE = re.compile(_DATE + r"\s*[~–-]\s*" + _DATE)
# A word naming a period of its own, which leaves the fiscal year not established
# ("Three Months Ended", "13 Weeks", "H1", "YTD", "Interim", "4분기", "누적", "기초"),
# including a month left without its day ("December 2024", "2023년 8월").
# A label-only row naming a part of the entity ("Data Center segment:", "DS 부문").
_PART = re.compile(
    r"\b(?:segments?|divisions?|regions?|geographic\w*|subsidiar\w*|joint\s+ventures?"
    r"|affiliates?|investees?|guarantors?|discontinued|pro\s+forma)\b"
    r"|부문|사업부|지역|종속|관계기업|공동기업|피투자",
    re.IGNORECASE,
)
# Words that name a period in a header without writing its year ("Current", "Prior",
# "Year end", "당기", "제56기", "분기"): a table with one is dated by its headers.
_PERIOD_WORD = re.compile(
    r"당기|전기|제\s*\d+\s*기|기말|기초|분기|반기"
    r"|\b(?:current|prior|previous|fiscal|years?|quarters?|months?|weeks?|periods?)\b",
    re.IGNORECASE,
)
# A header naming a column of note references.
_NOTE_HEADER = re.compile(r"\s*(?:notes?|주석)\s*", re.IGNORECASE)
# A cell that only cites notes ("Note 5", "주석 4,5") labels no row.
_NOTE_CITATION = re.compile(r"\s*(?:notes?|주석?)\s*[\d,\s~-]*", re.IGNORECASE)

_ENUMERATOR = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|\d+|[ivx]+|[가-하])[.)]\s*", re.IGNORECASE)


type ScopeCause = Literal[
    "statement_undeclared", "header_unread", "part_row", "second_label", "parent_unread"
]
SCOPE_REASONS: dict[ScopeCause, str] = {
    "statement_undeclared": "the statement does not declare a whole-entity scope",
    "header_unread": "the column header contains words not established as a reported amount",
    "part_row": "the row is under a heading naming part of the entity",
    "second_label": "a second row label leaves the entity scope unestablished",
    "parent_unread": "a parent heading is not understood as a whole-entity statement section",
}


@dataclass(frozen=True, slots=True)
class TableCellReading:
    """One original table cell holding figures: its values, years, unit and row item.

    ``row`` and ``column`` are the cell's zero-based source grid coordinates. ``scale``
    is None when the cell's unit is uncertain; ``percent`` is None when the evidence
    cannot show whether the cell is a percentage. ``currency`` is resolved from the
    table's notes and the markers bound to this cell's own numbers only, never from
    other rows or tables; ``marked`` says the cell's numbers carry currency markers.

    ``values`` carry the sign the notation or the tag establishes ("(1,641)" is
    -1641); ``direction`` in ``overrides`` marks values whose sign is not established
    (a ``▲`` figure, an unsigned figure under a loss-only label).

    A reading carries each fact its cell does not establish, so a figure check that
    compares readings and the cell's interpretation decide it the same way:
    ``values`` is empty when the figure is no one amount (digits not grouped in
    threes, or its one tag showing another number), ``scale`` is None when a scale
    word in the cell contradicts its unit, and ``percent`` is None for a figure whose
    normalized cell carries a lone "%" cell or whose amount tag contradicts a written
    percentage.
    """

    row: int
    column: int
    values: frozenset[Decimal]
    years: frozenset[int]
    scale: Decimal | None
    item: str | None
    percent: bool | None
    currency: str | None = None
    marked: bool = False
    row_label: str | None = None
    basis: Literal["text", "fact"] = "text"
    overrides: tuple[str, ...] = ()
    scope: str | None = None
    measure: Literal["amount", "per_share", "other"] | None = None

    @property
    def scope_cause(self) -> ScopeCause | None:
        """Read the typed scope cause persisted in the existing override column."""
        return next((cause for cause in SCOPE_REASONS if "scope:" + cause in self.overrides), None)

    @property
    def amount_problem(self) -> tuple[CellStatus, str] | None:
        """Name a structural hold shared by selection and comparison, excluding units/sign.

        Unit and direction uncertainty alone may withhold a written claim. Every other
        missing fact makes this cell ineligible as evidence, even for an undated claim.
        """
        if len(self.values) != 1 or any(x in self.overrides for x in ("multiple", "incomplete")):
            return "conflicting", "no single complete figure"
        if self.measure == "other" or self.percent is True:
            return "not_monetary", "the cell is not a monetary amount"
        if (
            self.measure == "per_share"
            and self.item is not None
            and self.item
            not in {
                "earnings per share",
                "basic earnings per share",
                "diluted earnings per share",
            }
        ):
            return "not_monetary", "a per-share tag is not this item's amount"
        if len(self.years) != 1:
            return "period_unknown", "no single fiscal year"
        if self.scope == UNKNOWN:
            cause = self.scope_cause
            return "scope_unknown", (
                SCOPE_REASONS[cause]
                if cause is not None
                else "the cell's row, column and statement do not establish entity scope"
            )
        if self.scope is not None:
            return "scope_qualified", self.scope
        if self.item is None:
            return "item_unknown", (
                "the tag's concept is not the row label's item"
                if "concept" in self.overrides
                else "row label names no item"
            )
        return None

    @property
    def evidence_eligible(self) -> bool:
        """Whether this cell can supply an amount, possibly held only for unit or sign."""
        return self.amount_problem is None


@dataclass(frozen=True, slots=True)
class CellFact:
    """One fact a filing tags inside a source cell, with its context and unit joined.

    ``fiscal_year`` is None when the context is not one fiscal year. ``numerator`` and
    ``denominator`` are the inline XBRL unit's measures (``iso4217:USD``,
    ``xbrli:shares``); DART facts state no unit, so both are None, as is ``scale``.
    ``sign`` is ``-`` when an inline XBRL tag negates its displayed number and ``+``
    when it states no sign; DART tags state none, so their ``sign`` is None.
    """

    concept: str
    fiscal_year: int | None
    dimensions: tuple[tuple[str, str], ...]
    numerator: str | None
    denominator: str | None
    scale: int | None
    text: str
    sign: Literal["-", "+"] | None = None


CellStatus = Literal[
    "known",
    "blank",
    "not_numeric",
    "conflicting",
    "not_monetary",
    "scale_unknown",
    "currency_unconfirmed",
    "period_unknown",
    "scope_qualified",
    "scope_unknown",
    "item_unknown",
]


@dataclass(frozen=True, slots=True)
class CellInterpretation:
    """Whether one normalized table cell can stand as a single selectable amount.

    ``value`` keeps the sign and every written decimal of the cell's one figure; it is
    None unless that figure is readable. ``reading`` is the one figure-bearing source
    cell the value comes from. ``status`` is ``known`` only when the value, its unit, its
    currency (or percentage), one fiscal year and one item are all established; any
    other status names the first missing fact and ``reason`` says why.
    """

    status: CellStatus
    reason: str | None
    value: Decimal | None
    reading: TableCellReading | None


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


@dataclass(frozen=True, slots=True)
class TableUnit:
    """The unit a table's own notes state and how certain it is.

    ``status`` is ``known`` when every readable note agrees, ``absent`` when the table
    carries no note, ``unknown`` when a note cannot be read as a monetary scale or a
    percentage ("(단위 : 주)"), and ``conflicting`` when notes state different scales or
    currencies, or a percentage beside a monetary scale with nothing mapping either to
    its rows.
    ``scale`` is the agreed monetary scale; ``percent`` marks a percentage note;
    ``per_share_plain`` marks an explicit per-share exception ("except per share data").
    ``currency`` holds the currency markers every note declares, resolved per cell
    together with the cell's own markers.
    """

    status: Literal["known", "absent", "unknown", "conflicting"]
    scale: Decimal | None = None
    percent: bool = False
    per_share_plain: bool = False
    currency: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Note:
    """One unit declaration: a monetary ``scale``, a ``currency`` only, a ``percent``
    note, or ``unknown``.

    ``currency`` holds the currency markers the note itself declares ("USD", "원", or
    the ambiguous "$"), empty when it names none ("(In millions)"); they are compared,
    never converted. ``plain`` marks "In <currency>", which states plain units only when
    no other note states a scale.
    """

    kind: Literal["scale", "currency", "percent", "unknown"]
    scale: Decimal | None = None
    per_share_plain: bool = False
    currency: frozenset[str] = frozenset()
    plain: bool = False


def _linked(caption: Mapping[str, object]) -> bool:
    """Whether a stored caption carries the source span that ties it to its table."""
    start, end = caption.get("start_char"), caption.get("end_char")
    return isinstance(start, int) and isinstance(end, int) and 0 <= start < end


def _english_note(declaration: str) -> _Note:
    """Read one English declaration, unknown unless all of it is understood."""
    if scale := _SCALE_DECLARATION.fullmatch(declaration):
        prefix = scale.group("prefix") or ""
        currency = currencies_in(" ".join((prefix, scale.group("of") or "")))
        return _Note(
            "scale",
            english_factor(scale.group("scale")),
            scale.group("per_share") is not None,
            currency,
        )
    if units := _UNITS_DECLARATION.fullmatch(declaration):
        currency = currencies_in(units.group("of") or "")
        return _Note("scale", english_factor(units.group("scale")), currency=currency)
    if plain := _PLAIN_DECLARATION.fullmatch(declaration):
        return _Note("currency", currency=currencies_in(plain.group("currency")), plain=True)
    if named := _CURRENCY_DECLARATION.fullmatch(declaration):
        return _Note("currency", currency=currencies_in(named.group("currency")))
    return _Note("unknown")


def _korean_note(content: str) -> _Note:
    """Read one Korean 단위 note; a list of several units leaves each row's unit unknown."""
    parts = [re.sub(r"\s+", "", part) for part in re.split(r"[,/、]", content)]
    if len(parts) != 1:
        return _Note("unknown")
    if parts[0] == "%":
        return _Note("percent")
    korean = _KOREAN_NOTE.fullmatch(parts[0])
    currency = currency_of(korean.group("currency")) if korean else None
    if korean is not None and currency is not None:
        # A 단위 note states the unit itself, so a bare currency ("원") means plain units.
        prefix = korean.group("scale")
        scale = KOREAN_SCALE.fullmatch(prefix) if prefix else None
        factor = korean_factor(scale) if scale is not None else Decimal(1)
        return _Note("scale", factor, currency=frozenset({currency}))
    return _Note("unknown")


def _notes(text: str) -> list[_Note]:
    """Read every unit declaration of one header cell or caption.

    Parenthetical declarations are read one by one, so a recognized "(In millions)"
    never hides "(Units: widgets)" beside it. Outside parentheses, every "Units:" clause
    is read, and what remains counts when it is itself one bare declaration ("In
    millions", "in widgets"); other words ("Change in revenue") declare nothing.
    """
    notes = [_korean_note(match.group(1)) for match in _KOREAN_UNIT_NOTE.finditer(text)]
    english = [
        content
        for content in _PARENTHESIS.findall(text)
        if "단위" not in content
        and (_DECLARATION.fullmatch(content) or _CURRENCY_DECLARATION.fullmatch(content))
    ]
    outside = _PARENTHESIS.sub(" ", text)
    english += _UNITS_CLAUSE.findall(outside)
    rest = _UNITS_CLAUSE.sub(" ", outside)
    if "단위" not in rest and _BARE_DECLARATION.fullmatch(rest):
        english.append(rest)
    return notes + [_english_note(" ".join(declaration.split())) for declaration in english]


def read_table_unit(fragment: Mapping[str, object]) -> TableUnit:
    """Read the unit a table's own header cells and linked captions state.

    Only notes demonstrably tied to this table count: its header cells, and captions
    the chunker attached with their source span (a caption row, a caption-only table
    or a caption paragraph directly before it). A caption without that span, and any
    other context, is ignored, so a stored fragment without one stays ``absent``.
    Nothing defaults to plain units: an absent, unreadable or contradictory note
    leaves the monetary scale unknown.
    """
    texts = [str(cell.get("text", "")) for cell in _entries(fragment, "header_cells")]
    texts += [
        str(caption.get("text", ""))
        for caption in _entries(fragment, "caption_sources")
        if _linked(caption)
    ]
    notes = [note for text in texts for note in _notes(text)]
    if not notes:
        return TableUnit("absent")
    percent = any(note.kind == "percent" for note in notes)
    if any(note.kind == "unknown" for note in notes):
        return TableUnit("unknown", percent=percent)
    scales = {note.scale for note in notes if note.kind == "scale" and note.scale is not None}
    if not scales and any(note.plain for note in notes):
        scales = {Decimal(1)}
    currency = frozenset(marker for note in notes for marker in note.currency)
    monetary = bool(scales or currency)
    if len(scales) > 1 or resolve(currency) == CONFLICT or (percent and monetary):
        return TableUnit("conflicting", percent=percent)
    per_share_plain = any(note.per_share_plain for note in notes)
    return TableUnit("known", next(iter(scales), None), percent, per_share_plain, currency)


def _term_year(text: str, terms: Mapping[str, int]) -> int | None:
    """Return the fiscal year a whole header names by a defined period word.

    The header must be the word alone, spaces aside, optionally with ``말`` for its
    end ("전기말", "제56기말"); a header with any other word names no term.
    """
    word = re.sub(r"\s+", "", text)
    return terms.get(word.removesuffix("말")) if word else None


def _headers_over(
    source: Mapping[str, object], headers: Sequence[Mapping[str, object]]
) -> list[str]:
    """Return the texts of the header cells whose columns overlap one data cell's."""
    start = _int(source["column"])
    end = start + _int(source.get("colspan", 1))
    return [
        str(header.get("text", ""))
        for header in headers
        if _int(header["column"]) < end
        and start < _int(header["column"]) + _int(header.get("colspan", 1))
    ]


def _annual_range(match: re.Match[str]) -> bool:
    """Whether a declared duration ("2024.01.01~2024.12.31") is one full year."""
    try:
        start = date(*(int(match.group(i)) for i in (1, 2, 3)))
        end = date(*(int(match.group(i)) for i in (4, 5, 6)))
    except ValueError:
        return False
    return 350 <= (end - start).days <= 380


def _header_residue(text: str) -> str:
    """Return what one header says beyond years, dates, units and full-year words.

    Unit declarations ("(In millions)", "(단위 : 백만원)", a bare "In millions except
    per share amounts") are set aside first; an empty residue means the header is
    wholly understood.
    """
    words = _KOREAN_UNIT_NOTE.sub(" ", text)
    words = _PARENTHESIS.sub(
        lambda match: (
            " "
            if _DECLARATION.fullmatch(match.group(1))
            or _CURRENCY_DECLARATION.fullmatch(match.group(1))
            else match.group(0)
        ),
        words,
    )
    words = _UNITS_CLAUSE.sub(" ", words)
    if _BARE_DECLARATION.fullmatch(words):
        return ""
    ranges = list(_RANGE.finditer(words))
    words = _RANGE.sub(" ", words)
    if ranges and not all(_annual_range(match) for match in ranges):
        words += " 기간"
    elif ranges:
        # A full year's cumulative figures ("제77기 누계(2024.01.01~2024.12.31)").
        words = words.replace("누계", " ")
    words = _ANNUAL_WORDS.sub(" ", _HEADER_DATES.sub(" ", words))
    return _HEADER_PUNCTUATION.sub(" ", words).strip()


def _header_reading(over: Sequence[str]) -> tuple[bool, bool]:
    """Return whether the headers above a cell leave its period, or its scope, unread.

    A residue word naming a period ("Three Months", "H1", "YTD", "분기") means the
    fiscal year is not established; any other residue word ("Adjustments",
    "Guidance", "계획") means the column is not shown to be the entity's reported
    amount.
    """
    period = scope = False
    for text in over:
        residue = _header_residue(text)
        if not residue:
            continue
        rest = PERIOD_WORDS.sub(" ", residue)
        period = period or classify_period(residue) in {"subannual", "date"}
        scope = scope or bool(_HEADER_PUNCTUATION.sub(" ", rest).strip())
    return period, scope


def _column_years(
    over: Sequence[str], caption_years: set[int] | None, terms: Mapping[str, int]
) -> set[int]:
    """Return the years the headers above one data cell's columns name.

    A header names years by writing them or, when it writes none, by being one period
    word its document defines (see :func:`_term_year`). Stacked headers that differ in
    breadth date the column by the most specific one: a header naming exactly one
    year narrows those naming several years that include it; otherwise the column
    keeps every year named, and so no single one. A header with a word naming a
    period of its own ("Three Months Ended December 28, 2024") names none.
    ``caption_years`` are the caption's years when they may date this column (see
    :func:`_caption_dates`); the column takes them only when they are one year.
    """
    if _header_reading(over)[0]:
        return set()
    named: list[set[int]] = []
    for text in over:
        written = {int(year) for year in YEAR.findall(text)}
        if not written and (term := _term_year(text, terms)) is not None:
            written = {term}
        if written:
            named.append(written)
    years = set().union(*named)
    leaves = {next(iter(written)) for written in named if len(written) == 1}
    if len(leaves) == 1 and all(leaves <= written for written in named):
        # A spanning header naming several years ("Years Ended December 28, 2024 and
        # December 30, 2023") is narrowed by the leaf header naming one of them.
        return leaves
    if not years and caption_years is not None and len(caption_years) == 1:
        return set(caption_years)
    return years


def _caption_dates(
    fragment: Mapping[str, object],
    headers: Sequence[Mapping[str, object]],
    terms: Mapping[str, int],
) -> int | None:
    """Return the one column a caption's year may date, or None.

    Only a table none of whose headers names a year or a period ("Current", "전기",
    a defined term) and with exactly one value column lets its caption date that
    column; a column headed Note(s)/주석 holds references, so it is no value column
    and is never dated.
    """
    texts = [str(header.get("text", "")) for header in headers]
    if any(
        YEAR.search(text) or _PERIOD_WORD.search(text) or _term_year(text, terms) is not None
        for text in texts
    ):
        return None
    columns: set[int] = set()
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            over = _headers_over(source, headers)
            if values(str(source.get("text", ""))) and not any(
                _NOTE_HEADER.fullmatch(text) for text in over
            ):
                columns.add(_int(source["column"]))
    return next(iter(columns)) if len(columns) == 1 else None


def _worded(text: str) -> bool:
    """Whether a cell without figures carries words that label a row.

    Currency markers ("$", "원") and note citations ("Note 5") label nothing.
    """
    return (
        re.search(r"[^\W\d_]", blank(text)) is not None
        and currency_of(text.strip()) is None
        and _NOTE_CITATION.fullmatch(text) is None
    )


def _row_structure(fragment: Mapping[str, object]) -> tuple[set[int], dict[int, list[int]]]:
    """Return the rows under a part of the entity, and each row's worded columns.

    A label-only row holds one worded cell and no figure. From one naming a part of
    the entity ("Data Center segment:"), every following row of the table is read as
    possibly that part's. The worded columns of a row are where its labels stand; the
    leftmost is its row label.
    """
    worded: dict[int, set[int]] = {}
    texts: dict[int, str] = {}
    figured: set[int] = set()
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            text = str(source.get("text", "")).strip()
            row = _int(source["row"])
            if values(text):
                figured.add(row)
            elif text and _worded(text):
                worded.setdefault(row, set()).add(_int(source["column"]))
                texts[row] = text
    under: set[int] = set()
    part = False
    for row in sorted(set(worded) | figured):
        if row not in figured and len(worded.get(row, ())) == 1:
            part = part or _PART.search(texts[row]) is not None
        elif part:
            under.add(row)
    return under, {row: sorted(columns) for row, columns in worded.items()}


def _row_labels(fragment: Mapping[str, object]) -> dict[int, str]:
    """Return the leftmost non-numeric cell text of each source row (its row label)."""
    labels: dict[int, tuple[int, str]] = {}
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            text = str(source.get("text", "")).strip()
            if text and not values(text):
                row, column = _int(source["row"]), _int(source["column"])
                if row not in labels or column < labels[row][0]:
                    labels[row] = (column, text)
    return {row: text for row, (_, text) in labels.items()}


def _label_key(label: str) -> str | None:
    """Return the phrase a row label is looked up by, or None when it is qualified.

    Enumerators ("Ⅰ.") and the parentheticals that keep the same item ("Net income
    (loss)", note references) are set aside. Any other parenthetical qualifies the
    row ("Net income (attributable to noncontrolling interests)"), so the label names
    no phrase. Korean labels are compared without spaces.
    """
    text = SAME_ITEM_QUALIFIER.sub("", _ENUMERATOR.sub("", label))
    if re.search(r"[()（）]", text):
        return None
    key = phrase_key(text).rstrip(":").strip()
    return key if key.isascii() else key.replace(" ", "")


def _label_item(label: str) -> str | None:
    """Return the item a row label names when the whole label is one accepted phrase."""
    key = _label_key(label)
    return None if key is None else PHRASE_ITEMS.get(key)


def _loss_only(label: str | None) -> bool:
    """Whether a row label names its item by a loss phrase alone ("Net loss", "영업손실").

    Such a label says the row is a loss, so an unsigned figure under it could be the
    loss itself or the item's (negative) amount. A label naming both ("Net income
    (loss)", "영업이익(손실)") reads as the item.
    """
    key = None if label is None else _label_key(label)
    return key is not None and key in PHRASE_ITEMS and ("loss" in key or "손실" in key)


# A concept of a standard taxonomy, as inline XBRL ("us-gaap:Revenues") and DART
# ("ifrs-full_Revenue") name it. Company extensions ("amd:...") and DART's own codes
# ("dart_OperatingIncomeLoss") cannot be judged from a list, so their rows keep the
# label's item.
_STANDARD_CONCEPT = re.compile(r"(?:us-gaap|ifrs-full)[:_](?P<name>\w+)")
# The DART statement axis whose consolidated member is the entity as a whole.
_ENTITY_SCOPE = (
    (
        "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
        "ifrs-full:ConsolidatedMember",
    ),
)
_ISO_CURRENCY = re.compile(r"iso4217:([A-Z]{3})")
# The scope a separate statement reads as, the same words its DART tags state.
_SEPARATE_SCOPE = (
    "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis=ifrs-full:SeparateMember"
)
# Consolidated statements whose cells are the entity's own figures; an equity
# statement's columns are components and notes describe parts and other entities.
_ENTITY_STATEMENTS = frozenset(
    {"balance_sheet", "income", "comprehensive_income", "cash_flow", "summary"}
)


@dataclass(frozen=True, slots=True)
class TableStatement:
    """What a filing declares about the statement one table belongs to.

    ``kind`` is the statement (``income``, ``notes``, ``summary``...) and ``scope``
    ``consolidated``, ``separate`` or ``conflicting``; either is None when nothing
    declares it.
    """

    kind: str | None
    scope: str | None


def _statement_scope(statement: TableStatement | None) -> str | None:
    """Return the scope an untagged cell of a table reads as under its declaration.

    Without a statement (a filing whose form presents one scope) a cell is the
    entity's. Under one, only a consolidated entity statement is; a separate one is
    that statement's scope and anything else (notes, equity, conflicting or no
    declaration) is unknown.
    """
    if statement is None:
        return None
    if statement.scope == "separate":
        return _SEPARATE_SCOPE
    if statement.scope == "consolidated" and statement.kind in _ENTITY_STATEMENTS:
        return None
    return UNKNOWN


def _scope(dimensions: tuple[tuple[str, str], ...]) -> str | None:
    """Name the dimensional scope of a fact, or None for the entity as a whole."""
    if not dimensions or dimensions == _ENTITY_SCOPE:
        return None
    return "; ".join(f"{axis}={member}" for axis, member in dimensions)


def _with_fact(
    reading: TableCellReading,
    fact: CellFact,
    notes: frozenset[str],
    negative: bool | None,
    declared: bool,
) -> TableCellReading:
    """Read one cell from the fact its filing tags, recording what overrides the text.

    The fact's fiscal year and scope always apply; a declared statement scope that
    the tag contradicts (a consolidated tag in a separate statement) is overridden.
    In a filing that declares its statements (``declared``), a tag with no dimension
    at all ("CFY2024dFY") states no statement scope, so the declared one stays.
    A standard concept not accepted for the row label's item ("Accounts receivable"
    tagged IncreaseDecreaseInAccountsReceivable) records ``concept`` and leaves the
    cell no item.
    An inline XBRL tag's sign is the value's sign: when it differs from the sign the
    cell's notation writes (``negative``), ``sign`` is recorded and the interpretation
    applies the tag's.
    An inline XBRL amount or per-share unit also fixes the currency (with the table's
    notes and the cell's own markers still able to contradict it) and the scale.
    Other units (shares, ratios) are not amounts, and DART facts state no unit, so
    the text keeps their unit.
    """
    overrides: list[str] = list(reading.overrides)
    if fact.sign is not None and (negative is None or (fact.sign == "-") != negative):
        overrides.append("sign")
    years = frozenset() if fact.fiscal_year is None else frozenset({fact.fiscal_year})
    if reading.years and reading.years != years:
        overrides.append("year")
    if declared and not fact.dimensions:
        scope = reading.scope
    else:
        scope = _scope(fact.dimensions)
        tagged_separate = _SEPARATE_SCOPE in (scope or "")
        if reading.scope != UNKNOWN and (reading.scope == _SEPARATE_SCOPE) != tagged_separate:
            overrides.append("scope")
    scale, percent, resolved = reading.scale, reading.percent, reading.currency
    measure = None
    currency = _ISO_CURRENCY.fullmatch(fact.numerator or "")
    if currency is not None and fact.denominator in (None, "xbrli:shares"):
        measure = "amount" if fact.denominator is None else "per_share"
        code = currency.group(1) if currency.group(1) in CODES else UNKNOWN
        scale = Decimal(10) ** (fact.scale or 0)
        if reading.scale is not None and reading.scale != scale:
            overrides.append("scale")
        # An amount tag on a figure the text writes as a percentage cannot show which.
        percent = None if reading.percent else False
        resolved = resolve(frozenset({code}) | notes)
    elif fact.numerator is not None:
        measure = "other"
        scale, resolved = None, None
    item = reading.item
    standard = _STANDARD_CONCEPT.fullmatch(fact.concept)
    if item is not None and standard is not None:
        if standard.group("name") not in ITEMS[item].concepts:
            overrides.append("concept")
            item = None
    if scope != UNKNOWN:
        overrides = [override for override in overrides if not override.startswith("scope:")]
    resolved_values = reading.values
    if fact.sign is not None and measure in {"amount", "per_share"}:
        resolved_values = frozenset(
            (-1 if fact.sign == "-" else 1) * abs(v) for v in reading.values
        )
        overrides = [override for override in overrides if override != "direction"]
    return replace(
        reading,
        values=resolved_values,
        years=years,
        item=item,
        scale=scale,
        percent=percent,
        currency=resolved,
        basis="fact",
        overrides=tuple(overrides),
        scope=scope,
        measure=measure,
    )


def _split_percent(fragment: Mapping[str, object]) -> set[tuple[int, int]]:
    """Return the figure source cells whose normalized cell carries a lone "%" cell.

    NVDA writes a margin as "72.7 | %": the percent sign stands in a source cell of
    its own beside the figure.
    """
    found: set[tuple[int, int]] = set()
    for member in _entries(fragment, "cells"):
        sources = _entries(member, "sources")
        if any(str(source.get("text", "")).strip() == "%" for source in sources):
            found.update(
                (_int(source["row"]), _int(source["column"]))
                for source in sources
                if values(str(source.get("text", "")))
            )
    return found


def _directed(reading: TableCellReading, notations: list[Decimal | None]) -> TableCellReading:
    """Give a reading's values the sign its notation or its tag establishes.

    A tag's ``sign`` override reverses the notation. Where neither establishes the
    direction (a ``▲`` figure, or an unsigned figure under a loss-only label that no
    tag signs), the values stay as written and ``direction`` is recorded.
    """
    if any(value is None for value in notations):
        return replace(reading, overrides=(*reading.overrides, "direction"))
    flip = -1 if "sign" in reading.overrides else 1
    values = frozenset(flip * value for value in notations if value is not None)
    if reading.measure is None and _loss_only(reading.row_label) and all(v > 0 for v in values):
        return replace(reading, values=values, overrides=(*reading.overrides, "direction"))
    return replace(reading, values=values)


def _negative(text: str) -> bool | None:
    """Whether a cell's one figure is written as negative; None for none, several or ▲."""
    spans = [figure for figure in figure_spans(blank(text)) if figure.value is not None]
    value = signed(spans[0]) if len(spans) == 1 else None
    return None if value is None else value < 0


def read_table_cells(
    fragment: Mapping[str, object],
    facts: Mapping[tuple[int, int], Sequence[CellFact]] | None = None,
    terms: Mapping[str, int] | None = None,
    statement: TableStatement | None = None,
) -> list[TableCellReading]:
    """Return each figure-bearing source cell of one table fragment as it is read.

    A source cell appears once per normalized cell it belongs to, as stored. ``facts``
    are the tagged facts of each source cell by grid coordinates; a cell read from
    exactly one fact showing the same number takes the fact's facts (see
    :func:`_with_fact`), any other cell keeps its text reading; one fact showing
    another number is recorded as a ``number`` override. When a tag overrides the year
    its column's header names, the column's untagged cells name no year. ``terms`` are the
    period words the table's document defines ("당기", "제56기") and their fiscal
    years; a header that is one of them dates its columns. ``statement`` is what the
    table's filing declares about its statement, when its form presents several
    entity scopes; it sets the scope of untagged cells (see :func:`_statement_scope`).
    """
    facts = facts or {}
    terms = terms or {}
    headers = _entries(fragment, "header_cells")
    caption_years = {
        int(year)
        for caption in _entries(fragment, "caption_sources")
        for year in YEAR.findall(str(caption.get("text", "")))
    }
    unit = read_table_unit(fragment)
    known = unit.status == "known"
    labels = _row_labels(fragment)
    under_part, label_columns = _row_structure(fragment)
    dated_by_caption = _caption_dates(fragment, headers, terms)
    split_percent = _split_percent(fragment)
    cells = []
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            text = str(source.get("text", ""))
            cell_values = values(text)
            if cell_values:
                spans = [f for f in figure_spans(blank(text)) if f.value is not None]
                # Digits not grouped in threes ("25,7851" with a glued footnote) state
                # no one amount, so the reading holds no value to compare.
                established = len(spans) == 1 and all(_GROUPED.fullmatch(f.text) for f in spans)
                label = labels.get(_int(source["row"]))
                per_share = label is not None and _PER_SHARE.search(label)
                scale = unit.scale if known else None
                if per_share and known:
                    # A per-share row is in plain currency only when the note says so or
                    # the whole table is; under a scaled note its unit is ambiguous.
                    plain = unit.per_share_plain or unit.scale == 1
                    scale = Decimal(1) if plain and unit.scale is not None else None
                written = {
                    figure.scale for figure in figure_spans(blank(text)) if figure.scale is not None
                }
                if written and known and unit.scale is not None:
                    # A scale word in the cell ("25.8 billion", "300조") states its unit
                    # under a table in plain currency units; beside a table scale it
                    # contradicts the table, so no unit is taken.
                    scale = next(iter(written)) if unit.scale == 1 and len(written) == 1 else None
                row, column = _int(source["row"]), _int(source["column"])
                percent: bool | None = "%" in text or (
                    known and unit.percent and unit.scale is None
                )
                if not percent and (not known or (row, column) in split_percent):
                    # Without a readable note a bare cell may or may not be a percentage,
                    # and a percent sign in a cell of its own beside the figure ("72.7 |
                    # %") does not show that the figure itself is the row's percentage.
                    percent = None
                # Only markers bound to the cell's own numbers count; other words in the
                # cell ("원가") name no denomination.
                own = frozenset(
                    marker for figure in figure_spans(blank(text)) for marker in figure.currency
                )
                over = _headers_over(source, headers)
                scope = _statement_scope(statement)
                cause: ScopeCause | None = "statement_undeclared" if scope == UNKNOWN else None
                second_label = any(col < column for col in label_columns.get(row, [])[1:])
                if scope is None and (
                    row in under_part or second_label or _header_reading(over)[1]
                ):
                    # A part's row, a row with a second label ("Revenue | Data Center")
                    # and a column whose header says more than a full fiscal year
                    # ("Adjustments", "Guidance") are not shown to be the whole
                    # entity's reported amount.
                    scope = UNKNOWN
                    cause = (
                        "part_row"
                        if row in under_part
                        else "second_label"
                        if second_label
                        else "header_unread"
                    )
                reading = TableCellReading(
                    row,
                    column,
                    frozenset(cell_values) if established else frozenset(),
                    frozenset(
                        _column_years(
                            over, caption_years if column == dated_by_caption else None, terms
                        )
                    ),
                    scale,
                    _label_item(label) if label is not None else None,
                    percent,
                    resolve(unit.currency | own),
                    bool(own),
                    label,
                    overrides=() if cause is None else ("scope:" + cause,),
                    scope=scope,
                )
                if reading.values:
                    reading = _directed(reading, [signed(figure) for figure in spans])
                tagged = facts.get((row, column), ())
                if len(tagged) == 1 and values(tagged[0].text) == cell_values:
                    reading = _with_fact(
                        reading,
                        tagged[0],
                        unit.currency | own,
                        _negative(text),
                        statement is not None,
                    )
                elif len(tagged) == 1:
                    # The tag shows another number ("25,785" tagged, "25,7851" with a
                    # glued footnote written): neither is established, so the reading
                    # holds no value and the disagreement is recorded.
                    reading = replace(reading, values=frozenset(), overrides=("number",))
                if (row, column) in split_percent and reading.percent is False:
                    # An amount tag does not settle a percent sign written beside it.
                    reading = replace(reading, percent=None)
                if written and reading.percent is False and written != {reading.scale}:
                    # A scale word the cell's unit, tagged or read, does not carry.
                    reading = replace(reading, scale=None)
                cells.append(reading)
    # A tag dating its column to another year than the header's text (a filer whose
    # "2023" ends in 2024) leaves the column's untagged cells without a year.
    multiple = {
        (_int(source["row"]), _int(source["column"]))
        for member in _entries(fragment, "cells")
        if sum(
            len([f for f in figure_spans(blank(str(src.get("text", "")))) if f.value is not None])
            for src in _entries(member, "sources")
        )
        > 1
        for source in _entries(member, "sources")
    }
    cells = [
        replace(cell, overrides=(*cell.overrides, "multiple"))
        if (cell.row, cell.column) in multiple
        else cell
        for cell in cells
    ]
    shifted = {cell.column for cell in cells if "year" in cell.overrides}
    return [
        replace(cell, years=frozenset())
        if cell.basis == "text" and cell.column in shifted
        else cell
        for cell in cells
    ]


def interpret_table_cell(text: str, readings: Sequence[TableCellReading]) -> CellInterpretation:
    """Decide whether one normalized cell is a single amount with established facts.

    ``text`` is the normalized cell text and ``readings`` its figure-bearing source
    cells. A blank or dash-only cell is ``blank``, never zero. Nothing is guessed: a
    missing scale, an ambiguous or missing currency, an unknown period or item leaves
    the cell unselectable with the first missing fact as its status. A tagged unit
    that is no amount (``not_monetary``) or a dimensional scope (``scope_qualified``)
    does too.

    A scale word written in the cell that its reading's unit does not carry (a
    billion beside a table in millions) is ``conflicting``.

    A figure whose digits are not grouped in threes, or whose one tag shows another
    number (``number``), is not one established amount: ``conflicting``.

    A value's sign comes from its notation, or from its inline XBRL tag when the tag
    overrides it (``sign``). An unsigned figure whose sign no tag states, under a
    label that names its item by a loss phrase alone ("Net loss | 1,641"), could be
    the loss or the item's amount, so it is ``conflicting``.
    """
    stripped = text.strip()
    if not stripped or not stripped.strip("-–—‐ "):
        return CellInterpretation("blank", None, None, None)
    spans = [figure for figure in figure_spans(blank(text)) if figure.value is not None]
    distinct = set(readings)
    if not spans or not distinct:
        return CellInterpretation("not_numeric", None, None, None)
    if len(spans) > 1 or len(distinct) > 1:
        return CellInterpretation("conflicting", "more than one figure", None, None)
    reading = next(iter(distinct))
    value = next(iter(reading.values)) if len(reading.values) == 1 else None
    if not _GROUPED.fullmatch(spans[0].text):
        return CellInterpretation("conflicting", "malformed digit grouping", value, reading)
    if "number" in reading.overrides:
        return CellInterpretation(
            "conflicting", "the tagged number differs from the text", value, reading
        )
    if not reading.values:
        return CellInterpretation("conflicting", "no established figure", value, reading)
    if "direction" in reading.overrides:
        return CellInterpretation(
            "conflicting", "the figure's direction is not established", value, reading
        )
    if reading.measure == "other":
        return CellInterpretation("not_monetary", "tagged unit is not an amount", value, reading)
    if spans[0].percent and reading.percent is not True:
        # A percent sign in a source cell of its own ("72.7 | %") makes the figure a
        # percentage the reading of its source cell does not carry.
        return CellInterpretation(
            "conflicting", "a percent sign outside the figure's own cell", value, reading
        )
    if spans[0].scale is not None and reading.percent is False and spans[0].scale != reading.scale:
        return CellInterpretation(
            "conflicting", "the cell's scale word disagrees with its unit", value, reading
        )
    if reading.percent is None:
        return CellInterpretation("scale_unknown", "percentage unknown", value, reading)
    if not reading.percent:
        if reading.scale is None:
            return CellInterpretation("scale_unknown", "no readable scale", value, reading)
        if reading.currency == CONFLICT:
            return CellInterpretation("conflicting", "currencies disagree", value, reading)
        if reading.currency is None or reading.currency in FAMILIES:
            return CellInterpretation(
                "currency_unconfirmed", "no explicit currency", value, reading
            )
    if (problem := reading.amount_problem) is not None:
        return CellInterpretation(problem[0], problem[1], value, reading)
    return CellInterpretation("known", None, value, reading)


def complete_cell(text: str, start: int, end: int) -> bool:
    """Whether a chunk membership carries the entire normalized cell, including labels."""
    return start == 0 and end == len(text)
