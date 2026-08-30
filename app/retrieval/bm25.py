"""Deterministic PostgreSQL BM25 retrieval over stored full-text lexemes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, get_args

from sqlalchemy import (
    Float,
    Integer,
    Select,
    SQLColumnExpression,
    String,
    bindparam,
    cast,
    delete,
    func,
    select,
    text,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf
from app.db.models import BM25CorpusStat, Chunk, ChunkLength, ChunkTerm, LexemeStat
from app.retrieval._sql import (
    TEXT_SEARCH_CONFIG,
    apply_filters,
    hit_columns,
    hit_order_by,
    positive_websearch_text,
    relaxed_websearch_query,
)
from app.retrieval.types import ChunkHit, RetrievalFilters, finite_float

BM25_IDF_VARIANTS: tuple[BM25Idf, ...] = get_args(BM25Idf)


@dataclass(frozen=True, slots=True)
class TermStatCounts:
    """Committed row counts for one complete BM25 statistic rebuild."""

    terms: int
    chunks: int
    lexemes: int


async def backfill_term_stats(session: AsyncSession) -> TermStatCounts:
    """Atomically rebuild every BM25 statistic from ``chunks.content_tsv``.

    Parameters
    ----------
    session : AsyncSession
        Idle session that owns the rebuild transaction.

    Returns
    -------
    TermStatCounts
        Committed term, chunk-length, and lexeme row counts.

    Raises
    ------
    RuntimeError
        If the session already owns an active transaction.

    Notes
    -----
    Source and derived-table locks keep the rebuilt rows and singleton corpus metadata
    on one consistent chunk snapshot.
    """
    if session.in_transaction():
        raise RuntimeError("backfill_term_stats requires a session without an active transaction")

    async with session.begin():
        await session.execute(text("LOCK TABLE chunks IN SHARE MODE"))
        await session.execute(
            text(
                "LOCK TABLE chunk_terms, chunk_lengths, lexeme_stats, bm25_corpus_stats "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )
        await session.execute(delete(BM25CorpusStat))
        await session.execute(delete(ChunkTerm))
        await session.execute(delete(ChunkLength))
        await session.execute(delete(LexemeStat))

        await session.execute(
            text(
                "INSERT INTO chunk_terms (chunk_id, lexeme, tf) "
                "SELECT c.id, t.lexeme, cardinality(t.positions) "
                "FROM chunks AS c CROSS JOIN LATERAL unnest(c.content_tsv) AS t "
                "WHERE t.positions IS NOT NULL AND cardinality(t.positions) > 0"
            )
        )
        await session.execute(
            text(
                "INSERT INTO chunk_lengths (chunk_id, dl) "
                "SELECT chunk_id, SUM(tf) FROM chunk_terms GROUP BY chunk_id"
            )
        )
        # Both derived statistics are partitioned by the chunk's corpus language:
        # the corpora share one table but are tokenized differently, so a global
        # N/avgdl/df would score each corpus against the other's distribution.
        await session.execute(
            text(
                "INSERT INTO lexeme_stats (language, lexeme, df) "
                "SELECT c.language, ct.lexeme, COUNT(*) "
                "FROM chunk_terms AS ct JOIN chunks AS c ON c.id = ct.chunk_id "
                "GROUP BY c.language, ct.lexeme"
            )
        )
        await session.execute(
            text(
                "INSERT INTO bm25_corpus_stats (language, n, avgdl) "
                "SELECT c.language, COUNT(*), AVG(cl.dl)::double precision "
                "FROM chunk_lengths AS cl JOIN chunks AS c ON c.id = cl.chunk_id "
                "GROUP BY c.language"
            )
        )

        row = (
            await session.execute(
                select(
                    select(func.count()).select_from(ChunkTerm).scalar_subquery().label("terms"),
                    select(func.count()).select_from(ChunkLength).scalar_subquery().label("chunks"),
                    select(func.count()).select_from(LexemeStat).scalar_subquery().label("lexemes"),
                )
            )
        ).one()
        counts = TermStatCounts(
            terms=int(row.terms),
            chunks=int(row.chunks),
            lexemes=int(row.lexemes),
        )

    return counts


def _idf_expression(
    variant: BM25Idf,
    corpus_size: SQLColumnExpression[Any],
    document_frequency: SQLColumnExpression[Any],
) -> ColumnElement[Any]:
    """Return the selected SQL inverse-document-frequency expression.

    Parameters
    ----------
    variant : BM25Idf
        Lucene's nonnegative variant or Robertson's signed variant.
    corpus_size : SQLColumnExpression[Any]
        Total number of chunks in the rebuilt corpus snapshot.
    document_frequency : SQLColumnExpression[Any]
        Chunks containing the current lexeme.

    Returns
    -------
    ColumnElement[Any]
        SQL logarithm expression for the selected variant.

    Raises
    ------
    ValueError
        If ``variant`` is unsupported.

    Notes
    -----
    Robertson can score corpus-wide terms negatively; Lucene remains nonnegative.
    """
    if variant not in BM25_IDF_VARIANTS:
        raise ValueError("idf must be 'lucene' or 'robertson'")
    size = cast(corpus_size, Float)
    df = cast(document_frequency, Float)
    ratio = (size - df + 0.5) / (df + 0.5)
    if variant == "lucene":
        return func.ln(1.0 + ratio)
    return func.ln(ratio)


def _validated_parameters(query: str, k: int, k1: float, b: float) -> tuple[float, float]:
    """Validate public BM25 inputs and return normalized numeric parameters."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    k1_message = "k1 must be a finite positive number"
    b_message = "b must be a finite number between 0 and 1"
    normalized_k1 = finite_float(k1, nonnumeric=k1_message, nonfinite=k1_message)
    normalized_b = finite_float(b, nonnumeric=b_message, nonfinite=b_message)
    if normalized_k1 <= 0:
        raise ValueError(k1_message)
    if not 0 <= normalized_b <= 1:
        raise ValueError(b_message)
    return normalized_k1, normalized_b


def bm25_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
    text_search_config: str = TEXT_SEARCH_CONFIG,
) -> Select[Any]:
    """Build a bound BM25 query with shared filters and deterministic ordering.

    Parameters
    ----------
    query : str
        Raw user query used for matching and positive score terms.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional shared evidence restrictions.
    k1 : float
        Positive term-frequency saturation value.
    b : float
        Length normalization in the inclusive range ``[0, 1]``.
    idf : BM25Idf
        Inverse-document-frequency variant.

    Returns
    -------
    Select[Any]
        Projected, filtered, and deterministically ordered SQL statement.

    Raises
    ------
    ValueError
        If query, limit, numeric parameters, or idf variant is invalid.

    Notes
    -----
    Scores use the atomically rebuilt corpus-size and average-length singleton row.
    """
    normalized_k1, normalized_b = _validated_parameters(query, k, k1, b)
    active_filters = filters or RetrievalFilters()

    parsed = func.websearch_to_tsquery(
        text_search_config,
        bindparam(
            "bm25_match_query",
            value=relaxed_websearch_query(query),
            type_=String(),
        ),
    ).label("tsquery")
    query_cte = select(parsed).cte("bm25_query").prefix_with("MATERIALIZED")
    tsquery = query_cte.c.tsquery
    query_terms = select(
        func.unnest(
            func.tsvector_to_array(
                func.to_tsvector(
                    text_search_config,
                    bindparam(
                        "bm25_positive_query",
                        value=positive_websearch_text(query),
                        type_=String(),
                    ),
                )
            )
        ).label("lexeme")
    ).subquery("bm25_query_terms")
    corpus = select(
        BM25CorpusStat.language,
        BM25CorpusStat.n,
        BM25CorpusStat.avgdl,
    ).subquery("bm25_corpus")

    k1_param = bindparam("bm25_k1", value=normalized_k1, type_=Float())
    b_param = bindparam("bm25_b", value=normalized_b, type_=Float())
    document_length = cast(ChunkLength.dl, Float)
    idf_term = _idf_expression(idf, corpus.c.n, LexemeStat.df)
    length_norm = 1.0 - b_param + b_param * document_length / corpus.c.avgdl
    saturation = (ChunkTerm.tf * (k1_param + 1.0)) / (ChunkTerm.tf + k1_param * length_norm)
    score = cast(func.sum(idf_term * saturation), Float).label("score")

    scores = (
        select(ChunkTerm.chunk_id.label("chunk_id"), score)
        .select_from(ChunkTerm)
        .join(Chunk, Chunk.id == ChunkTerm.chunk_id)
        .join(query_cte, true())
        .join(query_terms, query_terms.c.lexeme == ChunkTerm.lexeme)
        # Statistics join on the chunk's own language, so every chunk is scored
        # within its corpus even when the table hosts more than one.
        .join(
            LexemeStat,
            (LexemeStat.lexeme == ChunkTerm.lexeme) & (LexemeStat.language == Chunk.language),
        )
        .join(ChunkLength, ChunkLength.chunk_id == ChunkTerm.chunk_id)
        .join(corpus, corpus.c.language == Chunk.language)
        .where(Chunk.content_tsv.op("@@")(tsquery))
        .group_by(ChunkTerm.chunk_id)
        .subquery("bm25_scores")
    )

    statement = (
        select(*hit_columns(scores.c.score))
        .select_from(Chunk)
        .join(scores, scores.c.chunk_id == Chunk.id)
    )
    statement = apply_filters(statement, active_filters)
    return statement.order_by(*hit_order_by(scores.c.score.desc())).limit(
        bindparam("bm25_k", value=k, type_=Integer())
    )


async def bm25_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
    text_search_config: str = TEXT_SEARCH_CONFIG,
) -> list[ChunkHit]:
    """Rank chunks with BM25 and return complete typed evidence.

    Parameters
    ----------
    session : AsyncSession
        Session used for the search and statistic-readiness check.
    query : str
        Raw user query.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional shared evidence restrictions.
    k1 : float
        Positive term-frequency saturation value.
    b : float
        Length normalization in the inclusive range ``[0, 1]``.
    idf : BM25Idf
        Inverse-document-frequency variant.

    Returns
    -------
    list[ChunkHit]
        Complete evidence records carrying native BM25 scores.

    Raises
    ------
    RuntimeError
        If corpus statistics are missing or were invalidated by chunk writes.
    ValueError
        If public BM25 parameters are invalid.
    """
    result = await session.execute(
        bm25_statement(
            query, k, filters, k1=k1, b=b, idf=idf, text_search_config=text_search_config
        )
    )
    stats_ready = await session.scalar(select(func.count()).select_from(BM25CorpusStat))
    if not stats_ready:
        raise RuntimeError("BM25 statistics are missing or stale; rebuild them before searching")
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
