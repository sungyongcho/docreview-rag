"""Korean lexical tokenization shared by the seed path and the query path.

PostgreSQL's ``english`` configuration stems nothing in Korean, and whitespace
tokenization treats the agglutinative variants 삼성전자는/삼성전자가 as different
terms, so the Korean corpus indexes character n-grams instead: the index side stores
``tokenize_korean_text(index_text)`` in ``chunks.lexical_text`` and the query side
runs the same function over the raw query. Both sides calling one function is the
contract — an index tokenized with one rule and a query with another silently
returns zero candidates, which is the failure this module exists to prevent.
"""

import re
from typing import Final

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
    for match in re.finditer(f"{_HANGUL_RUN_RE.pattern}|{_WORD_RUN_RE.pattern}", text):
        run = match.group()
        if _HANGUL_RUN_RE.fullmatch(run):
            tokens.extend(hangul_ngrams(run, grams))
        else:
            tokens.append(run.lower())
    return " ".join(tokens)
