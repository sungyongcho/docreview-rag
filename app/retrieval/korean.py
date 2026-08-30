"""Corpus-language lexicalization shared by the seed path and the query paths.

PostgreSQL's ``english`` configuration stems nothing in Korean, and whitespace
tokenization treats the agglutinative variants 삼성전자는/삼성전자가 as different
terms, so the Korean corpus indexes character n-grams instead: the index side stores
``tokenize_korean_text(index_text)`` in ``chunks.lexical_text`` and the query side
runs the same function over the raw query. Both sides calling one function is the
contract — an index tokenized with one rule and a query with another silently
returns zero candidates, which is the failure this module exists to prevent.

``LEXICAL_PLANS`` is the one table pairing each corpus language with its index
transform, query transform, and text-search configuration. Every consumer — the
seed path, the retrieval service, and the evaluation retrievers — resolves the
pairing here instead of re-deriving it with its own ``== "ko"`` branch.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Final

from app.retrieval._sql import TEXT_SEARCH_CONFIG
from app.retrieval.types import RetrievalFilters

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


def tokenize_korean_text(text: str, *, grams: int = KOREAN_LEXICAL_GRAMS) -> str:
    """Return space-joined lexical tokens for Korean-corpus indexing and querying.

    Hangul runs become overlapping character n-grams; latin words and numbers stay
    whole so tickers, model names, and figures still match exactly. The output is
    consumed by ``to_tsvector('simple', ...)`` and ``websearch_to_tsquery('simple',
    ...)``, which both split on the spaces this function inserts.

    Parameters
    ----------
    text : str
        Raw text in its natural form; the caller never pre-tokenizes.
    grams : int
        N-gram width for Hangul runs. The measured default is the contract for
        stored rows: changing it invalidates every stored ``lexical_text``.
    """
    if grams < 1:
        raise ValueError("grams must be positive")
    tokens: list[str] = []
    for match in _LEXICAL_RUN_RE.finditer(text):
        run = match.group()
        if _HANGUL_RUN_RE.fullmatch(run):
            tokens.extend(hangul_ngrams(run, grams))
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
