"""Check that every figure an answer states is its cited evidence's value for one item.

Citation checks prove which chunks an answer cites, not that its numbers come from
them. This module reads each figure of an answer as a claim: the figure, the unit
written with it, the financial item its own words name and, when the answer dates it,
its year. The words around a figure are read with a closed vocabulary: listed item
phrases, connectives, years, units, currency and a few verbs. Any other word leaves
the figure without an item, so wording the checker does not understand fails closed
instead of borrowing an item named elsewhere.

A claim is verified only by one cited table cell whose whole row label is the same
item, whose column period is the claim's year (or, undated, a requested one) and
whose value equals the figure once both stated units are converted. It is a period
mismatch when that item's value sits only in another known period. Change claims
("grew 14%"), percentages against absolute cells, unreadable units and ambiguous
years cannot be verified by a table. Context labels and running text cannot show a
period, so they confirm only claims for which no period is asked or stated. With no
unit on either side the comparison is between magnitudes.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

# A figure: digits with optional thousands separators and decimals, optionally signed.
# A trailing comma is punctuation, not a separator ("In 2024, revenue ...").
_NUMBER = re.compile(r"[(△▲-]?\d(?:[\d,]*\d)?(?:\.\d+)?\)?")
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

# Scale words written after a figure ("25.8 billion", "25.8bn").
_ENGLISH_SCALE = re.compile(
    r"(?:trillions?|billions?|bn|millions?|mn|thousands?)(?![A-Za-z])", re.I
)
_ENGLISH_EXPONENTS = {"trillion": 12, "billion": 9, "bn": 9, "million": 6, "mn": 6, "thousand": 3}
# One scale letter glued to a currency figure ("$25.8B"); without the currency sign
# a glued letter marks an identifier ("3M", "10K").
_SCALE_LETTER = re.compile(r"[TBMK](?![A-Za-z])")
_LETTER_EXPONENTS = {"T": 12, "B": 9, "M": 6, "K": 3}
_CURRENCY = "$€£¥₩"
_PERCENT = re.compile(r"[ \t]*(?:%|percent\b)", re.IGNORECASE)
# The only digit-bearing words left out as identifiers besides _NOT_FIGURES: one or two
# digits glued to one capital ("3M", "10K", "5G") and ordinals ("3rd").
_IDENTIFIER = re.compile(r"\d{1,2}[A-Z]|\d+(?:st|nd|rd|th)")
_LETTERS_BEFORE = re.compile(r"[A-Za-z]+$")
_LETTERS_AFTER = re.compile(r"[A-Za-z]+")
_CURRENCY_CODE = re.compile(r"USD|US|KRW|EUR|JPY|GBP|CNY")
# Korean scales compose: a 십/백/천 prefix multiplies a 만/억/조 base ("천억" = 10^3 x 10^8).
# A bare 천 ("천원", "천US$") is a thousand.
_KOREAN_SCALE = re.compile(r"([십백천]?)([만억조])|천")
_KOREAN_PREFIX = {"": 1, "십": 10, "백": 100, "천": 1000}
_KOREAN_BASE = {"만": Decimal(10) ** 4, "억": Decimal(10) ** 8, "조": Decimal(10) ** 12}
# A table's unit annotation; the scale is read from the captured unit only, so other words
# in the same caption ("조정 후, 단위 : 백만원") are not taken for a unit.
_UNIT_NOTE = re.compile(
    r"\bin\s+(thousands|millions|billions)\b|단위\s*[:：]?\s*([^,)/]*)", re.IGNORECASE
)
# Per-share rows of a "(In millions, except per share data)" table are in plain currency.
_PER_SHARE = re.compile(r"per\s+share|주당", re.IGNORECASE)
# Rounding is accepted only for figures stated with at least this many significant digits.
_MIN_ROUNDED_DIGITS = 3

# The financial items a claim may name, each by the explicit phrases accepted for it.
# A phrase names its item only as a whole: qualifiers around it ("operating revenue",
# "adjusted net income", "조정매출액") are unknown words, never stripped. Distinct items
# are never treated as equivalent.
_ITEM_PHRASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "revenue",
        "revenues",
        "net revenue",
        "net revenues",
        "total revenue",
        "total revenues",
        "total net revenue",
        "net sales",
        "sales",
        "매출액",
        "매출",
        "영업수익",
    ),
    "cost of revenue": (
        "cost of revenue",
        "cost of revenues",
        "cost of sales",
        "cost of goods sold",
        "매출원가",
    ),
    "gross profit": ("gross profit", "gross margin", "매출총이익"),
    "operating income": (
        "operating income",
        "operating profit",
        "operating loss",
        "income from operations",
        "loss from operations",
        "영업이익",
        "영업손실",
    ),
    "net income": (
        "net income",
        "net earnings",
        "net profit",
        "net loss",
        "당기순이익",
        "순이익",
        "당기순손실",
        "순손실",
    ),
    "earnings per share": ("earnings per share", "eps", "net income per share", "주당순이익"),
    "basic earnings per share": (
        "basic earnings per share",
        "basic eps",
        "basic net income per share",
        "earnings per share - basic",
        "net income per share - basic",
        "기본주당순이익",
    ),
    "diluted earnings per share": (
        "diluted earnings per share",
        "diluted eps",
        "diluted net income per share",
        "earnings per share - diluted",
        "net income per share - diluted",
        "희석주당순이익",
    ),
    "research and development": (
        "research and development",
        "research and development expense",
        "research and development expenses",
        "r&d",
        "연구개발비",
    ),
    "sales and marketing": (
        "sales and marketing",
        "sales and marketing expense",
        "sales and marketing expenses",
        "selling and marketing",
    ),
    "selling, general and administrative": (
        "selling, general and administrative",
        "selling, general and administrative expense",
        "selling, general and administrative expenses",
        "sg&a",
        "판매비와관리비",
        "판관비",
    ),
    "income tax": (
        "income tax expense",
        "income taxes",
        "provision for income taxes",
        "법인세비용",
    ),
    "accounts receivable": ("accounts receivable", "trade receivables", "매출채권"),
    "total assets": ("total assets", "자산총계"),
    "total liabilities": ("total liabilities", "부채총계"),
    "total equity": (
        "total equity",
        "total stockholders' equity",
        "total shareholders' equity",
        "자본총계",
    ),
    "cash and cash equivalents": ("cash and cash equivalents", "현금및현금성자산"),
}

# Words of an answer: English words (with "&", apostrophes and hyphens inside), Korean
# words, digit runs, and single other characters.
_TOKEN = re.compile(r"[A-Za-z]+(?:[&'’-][A-Za-z]+)*['’]?|[가-힣]+|\d+(?:[.,]\d+)*|\S")
# The only parentheticals that keep a label or answer phrase the same item.
_SAME_ITEM_QUALIFIER = re.compile(
    r"\s*[(（]\s*(?:loss|losses|손실|note\s*\d+[a-z]?|주석\s*\d+)\s*[)）]", re.IGNORECASE
)
_ENUMERATOR = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|\d+|[ivx]+|[가-하])[.)]\s*", re.IGNORECASE)
# A sentence ends at terminal punctuation followed by space, or at ";" or a line break.
_SENTENCE_BREAK = re.compile(r"(?<!\bvs)[.!?。](?=\s|$)|[;\n]")

# English words that may stand around a figure without changing which item it is.
_FILLERS = frozenset(
    {
        *("a", "an", "the", "its", "their", "was", "were", "is", "are", "be", "been"),
        *("of", "at", "in", "for", "during", "on", "by", "as", "or"),
        *("totaled", "totalled", "totaling", "reached", "amounted", "came", "stood"),
        *("reported", "recorded", "approximately", "about", "around", "roughly", "nearly"),
        *("fiscal", "year", "years", "ended", "ending", "prior", "previous", "preceding"),
        *("last", "same", "period", "usd", "us", "krw", "won", "dollar", "dollars"),
        *("percent", "million", "millions", "billion", "billions", "thousand", "thousands"),
        *("trillion", "trillions", "bn", "mn"),
        *("january", "february", "march", "april", "may", "june", "july", "august"),
        *("september", "october", "november", "december"),
        *(",", ":", "(", ")", "-", "–", "—", "·", ".", "%", "'", '"', *_CURRENCY),
    }
)
# Words after which the next words describe another figure.
_CONNECTIVES = frozenset(
    {",", "(", "and", "but", "while", "whereas", "versus", "vs", "compared", "with", "from"}
    | {"to", "than"}
)
# Words that make a figure a change, not a level ("grew 14%", "increased by 300").
_CHANGES = frozenset(
    {
        *("grew", "grow", "grows", "growth", "increased", "increase", "increases"),
        *("decreased", "decrease", "decreases", "rose", "rise", "rises", "fell", "fall"),
        *("declined", "decline", "declines", "up", "down", "higher", "lower", "gained"),
        *("dropped", "drop", "jumped"),
    }
)
# "Up from 22,680" and "increased to 25,785" state levels, not changes.
_LEVEL_AFTER_CHANGE = frozenset({"from", "to"})
_POSSESSIVE = re.compile(r"[A-Z][A-Za-z.&-]*['’]s")
# Korean particles and endings that may follow a word; "의" makes the word a modifier.
_KOREAN_ENDINGS = (
    *("으로는", "에서는", "하였다", "이었다", "였으며", "입니다", "으로", "에서", "까지"),
    *("부터", "보다", "이며", "이고", "였고", "였다", "이다", "했다", "으며"),
    *("은", "는", "이", "가", "을", "를", "의", "에", "도", "와", "과", "로", "만", "고"),
    *("며", "다"),
)
_KOREAN_JOINS = frozenset({"이며", "이고", "였고", "였으며", "으며", "고", "며"})
_KOREAN_FILLERS = frozenset({"", "연결", "기준", "약", "총", "전년", "전년도", "동기", "대비"})
_KOREAN_FILLERS |= {"기록", "수준", "규모", "각각"}
_KOREAN_UNIT = re.compile(r"(?:[십백천]?[만억조]|천)?(?:원|달러|불)?")
_KOREAN_CHANGES = ("증가", "감소", "성장", "상승", "하락", "늘어", "줄어", "증대")

type Verdict = Literal["verified", "period_mismatch", "unverified"]


def _phrase_key(text: str) -> str:
    """Normalize a phrase for lookup: casefolded, single-spaced, plain hyphens and quotes."""
    text = text.casefold().replace("–", "-").replace("—", "-").replace("’", "'")
    return " ".join(text.split())


_PHRASE_ITEMS = {
    _phrase_key(phrase): item for item, phrases in _ITEM_PHRASES.items() for phrase in phrases
}
# English phrases as word sequences, longest first; Korean phrases as whole stems.
_ENGLISH_PHRASES = sorted(
    (
        (tuple(_TOKEN.findall(phrase)), item)
        for phrase, item in _PHRASE_ITEMS.items()
        if phrase.isascii()
    ),
    key=lambda entry: len(entry[0]),
    reverse=True,
)
_KOREAN_PHRASES = {phrase: item for phrase, item in _PHRASE_ITEMS.items() if not phrase.isascii()}


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
    """The outcome for one figure stated in the answer.

    ``item`` is the financial item the answer stated the figure for, or None when its
    words name no recognized item, more than one, or words the checker cannot read.
    """

    figure: str
    verdict: Verdict
    evidenced_years: tuple[int, ...] = ()
    item: str | None = None


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


@dataclass(frozen=True, slots=True)
class _Figure:
    """One figure occurrence with its position and the unit written with it.

    ``value`` is None when a unit glued to the figure cannot be read, so the figure
    is kept (and fails) instead of silently dropping out of the check. ``unit_end``
    is where the figure's unit and percent sign end.
    """

    text: str
    start: int
    end: int
    unit_end: int
    value: Decimal | None
    decimals: int
    scale: Decimal | None
    percent: bool


@dataclass(frozen=True, slots=True)
class _Word:
    """One classified word around a figure.

    ``kind`` is ``item`` (with ``item`` set), ``filler``, ``change`` or ``unknown``.
    ``joins`` marks a connective: what follows it describes the next figure.
    """

    start: int
    text: str
    kind: Literal["item", "filler", "change", "unknown"]
    item: str | None = None
    joins: bool = False


@dataclass(frozen=True, slots=True)
class _Claim:
    """One figure with the item, year and kind its own words give it.

    ``year`` is None when the claim is undated; ``dated_ambiguously`` when its words
    name more than one year. ``change`` marks a change claim ("grew 14%").
    """

    figure: _Figure
    item: str | None
    year: int | None
    dated_ambiguously: bool
    change: bool


@dataclass(frozen=True, slots=True)
class _Cell:
    """One table data cell: its figures, column years, table scale and row item."""

    values: frozenset[Decimal]
    years: frozenset[int]
    scale: Decimal | None
    item: str | None
    percent: bool


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


def _blank(text: str) -> str:
    """Blank identifiers and dates out of a text while keeping every position."""
    return _NOT_FIGURES.sub(lambda match: " " * len(match.group(0)), text)


def _korean_factor(match: re.Match[str]) -> Decimal:
    """Return the factor of one Korean scale match ("백만" = 10^6, bare "천" = 10^3)."""
    prefix, base = match.groups()
    if base is None:
        return Decimal(1000)
    return _KOREAN_PREFIX[prefix or ""] * _KOREAN_BASE[base]


def _english_factor(word: str) -> Decimal:
    """Return the factor of one English scale word."""
    return Decimal(10) ** _ENGLISH_EXPONENTS[word.casefold().removesuffix("s")]


def _unit_after(
    text: str, start: int, end: int, currency: bool
) -> tuple[Decimal | None, bool, int]:
    """Return the scale written right after a figure, whether it is readable, and its end.

    A glued scale word ("25.8bn") or, after a currency sign, one glued scale letter
    ("$25.8B") is read; any other glued ASCII letter is unreadable. Otherwise the scale
    is the English or Korean scale word starting right after the figure, if any.
    """
    if end < len(text) and text[end].isascii() and text[end].isalpha():
        if word := _ENGLISH_SCALE.match(text, end):
            return _english_factor(word.group(0)), True, word.end()
        if currency and (letter := _SCALE_LETTER.match(text, end)):
            return Decimal(10) ** _LETTER_EXPONENTS[letter.group(0)], True, letter.end()
        return None, False, end
    gap = end + len(text[end:]) - len(text[end:].lstrip(" \t"))
    if word := _ENGLISH_SCALE.match(text, gap):
        return _english_factor(word.group(0)), True, word.end()
    if korean := _KOREAN_SCALE.match(text, gap):
        return _korean_factor(korean), True, korean.end()
    return None, True, end


def _figure_spans(blanked: str) -> list[_Figure]:
    """Return each figure of an identifier-free text with its own position and unit.

    Only the explicitly recognized identifier shapes are left out: the blanked FY/Q/H,
    date and Item references, one or two digits glued to one capital ("3M", "10K",
    "5G") and ordinals ("3rd"). Any other digits touching letters stay a figure: a
    currency code prefix ("USD") is read as currency, while other glued letters
    ("99999xyz", "25785M", "v2") make the figure unreadable, so it fails instead of
    dropping out. A bare four-digit year is a date unless a currency, a scale, a percent
    sign or unreadable letters make it an amount ("$2024mn").
    """
    found = []
    for match in _NUMBER.finditer(blanked):
        token = match.group(0)
        start, end = match.span()
        prefix = _LETTERS_BEFORE.search(blanked, 0, start)
        suffix = _LETTERS_AFTER.match(blanked, end)
        before = blanked[:start].rstrip()
        code = prefix is not None and _CURRENCY_CODE.fullmatch(prefix.group(0)) is not None
        currency = code or (bool(before) and before[-1] in _CURRENCY)
        glued = token + (suffix.group(0) if suffix else "")
        if prefix is None and not currency and _IDENTIFIER.fullmatch(glued):
            continue
        scale, readable, unit_end = _unit_after(blanked, start, end, currency)
        readable = readable and (prefix is None or code)
        sign = _PERCENT.match(blanked, unit_end) if readable else None
        percent = sign is not None
        if sign is not None:
            unit_end = sign.end()
        amount = currency or scale is not None or percent or not readable
        if _BARE_YEAR.fullmatch(token.strip("()△▲-")) and not amount:
            continue
        digits = token.rstrip(")")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value = _value(token) if readable else None
        found.append(_Figure(token, start, end, unit_end, value, decimals, scale, percent))
    return found


def figures(text: str) -> tuple[str, ...]:
    """Return the figures a text states, without identifiers, dates or bare years."""
    return tuple(figure.text for figure in _figure_spans(_blank(text)))


def _values(text: str) -> set[Decimal]:
    """Return the magnitudes of every readable figure a text states."""
    return {figure.value for figure in _figure_spans(_blank(text)) if figure.value is not None}


def _korean_word(start: int, text: str) -> _Word:
    """Classify one Korean word, reading at most one particle or ending off its end.

    An item word followed by "의" modifies another noun ("매출액의 14%"), so it is
    unknown rather than the item.
    """
    if text.startswith(_KOREAN_CHANGES):
        return _Word(start, text, "change")
    for ending in ("", *_KOREAN_ENDINGS):
        if ending and not text.endswith(ending):
            continue
        stem = text[: len(text) - len(ending)]
        joins = ending in _KOREAN_JOINS
        if stem in _KOREAN_PHRASES:
            if ending == "의":
                return _Word(start, text, "unknown")
            return _Word(start, text, "item", _KOREAN_PHRASES[stem], joins)
        if stem in _KOREAN_FILLERS or _KOREAN_UNIT.fullmatch(stem):
            return _Word(start, text, "filler", joins=joins)
    return _Word(start, text, "unknown")


def _english_word(start: int, text: str) -> _Word:
    """Classify one English word, digit run or symbol outside any item phrase."""
    key = text.casefold().replace("’", "'")
    if key in _CHANGES:
        return _Word(start, text, "change", joins=key in {"up", "down"})
    if key in _CONNECTIVES:
        return _Word(start, text, "filler", joins=True)
    if key in _FILLERS or _POSSESSIVE.fullmatch(text) or _BARE_YEAR.fullmatch(text):
        return _Word(start, text, "filler")
    return _Word(start, text, "unknown")


def _words(masked: str, start: int, end: int) -> list[_Word]:
    """Classify the words of ``masked[start:end]``, joining item phrases into one word."""
    tokens = [
        (start + match.start(), match.group(0)) for match in _TOKEN.finditer(masked[start:end])
    ]
    words: list[_Word] = []
    index = 0
    while index < len(tokens):
        at, text = tokens[index]
        keys = tuple(_phrase_key(token) for _, token in tokens[index:])
        phrase = next(
            (
                (len(phrase_words), item)
                for phrase_words, item in _ENGLISH_PHRASES
                if keys[: len(phrase_words)] == phrase_words
            ),
            None,
        )
        if phrase is not None:
            words.append(_Word(at, text, "item", phrase[1]))
            index += phrase[0]
            continue
        is_korean = "가" <= text[0] <= "힣"
        words.append(_korean_word(at, text) if is_korean else _english_word(at, text))
        index += 1
    return words


def _split(words: Sequence[_Word]) -> int:
    """Return where the words between two figures stop describing the first one.

    That is the first connective or change word (after a Korean joining ending, the
    word after it), else the first item phrase, else the end.
    """
    for index, word in enumerate(words):
        if word.kind == "change" or (word.joins and not "가" <= word.text[0] <= "힣"):
            return index
        if word.joins:
            return index + 1
    return next((index for index, word in enumerate(words) if word.kind == "item"), len(words))


def _is_change(head: Sequence[_Word], tail: Sequence[_Word]) -> bool:
    """Whether the words around a figure make it a change rather than a level."""
    if any(word.kind == "change" for word in tail):
        return True
    changes = [index for index, word in enumerate(head) if word.kind == "change"]
    if not changes:
        return False
    after = head[changes[-1] + 1 :]
    return not any(word.text.casefold() in _LEVEL_AFTER_CHANGE for word in after)


def _sentence_claims(masked: str, text: str, start: int, end: int) -> list[_Claim]:
    """Read the claims of one sentence ``[start, end)``.

    The words before the first figure, between figures and after the last one are
    split into each figure's head (before it) and tail (after it). A figure's item is
    the only item phrase of its head; with no item phrase there, a figure continues the
    item of the figure before it in the same sentence. An unknown word in its head or
    tail, an item phrase in its tail, or two items in its head leave it without one.
    """
    found = [figure for figure in _figure_spans(masked[:end]) if figure.start >= start]
    if not found:
        return []
    years = [
        (match.start(), int(match.group(0)))
        for match in _YEAR.finditer(text, start, end)
        if not any(figure.start <= match.start() < figure.unit_end for figure in found)
    ]
    heads: list[tuple[int, list[_Word]]] = []
    tails: list[tuple[int, list[_Word]]] = []
    head_start = start
    for index, figure in enumerate(found):
        heads.append((head_start, _words(masked, head_start, figure.start)))
        stop = found[index + 1].start if index + 1 < len(found) else end
        between = _words(masked, figure.unit_end, stop)
        cut = _split(between) if index + 1 < len(found) else len(between)
        head_start = between[cut].start if cut < len(between) else stop
        tails.append((head_start, between[:cut]))

    first_item = next((word.start for word in heads[0][1] if word.kind == "item"), found[0].start)
    sentence_years = {year for at, year in years if start <= at < first_item}
    claims: list[_Claim] = []
    for index, figure in enumerate(found):
        head_at, head = heads[index]
        tail_end, tail = tails[index]
        items = {word.item for word in head if word.kind == "item"}
        unreadable = any(word.kind == "unknown" for word in (*head, *tail)) or any(
            word.kind == "item" for word in tail
        )
        item: str | None
        if unreadable or len(items) > 1:
            item = None
        elif items:
            item = items.pop()
        else:
            item = claims[-1].item if claims else None
        own = {
            year
            for at, year in years
            if (head_at <= at < figure.start or figure.unit_end <= at < tail_end)
            and not (index == 0 and at < first_item)
        }
        dated = own or sentence_years
        claims.append(
            _Claim(
                figure,
                item,
                next(iter(dated)) if len(dated) == 1 else None,
                len(dated) > 1,
                _is_change(head, tail),
            )
        )
    return claims


def _claims(text: str) -> list[_Claim]:
    """Read every figure of a text as a claim, sentence by sentence."""
    masked = _blank(_SAME_ITEM_QUALIFIER.sub(lambda match: " " * len(match.group(0)), text))
    bounds = [0, *(match.start() for match in _SENTENCE_BREAK.finditer(masked)), len(masked)]
    return [
        claim
        for first, last in zip(bounds, bounds[1:], strict=False)
        for claim in _sentence_claims(masked, text, first, last)
    ]


def _scale_in(text: str) -> Decimal | None:
    """Return the first scale a unit annotation names, or None."""
    found = [
        (match.start(), _english_factor(match.group(0)))
        for match in re.finditer(r"trillions?|billions?|millions?|thousands?", text, re.I)
    ]
    if korean := _KOREAN_SCALE.search(text):
        found.append((korean.start(), _korean_factor(korean)))
    return min(found, key=lambda match: match[0])[1] if found else None


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


def _table_scale(fragment: Mapping[str, object]) -> Decimal | None:
    """Read the scale of an explicit unit note in header cells or captions; None if absent."""
    for entry in _entries(fragment, "header_cells") + _entries(fragment, "caption_sources"):
        if note := _UNIT_NOTE.search(str(entry.get("text", ""))):
            return _scale_in(note.group(1) or note.group(2) or "") or Decimal(1)
    return None


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


def _row_labels(fragment: Mapping[str, object]) -> dict[int, str]:
    """Return the leftmost non-numeric cell text of each source row (its row label)."""
    labels: dict[int, tuple[int, str]] = {}
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            text = str(source.get("text", "")).strip()
            if text and not _values(text):
                row, column = _int(source["row"]), _int(source["column"])
                if row not in labels or column < labels[row][0]:
                    labels[row] = (column, text)
    return {row: text for row, (_, text) in labels.items()}


def _label_item(label: str) -> str | None:
    """Return the item a row label names when the whole label is one accepted phrase.

    Enumerators ("Ⅰ.") and the parentheticals that keep the same item ("Net income
    (loss)", note references) are set aside. Any other parenthetical qualifies the
    row ("Net income (attributable to noncontrolling interests)"), so the label names
    no item. Korean labels are compared without spaces.
    """
    text = _SAME_ITEM_QUALIFIER.sub("", _ENUMERATOR.sub("", label))
    if re.search(r"[()（）]", text):
        return None
    key = _phrase_key(text).rstrip(":").strip()
    if not key.isascii():
        key = key.replace(" ", "")
    return _PHRASE_ITEMS.get(key)


def _table_cells(fragment: Mapping[str, object]) -> list[_Cell]:
    """Return each data cell of one stored fragment with its years, scale and item."""
    headers = _entries(fragment, "header_cells")
    caption_years = {
        int(year)
        for caption in _entries(fragment, "caption_sources")
        for year in _YEAR.findall(str(caption.get("text", "")))
    }
    scale = _table_scale(fragment)
    labels = _row_labels(fragment)
    cells = []
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            text = str(source.get("text", ""))
            values = _values(text)
            if values:
                label = labels.get(_int(source["row"]))
                per_share = scale is not None and label is not None and _PER_SHARE.search(label)
                cells.append(
                    _Cell(
                        frozenset(values),
                        frozenset(_column_years(source, headers, caption_years)),
                        Decimal(1) if per_share else scale,
                        _label_item(label) if label is not None else None,
                        "%" in text,
                    )
                )
    return cells


def _same_amount(figure: _Figure, value: Decimal, cell: Decimal, table: Decimal | None) -> bool:
    """Compare magnitudes, converting units when both sides state one.

    A converted figure may be rounded to its own last digit, but only when it keeps at
    least three significant digits: "$25.8 billion" passes for 25,785 million, while
    "$26 billion" must match exactly.
    """
    scale = figure.scale
    if scale is None or table is None:
        return value == cell
    if value * scale == cell * table:
        return True
    if len(value.as_tuple().digits) < _MIN_ROUNDED_DIGITS:
        return False
    tolerance = Decimal(5) * Decimal(10) ** (-figure.decimals - 1) * scale
    return abs(value * scale - cell * table) <= tolerance


def _judge(
    claim: _Claim, cells: Sequence[_Cell], facts: Sequence[_Claim], requested: set[int]
) -> tuple[FigureCheck, bool]:
    """Judge one claim; the flag marks a verified claim dated outside the requested years.

    Only a table cell holding the claim's item, value and period confirms a level. A
    change claim, or any claim when a period is asked or stated, gets no help from
    labels or running text, which cannot show a period; otherwise a fact of the same
    item, kind and value confirms it.
    """
    figure, item = claim.figure, claim.item
    if figure.value is None or item is None or claim.dated_ambiguously:
        return FigureCheck(figure.text, "unverified", (), item), False
    value = figure.value
    wanted = {claim.year} if claim.year is not None else requested
    matched = [
        cell.years
        for cell in cells
        if not claim.change
        and cell.item == item
        and cell.percent == figure.percent
        and any(_same_amount(figure, value, v, cell.scale) for v in cell.values)
    ]
    if matched:
        evidenced = tuple(sorted(frozenset[int]().union(*matched)))
        if not wanted or any(years & wanted for years in matched):
            outside = bool(requested) and claim.year is not None and claim.year not in requested
            return FigureCheck(figure.text, "verified", evidenced, item), outside
        if all(matched):
            return FigureCheck(figure.text, "period_mismatch", evidenced, item), False
        return FigureCheck(figure.text, "unverified", evidenced, item), False
    confirmed = not wanted and any(
        fact.item == item
        and not fact.dated_ambiguously
        and fact.change == claim.change
        and fact.figure.percent == figure.percent
        and fact.figure.value is not None
        and _same_amount(figure, value, fact.figure.value, fact.figure.scale)
        for fact in facts
    )
    return FigureCheck(figure.text, "verified" if confirmed else "unverified", (), item), False


def check_figures(
    answer: str, evidence: Sequence[EvidenceText], requested_years: Sequence[int]
) -> FiguresResult:
    """Check every figure of ``answer`` against the cited evidence and requested periods.

    Every occurrence is judged on its own words and reported as its own check. A
    figure the answer itself dates outside the requested years is verified only as
    context beside a figure confirmed for a requested year; alone it is reported as a
    period mismatch.
    """
    requested = set(requested_years)
    cells = [
        cell
        for item in evidence
        if item.table_fragment is not None
        for cell in _table_cells(item.table_fragment)
    ]
    data_values = {value for cell in cells for value in cell.values}
    facts = [
        claim
        for item in evidence
        for claim in _claims(item.context_header)
        + (
            [fact for fact in _claims(item.body) if fact.figure.value not in data_values]
            if item.table_fragment is not None
            else _claims(item.body)
        )
    ]
    judged = [_judge(claim, cells, facts, requested) for claim in _claims(answer)]
    anchored = any(check.verdict == "verified" and not outside for check, outside in judged)
    return FiguresResult(
        tuple(
            replace(check, verdict="period_mismatch") if outside and not anchored else check
            for check, outside in judged
        )
    )
