"""The closed vocabulary figures and their items are read with.

The words around a figure are read with a closed vocabulary: listed item phrases,
connectives, years, units, currency and a few verbs. Any other word leaves the figure
without an item, so wording the checker does not understand fails closed instead of
borrowing an item named elsewhere.
"""

import re

from app.figures.currency import _CURRENCY

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
    r"\s*[(（]\s*(?:loss|losses|손실|"
    r"(?:notes?|주석?)\s*\d+[a-z]?(?:\s*(?:[,，、~-]|and|&)\s*\d+[a-z]?)*)\s*[)）]",
    re.IGNORECASE,
)


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


def items_named(text: str) -> frozenset[str]:
    """Return the financial items a question names, read with the answers' vocabulary.

    English phrases match whole words, longest first; Korean phrases match as stems,
    longest first, so "매출원가" is not also read as "매출". A question naming no listed
    phrase names no item: nothing is inferred from other words.
    """
    found: set[str] = set()
    words = [word.casefold() for word in _TOKEN.findall(text)]
    used = [False] * len(words)
    for phrase, item in _ENGLISH_PHRASES:
        size = len(phrase)
        for start in range(len(words) - size + 1):
            if not any(used[start : start + size]) and tuple(words[start : start + size]) == phrase:
                found.add(item)
                used[start : start + size] = [True] * size
    remaining = "".join(text.split())
    for phrase in sorted(_KOREAN_PHRASES, key=len, reverse=True):
        if phrase in remaining:
            found.add(_KOREAN_PHRASES[phrase])
            remaining = remaining.replace(phrase, " ")
    return frozenset(found)
