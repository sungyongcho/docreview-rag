"""Compose normalized vector and lexical retrieval into inspectable fused evidence.

Both database components share one ``AsyncSession`` sequentially, native scores remain
inside their retrieval lanes, and optional reranking changes only the final hit scores.
"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

RankedChunkId = Annotated[StrictInt, Field(gt=0)]
ScoreStage = Literal["rrf", "reranker"]
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def normalize_query(query: str) -> str:
    """Expand the common R&D abbreviation for both retrieval components.

    Parameters
    ----------
    query : str
        Validated user query shared by vector and lexical retrieval.

    Returns
    -------
    str
        Original query when no ampersand is present, otherwise the query with
        R&D spelling variants expanded to ``research development``.
    """
    if "&" not in query:
        return query
    return RESEARCH_AND_DEVELOPMENT.sub("research development", query)


class ComponentRankings(BaseModel):
    """Immutable component ranks that prevent native scores from being compared.

    The model records only positive chunk identifiers in retrieval order and rejects
    unknown fields. Vector and lexical score scales therefore remain inside their
    respective adapters instead of leaking into rank fusion or response provenance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    vector: tuple[RankedChunkId, ...]
    lexical: tuple[RankedChunkId, ...]


class RetrievalResult(BaseModel):
    """Immutable fused evidence with the component ranks that produced it.

    ``score_stage`` identifies whether final hit scores came from fusion or reranking,
    while ``component_rankings`` preserves the pre-fusion proposal order independently
    of those scores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
    score_stage: ScoreStage
    component_rankings: ComponentRankings


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    reranker: RerankProvider | None = None,
) -> RetrievalResult:
    """Run vector then lexical search through one session and fuse their ranks.

    Parameters
    ----------
    session : AsyncSession
        Session shared sequentially by the vector and lexical database queries.
    query : str
        Nonblank user query normalized once for both retrieval components.
    provider : EmbeddingProvider | None, optional
        Query embedding provider, or the configured provider when omitted.
    k : int, optional
        Positive number of final hits to return.
    candidate_k : int | None, optional
        Component candidate depth. ``None`` expands to ``max(20, 4 * k)``.
    filters : RetrievalFilters | None, optional
        Canonical evidence restrictions applied identically to both components.
    rrf_k : int, optional
        Positive reciprocal-rank-fusion constant.
    reranker : RerankProvider | None, optional
        Optional second-stage scorer for the fused candidate list.

    Returns
    -------
    RetrievalResult
        Final evidence and rank-only component provenance.

    Raises
    ------
    ValueError
        If the query or limits are invalid, or embedding dimensions do not match.

    Notes
    -----
    The component adapters close over one ``AsyncSession`` and must remain sequential;
    concurrent use of that session is unsafe. Without a reranker, the service slices the
    fused candidate pool to ``k``. With a reranker, the complete pool is retained and the
    reranker supplies final scores without changing the recorded component ranks.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    limit = max(20, 4 * k) if candidate_k is None else candidate_k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    normalized_query = normalize_query(query)

    active_provider = provider if provider is not None else get_embedding_provider()
    if active_provider.dimensions != DIM:
        raise ValueError(
            f"embedding provider dimension {active_provider.dimensions} does not match "
            f"database dimension {DIM}"
        )

    vector_hits: list[ChunkHit] = []
    lexical_hits: list[ChunkHit] = []

    async def vector_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        """Embed and retrieve vector candidates through the shared session."""
        query_vector = await active_provider.embed_query(component_query)
        hits = await vector_search(
            session,
            query_vector,
            k=component_k,
            filters=component_filters,
        )
        vector_hits.extend(hits)
        return hits

    async def lexical_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        """Retrieve PostgreSQL full-text candidates through the shared session."""
        hits = await lexical_search(
            session,
            component_query,
            component_k,
            component_filters,
        )
        lexical_hits.extend(hits)
        return hits

    fused = await hybrid_search(
        normalized_query,
        limit,
        filters,
        vector_search=vector_component,
        lexical_search=lexical_component,
        rrf_k=rrf_k,
    )
    if reranker is not None:
        fused = await rerank_hits(
            query,
            fused,
            provider=reranker,
            top_k=k,
        )
    else:
        fused = fused[:k]
    return RetrievalResult(
        hits=tuple(fused),
        score_stage="reranker" if reranker is not None else "rrf",
        component_rankings=ComponentRankings(
            vector=tuple(hit.chunk_id for hit in vector_hits),
            lexical=tuple(hit.chunk_id for hit in lexical_hits),
        ),
    )
