"""Filtered, deterministic pgvector cosine retrieval."""

from collections.abc import Sequence
import math
from numbers import Real
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM, Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters


def validate_query_vector(values: Sequence[float], *, dimensions: int = DIM) -> list[float]:
    """Return a finite vector whose shape matches the database column."""
    if len(values) != dimensions:
        raise ValueError(f"query vector has dimension {len(values)}, expected {dimensions}")
    vector: list[float] = []
    for component in values:
        if isinstance(component, bool) or not isinstance(component, Real):
            raise ValueError("query vector contains a nonnumeric component")
        number = float(component)
        if not math.isfinite(number):
            raise ValueError("query vector contains a non-finite component")
        vector.append(number)
    return vector


def _filtered_statement(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    """Apply exact-match chunk and document filters with AND semantics."""
    if filters.tickers or filters.fiscal_years or filters.forms:
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    if filters.doc_ids:
        statement = statement.where(Chunk.doc_id.in_(filters.doc_ids))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates = []
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        statement = statement.where(or_(*item_predicates))
    if filters.kinds:
        statement = statement.where(Chunk.kind.in_(filters.kinds))
    if filters.tickers:
        statement = statement.where(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        statement = statement.where(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        statement = statement.where(Document.form.in_(filters.forms))
    return statement


def vector_search_statement(
    query_vector: Sequence[float],
    *,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build the exact cosine query used by runtime and SQL contract tests."""
    if k <= 0:
        raise ValueError("vector search k must be positive")
    vector = validate_query_vector(query_vector)
    restrictions = filters or RetrievalFilters()
    distance = Chunk.embedding.cosine_distance(vector).label("distance")
    statement = select(Chunk, distance).where(Chunk.embedding.is_not(None))
    statement = _filtered_statement(statement, restrictions)
    return statement.order_by(
        distance.asc(),
        Chunk.doc_id.asc(),
        Chunk.source_sha256.asc(),
        Chunk.start_char.asc(),
        Chunk.end_char.asc(),
        Chunk.id.asc(),
    ).limit(k)


async def vector_search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Return complete chunk evidence ordered by cosine similarity."""
    if k < 0:
        raise ValueError("vector search k must not be negative")
    if k == 0:
        return []

    statement = vector_search_statement(query_vector, k=k, filters=filters)
    rows = (await session.execute(statement)).all()
    return [
        ChunkHit(
            chunk_id=chunk.id,
            doc_id=chunk.doc_id,
            item=chunk.item,
            kind=chunk.kind,
            citation=chunk.citation,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            source_sha256=chunk.source_sha256,
            body=chunk.body,
            context_header=chunk.context_header,
            index_text=chunk.index_text,
            score=1.0 - float(distance),
        )
        for chunk, distance in rows
    ]
