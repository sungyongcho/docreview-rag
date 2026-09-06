"""PostgreSQL full-text lexical retrieval.

This is the project's mandatory lexical baseline. It uses PostgreSQL full-text
search with cover-density ranking; ``ts_rank_cd`` is not literal BM25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, SQLColumnExpression, Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters

TS_RANK_NORMALIZATION = 4 | 1
TEXT_SEARCH_CONFIG = "english"


def filter_predicates(filters: RetrievalFilters) -> tuple[ColumnElement[bool], ...]:
    """Translate shared exact-match filters to composable SQL predicates.

    Every retrieval strategy (lexical, vector, BM25) restricts the same chunk
    and document dimensions, so this module owns the single translation from
    :class:`RetrievalFilters` to SQL. Predicates referencing ``Document`` are
    only valid on statements that join it; use :func:`needs_document_join`.

    Parameters
    ----------
    filters : RetrievalFilters
        Canonical chunk and document restrictions.

    Returns
    -------
    tuple[ColumnElement[bool], ...]
        Predicates combined with AND by the caller.
    """
    predicates: list[ColumnElement[bool]] = []
    if filters.doc_ids:
        predicates.append(Chunk.doc_id.in_(filters.doc_ids))
    if filters.tickers:
        predicates.append(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        predicates.append(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        predicates.append(Document.form.in_(filters.forms))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(Chunk.kind.in_(filters.kinds))
    return tuple(predicates)


def needs_document_join(filters: RetrievalFilters) -> bool:
    """Return whether :func:`filter_predicates` output references ``Document``.

    Joining ``documents`` unconditionally would tax the common unfiltered path,
    so every strategy joins it only when a document-level filter is active.

    Parameters
    ----------
    filters : RetrievalFilters
        Canonical chunk and document restrictions.

    Returns
    -------
    bool
        True when a ticker, fiscal-year, or form filter requires the join.
    """
    return bool(filters.tickers or filters.fiscal_years or filters.forms)


def hit_columns(score: ColumnElement[Any]) -> tuple[SQLColumnExpression[Any], ...]:
    """Return the shared :class:`ChunkHit` projection with the score column last.

    Parameters
    ----------
    score : ColumnElement[Any]
        Strategy-specific score (or distance) column, already labeled.

    Returns
    -------
    tuple[SQLColumnExpression[Any], ...]
        Columns matching the ``ChunkHit`` contract in declaration order.
    """
    return (
        Chunk.id.label("chunk_id"),
        Chunk.doc_id,
        Chunk.item,
        Chunk.kind,
        Chunk.citation,
        Chunk.start_char,
        Chunk.end_char,
        Chunk.source_sha256,
        Chunk.body,
        Chunk.context_header,
        Chunk.index_text,
        score,
    )


def hit_order_by(score_ordering: ColumnElement[Any]) -> tuple[ColumnElement[Any], ...]:
    """Return the deterministic ordering with the score direction first.

    Parameters
    ----------
    score_ordering : ColumnElement[Any]
        Strategy-specific score ordering, e.g. ``score.desc()`` or
        ``distance.asc()``.

    Returns
    -------
    tuple[ColumnElement[Any], ...]
        Ordering that breaks score ties by stable source identity.
    """
    return (
        score_ordering,
        Chunk.doc_id.asc(),
        Chunk.source_sha256.asc(),
        Chunk.start_char.asc(),
        Chunk.end_char.asc(),
        Chunk.id.asc(),
    )


def lexical_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build a safe PostgreSQL FTS statement ranked by cover density.

    Parameters
    ----------
    query : str
        Raw user text parsed by ``websearch_to_tsquery``.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional exact-match restrictions.

    Returns
    -------
    Select[Any]
        Fully projected, filtered, and deterministically ordered FTS statement.

    Raises
    ------
    ValueError
        If ``query`` is blank or ``k`` is not positive.

    Notes
    -----
    SQLAlchemy binds ``query`` as a value instead of interpolating it. PostgreSQL FTS
    is the lexical baseline here; this statement does not implement BM25.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    active_filters = filters or RetrievalFilters()
    parsed = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)
    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, func.replace(cast(parsed, Text), "&", "|"))
    score = func.ts_rank_cd(Chunk.content_tsv, tsquery, TS_RANK_NORMALIZATION).label("score")
    statement = select(*hit_columns(score))
    if needs_document_join(active_filters):
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    return (
        statement.where(Chunk.content_tsv.op("@@")(tsquery), *filter_predicates(active_filters))
        .order_by(*hit_order_by(score.desc()))
        .limit(k)
    )


async def lexical_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Run the PostgreSQL FTS baseline and return typed, deterministically ordered hits.

    Parameters
    ----------
    session : AsyncSession
        Session used for the single lexical-search statement.
    query : str
        Raw user query.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional exact-match restrictions.

    Returns
    -------
    list[ChunkHit]
        Complete evidence records carrying native cover-density scores.

    Raises
    ------
    ValueError
        If ``query`` is blank or ``k`` is not positive.

    Notes
    -----
    The score is native ``ts_rank_cd``, not BM25 or a probability. Fusion must consume
    its rank instead of comparing it directly with another strategy's score.
    """
    result = await session.execute(lexical_statement(query, k, filters))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
