"""Read the currency written with a figure, a cell or a table note.

The currency is part of the unit. An amount's currency comes from the markers written
with it; a cell's from the table's notes and that cell's own text. ISO codes and names
that fix a country ("U.S. dollars", "원") are explicit; "$", "dollars"/"달러" and "¥"
name only a family and are resolved solely by an explicit currency of the same cell or
table. Known different currencies never match and are never converted; a missing,
still-ambiguous or conflicting currency withholds the figure.
"""

import re
from typing import Literal
import unicodedata

CURRENCY = "$€£¥₩"


# Currency evidence. An ISO code, or a name that fixes the country, names one currency.
# "$", a bare "dollar"/"달러"/"불" and "¥" name only a family; they are resolved solely by
# an explicit code tied to the same figure, cell or table. Nothing is ever converted.
CODES = ("USD", "KRW", "JPY", "CNY", "EUR", "GBP", "CAD", "AUD", "HKD", "TWD", "SGD", "CHF")
_DOLLAR, _YEN, CONFLICT = "$", "¥", "!"
FAMILIES = {
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
    *((code, code) for code in CODES),
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
# unknown (``UNKNOWN``) so it is withheld, never stripped. That covers every other Unicode
# currency sign ("₹", "₽") and these real ISO codes outside ``CODES``.
UNKNOWN = "?"
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
UNKNOWN_BEFORE = re.compile(rf"(?:{_UNKNOWN_CURRENCY})[ \t]*$", re.IGNORECASE)
UNKNOWN_AFTER = re.compile(rf"[ \t]*(?:{_UNKNOWN_CURRENCY})", re.IGNORECASE)


def _bounded(pattern: str) -> str:
    """Give a Latin currency pattern word boundaries; symbols and Korean need none."""
    latin = pattern.startswith("(?:") or (pattern[0].isascii() and pattern[0].isalpha())
    return rf"(?<![A-Za-z])(?:{pattern})(?![A-Za-z])" if latin else pattern


_CURRENCY_PATTERNS = tuple(
    (re.compile(_bounded(pattern), re.IGNORECASE), currency)
    for pattern, currency in _CURRENCY_FORMS
)
ANY_CURRENCY = "|".join(f"(?:{_bounded(pattern)})" for pattern, _ in _CURRENCY_FORMS)
# The same forms by script. A Korean currency word may begin an ordinary word ("원가",
# "불가", "엔진"), so a reader that must not take such a word for a unit asks for the
# Korean words apart from the signs and Latin words, which carry their own boundaries.
KOREAN_CURRENCY = "|".join(
    f"(?:{pattern})" for pattern, _ in _CURRENCY_FORMS if "가" <= pattern[0] <= "힣"
)
BOUNDED_CURRENCY = "|".join(
    f"(?:{_bounded(pattern)})" for pattern, _ in _CURRENCY_FORMS if not "가" <= pattern[0] <= "힣"
)
# Every currency mention of a cell or note.
_CURRENCY_MENTION = re.compile(ANY_CURRENCY, re.IGNORECASE)
# A currency written right after a figure (and its scale): "25 USD", "300조원", "5 dollars".
CURRENCY_AFTER = re.compile(rf"[ \t]*(?:{ANY_CURRENCY})", re.IGNORECASE)
# A currency symbol or code written right before a figure: "$", "US$", "₩", "USD ".
CURRENCY_BEFORE = re.compile(
    "(?:"
    + "|".join(
        f"(?:{_bounded(pattern)})"
        for pattern, _ in _CURRENCY_FORMS
        if "$" in pattern or pattern in CODES or pattern in ("[₩￦]", "€", "[£￡]", "[¥￥]")
    )
    + r")[ \t]*$",
    re.IGNORECASE,
)


def currency_of(text: str) -> str | None:
    """Return the canonical currency (or family) one currency mention names."""
    mention = " ".join(text.split())
    return next(
        (currency for pattern, currency in _CURRENCY_PATTERNS if pattern.fullmatch(mention)),
        None,
    )


def currencies_in(text: str) -> frozenset[str]:
    """Return the currencies (or families) every mention in a text names."""
    return frozenset(
        currency
        for match in _CURRENCY_MENTION.finditer(text)
        if (currency := currency_of(match.group(0))) is not None
    )


def resolve(markers: frozenset[str]) -> str | None:
    """Resolve the currency markers tied to one figure, cell or table.

    Returns None without markers, one ISO code when an explicit code is the only one and
    every family marker admits it ("$" with "USD"), a still-ambiguous family ("$", "¥")
    when only one family is named, and ``CONFLICT`` for anything incompatible.
    """
    if not markers:
        return None
    if UNKNOWN in markers:
        return CONFLICT
    codes = {marker for marker in markers if marker not in FAMILIES}
    families = markers - codes
    if len(codes) > 1:
        return CONFLICT
    if codes:
        code = next(iter(codes))
        return code if all(code in FAMILIES[family] for family in families) else CONFLICT
    return next(iter(families)) if len(families) == 1 else CONFLICT


def same_currency(answer: str | None, evidence: str | None) -> Literal["match", "uncertain", "no"]:
    """Compare a claim's resolved currency with its evidence's, never converting.

    Two codes match only when equal. A family on the answer ("$") takes an evidence code
    of that family; a family on the evidence alone cannot certify an explicit code. A
    missing, conflicting or still-ambiguous currency is ``uncertain``; a currency outside
    the other side's family is ``no``.
    """
    if answer is None or evidence is None or CONFLICT in (answer, evidence):
        return "uncertain"
    if answer not in FAMILIES and evidence not in FAMILIES:
        return "match" if answer == evidence else "no"
    if answer in FAMILIES and evidence not in FAMILIES:
        return "match" if evidence in FAMILIES[answer] else "no"
    if evidence in FAMILIES and answer not in FAMILIES:
        return "uncertain" if answer in FAMILIES[evidence] else "no"
    return "uncertain" if answer == evidence else "no"
