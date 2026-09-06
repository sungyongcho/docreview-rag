"""Exact pgvector cosine retrieval with shared evidence filters."""

from collections.abc import Sequence
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM, Chunk, ChunkEmbedding, SnapshotChunk
from app.retrieval._sql import apply_filters, hit_columns, hit_order_by
from app.retrieval.embeddings import EmbeddingIdentity, matching_embedding
from app.retrieval.types import ChunkHit, RetrievalFilters, finite_float


def validate_query_vector(values: Sequence[float], *, dimensions: int = DIM) -> list[float]:
    """Return a finite, nonzero vector matching the database dimensions.

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
        If width, numeric type, finiteness, or vector norm is invalid.
    """
    if len(values) != dimensions:
        raise ValueError(f"query vector has dimension {len(values)}, expected {dimensions}")

    vector = [
        finite_float(
            component,
            nonnumeric="query vector contains a nonnumeric component",
            nonfinite="query vector contains a non-finite component",
        )
        for component in values
    ]
    if not any(vector):
        raise ValueError("query vector must have a nonzero norm")
    return vector


def vector_search_statement(
    query_vector: Sequence[float],
    *,
    k: int,
    filters: RetrievalFilters | None = None,
    identity: EmbeddingIdentity,
) -> Select[Any]:
    """Build the exact cosine query used by runtime and SQL contract tests.

    Parameters
    ----------
    query_vector : Sequence[float]
        Finite, nonzero query embedding with database dimensions.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional exact-match restrictions.

    Returns
    -------
    Select[Any]
        Projected, filtered, and deterministically ordered SQL statement.

    Raises
    ------
    ValueError
        If ``k`` or the query vector is invalid.

    Notes
    -----
    The query remains an exact scan until measurements justify an approximate index.
    """
    if k <= 0:
        raise ValueError("vector search k must be positive")
    vector = validate_query_vector(query_vector, dimensions=identity.dimensions)
    restrictions = filters or RetrievalFilters()
    source = Chunk if restrictions.snapshot_id is None else SnapshotChunk
    embedding = ChunkEmbedding.embedding if source is Chunk else SnapshotChunk.embedding
    distance = embedding.cast(Vector(identity.dimensions)).cosine_distance(vector).label("distance")
    statement = select(*hit_columns(distance, source)).select_from(source)
    if source is Chunk:
        statement = statement.join(ChunkEmbedding, matching_embedding(identity))
    else:
        statement = statement.where(
            SnapshotChunk.embedding_provider == identity.provider,
            SnapshotChunk.embedding_model == identity.model,
            SnapshotChunk.embedding_dimensions == identity.dimensions,
            SnapshotChunk.embedding_tokenizer == identity.tokenizer,
            SnapshotChunk.embedding.is_not(None),
        )
    statement = apply_filters(statement, restrictions, source)
    return statement.order_by(*hit_order_by(distance.asc(), source)).limit(k)


async def vector_search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    identity: EmbeddingIdentity,
) -> list[ChunkHit]:
    """Return complete chunk evidence ordered by exact cosine similarity.

    Parameters
    ----------
    session : AsyncSession
        Session used for the single search statement.
    query_vector : Sequence[float]
        Finite, nonzero query embedding with database dimensions.
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

    statement = vector_search_statement(query_vector, k=k, filters=filters, identity=identity)
    rows = (await session.execute(statement)).mappings().all()
    hits: list[ChunkHit] = []
    for row in rows:
        values = dict(row)
        distance = float(values.pop("distance"))
        values["score"] = 1.0 - distance
        hits.append(ChunkHit.model_validate(values))
    return hits
