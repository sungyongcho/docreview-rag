"""Own annual-period forms and classification before readers blank identifiers.

Readers retain their identifier-versus-amount and bare header-date grammars. Annual
endings, full durations and full-year ranges are recognized here for every reader.
"""

from datetime import date, datetime
import re
from typing import Literal

MONTH_NAMES = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
# A month word needs a numeric date neighbour or a dating preposition. Case alone
# cannot distinguish "May" the modal or "March" the verb in case-folded headers.
_MONTH = rf"\b{MONTH_NAMES}\b\.?"
_MONTH_DATE = re.compile(
    rf"{_MONTH}(?=\s+(?:\d{{1,2}}\b|(?:19|20)\d{{2}}\b))"
    rf"|\b\d{{1,2}}\s+{_MONTH}|\b(?:in|during|for|as\s+of)\s+{_MONTH}",
    re.I,
)
PERIOD_WORDS = re.compile(
    r"\b(?:months?|weeks?|quarter(?:s|ly)?|q\s*[1-4](?:\d{2})?|[1-4]q(?:\d{2})?|h\s*[12](?:\d{2})?|[12]h(?:\d{2})?|half(?:[\s-]year)?"
    r"|ytd|year[\s-]to[\s-]date|to[\s-]date|interim|periods?|semi[\s-]?annual)\b"
    rf"|{_MONTH_DATE.pattern}"
    r"|분\s*기|반\s*기|개월|누적|누계|기\s*초|기간|(?<!\d)\d{1,2}\s*월",
    re.I,
)

type PeriodKind = Literal["annual", "subannual", "date", "none"]

_YEAR_NUMBER = r"(?:19|20)\d{2}"
_YEAR = re.compile(
    rf"(?<!\d){_YEAR_NUMBER}(?!\d)|\bfy\s*\d{{2,4}}\b|회계\s*연도|사업\s*연도|당기|전기|제\s*\d+\s*기|\b(?:annual|fiscal|year)\b",
    re.I,
)
_NUMERIC_DATE = rf"{_YEAR_NUMBER}\s*[./-]\s*\d{{1,2}}\s*[./-]\s*\d{{1,2}}"
_KOREAN_DATE = rf"{_YEAR_NUMBER}\s*년\s*\d{{1,2}}\s*월\s*\d{{1,2}}\s*일"
_END_DATE = (
    rf"(?:{_MONTH}\s+\d{{1,2}},?\s+{_YEAR_NUMBER}"
    rf"|{_NUMERIC_DATE}|\d{{1,2}}/\d{{1,2}}/{_YEAR_NUMBER}|{_KOREAN_DATE})(?!\w|[,.]\d)"
)
# Korean particles follow 일 without a word boundary.
_KO_END_DATE = rf"(?:{_KOREAN_DATE}|{_NUMERIC_DATE})(?!\d)"
_DATE = re.compile(
    rf"{_MONTH_DATE.pattern}|(?<!\d){_NUMERIC_DATE}"
    rf"|(?<!\d)\d{{1,2}}/\d{{1,2}}/{_YEAR_NUMBER}|(?<!\d)\d{{1,2}}\s*월",
    re.I,
)
_DURATION = (
    r"(?:\b(?:twelve|12)[\s-]+months?\b"
    r"|\b(?:52|53|fifty[\s-]two|fifty[\s-]three)[\s-]+weeks?\b)"
)
_ANNUAL_NOUN = r"(?:fiscal[\s-]+years?|annual[\s-]+periods?|years?)"
_FULL_DURATION = rf"{_DURATION}(?:\s+(?:fiscal[\s-]+years?|years?|periods?))?"
# A hyphen straight after a digit joins a range ("FY24-FY25"), so its second
# identifier is read too; any other hyphenated prefix ("non-FY24") is not one.
_FISCAL_YEAR = re.compile(
    r"(?:(?<![\w-])|(?<=\d-))(?:fy\s*['’]?\s*|fiscal\s+(?:year\s+)?)"
    r"(?P<year>(?:19|20)\d{2}|\d{2})(?!\w|[,.]\d|-[a-z]\b)",
    re.I,
)
# One ending grammar: an annual noun, full duration or explicit FY identifier,
# optionally followed by a relative/parenthetical ending clause, then a date.
_ANNUAL_END = re.compile(
    rf"(?<![\w-])(?:{_FISCAL_YEAR.pattern}|{_FULL_DURATION}|{_ANNUAL_NOUN})"
    rf"\s*(?:[,(:]\s*)?(?:which\s+)?end(?:ed|ing)\s+(?:on\s+)?{_END_DATE}"
    rf"|(?<!\w){_KO_END_DATE}\s*(?:(?:로|에)\s*)?종료(?:된|되는|하는)?\s*(?:회계|사업)\s*연도(?:의|에)?",
    re.I,
)
_FULL_ANNUAL = re.compile(
    rf"{_FULL_DURATION}|\bannual[\s-]+periods?\b"
    rf"|\bfiscal[\s-]+year\s+periods?\b|{_FISCAL_YEAR.pattern}\s+periods?\b",
    re.I,
)
_RANGE_DATE = rf"(?:{_NUMERIC_DATE}|{_KOREAN_DATE})"
_DATE_RANGE = re.compile(
    rf"(?<!\d)(?P<start>{_RANGE_DATE})\s*(?:[~–—-]|부터)\s*(?P<end>{_RANGE_DATE})(?:\s*까지)?(?!\d)"
)


def _calendar_date(text: str) -> date | None:
    """Read one complete calendar date, rejecting impossible days and months."""
    numeric = re.fullmatch(_NUMERIC_DATE + "|" + _KOREAN_DATE, text)
    if numeric:
        try:
            return date(*(int(n) for n in re.findall(r"\d+", text)))
        except ValueError:
            return None
    text = re.sub(r"\b([A-Za-z]{3})[A-Za-z]*\.?", r"\1", text).replace(",", "")
    for form in ("%b %d %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, form).date()
        except ValueError:
            continue
    return None


def _annual_range(match: re.Match[str]) -> bool:
    """Accept inclusive 12-month calendar years or 52/53-week fiscal years."""
    start, end = (_calendar_date(match[name]) for name in ("start", "end"))
    return start is not None and end is not None and (end - start).days + 1 in {364, 365, 366, 371}


def annual_period_spans(text: str) -> list[tuple[int, int]]:
    """Return understood annual forms, never bare dates or shorter/unknown periods.

    Full ranges must be valid full-year durations. An explicit fiscal identifier
    establishes its own year; this function never maps a calendar end to a fiscal year.
    """
    spans = [(m.start(), m.end()) for m in _FULL_ANNUAL.finditer(text)]
    for match in _ANNUAL_END.finditer(text):
        dates = list(re.finditer(_END_DATE + "|" + _KO_END_DATE, match.group(), re.I))
        if dates and _calendar_date(dates[-1].group()) is not None:
            spans.append((match.start(), match.end()))
    for match in _DATE_RANGE.finditer(text):
        if not _annual_range(match):
            continue
        start, end = match.span()
        prefix = re.search(r"(?:누계|보고기간)\s*[:：]?\s*(?:&cr;?\s*)?[(（]?\s*$", text[:start])
        if prefix is not None:
            start = prefix.start()
        suffix = re.match(r"\s*[)）]?\s*보고기간", text[end:])
        if suffix is not None:
            end += suffix.end()
        spans.append((start, end))
    # Merge overlapping duration/ending matches so consumers blank one complete form.
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def blank_annual_periods(text: str) -> str:
    """Blank shared annual forms without moving any reader's offsets."""
    for start, end in reversed(annual_period_spans(text)):
        text = text[:start] + " " * (end - start) + text[end:]
    return text


def header_period_residue(text: str) -> str:
    """Consume annual forms, retaining an unread-period marker for shorter ranges.

    Headers may separately consume bare end dates as identifiers. A shorter range
    must survive that step; a full year's cumulative marker is understood with it.
    """
    ranges = list(_DATE_RANGE.finditer(text))
    rest = blank_annual_periods(text)
    if ranges and not all(_annual_range(match) for match in ranges):
        return rest + " period "
    return rest.replace("누계", " ") if ranges else rest


def classify_period(text: str) -> PeriodKind:
    """Classify the whole sentence; any unconsumed date or shorter period wins."""
    text = normalize_fiscal_years(text)
    rest = blank_annual_periods(text)
    if PERIOD_WORDS.search(_DATE.sub(" ", rest)):
        return "subannual"
    if _DATE.search(rest):
        return "date"
    return "annual" if rest != text or _YEAR.search(rest) else "none"


def fiscal_year_spans(text: str) -> list[tuple[int, int, int]]:
    """Read explicit FY/fiscal identifiers; two digits always mean 2000–2099.

    The century is fixed, never inferred from the clock or a nearby cell. Callers
    retain their own identifier-versus-amount grammar before consuming these spans.
    """
    return [
        (m.start(), m.end(), int(m["year"]) + (2000 if len(m["year"]) == 2 else 0))
        for m in _FISCAL_YEAR.finditer(text)
    ]


def annual_fiscal_year_spans(text: str) -> list[tuple[int, int, int]]:
    """Bind an annual ending's dates to its explicit FY identifier, when present.

    No date-to-fiscal-year mapping is inferred. A form with no explicit identifier
    leaves the caller's existing calendar-year reading intact.
    """
    identifiers = fiscal_year_spans(text)
    spans: list[tuple[int, int, int]] = []
    for start, end in annual_period_spans(text):
        years = {year for first, last, year in identifiers if start <= first and last <= end}
        if len(years) == 1:
            spans.append((start, end, next(iter(years))))
    return spans


def normalize_fiscal_years(text: str) -> str:
    """Expand only explicit fiscal-year identifiers, preserving ordinary short numbers."""
    for start, end, year in reversed(fiscal_year_spans(text)):
        text = text[:start] + f"FY{year}" + text[end:]
    return text
