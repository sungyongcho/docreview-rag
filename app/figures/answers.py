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
mismatch when that item's value sits only in another known period. The claim and the
cell must also agree in direction: a claim states a loss when its figure is written
negative ("-1,641", "(1,641)", "△1,234") or its item by a loss phrase ("net loss",
"영업손실"), a gain otherwise; a cell's direction is its signed value. Equal
magnitudes in opposite directions are not a match, and a cell or claim whose
direction is not established ("▲", "Net loss | 1,641") is withheld. Change claims
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
from app.figures.text import (
    BARE_YEAR,
    YEAR,
    Figure,
    blank,
    blank_answer,
    figure_spans,
    unit_follows,
)
from app.figures.vocabulary import (
    ANSWER_SAME_ITEM_QUALIFIER,
    CHANGES,
    CONNECTIVES,
    ENGLISH_PHRASES,
    FILLERS,
    KOREAN_PHRASES,
    SAME_ITEM_QUALIFIER,
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
_KOREAN_FILLERS |= {"기록", "수준", "규모", "각각", "회계연도"}
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


# What a report says in place of an answer that ``unit_unverified`` withholds.
UNIT_UNVERIFIED_ANSWER = (
    "The cited evidence names this item, but the unit or sign of its figures could not be "
    "confirmed, so no figure is reported."
)
UNIT_UNVERIFIED_ANSWER_KO = (
    "인용 근거에 해당 항목은 있지만 수치의 단위나 부호를 확인할 수 없어 수치를 보고하지 않습니다."
)
# Why such an answer is withheld: the unit, the currency or the direction is not established.
UNIT_UNVERIFIED_RATIONALE = (
    "The cited table states no readable unit or explicit currency, or contradictory ones, in "
    "its own notes, cells or a caption linked to it, the answer states none, or the table or "
    "the answer does not establish whether the figure is a gain or a loss."
)
UNIT_UNVERIFIED_RATIONALE_KO = (
    "인용한 표 자체나 셀, 표에 연결된 단위 주석에서 단위나 명시적 통화를 확인할 수 없거나 서로 "
    "다르거나, 답변에 단위나 통화가 없거나, 표나 답변이 수치의 손익 방향을 확정하지 않습니다."
)


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
    ``joins`` marks a connective: what follows it describes the next figure. ``loss``
    marks an item named by one of the vocabulary's loss phrases ("net loss", "영업손실").
    """

    start: int
    text: str
    kind: Literal["item", "filler", "change", "unknown"]
    item: str | None = None
    joins: bool = False
    loss: bool = False


@dataclass(frozen=True, slots=True)
class _Claim:
    """One figure with the item, year and kind its own words give it.

    ``year`` is None when the claim is undated; ``dated_ambiguously`` when its words
    name more than one year. ``change`` marks a change claim ("grew 14%"). ``loss``
    says the item was named by a loss phrase. ``negative`` is the direction the claim
    states: a loss when its figure is written negative or its item by a loss phrase,
    a gain otherwise, None when its sign marker is ambiguous ("▲").
    """

    figure: Figure
    item: str | None
    year: int | None
    dated_ambiguously: bool
    change: bool
    loss: bool = False
    negative: bool | None = False


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
            return _Word(start, text, "item", KOREAN_PHRASES[stem], joins, "손실" in stem)
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
            length, item = phrase
            loss = any(key in {"loss", "losses"} for key in keys[:length])
            words.append(_Word(at, text, "item", item, loss=loss))
            index += length
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


def _sentence_claims(masked: str, text: str, start: int, end: int, answer: bool) -> list[_Claim]:
    """Read the claims of one sentence ``[start, end)``; ``answer`` as in :func:`_claims`.

    The words before the first figure, between figures and after the last one are
    split into each figure's head (before it) and tail (after it). A figure's item is
    the only item phrase of its head; with no item phrase there, a figure continues the
    item of the figure before it in the same sentence. An unknown word in its head or
    tail, an item phrase in its tail, or two items in its head leave it without one.
    """
    spans = figure_spans(masked[:end], answer=answer)
    found = [figure for figure in spans if figure.start >= start]
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
        losses = {word.loss for word in head if word.kind == "item"}
        unreadable = any(word.kind == "unknown" for word in (*head, *tail)) or any(
            word.kind == "item" for word in tail
        )
        item: str | None
        loss = False
        if unreadable or len(items) > 1:
            item = None
        elif items:
            item = items.pop()
            loss = True in losses
        else:
            item = claims[-1].item if claims else None
            loss = claims[-1].loss if claims else False
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
                loss,
                _negative(masked, figure, loss),
            )
        )
    return claims


def _negative(masked: str, figure: Figure, loss: bool) -> bool | None:
    """Return the direction a figure's own notation and its item's words state.

    A figure is written negative by a leading "-" or "△" ("-1,641", "-$1,641",
    "△1,234") or by parentheses around its digits ("(1,641)", "$(1,641)",
    "($1,641)"); a parenthesis that belongs to the sentence ("(25,785 million)")
    is not a sign. "▲" marks a loss in some filings and an increase in others, so its
    direction is None. A loss phrase ("net loss", "영업손실") states a loss too.
    """
    text = figure.text
    if text.startswith("▲"):
        return None
    before = masked[: figure.unit_start if 0 <= figure.unit_start < figure.start else figure.start]
    before = before.rstrip(" \t")
    written = (
        text.startswith(("-", "△"))
        or (text.startswith("(") and text.endswith(")"))
        or (before.endswith(("-", "−", "△")) and not before[:-1][-1:].isalnum())
        or (before.endswith("(") and text.endswith(")"))
    )
    return written or loss


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


def _claims(text: str, *, answer: bool = False, issuer: str | None = None) -> list[_Claim]:
    """Read every figure of a text as a claim, sentence by sentence.

    ``answer`` reads a model's answer, whose identifiers have bounded shapes so that no
    amount drops out of the check. A cited passage or header is a filing's own text and
    keeps the filing rules (a label may cite a list of notes), so a reference number in
    it never becomes a fact that could confirm a claim.
    """
    formatted = _STRONG.sub(lambda match: "  " + match[1] + "  ", text)
    subject = _issuer_subjects(formatted, issuer)
    qualifier, identifiers = (
        (ANSWER_SAME_ITEM_QUALIFIER, blank_answer) if answer else (SAME_ITEM_QUALIFIER, blank)
    )

    def qualified(match: re.Match[str]) -> str:
        """Blank a same-item parenthetical unless an answer writes a unit after it."""
        if answer and unit_follows(subject, match.end()):
            return match.group(0)
        return " " * len(match.group(0))

    masked = identifiers(qualifier.sub(qualified, subject))
    bounds = [0, *(match.start() for match in _SENTENCE_BREAK.finditer(masked)), len(masked)]
    return [
        claim
        for first, last in zip(bounds, bounds[1:], strict=False)
        for claim in _sentence_claims(masked, text, first, last, answer)
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


def _written(figure: Figure) -> str:
    """Return a figure as the answer wrote it, without a parenthesis that is not its own.

    "(1,234)" is a figure in parentheses; in "(Note 2: 99,999)" or "(99,999 million)" the
    parenthesis belongs to the sentence.
    """
    text = figure.text
    return text.strip("()") if text.startswith("(") != text.endswith(")") else text


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
    shown = _written(figure)
    negative = claim.negative

    def directed(outcome: _Comparison, other: Decimal, established: bool) -> _Comparison:
        """Hold a match whose direction is unknown; refuse one in the other direction."""
        if outcome != "match" or claim.change:
            return outcome
        if not established or negative is None:
            return "uncertain"
        return "no" if other != 0 and (other < 0) != negative else outcome

    if figure.value is None or item is None or claim.dated_ambiguously:
        return FigureCheck(shown, "unverified", (), item), False
    value = figure.value
    wanted = {claim.year} if claim.year is not None else requested

    def in_period(years: frozenset[int]) -> bool:
        """Whether a cell's column is one fiscal year of the claim's period.

        A column of several years (a spanning header nothing narrows, "2023-2024")
        holds no one year's value, so it belongs to no single-year period.
        """
        return not wanted or (len(years) == 1 and years <= wanted)

    compared = [
        (
            cell.years,
            _best(
                {
                    directed(
                        _compare(
                            figure,
                            value,
                            abs(v),
                            cell.scale,
                            cell.percent,
                            cell.currency,
                            cell.marked,
                        ),
                        v,
                        "direction" not in cell.overrides,
                    )
                    for v in cell.values
                }
            ),
        )
        for cell in cells
        if not claim.change and cell.item == item and cell.evidence_eligible
    ]
    certain = [years for years, outcome in compared if outcome == "match"]
    unsure = [years for years, outcome in compared if outcome == "uncertain"]
    if any(in_period(years) for years in certain):
        evidenced = tuple(sorted(frozenset[int]().union(*certain)))
        outside = bool(requested) and claim.year is not None and claim.year not in requested
        return FigureCheck(shown, "verified", evidenced, item), outside
    if unsure and (not certain or any(in_period(years) for years in unsure)):
        # No unit is guessed, so the digits cannot pick a cell: report the item's cells of
        # the claim's period, or all of them when none is in that period.
        held = [years for years in unsure if in_period(years)] or unsure
        evidenced = tuple(sorted(frozenset[int]().union(*held)))
        return FigureCheck(shown, "unit_unverified", evidenced, item), False
    if certain:
        evidenced = tuple(sorted(frozenset[int]().union(*certain)))
        # Only cells of one known other year make it another period's value.
        verdict: Verdict = (
            "period_mismatch" if all(len(years) == 1 for years in certain) else "unverified"
        )
        return FigureCheck(shown, verdict, evidenced, item), False
    outcome = _best(
        {
            directed(
                _compare(
                    figure,
                    value,
                    fact.figure.value,
                    fact.figure.stated_scale,
                    fact.figure.percent,
                    fact.figure.stated_currency,
                    bool(fact.figure.currency),
                ),
                -fact.figure.value if fact.negative else fact.figure.value,
                fact.negative is not None,
            )
            for fact in facts
            if not wanted
            and fact.item == item
            and not fact.dated_ambiguously
            and fact.change == claim.change
            and fact.figure.value is not None
        }
    )
    return FigureCheck(shown, _FACT_VERDICTS[outcome], (), item), False


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
    facts = [
        claim
        for item in evidence
        if item.table_cells is None
        for claim in _claims(item.context_header) + _claims(item.body)
    ]
    judged = [
        _judge(claim, cells, facts, requested)
        for claim in _claims(answer, answer=True, issuer=_cited_issuer(evidence))
    ]
    anchored = any(check.verdict == "verified" and not outside for check, outside in judged)
    return FiguresResult(
        tuple(
            replace(check, verdict="period_mismatch") if outside and not anchored else check
            for check, outside in judged
        )
    )
