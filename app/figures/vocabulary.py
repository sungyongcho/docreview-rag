"""The closed vocabulary figures and their items are read with.

The words around a figure are read with a closed vocabulary: listed item phrases,
connectives, years, units, currency and a few verbs. Any other word leaves the figure
without an item, so wording the checker does not understand fails closed instead of
borrowing an item named elsewhere.
"""

from collections.abc import Collection, Sequence
import re
from typing import Literal

from app.figures.currency import CURRENCY

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
TOKEN = re.compile(r"[A-Za-z]+(?:[&'’-][A-Za-z]+)*['’]?|[가-힣]+|\d+(?:[.,]\d+)*|\S")


# The only parentheticals that keep a label or answer phrase the same item. A label may
# cite a list of notes ("(Notes 2 and 3)"); in an answer a note reference has exactly
# one short number, so a figure written after it or in its place stays a figure.
_QUALIFIER_WORD = r"\s*[(（]\s*(?:loss|losses|손실|(?:notes?|주석?)\s*"
_QUALIFIER = _QUALIFIER_WORD + r"\d+[a-z]?"
_QUALIFIER_LIST = r"(?:\s*(?:[,，、~-]|and|&)\s*\d+[a-z]?)*"
_QUALIFIER_END = r")\s*[)）]"
SAME_ITEM_QUALIFIER = re.compile(_QUALIFIER + _QUALIFIER_LIST + _QUALIFIER_END, re.IGNORECASE)
ANSWER_SAME_ITEM_QUALIFIER = re.compile(
    _QUALIFIER_WORD + r"\d{1,3}[a-z]?" + _QUALIFIER_END, re.IGNORECASE
)


# English words that may stand around a figure without changing which item it is.
FILLERS = frozenset(
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
        *(",", ":", "(", ")", "-", "–", "—", "·", ".", "%", "'", '"', *CURRENCY),
    }
)
# Words after which the next words describe another figure.
CONNECTIVES = frozenset(
    {",", "(", "and", "but", "while", "whereas", "versus", "vs", "compared", "with", "from"}
    | {"to", "than"}
)
# Words that make a figure a change, not a level ("grew 14%", "increased by 300").
CHANGES = frozenset(
    {
        *("grew", "grow", "grows", "growth", "increased", "increase", "increases"),
        *("decreased", "decrease", "decreases", "rose", "rise", "rises", "fell", "fall"),
        *("declined", "decline", "declines", "up", "down", "higher", "lower", "gained"),
        *("dropped", "drop", "jumped"),
    }
)


def phrase_key(text: str) -> str:
    """Normalize a phrase for lookup: casefolded, single-spaced, plain hyphens and quotes."""
    text = text.casefold().replace("–", "-").replace("—", "-").replace("’", "'")
    return " ".join(text.split())


PHRASE_ITEMS = {
    phrase_key(phrase): item for item, phrases in _ITEM_PHRASES.items() for phrase in phrases
}
# English phrases as word sequences, longest first; Korean phrases as whole stems.
ENGLISH_PHRASES = sorted(
    (
        (tuple(TOKEN.findall(phrase)), item)
        for phrase, item in PHRASE_ITEMS.items()
        if phrase.isascii()
    ),
    key=lambda entry: len(entry[0]),
    reverse=True,
)
KOREAN_PHRASES = {phrase: item for phrase, item in PHRASE_ITEMS.items() if not phrase.isascii()}
# Words of the English item phrases ("net", "tax"), never mistaken for currency codes.
ITEM_WORDS = frozenset(word for words, _ in ENGLISH_PHRASES for word in words)


# How a question's words are read around its item phrases (see :func:`items_named`).
# Words that leave an item plain: fillers without "%", "percent" and "us" ("US
# revenue" is a segment), connectives, question words, a fiscal year in any form
# ("2024", "FY2024", "fiscal 2024", "2024년", "annual", "연간"), the question's own company ("the
# company's", "당사의") and words that only restate the entity scope ("consolidated",
# "total", "연결 기준", "전체", "총"). "별도", "segment" and "부문" narrow the scope, so
# they are not among them.
#
# The words were taken from every question the project holds (golden sets, tests,
# lessons): those that only ask to be told, shown, found or cited, or name the unit
# of the answer, cannot change which figure is asked. Comparison, growth, ratio,
# segment, product, geography, basis and sub-annual words were left out.
_UNIT_WORDS = frozenset(
    {"usd", "krw", "won", "dollar", "dollars", "jpy", "cny", "rmb", "eur", "gbp", "cad"}
    | {"aud", "hkd", "twd", "sgd", "chf", "million", "millions", "billion", "billions"}
    | {"thousand", "thousands", "trillion", "trillions", "bn", "mn", *CURRENCY}
)
_UNIT_WORDS_KO = frozenset({"원", "천원", "만원", "백만원", "억원", "조원", "달러", "백만달러"})
_QUESTION_PASS = (FILLERS - {"%", "percent", "us"} - _UNIT_WORDS) | CONNECTIVES
_QUESTION_PASS |= {"fy", "company's", "companies'", "consolidated", "total"}
_QUESTION_PASS |= {"what", "what's", "which", "how", "much", "did", "does", "do", "please"}
_QUESTION_PASS |= {"tell", "show", "give", "me", "report", "annual", "full-year"}
_QUESTION_PASS |= {"find", "cite", "citing", "citation", "citations", "evidence"}
_QUESTION_PASS |= {"source", "sources", "provide", "along"}
_QUESTION_PASS_KO = frozenset({"년", "년도", "회계연도", "사업연도", "각각", "회사의", "당사의"})
_QUESTION_PASS_KO |= {"연결", "기준", "연결기준", "전체", "총", "연간"}
_QUESTION_PASS_KO |= {"근거", "출처", "인용", "함께", "주세요", "줘"}
# Words that ask how much, or ask to be told, found or shown ("알려줘", "찾아주세요").
_QUESTION_WORDS_KO = ("얼마", "무엇", "몇", "어떻게", "알려", "찾아", "보여", "말해")
# Words a question may name an item by beyond the answers' phrases: "net revenue" is
# revenue there, so "순매출" is too; "R&D" is research and development.
_QUESTION_SYNONYMS = {
    "순매출": "revenue",
    "순매출액": "revenue",
    "r&d expense": "research and development",
    "r&d expenses": "research and development",
}
_QUESTION_ENGLISH = sorted(
    [
        *ENGLISH_PHRASES,
        *((tuple(TOKEN.findall(p)), item) for p, item in _QUESTION_SYNONYMS.items() if p.isascii()),
    ],
    key=lambda entry: len(entry[0]),
    reverse=True,
)
_QUESTION_KOREAN = KOREAN_PHRASES | {
    p: item for p, item in _QUESTION_SYNONYMS.items() if not p.isascii()
}
# Scope words that may be written glued to a Korean item ("연결매출액", "총매출액").
_SCOPE_PREFIXES_KO = ("연결", "전체", "총")
# Periods shorter than a fiscal year. Stored cells carry a fiscal year only, so such a
# period always qualifies the item, whatever list its words may also appear in.
_SUB_ANNUAL = frozenset(
    {"q", "h", "quarter", "quarters", "quarterly", "half", "halves", "half-year"}
    | {"semiannual", "semi-annual", "interim", "month", "months", "ytd", "year-to-date"}
    | {"three-month", "six-month", "nine-month", "first-half", "second-half"}
)
_SUB_ANNUAL_KO = ("분기", "반기")
# Only these end a sentence of a question; "." does not ("U.S.", "Inc.").
_QUESTION_ENDS = frozenset({"?", "!", "？", "！"})
_QUESTION_YEAR = re.compile(r"(?:19|20)\d{2}")
# A day of the month after its month ("December 31, 2024") is passed over.
_QUESTION_DAY = re.compile(r"\d{1,2}")
_MONTHS = frozenset(
    {"january", "february", "march", "april", "may", "june", "july", "august"}
    | {"september", "october", "november", "december"}
)
# Korean particles and copulas a question word may carry ("매출액은", "million인가");
# "의" makes an item word a modifier.
_QUESTION_ENDINGS_KO = (
    *("이었습니까", "였습니까", "이었나요", "입니까", "입니다", "였나요", "인가요"),
    *("이었나", "일까요", "이에요", "으로는", "에서는", "인가", "인지", "였나", "일까"),
    *("예요", "으로", "에서", "까지", "부터", "이며", "이고"),
    *("은", "는", "이", "가", "을", "를", "의", "에", "도", "와", "과", "로", "만", "고", "며"),
)
# Words an issuer name made only of would blank out of the vocabulary itself.
_VOCABULARY_WORDS = FILLERS | CONNECTIVES | ITEM_WORDS | _QUESTION_ENDS | _QUESTION_PASS
_VOCABULARY_WORDS |= _UNIT_WORDS | _UNIT_WORDS_KO | _QUESTION_PASS_KO | set(_QUESTION_KOREAN)

# ``unit`` is a currency or scale word: the unit of the answer after an item phrase
# ("revenue in USD millions", "몇 백만원인가"), a qualifier before one ("USD revenue").
type _QuestionKind = Literal["item", "pass", "unit", "end", "unknown"]


def _korean_question_word(word: str) -> tuple[_QuestionKind, str | None]:
    """Classify one Korean question word, reading at most one particle off its end.

    A scope word written glued to the front of an item ("연결매출액") keeps the item;
    a word naming a quarter or half ("1분기", "상반기") is unknown.
    """
    if any(period in word for period in _SUB_ANNUAL_KO):
        return "unknown", None
    if word.startswith(_QUESTION_WORDS_KO):
        return "pass", None
    for prefix in ("", *_SCOPE_PREFIXES_KO):
        if prefix and not word.startswith(prefix):
            continue
        body = word[len(prefix) :]
        for ending in ("", *_QUESTION_ENDINGS_KO):
            if ending and not body.endswith(ending):
                continue
            stem = body[: len(body) - len(ending)]
            if stem in _QUESTION_KOREAN:
                return ("unknown", None) if ending == "의" else ("item", _QUESTION_KOREAN[stem])
            if not prefix and stem in _QUESTION_PASS_KO:
                return "pass", None
            if not prefix and stem in _UNIT_WORDS_KO:
                return "unit", None
    return "unknown", None


def _question_word(word: str) -> _QuestionKind:
    """Classify one question word outside any English item phrase."""
    key = phrase_key(word)
    if key in _SUB_ANNUAL:
        return "unknown"
    if key in _QUESTION_ENDS:
        return "end"
    if key in _QUESTION_PASS or _QUESTION_YEAR.fullmatch(key):
        return "pass"
    if key in _UNIT_WORDS:
        return "unit"
    return "unknown"


def _plain_sentences(kinds: Sequence[_QuestionKind]) -> bool:
    """Whether every sentence holding an item phrase holds no unknown word.

    A sentence ends at "?" or "!"; a sentence without an item phrase is not read. A
    unit word before the sentence's first item phrase is unknown.
    """
    sentence: list[_QuestionKind] = []
    for kind in (*kinds, "end"):
        if kind == "unit":
            kind = "pass" if "item" in sentence else "unknown"
        if kind != "end":
            sentence.append(kind)
            continue
        if "item" in sentence and "unknown" in sentence:
            return False
        sentence = []
    return True


def _issuer_names(issuers: Collection[str]) -> re.Pattern[str] | None:
    """Match the question's issuer names as whole names, with a possessive or particle.

    A name made only of vocabulary words ("Revenue", "US", "Total") or naming an item
    is ignored, so an issuer can never blank an item or unlock a qualifier; nor can a
    word inside a longer name ("Data" leaves "Center" in "Data Center revenue").
    """
    names: set[str] = set()
    for issuer in issuers:
        name = " ".join(issuer.split())
        words = TOKEN.findall(phrase_key(name))
        if not words or phrase_key(name) in PHRASE_ITEMS or name in _QUESTION_SYNONYMS:
            continue
        if all(word in _VOCABULARY_WORDS for word in words):
            continue
        names.add(name)
    if not names:
        return None
    spelled = "|".join(
        re.escape(name).replace(r"\ ", r"\s+") for name in sorted(names, key=len, reverse=True)
    )
    particles = "|".join(sorted(_QUESTION_ENDINGS_KO, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{spelled})(?:['’]s|['’]|{particles})?(?!\w)", re.IGNORECASE)


def _question_words(
    text: str, issuers: Collection[str]
) -> tuple[list[str], list[_QuestionKind], list[tuple[int, int, str]]]:
    """Classify a question's words after blanking its issuer names.

    Returns the written words, each word's kind and the item phrases as
    ``(start, end, item)`` word spans. A Korean particle written glued to the word
    before it ("revenue는") is read as that word's particle.
    """
    pattern = _issuer_names(issuers)
    if pattern is not None:
        text = pattern.sub(" ", text)
    matches = list(TOKEN.finditer(SAME_ITEM_QUALIFIER.sub(" ", text)))
    written = [match.group(0) for match in matches]
    words = [phrase_key(word) for word in written]
    kinds: list[_QuestionKind] = ["unknown"] * len(words)
    spans: list[tuple[int, int, str]] = []
    for phrase, item in _QUESTION_ENGLISH:
        size = len(phrase)
        for start in range(len(words) - size + 1):
            if (
                all(kind == "unknown" for kind in kinds[start : start + size])
                and tuple(words[start : start + size]) == phrase
            ):
                spans.append((start, start + size, item))
                covered: list[_QuestionKind] = ["item"] * size
                kinds[start : start + size] = covered
    for index, word in enumerate(words):
        if kinds[index] == "item":
            continue
        glued = index > 0 and matches[index].start() == matches[index - 1].end()
        if glued and word in _QUESTION_ENDINGS_KO and kinds[index - 1] != "unknown":
            kind: _QuestionKind = "pass"
        elif "가" <= word[0] <= "힣":
            kind, item = _korean_question_word(word)
            if item is not None:
                spans.append((index, index + 1, item))
        elif _QUESTION_DAY.fullmatch(word) and index and words[index - 1] in _MONTHS:
            kind = "pass"
        else:
            kind = _question_word(written[index])
        kinds[index] = kind
    return written, kinds, spans


def items_named(text: str, *, issuers: Collection[str] = ()) -> frozenset[str]:
    """Return the financial items a question names, read with the answers' vocabulary.

    Rule: an item phrase names its item only when every other word of its sentence
    is a filler, connective, question word, fiscal year, entity-scope word, issuer
    name or another item phrase; any other word anywhere in that sentence, including
    a period shorter than a fiscal year ("Q4", "상반기"), qualifies it, and then the
    question names no item at all, so a total annual row never answers a qualified
    question. Words that only ask to be told, shown, found or cited ("알려줘", "with
    citations") are plain; a currency or scale word is plain only after an item phrase,
    as the answer's unit ("몇 USD million인가"), never before one ("USD revenue").

    English phrases match whole words, longest first; a Korean word names an item when
    it is a listed phrase with at most one particle or copula, so "매출원가" is never also
    read as "매출" and "영업이익률" names nothing; a question may also say "순매출" or
    "R&D expense". A "(loss)" or note reference keeps the item, as in a row label. A
    question naming no listed phrase names no item: nothing is inferred from other words.

    Boundary: a sentence ends only at "?" or "!", so a qualifier in another such
    sentence ("Data Center grew! What was revenue?") is not read; a qualifier left
    unwritten, or an issuer name that is itself a segment, is not detected.

    Parameters
    ----------
    text : str
        The question.
    issuers : Collection[str]
        Names and aliases of the companies the question is about. Each is blanked as
        a whole name, case-insensitively, with its possessive ("AMD's", "Devices'")
        or Korean particle ("삼성전자의"), before items are read. No other company
        name is guessed, so without them a company name next to an item qualifies it.
    """
    _, kinds, spans = _question_words(text, issuers)
    plain = _plain_sentences(kinds)
    return frozenset(item for _, _, item in spans) if plain else frozenset()
