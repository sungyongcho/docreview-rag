"""Query-language detection for the cross-lingual retrieval path."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Final, Literal

from app.retrieval.search.sql import TEXT_SEARCH_CONFIG
from app.retrieval.types import RetrievalFilters

QueryLanguage = Literal["en", "ko"]

# Korean reaches this boundary in three Unicode ranges: precomposed syllables,
# the conjoining jamo that decomposed (NFD) input carries, and the compatibility
# jamo an input method emits for a bare consonant or vowel. Scanning all three
# means a query is classified from its own characters, with no model, no API call,
# and no dependency on how the client normalized the text.
HANGUL_SYLLABLES = (0xAC00, 0xD7A3)
HANGUL_JAMO = (0x1100, 0x11FF)
HANGUL_COMPATIBILITY_JAMO = (0x3130, 0x318F)
HANGUL_RANGES = (HANGUL_SYLLABLES, HANGUL_JAMO, HANGUL_COMPATIBILITY_JAMO)


def contains_hangul(text: str) -> bool:
    """Return whether any character of ``text`` is a Hangul syllable or jamo."""
    return any(start <= ord(character) <= end for character in text for start, end in HANGUL_RANGES)


def detect_query_language(query: str) -> QueryLanguage:
    """Classify a nonblank query as Korean when it contains any Hangul.

    Presence, rather than script proportion, preserves mixed queries such as tickers
    and process nodes surrounded by Korean text.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    return "ko" if contains_hangul(query) else "en"


def detect_query_languages(query: str) -> tuple[QueryLanguage, ...]:
    """Return every supported script language visibly present in a query.

    Korean and Latin text can coexist in one issuer comparison. Returning both keeps
    lexical routing from collapsing a mixed query onto one corpus tokenizer. Numbers
    alone do not imply English; an otherwise script-free query retains the historical
    English default.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    languages: list[QueryLanguage] = []
    if any(character.isascii() and character.isalpha() for character in query):
        languages.append("en")
    if contains_hangul(query):
        languages.append("ko")
    return tuple(languages or ["en"])


# The Korean corpus is indexed under PostgreSQL's ``simple`` configuration: the
# n-grams are the lexemes, so no stemming or stop-word list may rewrite them.
KOREAN_TEXT_SEARCH_CONFIG: Final[str] = "simple"

# Grams per token. Measured 2026-08-30 on the DART FY2024 corpus against the 24
# positive Korean golden cases, hit_rate@5 / MRR@5 under BM25 ('simple' config):
# bigram 0.875/0.684, trigram 0.792/0.649, whitespace 0.792/0.653 — and under
# ts_rank_cd every variant collapses (0.33-0.42) because cover density carries no
# IDF to damp the grams a question's own particles contribute. Bigrams win with no
# added dependency, so a morphological analyzer was not brought in.
KOREAN_LEXICAL_GRAMS: Final[int] = 2

# Hangul syllables plus the jamo ranges an IME or NFD normalization can emit.
_HANGUL_RUN_RE: Final[re.Pattern[str]] = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]+")
# Everything else that carries lexical content: latin/digit words with the joiners
# filings use inside figures (300,870,903 stays one token, as in websearch parsing).
_WORD_RUN_RE: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z]+(?:[.,'′-][0-9A-Za-z]+)*")
# Compiled once: this runs per chunk at seed time and per query on the hot path.
_LEXICAL_RUN_RE: Final[re.Pattern[str]] = re.compile(
    f"{_HANGUL_RUN_RE.pattern}|{_WORD_RUN_RE.pattern}"
)


def hangul_ngrams(run: str, grams: int) -> list[str]:
    """Return the overlapping n-grams of one Hangul run, or the run when shorter."""
    if len(run) < grams:
        return [run]
    return [run[i : i + grams] for i in range(len(run) - grams + 1)]


def tokenize_korean_text(text: str) -> str:
    """Return space-joined lexical tokens for Korean-corpus indexing and querying.

    Hangul runs become overlapping character n-grams; latin words and numbers stay
    whole so tickers, model names, and figures still match exactly. The output is
    consumed by ``to_tsvector('simple', ...)`` and ``websearch_to_tsquery('simple',
    ...)``, which both split on the spaces this function inserts.

    Parameters
    ----------
    text : str
        Raw text in its natural form; the caller never pre-tokenizes.

    Notes
    -----
    Hangul runs use the ``KOREAN_LEXICAL_GRAMS`` n-gram width. That width is the
    contract for stored rows: changing it invalidates every stored ``lexical_text``.
    """
    tokens: list[str] = []
    for match in _LEXICAL_RUN_RE.finditer(text):
        run = match.group()
        if _HANGUL_RUN_RE.fullmatch(run):
            tokens.extend(hangul_ngrams(run, KOREAN_LEXICAL_GRAMS))
        else:
            tokens.append(run.lower())
    return " ".join(tokens)


def _identity(text: str) -> str:
    """Return the text unchanged; the English index needs no pre-tokenization."""
    return text


@dataclass(frozen=True, slots=True)
class LexicalPlan:
    """How one corpus language reaches the shared tsvector index.

    ``index_transform`` produces the stored ``chunks.lexical_text`` — ``None`` keeps
    the column NULL so the generated tsvector falls through to ``index_text``.
    ``query_transform`` prepares a query for ``websearch_to_tsquery``. Both sides
    must agree with ``text_search_config``, or lexical retrieval parses queries
    under a configuration the rows were never indexed with and silently returns
    zero candidates.
    """

    index_transform: Callable[[str], str] | None
    query_transform: Callable[[str], str]
    text_search_config: str


LEXICAL_PLANS: Final[Mapping[str, LexicalPlan]] = MappingProxyType(
    {
        "en": LexicalPlan(
            index_transform=None,
            query_transform=_identity,
            text_search_config=TEXT_SEARCH_CONFIG,
        ),
        "ko": LexicalPlan(
            index_transform=tokenize_korean_text,
            query_transform=tokenize_korean_text,
            text_search_config=KOREAN_TEXT_SEARCH_CONFIG,
        ),
    }
)


def lexical_plan(language: str) -> LexicalPlan:
    """Return the lexical plan for one corpus language.

    Raises
    ------
    ValueError
        If no plan covers the language; retrieving or seeding under a guessed
        tokenization would desynchronize the index and query sides.
    """
    plan = LEXICAL_PLANS.get(language)
    if plan is None:
        known = ", ".join(sorted(LEXICAL_PLANS))
        raise ValueError(f"no lexical plan for language {language!r}; known: {known}")
    return plan


def lexical_corpus_language(filters: RetrievalFilters | None) -> str:
    """Return the corpus language the lexical component must tokenize for.

    An absent or empty language filter keeps the committed English behavior; a
    filter naming exactly one language selects that language's plan. A filter
    mixing corpus languages is refused rather than guessed.

    Raises
    ------
    ValueError
        If ``filters.languages`` names more than one language — the corpora are
        tokenized differently, so one lexical statement cannot serve both.
    """
    languages = set(filters.languages) if filters is not None else set()
    if not languages:
        return "en"
    if len(languages) > 1:
        raise ValueError("lexical retrieval cannot span corpus languages; filter to exactly one")
    return next(iter(languages))
