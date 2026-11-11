"""Find the figures a text states, each with the unit and currency written with it.

Identifiers and calendar dates carry digits but state no figure. Note references
("Note 5", "(주29)") are identifiers, not figures.
"""

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import re

from app.figures.currency import (
    BOUNDED_CURRENCY,
    CODES,
    CURRENCY,
    CURRENCY_AFTER,
    CURRENCY_BEFORE,
    KOREAN_CURRENCY,
    UNKNOWN,
    UNKNOWN_AFTER,
    UNKNOWN_BEFORE,
    currency_of,
    resolve,
)
from app.figures.vocabulary import CHANGES, CONNECTIVES, FILLERS, ITEM_WORDS

# A figure: digits with optional thousands separators and decimals, optionally signed.
# A trailing comma is punctuation, not a separator ("In 2024, revenue ...").
_NUMBER = re.compile(r"[(△▲-]?\d(?:[\d,]*\d)?(?:\.\d+)?\)?")
# Identifiers and calendar dates carry digits but state no figure.
_PERIODS_AND_CODES = (
    r"\b(?:FY\s?['’]?\s?|fiscal\s+(?:year\s+)?|[QH]\s?)\d+|\b\d+[QH]\b|\d+-[A-Z]\b|"
)
_REFERENCE_WORD = r"\b(?:Item|Note|Part|Exhibit|Section)s?\s+"
_REFERENCE = _REFERENCE_WORD + r"\d+[A-Z]?(?:\.\d+)*"
_REFERENCE_LIST = r"(?:\s*(?:,|and|&)\s*\d+[A-Z]?(?:\.\d+)*)*"
# A Korean note reference: "(주29)", "(주 5, 30)", "(주석 12)".
_KOREAN_NOTE_WORD = r"[(（]\s*주석?\s*"
_KOREAN_NOTE = _KOREAN_NOTE_WORD + r"\d+[A-Za-z]?"
_KOREAN_NOTE_LIST = r"(?:\s*[,，、~-]\s*\d+[A-Za-z]?)*"
_KOREAN_NOTE_END = r"\s*[)）]|"
_MONTH_AND_DAY = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+"
_DATES = (
    _MONTH_AND_DAY + r"\d{4}|"
    r"\d{4}\s?[./-]\s?\d{1,2}\s?[./-]\s?\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|"
    r"\d{4}\s?년(?:\s?\d{1,2}\s?월)?(?:\s?\d{1,2}\s?일)?|\d{1,2}\s?월\s?\d{1,2}\s?일|"
    r"\d\s?분기|제\s?\d+\s?기"
)
# A label may cite a list of notes ("Notes 2 and 3", "(주 5, 30)"): every number of the
# list is an identifier.
_NOT_FIGURES = re.compile(
    _PERIODS_AND_CODES
    + _REFERENCE
    + _REFERENCE_LIST
    + "|"
    + _KOREAN_NOTE
    + _KOREAN_NOTE_LIST
    + _KOREAN_NOTE_END
    + _DATES,
    re.IGNORECASE,
)
BARE_YEAR = re.compile(r"(?:19|20)\d{2}")
YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

# Scale words written after a figure ("25.8 billion", "25.8bn").
_ENGLISH_SCALE = re.compile(
    r"(?:trillions?|billions?|bn|millions?|mn|thousands?)(?![A-Za-z])", re.I
)
_ENGLISH_EXPONENTS = {"trillion": 12, "billion": 9, "bn": 9, "million": 6, "mn": 6, "thousand": 3}
# One scale letter glued to a currency figure ("$25.8B"); without the currency sign
# a glued letter marks an identifier ("3M", "10K").
_SCALE_LETTER = re.compile(r"[TBMK](?![A-Za-z])")
_LETTER_EXPONENTS = {"T": 12, "B": 9, "M": 6, "K": 3}


_PERCENT = re.compile(r"[ \t]*(?:%|percent\b)", re.IGNORECASE)

# An answer is checked figure by figure, so its identifiers have bounded shapes: a
# reference is followed by exactly its own short number, a period by its own one to four
# digits and a date by a calendar year. No identifier number is part of a longer number
# ("FY 99,999", "25,785.5H") or carries a unit ("Note 500 million", "(주석 300)억원"):
# a number with a percent sign, a scale word or a currency after it is an amount. So an
# amount written where an identifier number would stand stays a figure. A Korean scale
# or currency word may begin an ordinary word ("FY2024 조정", "Q4 원가"), so a Korean
# unit is a scale word with a currency after it or at the end of its word. A currency
# with a number after it belongs to that number ("(Note 5) $25,785 million"), not to
# the identifier before it.
_NEXT_NUMBER = r"[ \t]*[(△▲-]?\d"
_UNIT_FOLLOWS = "|".join(
    (
        _PERCENT.pattern,
        r"[ \t]*" + _ENGLISH_SCALE.pattern,
        r"[ \t]*(?:[십백천]?[만억조]|천)(?:[ \t]*(?:" + KOREAN_CURRENCY + r")|(?![가-힣]))",
        r"[ \t]*(?:" + BOUNDED_CURRENCY + ")(?!" + _NEXT_NUMBER + ")",
        UNKNOWN_AFTER.pattern + "(?!" + _NEXT_NUMBER + ")",
    )
)
_UNIT_AT = re.compile(_UNIT_FOLLOWS, re.IGNORECASE)
_NO_UNIT = r"(?![ \t]*[)）]?(?:" + _UNIT_FOLLOWS + "))"
_OWN_START = r"(?<![\d,.])"
_OWN_END = r"(?!\d|[,.]\d)" + _NO_UNIT
# A reference number may end in one letter ("Item 7A", "Item 9B"). After two or three
# digits a scale letter is not such a suffix, so "Note 26B" and "Note 500M" stay figures.
_REFERENCE_NUMBER = r"(?:\d{2,3}[AC-JLN-SU-Z]?|\d[A-Z]?)(?![A-Za-z])(?:\.\d{1,3})*"
_CALENDAR_YEAR = r"(?:19|20)\d{2}" + _OWN_END
_ANSWER_NOT_FIGURES = re.compile(
    "|".join(
        (
            r"\b(?:(?:FY\s?['’]?\s?|fiscal\s+(?:year\s+)?)(?:\d{4}|\d{2})|[QH]\s?\d)" + _OWN_END,
            _OWN_START + r"\d[QH]\b" + _NO_UNIT,
            _OWN_START + r"\d{1,2}-[A-Z]\b" + _NO_UNIT,
            _REFERENCE_WORD + _REFERENCE_NUMBER + _OWN_END,
            _KOREAN_NOTE_WORD + r"\d{1,3}[A-Za-z]?" + _OWN_END + r"\s*[)）]",
            _MONTH_AND_DAY + _CALENDAR_YEAR,
            _OWN_START + r"(?:19|20)\d{2}\s?[./-]\s?\d{1,2}\s?[./-]\s?\d{1,2}" + _OWN_END,
            _OWN_START + r"\d{1,2}/\d{1,2}/" + _CALENDAR_YEAR,
            _OWN_START + r"(?:19|20)\d{2}\s?년(?:\s?\d{1,2}\s?월)?(?:\s?\d{1,2}\s?일)?",
            _OWN_START + r"\d{1,2}\s?월\s?\d{1,2}\s?일",
            _OWN_START + r"\d\s?분기",
            r"제\s?\d{1,3}\s?기",
        )
    ),
    re.IGNORECASE,
)


# Any other three-letter token written right against an amount has the shape of an ISO
# currency code ("BHD 2024", "25 omr"). Unless it is one of the ordinary words below, it
# marks the amount's currency unknown, so an unlisted currency is withheld, not dropped.
_CODE_SHAPED_BEFORE = re.compile(r"(?<![A-Za-z])([A-Za-z]{3})[ \t]*$")
_CODE_SHAPED_AFTER = re.compile(r"[ \t]*([A-Za-z]{3})(?![A-Za-z])")
_ORDINARY_SHORT_WORDS = frozenset(
    {
        *("the", "and", "for", "was", "are", "has", "had", "its", "our", "per", "net"),
        *("not", "but", "nor", "yet", "all", "any", "one", "two", "six", "ten", "new"),
        *("old", "due", "via", "off", "out", "own", "top", "low", "key", "end", "ago"),
        *("few", "who", "how", "may", "can", "did", "got", "set", "sum", "ytd", "yoy"),
        *("qoq", "est", "avg", "eps", "his", "her", "now", "use", "see"),
        *("jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
    }
)


# The only digit-bearing words left out as identifiers besides _NOT_FIGURES: one or two
# digits glued to one capital ("3M", "10K", "5G") and ordinals ("3rd").
_IDENTIFIER = re.compile(r"\d{1,2}[A-Z]|\d+(?:st|nd|rd|th)")
# In an answer a scale letter glued to a number may state an amount ("26B"), so only the
# other capitals ("5G"), the SEC form names written without a hyphen and short ordinals
# are identifiers.
_ANSWER_IDENTIFIER = re.compile(r"\d{1,2}[AC-JLN-SU-Z]|10[KQ]|[68]K|[24]0F|\d{1,3}(?:st|nd|rd|th)")
_LETTERS_BEFORE = re.compile(r"[A-Za-z]+$")
_LETTERS_AFTER = re.compile(r"[A-Za-z]+")
_CURRENCY_CODE = re.compile(
    r"USD|US|KRW|EUR|JPY|GBP|CNY|CAD|AUD|HKD|TWD|SGD|CHF|RMB", re.IGNORECASE
)
# Korean scales compose: a 십/백/천 prefix multiplies a 만/억/조 base ("천억" = 10^3 x 10^8).
# A bare 천 ("천원", "천US$") is a thousand.
KOREAN_SCALE = re.compile(r"([십백천]?)([만억조])|천")
_KOREAN_PREFIX = {"": 1, "십": 10, "백": 100, "천": 1000}
_KOREAN_BASE = {"만": Decimal(10) ** 4, "억": Decimal(10) ** 8, "조": Decimal(10) ** 12}


@dataclass(frozen=True, slots=True)
class Figure:
    """One figure occurrence with its position and the unit written with it.

    ``value`` is None when a unit glued to the figure cannot be read, so the figure
    is kept (and fails) instead of silently dropping out of the check. ``unit_end``
    is where the figure's unit, currency and percent sign end, and ``unit_start`` where
    a currency written before it begins. ``currency`` holds the currency markers
    written with the figure ("$", "USD", "원"); with no scale word they state plain
    currency units ("$1.00", "300원").
    """

    text: str
    start: int
    end: int
    unit_end: int
    value: Decimal | None
    decimals: int
    scale: Decimal | None
    percent: bool
    currency: frozenset[str] = frozenset()
    unit_start: int = -1

    @property
    def stated_scale(self) -> Decimal | None:
        """Return the unit the figure states: its scale, plain currency, or None."""
        if self.scale is not None:
            return self.scale
        return Decimal(1) if self.currency else None

    @property
    def stated_currency(self) -> str | None:
        """Return the currency the figure's own markers resolve to (see ``resolve``)."""
        return resolve(self.currency)


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


def blank(text: str) -> str:
    """Blank identifiers and dates out of a label or cell text while keeping every position."""
    return _NOT_FIGURES.sub(lambda match: " " * len(match.group(0)), text)


def blank_answer(text: str) -> str:
    """Blank an answer's identifiers and dates, each of a bounded shape with its own number."""
    return _ANSWER_NOT_FIGURES.sub(lambda match: " " * len(match.group(0)), text)


def unit_follows(text: str, position: int) -> bool:
    """Whether a scale word, a currency or a percent sign is written from ``position``."""
    return _UNIT_AT.match(text, position) is not None


def _markers_before(text: str, start: int) -> tuple[set[str], int]:
    """Read the whole run of currency markers written right before a figure.

    Returns the markers and where the run begins. A supported "$" form with a letter
    glued in front ("NZ$", "ZZ$") and any unsupported sign or code is ``UNKNOWN``.
    """
    markers: set[str] = set()
    position = start
    while True:
        if known := CURRENCY_BEFORE.search(text, 0, position):
            written = known.group(0).strip()
            qualified = known.start() > 0 and text[known.start() - 1].isalpha()
            currency = currency_of(written)
            markers.add(UNKNOWN if currency is None or ("$" in written and qualified) else currency)
            position = known.start()
        elif unknown := UNKNOWN_BEFORE.search(text, 0, position):
            markers.add(UNKNOWN)
            position = unknown.start()
        elif (shaped := _CODE_SHAPED_BEFORE.search(text, 0, position)) and _code_shaped(
            shaped.group(1)
        ):
            markers.add(UNKNOWN)
            position = shaped.start()
        else:
            return markers, position


def _markers_after(text: str, end: int) -> tuple[set[str], int]:
    """Read the whole run of currency markers written right after a figure and its unit."""
    markers: set[str] = set()
    position = end
    while True:
        if known := CURRENCY_AFTER.match(text, position):
            markers.add(currency_of(known.group(0)) or UNKNOWN)
            position = known.end()
        elif unknown := UNKNOWN_AFTER.match(text, position):
            markers.add(UNKNOWN)
            position = unknown.end()
        elif (shaped := _CODE_SHAPED_AFTER.match(text, position)) and _code_shaped(shaped.group(1)):
            markers.add(UNKNOWN)
            position = shaped.end()
        else:
            return markers, position


def _code_shaped(word: str) -> bool:
    """Whether a three-letter word beside an amount may be a currency code.

    Ordinary words that stand beside figures (fillers, connectives, change words, item
    words, scale words, month abbreviations and a few other short words) are not; any
    other three-letter word is treated as an unsupported currency, never ignored.
    """
    key = word.casefold()
    ordinary = FILLERS | CONNECTIVES | CHANGES | _ORDINARY_SHORT_WORDS | ITEM_WORDS
    return key not in ordinary and currency_of(word) is None


def korean_factor(match: re.Match[str]) -> Decimal:
    """Return the factor of one Korean scale match ("백만" = 10^6, bare "천" = 10^3)."""
    prefix, base = match.groups()
    if base is None:
        return Decimal(1000)
    return _KOREAN_PREFIX[prefix or ""] * _KOREAN_BASE[base]


def english_factor(word: str) -> Decimal:
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
            return english_factor(word.group(0)), True, word.end()
        if currency and (letter := _SCALE_LETTER.match(text, end)):
            return Decimal(10) ** _LETTER_EXPONENTS[letter.group(0)], True, letter.end()
        code = CURRENCY_AFTER.match(text, end)
        if code is not None and currency_of(code.group(0)) in CODES:
            # A glued ISO code ("25,785USD") is a currency, read after the figure.
            return None, True, end
        return None, False, end
    gap = end + len(text[end:]) - len(text[end:].lstrip(" \t"))
    if word := _ENGLISH_SCALE.match(text, gap):
        return english_factor(word.group(0)), True, word.end()
    if korean := KOREAN_SCALE.match(text, gap):
        return korean_factor(korean), True, korean.end()
    return None, True, end


def figure_spans(blanked: str, *, answer: bool = False) -> list[Figure]:
    """Return each figure of an identifier-free text with its own position and unit.

    ``answer`` reads the text as a model's answer rather than a filing's own label, cell
    or passage: only the bounded identifier shapes of an answer are left out, so a
    scale letter glued to a number with no currency sign ("26B") is an unreadable figure
    that fails, like "25785M", instead of an identifier that drops out.

    Only the explicitly recognized identifier shapes are left out: the blanked FY/Q/H,
    date and Item references, one or two digits glued to one capital ("3M", "10K",
    "5G") and ordinals ("3rd"). Any other digits touching letters stay a figure: a
    currency code prefix ("USD") is read as currency, while other glued letters
    ("99999xyz", "25785M", "v2") make the figure unreadable, so it fails instead of
    dropping out. A bare four-digit year is a date unless a currency, a scale, a percent
    sign or unreadable letters make it an amount ("$2024mn", "USD 2024", "2024원",
    "₹2024"): currency markers, supported or not, are read before that decision.

    Every currency marker written with a figure, the whole run before it and after it,
    is kept, so disagreeing markers ("USD EUR 25") resolve as a conflict. A marker run
    that touches two figures could belong to either, so both are marked unknown.
    """
    identifier = _ANSWER_IDENTIFIER if answer else _IDENTIFIER
    found: list[Figure] = []
    for match in _NUMBER.finditer(blanked):
        token = match.group(0)
        start, end = match.span()
        prefix = _LETTERS_BEFORE.search(blanked, 0, start)
        suffix = _LETTERS_AFTER.match(blanked, end)
        before = blanked[:start].rstrip()
        code = prefix is not None and _CURRENCY_CODE.fullmatch(prefix.group(0)) is not None
        markers, unit_start = _markers_before(blanked, start)
        currency = code or bool(markers) or (bool(before) and before[-1] in CURRENCY)
        glued = token + (suffix.group(0) if suffix else "")
        if prefix is None and not currency and identifier.fullmatch(glued):
            # In an answer an identifier with a unit after it is an amount ("5Q million").
            if not (answer and unit_follows(blanked, suffix.end() if suffix else end)):
                continue
        scale, readable, unit_end = _unit_after(blanked, start, end, currency)
        readable = readable and (prefix is None or code)
        sign = _PERCENT.match(blanked, unit_end) if readable else None
        percent = sign is not None
        if sign is not None:
            unit_end = sign.end()
        after, unit_end = _markers_after(blanked, unit_end)
        markers |= after
        amount = currency or bool(markers) or scale is not None or percent or not readable
        if BARE_YEAR.fullmatch(token.strip("()△▲-")) and not amount:
            continue
        digits = token.rstrip(")")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value = _value(token) if readable else None
        if found and found[-1].unit_end > unit_start:
            # One marker run between two figures: neither can claim it alone.
            markers.add(UNKNOWN)
            found[-1] = replace(found[-1], currency=found[-1].currency | {UNKNOWN})
        found.append(
            Figure(
                token,
                start,
                end,
                unit_end,
                value,
                decimals,
                scale,
                percent,
                frozenset(markers),
                unit_start,
            )
        )
    return found


def figures(text: str) -> tuple[str, ...]:
    """Return the figures a text states, without identifiers, dates or bare years."""
    return tuple(figure.text for figure in figure_spans(blank(text)))


def values(text: str) -> set[Decimal]:
    """Return the magnitudes of every readable figure a text states."""
    return {figure.value for figure in figure_spans(blank(text)) if figure.value is not None}


def signed(figure: Figure) -> Decimal | None:
    """Return a figure's value with the sign its notation writes; None for ``▲``.

    ``(1,234)``, ``△1,234`` and ``-1,234`` are losses. ``▲`` marks a loss in some
    Korean filings and an increase in others, so its sign is not guessed.
    """
    if figure.value is None or figure.text.startswith("▲"):
        return None
    negative = figure.text.startswith(("(", "△", "-"))
    return -figure.value if negative else figure.value
