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
from app.db.models import Chunk, ChunkLength, ChunkTerm, Document, LexemeStat
from app.retrieval.lexical import (
    TEXT_SEARCH_CONFIG,
    filter_predicates,
    hit_columns,
    hit_order_by,
    needs_document_join,
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

    The function owns one transaction so readers observe either the previous
    complete statistic set or the new one. The source-table lock prevents a
    concurrent chunk write from producing a mixed-corpus snapshot, while the
    derived-table lock serializes competing rebuilds without blocking readers.
    """
    if session.in_transaction():
        raise RuntimeError("backfill_term_stats requires a session without an active transaction")

    async with session.begin():
        await session.execute(text("LOCK TABLE chunks IN SHARE MODE"))
        await session.execute(
            text("LOCK TABLE chunk_terms, chunk_lengths, lexeme_stats IN SHARE ROW EXCLUSIVE MODE")
        )
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
        await session.execute(
            text(
                "INSERT INTO lexeme_stats (lexeme, df) "
                "SELECT lexeme, COUNT(*) FROM chunk_terms GROUP BY lexeme"
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
    """Return the SQL inverse document frequency for one lexeme.

    Both published variants are available because they disagree about common
    terms. Robertson's original is ``ln((N - df + 0.5) / (df + 0.5))``, which turns
    negative once a lexeme appears in more than half the corpus; a chunk is then
    penalised for containing it, and on a small corpus that inverts the ranking
    outright. Lucene adds one before the logarithm, so its idf never drops below
    zero and a common term merely stops contributing. Lucene is the default for
    that reason; Robertson stays selectable because the difference is the whole
    lesson.

    ``df`` is clamped to the corpus size because a lexeme cannot occur in more
    chunks than exist. The clamp only bites on stale statistics: deleting chunks
    cascades their ``chunk_terms`` and ``chunk_lengths`` rows away but leaves
    ``lexeme_stats`` untouched, and an unclamped Robertson numerator would then go
    negative and make PostgreSQL raise on ``ln`` of a nonpositive argument.
    """
    if variant not in BM25_IDF_VARIANTS:
        raise ValueError("idf must be 'lucene' or 'robertson'")
    size = cast(corpus_size, Float)
    df = func.least(cast(document_frequency, Float), size)
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
) -> Select[Any]:
    """Build a bound BM25 query with shared filters and deterministic ordering."""
    normalized_k1, normalized_b = _validated_parameters(query, k, k1, b)
    active_filters = filters or RetrievalFilters()

    query_terms = select(
        func.unnest(
            func.tsvector_to_array(
                func.to_tsvector(
                    TEXT_SEARCH_CONFIG,
                    bindparam("bm25_query", value=query, type_=String()),
                )
            )
        ).label("lexeme")
    ).subquery("bm25_query_terms")
    corpus = select(
        func.count(ChunkLength.chunk_id).label("n"),
        func.avg(ChunkLength.dl).label("avgdl"),
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
        .join(query_terms, query_terms.c.lexeme == ChunkTerm.lexeme)
        .join(LexemeStat, LexemeStat.lexeme == ChunkTerm.lexeme)
        .join(ChunkLength, ChunkLength.chunk_id == ChunkTerm.chunk_id)
        .join(corpus, true())
        .group_by(ChunkTerm.chunk_id)
        .subquery("bm25_scores")
    )

    statement = (
        select(*hit_columns(scores.c.score))
        .select_from(Chunk)
        .join(scores, scores.c.chunk_id == Chunk.id)
    )
    if needs_document_join(active_filters):
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    return (
        statement.where(*filter_predicates(active_filters))
        .order_by(*hit_order_by(scores.c.score.desc()))
        .limit(bindparam("bm25_k", value=k, type_=Integer()))
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
) -> list[ChunkHit]:
    """Rank chunks by BM25 and return complete, deterministically ordered hits."""
    result = await session.execute(bm25_statement(query, k, filters, k1=k1, b=b, idf=idf))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
