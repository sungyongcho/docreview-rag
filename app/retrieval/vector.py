"""Exact pgvector cosine retrieval with shared evidence filters."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM, Chunk, Document
from app.retrieval.lexical import filter_predicates, hit_columns, hit_order_by, needs_document_join
from app.retrieval.types import ChunkHit, RetrievalFilters, finite_float


def validate_query_vector(values: Sequence[float], *, dimensions: int = DIM) -> list[float]:
    """Return a finite vector whose shape matches the database column.

    Parameters
    ----------
    values : Sequence[float]
        Query-vector components supplied by the embedding provider.
    dimensions : int
        Required database-vector width.

    Returns
    -------
    list[float]
        Materialized finite floats in caller order.

    Raises
    ------
    ValueError
        If the vector has the wrong width or contains a boolean, nonnumeric, or
        non-finite component.
    """
    if len(values) != dimensions:
        raise ValueError(f"query vector has dimension {len(values)}, expected {dimensions}")

    return [
        finite_float(
            component,
            nonnumeric="query vector contains a nonnumeric component",
            nonfinite="query vector contains a non-finite component",
        )
        for component in values
    ]


def _filtered_statement(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    """Apply exact-match chunk and document filters with AND semantics.

    Parameters
    ----------
    statement : Select[Any]
        Chunk-based statement to restrict.
    filters : RetrievalFilters
        Canonical exact-match restrictions shared by all retrieval paths.

    Returns
    -------
    Select[Any]
        Statement with the required document join and filter predicates.
    """
    if needs_document_join(filters):
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    return statement.where(*filter_predicates(filters))


def vector_search_statement(
    query_vector: Sequence[float],
    *,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build the exact cosine query used by runtime and SQL contract tests.

    Parameters
    ----------
    query_vector : Sequence[float]
        Finite query embedding with the database column width.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional exact-match restrictions.

    Returns
    -------
    Select[Any]
        Fully projected, filtered, and deterministically ordered SQL statement.

    Raises
    ------
    ValueError
        If ``k`` is not positive or the query vector is invalid.

    Notes
    -----
    This remains an exact scan until M3 supplies evidence for an approximate index.
    """
    if k <= 0:
        raise ValueError("vector search k must be positive")
    vector = validate_query_vector(query_vector)
    restrictions = filters or RetrievalFilters()
    distance = Chunk.embedding.cosine_distance(vector).label("distance")
    statement = select(*hit_columns(distance)).where(Chunk.embedding.is_not(None))
    statement = _filtered_statement(statement, restrictions)
    return statement.order_by(*hit_order_by(distance.asc())).limit(k)


async def vector_search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Return complete chunk evidence ordered by cosine similarity.

    Parameters
    ----------
    session : AsyncSession
        Session used for the single exact-search statement.
    query_vector : Sequence[float]
        Finite query embedding with the database column width.
    k : int
        Maximum number of hits; zero returns without database access.
    filters : RetrievalFilters | None
        Optional exact-match restrictions.

    Returns
    -------
    list[ChunkHit]
        Complete evidence records with cosine similarity scores.

    Raises
    ------
    ValueError
        If ``k`` is negative or the query vector is invalid.
    """
    if k < 0:
        raise ValueError("vector search k must not be negative")
    if k == 0:
        return []

    statement = vector_search_statement(query_vector, k=k, filters=filters)
    rows = (await session.execute(statement)).mappings().all()
    return [
        ChunkHit(
            chunk_id=row["chunk_id"],
            doc_id=row["doc_id"],
            item=row["item"],
            kind=row["kind"],
            citation=row["citation"],
            start_char=row["start_char"],
            end_char=row["end_char"],
            source_sha256=row["source_sha256"],
            body=row["body"],
            context_header=row["context_header"],
            index_text=row["index_text"],
            score=1.0 - float(row["distance"]),
        )
        for row in rows
    ]
