"""Check that every figure an answer states is its cited evidence's value for one item.

Citation checks prove which chunks an answer cites, not that its numbers come from
them. This module reads each figure of an answer as a claim: the figure, the unit
written with it, the financial item its own words name and, when the answer dates it,
its year. The words around a figure are read with a closed vocabulary: listed item
phrases, connectives, years, units, currency and a few verbs. Any other word leaves
the figure without an item, so wording the checker does not understand fails closed
instead of borrowing an item named elsewhere.

Paired Markdown bold delimiters are presentation, not financial words. A leading
issuer subject may also be blanked when all cited chunk contexts name the same
issuer. Financial qualifiers and unknown subjects still fail closed.

A claim is verified only by one cited table cell whose whole row label is the same
item, whose column period is the claim's year (or, undated, a requested one) and
whose value equals the figure once both stated units are converted. It is a period
mismatch when that item's value sits only in another known period. Change claims
("grew 14%"), percentages against absolute cells, unreadable units and ambiguous
years cannot be verified by a table. Context labels and running text cannot show a
period, so they confirm only claims for which no period is asked or stated.

An amount is certified only when both sides state its unit: the answer by a scale
word or currency, the table by unit declarations in its own header cells or in the
caption run the chunker linked to it with source spans, every one of them fully read.
When the unit of the item's cells is absent, not fully readable or contradictory, or
the answer states none, no unit is guessed and the figure is ``unit_unverified``:
withheld, neither confirmed nor reported as absent. One such figure withholds the
whole answer, even beside a figure that is wrong.

The currency is part of the unit. An amount's currency comes from the markers written
with it; a cell's from the table's notes and that cell's own text. ISO codes and names
that fix a country ("U.S. dollars", "원") are explicit; "$", "dollars"/"달러" and "¥"
name only a family and are resolved solely by an explicit currency of the same cell or
table. Known different currencies never match and are never converted; a missing,
still-ambiguous or conflicting currency withholds the figure.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import re
from typing import Literal
import unicodedata

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

# Currency evidence. An ISO code, or a name that fixes the country, names one currency.
# "$", a bare "dollar"/"달러"/"불" and "¥" name only a family; they are resolved solely by
# an explicit code tied to the same figure, cell or table. Nothing is ever converted.
_CODES = ("USD", "KRW", "JPY", "CNY", "EUR", "GBP", "CAD", "AUD", "HKD", "TWD", "SGD", "CHF")
_DOLLAR, _YEN, _CONFLICT = "$", "¥", "!"
_FAMILIES = {
    _DOLLAR: frozenset({"USD", "CAD", "AUD", "HKD", "TWD", "SGD"}),
    _YEN: frozenset({"JPY", "CNY"}),
}
# (pattern, canonical currency), most specific first. Latin patterns get word boundaries.
_CURRENCY_FORMS: tuple[tuple[str, str], ...] = (
    (r"U\.\s?S\.\s?\$|US\$", "USD"),
    (r"CA?\$", "CAD"),
    (r"AU?\$", "AUD"),
    (r"HK\$", "HKD"),
    (r"NT\$", "TWD"),
    (r"S\$", "SGD"),
    (r"(?:U\.\s?S\.|US|United\s+States)\s+dollars?", "USD"),
    (r"Canadian\s+dollars?", "CAD"),
    (r"Australian\s+dollars?", "AUD"),
    (r"Hong\s+Kong\s+dollars?", "HKD"),
    (r"Korean\s+won", "KRW"),
    (r"(?:British\s+)?pounds?\s+sterling|British\s+pounds?", "GBP"),
    (r"euros?", "EUR"),
    (r"yen", "JPY"),
    (r"yuan|renminbi|RMB", "CNY"),
    (r"won", "KRW"),
    (r"dollars?", _DOLLAR),
    *((code, code) for code in _CODES),
    (r"미국\s*달러", "USD"),
    (r"원", "KRW"),
    (r"유로", "EUR"),
    (r"파운드", "GBP"),
    (r"엔", "JPY"),
    (r"위안", "CNY"),
    (r"달러|불", _DOLLAR),
    (r"[$＄﹩]", _DOLLAR),
    (r"[₩￦]", "KRW"),
    (r"€", "EUR"),
    (r"[£￡]", "GBP"),
    (r"[¥￥]", _YEN),
)
# A currency the checker does not support is still a currency: it marks the figure as
# unknown (``_UNKNOWN``) so it is withheld, never stripped. That covers every other Unicode
# currency sign ("₹", "₽") and these real ISO codes outside ``_CODES``.
_UNKNOWN = "?"
_UNSUPPORTED_CODES = (
    *("INR", "NZD", "BRL", "MXN", "ZAR", "RUB", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF"),
    *("TRY", "IDR", "THB", "MYR", "PHP", "VND", "ILS", "SAR", "AED", "ARS", "CLP", "COP"),
    *("PEN", "EGP", "NGN", "KES", "PKR", "BDT", "LKR", "QAR", "KWD", "MOP"),
)
_KNOWN_SIGNS = frozenset("$＄﹩₩￦€£￡¥￥")
_UNKNOWN_SIGNS = "".join(
    sign
    for sign in map(chr, range(0x10000))
    if unicodedata.category(sign) == "Sc" and sign not in _KNOWN_SIGNS
)
_UNKNOWN_CURRENCY = (
    f"[{re.escape(_UNKNOWN_SIGNS)}]"
    rf"|(?<![A-Za-z])(?:{'|'.join(_UNSUPPORTED_CODES)})(?![A-Za-z])"
)
_UNKNOWN_BEFORE = re.compile(rf"(?:{_UNKNOWN_CURRENCY})[ \t]*$", re.IGNORECASE)
_UNKNOWN_AFTER = re.compile(rf"[ \t]*(?:{_UNKNOWN_CURRENCY})", re.IGNORECASE)
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


def _bounded(pattern: str) -> str:
    """Give a Latin currency pattern word boundaries; symbols and Korean need none."""
    latin = pattern.startswith("(?:") or (pattern[0].isascii() and pattern[0].isalpha())
    return rf"(?<![A-Za-z])(?:{pattern})(?![A-Za-z])" if latin else pattern


_CURRENCY_PATTERNS = tuple(
    (re.compile(_bounded(pattern), re.IGNORECASE), currency)
    for pattern, currency in _CURRENCY_FORMS
)
_ANY_CURRENCY = "|".join(f"(?:{_bounded(pattern)})" for pattern, _ in _CURRENCY_FORMS)
# Every currency mention of a cell or note.
_CURRENCY_MENTION = re.compile(_ANY_CURRENCY, re.IGNORECASE)
# A currency written right after a figure (and its scale): "25 USD", "300조원", "5 dollars".
_CURRENCY_AFTER = re.compile(rf"[ \t]*(?:{_ANY_CURRENCY})", re.IGNORECASE)
# A currency symbol or code written right before a figure: "$", "US$", "₩", "USD ".
_CURRENCY_BEFORE = re.compile(
    "(?:"
    + "|".join(
        f"(?:{_bounded(pattern)})"
        for pattern, _ in _CURRENCY_FORMS
        if "$" in pattern or pattern in _CODES or pattern in ("[₩￦]", "€", "[£￡]", "[¥￥]")
    )
    + r")[ \t]*$",
    re.IGNORECASE,
)


def _currency_of(text: str) -> str | None:
    """Return the canonical currency (or family) one currency mention names."""
    mention = " ".join(text.split())
    return next(
        (currency for pattern, currency in _CURRENCY_PATTERNS if pattern.fullmatch(mention)),
        None,
    )


def _currencies_in(text: str) -> frozenset[str]:
    """Return the currencies (or families) every mention in a text names."""
    return frozenset(
        currency
        for match in _CURRENCY_MENTION.finditer(text)
        if (currency := _currency_of(match.group(0))) is not None
    )


def _resolve(markers: frozenset[str]) -> str | None:
    """Resolve the currency markers tied to one figure, cell or table.

    Returns None without markers, one ISO code when an explicit code is the only one and
    every family marker admits it ("$" with "USD"), a still-ambiguous family ("$", "¥")
    when only one family is named, and ``_CONFLICT`` for anything incompatible.
    """
    if not markers:
        return None
    if _UNKNOWN in markers:
        return _CONFLICT
    codes = {marker for marker in markers if marker not in _FAMILIES}
    families = markers - codes
    if len(codes) > 1:
        return _CONFLICT
    if codes:
        code = next(iter(codes))
        return code if all(code in _FAMILIES[family] for family in families) else _CONFLICT
    return next(iter(families)) if len(families) == 1 else _CONFLICT


def _same_currency(answer: str | None, evidence: str | None) -> Literal["match", "uncertain", "no"]:
    """Compare a claim's resolved currency with its evidence's, never converting.

    Two codes match only when equal. A family on the answer ("$") takes an evidence code
    of that family; a family on the evidence alone cannot certify an explicit code. A
    missing, conflicting or still-ambiguous currency is ``uncertain``; a currency outside
    the other side's family is ``no``.
    """
    if answer is None or evidence is None or _CONFLICT in (answer, evidence):
        return "uncertain"
    if answer not in _FAMILIES and evidence not in _FAMILIES:
        return "match" if answer == evidence else "no"
    if answer in _FAMILIES and evidence not in _FAMILIES:
        return "match" if evidence in _FAMILIES[answer] else "no"
    if evidence in _FAMILIES and answer not in _FAMILIES:
        return "uncertain" if answer in _FAMILIES[evidence] else "no"
    return "uncertain" if answer == evidence else "no"


# The only digit-bearing words left out as identifiers besides _NOT_FIGURES: one or two
# digits glued to one capital ("3M", "10K", "5G") and ordinals ("3rd").
_IDENTIFIER = re.compile(r"\d{1,2}[A-Z]|\d+(?:st|nd|rd|th)")
_LETTERS_BEFORE = re.compile(r"[A-Za-z]+$")
_LETTERS_AFTER = re.compile(r"[A-Za-z]+")
_CURRENCY_CODE = re.compile(
    r"USD|US|KRW|EUR|JPY|GBP|CNY|CAD|AUD|HKD|TWD|SGD|CHF|RMB", re.IGNORECASE
)
# Korean scales compose: a 십/백/천 prefix multiplies a 만/억/조 base ("천억" = 10^3 x 10^8).
# A bare 천 ("천원", "천US$") is a thousand.
_KOREAN_SCALE = re.compile(r"([십백천]?)([만억조])|천")
_KOREAN_PREFIX = {"": 1, "십": 10, "백": 100, "천": 1000}
_KOREAN_BASE = {"만": Decimal(10) ** 4, "억": Decimal(10) ** 8, "조": Decimal(10) ** 12}
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
    rf"(?:\s+of\s+(?P<of>{_ANY_CURRENCY}))?"
)
# "In millions [of <currency>]", optionally led by a currency or "Amounts".
_SCALE_DECLARATION = re.compile(
    rf"\s*(?:(?P<prefix>amounts|{_ANY_CURRENCY})\s+)?in\s+{_SCALE_WORD}"
    r"(?P<per_share>\s*,\s*except\s+(?:for\s+)?(?:share\s+and\s+)?per[\s-]share"
    r"(?:\s+and\s+share)?(?:\s+(?:data|amounts|information|figures))?)?\s*",
    re.IGNORECASE,
)
# "In <currency>" ("(In U.S. dollars)") declares a currency, and plain units only when no
# other note of the table states a scale; "(In millions) (In U.S. dollars)" is millions.
_PLAIN_DECLARATION = re.compile(rf"\s*in\s+(?P<currency>{_ANY_CURRENCY})\s*", re.IGNORECASE)
# A currency-only declaration states no scale at all: "(USD)", "(Currency: KRW)",
# "(Expressed in U.S. dollars)".
_CURRENCY_DECLARATION = re.compile(
    r"\s*(?:(?:currency|denomination)\s*[:：]\s*|(?:expressed|presented|reported)\s+in\s+)?"
    rf"(?P<currency>{_ANY_CURRENCY})\s*",
    re.IGNORECASE,
)
_UNITS_DECLARATION = re.compile(rf"\s*units?\s*[:：]\s*{_SCALE_WORD}\s*", re.IGNORECASE)
# A Korean 단위 note runs to its closing parenthesis; it lists one unit or several.
_KOREAN_UNIT_NOTE = re.compile(r"단위\s*[:：]?\s*([^)）]*)")
# The monetary unit a Korean 단위 note may state: an optional scale and a currency.
_KOREAN_NOTE = re.compile(r"(?P<scale>(?:[십백천]?[만억조])|천)?(?P<currency>.+)")
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
_STRONG = re.compile(r"(?<![\\*])\*\*(?!\s)([^*\n]+?)(?<![\s\\])\*\*(?!\*)")
# The prefix is emitted by ingestion's context-header builder, not filing prose.
_ISSUER_CONTEXT = re.compile(r"(?P<issuer>[^\n]+?) FY\d{4} · ")
# The only parentheticals that keep a label or answer phrase the same item.
_SAME_ITEM_QUALIFIER = re.compile(
    r"\s*[(（]\s*(?:loss|losses|손실|note\s*\d+[a-z]?|주석\s*\d+)\s*[)）]", re.IGNORECASE
)
_ENUMERATOR = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|\d+|[ivx]+|[가-하])[.)]\s*", re.IGNORECASE)
# A sentence ends at terminal punctuation followed by space, or at ";" or a line break.
_SENTENCE_BREAK = re.compile(r"(?<!\bvs)(?<!U\.S)[.!?。](?=\s|$)|[;\n]")

# English words that may stand around a figure without changing which item it is.
_FILLERS = frozenset(
    {
        *("a", "an", "the", "its", "their", "was", "were", "is", "are", "be", "been"),
        *("of", "at", "in", "for", "during", "on", "by", "as", "or"),
        *("totaled", "totalled", "totaling", "reached", "amounted", "came", "stood"),
        *("reported", "recorded", "approximately", "about", "around", "roughly", "nearly"),
        *("fiscal", "year", "years", "ended", "ending", "prior", "previous", "preceding"),
        *("last", "same", "period", "usd", "us", "krw", "won", "dollar", "dollars"),
        *("jpy", "cny", "rmb", "eur", "gbp", "cad", "aud", "hkd", "twd", "sgd", "chf"),
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

# ``unit_unverified``: the figure names an item whose cited cells' unit, or whose own
# unit, is missing, not fully readable or contradictory, so the value can be neither
# confirmed nor refuted. It is withheld, never reported as absent from the documents.
type Verdict = Literal["verified", "period_mismatch", "unit_unverified", "unverified"]
type _Comparison = Literal["match", "uncertain", "no"]
_FACT_VERDICTS: dict[_Comparison, Verdict] = {
    "match": "verified",
    "uncertain": "unit_unverified",
    "no": "unverified",
}


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
# Words of the English item phrases ("net", "tax"), never mistaken for currency codes.
_ITEM_WORDS = frozenset(word for words, _ in _ENGLISH_PHRASES for word in words)


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
        """Withhold an uncertain unit first, then fail an unverified figure, then mismatch.

        A figure whose unit cannot be confirmed outranks every other outcome, so missing
        unit certainty never turns into a statement that the documents lack the answer or
        that it belongs to another period; the whole answer is withheld instead.
        """
        verdicts = {check.verdict for check in self.checks}
        for verdict in ("unit_unverified", "unverified", "period_mismatch"):
            if verdict in verdicts:
                return verdict
        return "verified"


@dataclass(frozen=True, slots=True)
class _Figure:
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
        """Return the currency the figure's own markers resolve to (see ``_resolve``)."""
        return _resolve(self.currency)


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
class TableCellReading:
    """One original table cell holding figures: its values, years, unit and row item.

    ``row`` and ``column`` are the cell's zero-based source grid coordinates. ``scale``
    is None when the cell's unit is uncertain; ``percent`` is None when the evidence
    cannot show whether the cell is a percentage. ``currency`` is resolved from the
    table's notes and the markers bound to this cell's own numbers only, never from
    other rows or tables; ``marked`` says the cell's numbers carry currency markers.
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


def _markers_before(text: str, start: int) -> tuple[set[str], int]:
    """Read the whole run of currency markers written right before a figure.

    Returns the markers and where the run begins. A supported "$" form with a letter
    glued in front ("NZ$", "ZZ$") and any unsupported sign or code is ``_UNKNOWN``.
    """
    markers: set[str] = set()
    position = start
    while True:
        if known := _CURRENCY_BEFORE.search(text, 0, position):
            written = known.group(0).strip()
            qualified = known.start() > 0 and text[known.start() - 1].isalpha()
            currency = _currency_of(written)
            markers.add(
                _UNKNOWN if currency is None or ("$" in written and qualified) else currency
            )
            position = known.start()
        elif unknown := _UNKNOWN_BEFORE.search(text, 0, position):
            markers.add(_UNKNOWN)
            position = unknown.start()
        elif (shaped := _CODE_SHAPED_BEFORE.search(text, 0, position)) and _code_shaped(
            shaped.group(1)
        ):
            markers.add(_UNKNOWN)
            position = shaped.start()
        else:
            return markers, position


def _markers_after(text: str, end: int) -> tuple[set[str], int]:
    """Read the whole run of currency markers written right after a figure and its unit."""
    markers: set[str] = set()
    position = end
    while True:
        if known := _CURRENCY_AFTER.match(text, position):
            markers.add(_currency_of(known.group(0)) or _UNKNOWN)
            position = known.end()
        elif unknown := _UNKNOWN_AFTER.match(text, position):
            markers.add(_UNKNOWN)
            position = unknown.end()
        elif (shaped := _CODE_SHAPED_AFTER.match(text, position)) and _code_shaped(shaped.group(1)):
            markers.add(_UNKNOWN)
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
    ordinary = _FILLERS | _CONNECTIVES | _CHANGES | _ORDINARY_SHORT_WORDS | _ITEM_WORDS
    return key not in ordinary and _currency_of(word) is None


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
        code = _CURRENCY_AFTER.match(text, end)
        if code is not None and _currency_of(code.group(0)) in _CODES:
            # A glued ISO code ("25,785USD") is a currency, read after the figure.
            return None, True, end
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
    sign or unreadable letters make it an amount ("$2024mn", "USD 2024", "2024원",
    "₹2024"): currency markers, supported or not, are read before that decision.

    Every currency marker written with a figure, the whole run before it and after it,
    is kept, so disagreeing markers ("USD EUR 25") resolve as a conflict. A marker run
    that touches two figures could belong to either, so both are marked unknown.
    """
    found: list[_Figure] = []
    for match in _NUMBER.finditer(blanked):
        token = match.group(0)
        start, end = match.span()
        prefix = _LETTERS_BEFORE.search(blanked, 0, start)
        suffix = _LETTERS_AFTER.match(blanked, end)
        before = blanked[:start].rstrip()
        code = prefix is not None and _CURRENCY_CODE.fullmatch(prefix.group(0)) is not None
        markers, unit_start = _markers_before(blanked, start)
        currency = code or bool(markers) or (bool(before) and before[-1] in _CURRENCY)
        glued = token + (suffix.group(0) if suffix else "")
        if prefix is None and not currency and _IDENTIFIER.fullmatch(glued):
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
        if _BARE_YEAR.fullmatch(token.strip("()△▲-")) and not amount:
            continue
        digits = token.rstrip(")")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value = _value(token) if readable else None
        if found and found[-1].unit_end > unit_start:
            # One marker run between two figures: neither can claim it alone.
            markers.add(_UNKNOWN)
            found[-1] = replace(found[-1], currency=found[-1].currency | {_UNKNOWN})
        found.append(
            _Figure(
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
        if not any(figure.unit_start <= match.start() < figure.unit_end for figure in found)
    ]
    heads: list[tuple[int, list[_Word]]] = []
    tails: list[tuple[int, list[_Word]]] = []
    head_start = start
    for index, figure in enumerate(found):
        # A currency written before the figure belongs to it, not to its head words.
        heads.append((head_start, _words(masked, head_start, max(head_start, figure.unit_start))))
        stop = found[index + 1].unit_start if index + 1 < len(found) else end
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
            if (head_at <= at < figure.unit_start or figure.unit_end <= at < tail_end)
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


def _issuer_subjects(text: str, issuer: str | None) -> str:
    """Blank one grounded issuer only in subject position, preserving every offset.

    The prefix of its sentence must contain only ordinary filler words or dates,
    never another item, figure or qualifier. Matching the complete issuer before
    sentence splitting also handles punctuation in names such as ``Acme, Inc.``.
    """
    if issuer is None:
        return text
    pattern = re.compile(rf"(?<!\w){re.escape(issuer)}(?![\w'’])")
    masked = text
    for match in pattern.finditer(text):
        before = _blank(masked[: match.start()])
        start = max((end.end() for end in _SENTENCE_BREAK.finditer(before)), default=0)
        if all(
            word.kind == "filler" and not _POSSESSIVE.fullmatch(word.text)
            for word in _words(before, start, len(before))
        ):
            masked = masked[: match.start()] + " " * len(match.group()) + masked[match.end() :]
    return masked


def _cited_issuer(evidence: Sequence[EvidenceText]) -> str | None:
    """Return one exact issuer shared by every structured context, else fail closed.

    Mixed or absent issuer metadata cannot justify treating a company name as
    harmless wording: a figure might otherwise borrow another company's cell.
    """
    issuers = set()
    for item in evidence:
        match = _ISSUER_CONTEXT.match(item.context_header)
        if match is None:
            return None
        issuers.add(match["issuer"])
    return next(iter(issuers)) if len(issuers) == 1 else None


def _claims(text: str, *, issuer: str | None = None) -> list[_Claim]:
    """Read every figure of a text as a claim, sentence by sentence."""
    formatted = _STRONG.sub(lambda match: "  " + match[1] + "  ", text)
    subject = _issuer_subjects(formatted, issuer)
    masked = _blank(_SAME_ITEM_QUALIFIER.sub(lambda match: " " * len(match.group(0)), subject))
    bounds = [0, *(match.start() for match in _SENTENCE_BREAK.finditer(masked)), len(masked)]
    return [
        claim
        for first, last in zip(bounds, bounds[1:], strict=False)
        for claim in _sentence_claims(masked, text, first, last)
    ]


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
        currency = _currencies_in(" ".join((prefix, scale.group("of") or "")))
        return _Note(
            "scale",
            _english_factor(scale.group("scale")),
            scale.group("per_share") is not None,
            currency,
        )
    if units := _UNITS_DECLARATION.fullmatch(declaration):
        currency = _currencies_in(units.group("of") or "")
        return _Note("scale", _english_factor(units.group("scale")), currency=currency)
    if plain := _PLAIN_DECLARATION.fullmatch(declaration):
        return _Note("currency", currency=_currencies_in(plain.group("currency")), plain=True)
    if named := _CURRENCY_DECLARATION.fullmatch(declaration):
        return _Note("currency", currency=_currencies_in(named.group("currency")))
    return _Note("unknown")


def _korean_note(content: str) -> _Note:
    """Read one Korean 단위 note; a list of several units leaves each row's unit unknown."""
    parts = [re.sub(r"\s+", "", part) for part in re.split(r"[,/、]", content)]
    if len(parts) != 1:
        return _Note("unknown")
    if parts[0] == "%":
        return _Note("percent")
    korean = _KOREAN_NOTE.fullmatch(parts[0])
    currency = _currency_of(korean.group("currency")) if korean else None
    if korean is not None and currency is not None:
        # A 단위 note states the unit itself, so a bare currency ("원") means plain units.
        prefix = korean.group("scale")
        scale = _KOREAN_SCALE.fullmatch(prefix) if prefix else None
        factor = _korean_factor(scale) if scale is not None else Decimal(1)
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
    if len(scales) > 1 or _resolve(currency) == _CONFLICT or (percent and monetary):
        return TableUnit("conflicting", percent=percent)
    per_share_plain = any(note.per_share_plain for note in notes)
    return TableUnit("known", next(iter(scales), None), percent, per_share_plain, currency)


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


def read_table_cells(fragment: Mapping[str, object]) -> list[TableCellReading]:
    """Return each figure-bearing source cell of one table fragment as it is read.

    A source cell appears once per normalized cell it belongs to, as stored.
    """
    headers = _entries(fragment, "header_cells")
    caption_years = {
        int(year)
        for caption in _entries(fragment, "caption_sources")
        for year in _YEAR.findall(str(caption.get("text", "")))
    }
    unit = read_table_unit(fragment)
    known = unit.status == "known"
    labels = _row_labels(fragment)
    cells = []
    for member in _entries(fragment, "cells"):
        for source in _entries(member, "sources"):
            text = str(source.get("text", ""))
            values = _values(text)
            if values:
                label = labels.get(_int(source["row"]))
                per_share = label is not None and _PER_SHARE.search(label)
                scale = unit.scale if known else None
                if per_share and known:
                    # A per-share row is in plain currency only when the note says so or
                    # the whole table is; under a scaled note its unit is ambiguous.
                    plain = unit.per_share_plain or unit.scale == 1
                    scale = Decimal(1) if plain and unit.scale is not None else None
                percent: bool | None = "%" in text or (
                    known and unit.percent and unit.scale is None
                )
                if not percent and not known:
                    # Without a readable note a bare cell may or may not be a percentage.
                    percent = None
                # Only markers bound to the cell's own numbers count; other words in the
                # cell ("원가") name no denomination.
                own = frozenset(
                    marker for figure in _figure_spans(_blank(text)) for marker in figure.currency
                )
                cells.append(
                    TableCellReading(
                        _int(source["row"]),
                        _int(source["column"]),
                        frozenset(values),
                        frozenset(_column_years(source, headers, caption_years)),
                        scale,
                        _label_item(label) if label is not None else None,
                        percent,
                        _resolve(unit.currency | own),
                        bool(own),
                    )
                )
    return cells


def _within(figure: _Figure, amount: Decimal, target: Decimal, scale: Decimal) -> bool:
    """Whether a stated amount equals a target, allowing rounding to its last digit.

    A converted figure may be rounded to its own last expressed digit (half of it either
    way), but only when it keeps at least three significant digits: "$25.8 billion"
    passes for 25,785 million, while "$26 billion" must match exactly.
    """
    if amount == target:
        return True
    value = figure.value
    if value is None or len(value.as_tuple().digits) < _MIN_ROUNDED_DIGITS:
        return False
    tolerance = Decimal(5) * Decimal(10) ** (-figure.decimals - 1) * scale
    return abs(amount - target) <= tolerance


def _compare(
    figure: _Figure,
    value: Decimal,
    other: Decimal,
    scale: Decimal | None,
    percent: bool | None,
    currency: str | None,
    marked: bool = False,
) -> _Comparison:
    """Compare a figure with one evidence value of the given unit and currency.

    Percentages compare only with percentages, without a scale or currency; ``percent``
    is None when the evidence cannot show whether its value is one. A percentage that
    also carries a currency marker, on the claim or on the evidence (``marked``), is a
    contradiction and stays ``uncertain``. Amounts compare only
    when both sides state a scale and the same currency: a known different currency is
    ``no`` whatever the numbers, and a missing, ambiguous or conflicting currency or
    scale is ``uncertain`` whatever the digits. No unit or currency is guessed or
    converted.
    """
    if percent is None:
        return "uncertain"
    if figure.percent != percent:
        return "no"
    if percent:
        if figure.currency or marked:
            return "uncertain"
        return "match" if _within(figure, value, other, Decimal(1)) else "no"
    same = _same_currency(figure.stated_currency, currency)
    if same == "no":
        return "no"
    stated = figure.stated_scale
    if same == "uncertain" or stated is None or scale is None:
        return "uncertain"
    return "match" if _within(figure, value * stated, other * scale, stated) else "no"


def _best(comparisons: set[_Comparison]) -> _Comparison:
    """Return the strongest outcome among one evidence item's values."""
    for comparison in ("match", "uncertain"):
        if comparison in comparisons:
            return comparison
    return "no"


def _judge(
    claim: _Claim, cells: Sequence[TableCellReading], facts: Sequence[_Claim], requested: set[int]
) -> tuple[FigureCheck, bool]:
    """Judge one claim; the flag marks a verified claim dated outside the requested years.

    Only a table cell holding the claim's item, value and period, in units both sides
    state, confirms a level. A cell of the item whose unit, or the claim's own unit, is
    uncertain withholds the claim (``unit_unverified``) whatever its digits, instead of
    confirming, refuting or calling it another period. A change claim, or any claim
    when a period is asked or stated, gets no help from labels or running text, which
    cannot show a period;
    otherwise a fact of the same item, kind and value confirms or withholds it alike.
    """
    figure, item = claim.figure, claim.item
    if figure.value is None or item is None or claim.dated_ambiguously:
        return FigureCheck(figure.text, "unverified", (), item), False
    value = figure.value
    wanted = {claim.year} if claim.year is not None else requested

    def in_period(years: frozenset[int]) -> bool:
        """Whether a cell's column belongs to the claim's period."""
        return not wanted or bool(years & wanted)

    compared = [
        (
            cell.years,
            _best(
                {
                    _compare(figure, value, v, cell.scale, cell.percent, cell.currency, cell.marked)
                    for v in cell.values
                }
            ),
        )
        for cell in cells
        if not claim.change and cell.item == item
    ]
    certain = [years for years, outcome in compared if outcome == "match"]
    unsure = [years for years, outcome in compared if outcome == "uncertain"]
    if any(in_period(years) for years in certain):
        evidenced = tuple(sorted(frozenset[int]().union(*certain)))
        outside = bool(requested) and claim.year is not None and claim.year not in requested
        return FigureCheck(figure.text, "verified", evidenced, item), outside
    if unsure and (not certain or any(in_period(years) for years in unsure)):
        # No unit is guessed, so the digits cannot pick a cell: report the item's cells of
        # the claim's period, or all of them when none is in that period.
        held = [years for years in unsure if in_period(years)] or unsure
        evidenced = tuple(sorted(frozenset[int]().union(*held)))
        return FigureCheck(figure.text, "unit_unverified", evidenced, item), False
    if certain:
        evidenced = tuple(sorted(frozenset[int]().union(*certain)))
        verdict: Verdict = "period_mismatch" if all(certain) else "unverified"
        return FigureCheck(figure.text, verdict, evidenced, item), False
    outcome = _best(
        {
            _compare(
                figure,
                value,
                fact.figure.value,
                fact.figure.stated_scale,
                fact.figure.percent,
                fact.figure.stated_currency,
                bool(fact.figure.currency),
            )
            for fact in facts
            if not wanted
            and fact.item == item
            and not fact.dated_ambiguously
            and fact.change == claim.change
            and fact.figure.value is not None
        }
    )
    return FigureCheck(figure.text, _FACT_VERDICTS[outcome], (), item), False


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
        for cell in read_table_cells(item.table_fragment)
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
    judged = [
        _judge(claim, cells, facts, requested)
        for claim in _claims(answer, issuer=_cited_issuer(evidence))
    ]
    anchored = any(check.verdict == "verified" and not outside for check, outside in judged)
    return FiguresResult(
        tuple(
            replace(check, verdict="period_mismatch") if outside and not anchored else check
            for check, outside in judged
        )
    )
