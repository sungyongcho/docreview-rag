"""Check that every figure an answer states is its cited evidence's value for one item.

Citation checks prove which chunks an answer cites, not that its numbers come from
them. This module reads each figure of an answer as a claim: the figure, the unit
written with it, the financial item its own words name and, when the answer dates it,
its year.

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
word or currency, the table by its own unit declarations. When the unit of the item's
cells is absent, not fully readable or contradictory, or the answer states none, no
unit is guessed and the figure is ``unit_unverified``: withheld, neither confirmed nor
reported as absent. One such figure withholds the whole answer, even beside a figure
that is wrong.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
import re
from typing import Literal

from app.figures.currency import same_currency
from app.figures.tables import TableCellReading
from app.figures.text import BARE_YEAR, YEAR, Figure, blank_answer, figure_spans
from app.figures.vocabulary import (
    ANSWER_SAME_ITEM_QUALIFIER,
    CHANGES,
    CONNECTIVES,
    ENGLISH_PHRASES,
    FILLERS,
    KOREAN_PHRASES,
    TOKEN,
    phrase_key,
)

# Rounding is accepted only for figures stated with at least this many significant digits.
_MIN_ROUNDED_DIGITS = 3


_STRONG = re.compile(r"(?<![\\*])\*\*(?!\s)([^*\n]+?)(?<![\s\\])\*\*(?!\*)")
# The prefix is emitted by ingestion's context-header builder, not filing prose.
_ISSUER_CONTEXT = re.compile(r"(?P<issuer>[^\n]+?) FY\d{4} · ")


# A sentence ends at terminal punctuation followed by space, or at ";" or a line break.
_SENTENCE_BREAK = re.compile(r"(?<!\bvs)(?<!U\.S)[.!?。](?=\s|$)|[;\n]")


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


@dataclass(frozen=True, slots=True)
class EvidenceText:
    """One cited chunk as the checker reads it.

    ``table_cells`` are the stored readings of a table chunk's figure-bearing cells,
    in fragment order (see :func:`read_table_cells`); None for running text.
    """

    chunk_id: int
    body: str
    context_header: str
    table_cells: Sequence[TableCellReading] | None = None


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

    figure: Figure
    item: str | None
    year: int | None
    dated_ambiguously: bool
    change: bool


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
        if stem in KOREAN_PHRASES:
            if ending == "의":
                return _Word(start, text, "unknown")
            return _Word(start, text, "item", KOREAN_PHRASES[stem], joins)
        if stem in _KOREAN_FILLERS or _KOREAN_UNIT.fullmatch(stem):
            return _Word(start, text, "filler", joins=joins)
    return _Word(start, text, "unknown")


def _english_word(start: int, text: str) -> _Word:
    """Classify one English word, digit run or symbol outside any item phrase."""
    key = text.casefold().replace("’", "'")
    if key in CHANGES:
        return _Word(start, text, "change", joins=key in {"up", "down"})
    if key in CONNECTIVES:
        return _Word(start, text, "filler", joins=True)
    if key in FILLERS or _POSSESSIVE.fullmatch(text) or BARE_YEAR.fullmatch(text):
        return _Word(start, text, "filler")
    return _Word(start, text, "unknown")


def _words(masked: str, start: int, end: int) -> list[_Word]:
    """Classify the words of ``masked[start:end]``, joining item phrases into one word."""
    tokens = [
        (start + match.start(), match.group(0)) for match in TOKEN.finditer(masked[start:end])
    ]
    words: list[_Word] = []
    index = 0
    while index < len(tokens):
        at, text = tokens[index]
        keys = tuple(phrase_key(token) for _, token in tokens[index:])
        phrase = next(
            (
                (len(phrase_words), item)
                for phrase_words, item in ENGLISH_PHRASES
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
    found = [figure for figure in figure_spans(masked[:end]) if figure.start >= start]
    if not found:
        return []
    years = [
        (match.start(), int(match.group(0)))
        for match in YEAR.finditer(text, start, end)
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
        before = blank_answer(masked[: match.start()])
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
    masked = blank_answer(
        ANSWER_SAME_ITEM_QUALIFIER.sub(lambda match: " " * len(match.group(0)), subject)
    )
    bounds = [0, *(match.start() for match in _SENTENCE_BREAK.finditer(masked)), len(masked)]
    return [
        claim
        for first, last in zip(bounds, bounds[1:], strict=False)
        for claim in _sentence_claims(masked, text, first, last)
    ]


def _within(figure: Figure, amount: Decimal, target: Decimal, scale: Decimal) -> bool:
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
    figure: Figure,
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
    same = same_currency(figure.stated_currency, currency)
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
    state, confirms a level; a cell scoped to a dimension holds a part of the entity,
    not its item, so it is not compared. A cell of the item whose unit, or the claim's own unit, is
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
        if not claim.change and cell.item == item and cell.scope is None
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
    cells = [cell for item in evidence if item.table_cells is not None for cell in item.table_cells]
    data_values = {value for cell in cells for value in cell.values}
    facts = [
        claim
        for item in evidence
        for claim in _claims(item.context_header)
        + (
            [fact for fact in _claims(item.body) if fact.figure.value not in data_values]
            if item.table_cells is not None
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
