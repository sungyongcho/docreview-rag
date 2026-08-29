"""Compose normalized vector and lexical retrieval into inspectable fused evidence.

Both database components share one ``AsyncSession`` sequentially, native scores remain
inside their retrieval lanes, and optional reranking changes only the final hit scores.
"""

import math
import re
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_IDF,
    DEFAULT_BM25_K1,
    BM25Idf,
    LexicalRanker,
)
from app.db.models import DIM
from app.retrieval.bm25 import BM25_IDF_VARIANTS, bm25_search
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

RankedChunkId = Annotated[StrictInt, Field(gt=0)]
ScoreStage = Literal["rrf", "reranker"]
LEXICAL_RANKERS: tuple[LexicalRanker, ...] = get_args(LexicalRanker)
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def normalize_query(query: str) -> str:
    """Expand R&D variants without changing unrelated ampersands."""
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
    lexical_ranker: LexicalRanker = "ts_rank_cd",
    bm25_k1: float = DEFAULT_BM25_K1,
    bm25_b: float = DEFAULT_BM25_B,
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
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
    lexical_ranker : LexicalRanker, optional
        Explicit lexical algorithm. PostgreSQL ``ts_rank_cd`` is the stable default.
    bm25_k1 : float, optional
        Positive BM25 term-frequency saturation.
    bm25_b : float, optional
        BM25 length normalization in the inclusive range ``[0, 1]``.
    bm25_idf : BM25Idf, optional
        BM25 inverse-document-frequency variant.

    Returns
    -------
    RetrievalResult
        Final evidence and rank-only component provenance.

    Raises
    ------
    ValueError
        If query, limits, lexical settings, or embedding dimensions are invalid.

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

    if lexical_ranker not in LEXICAL_RANKERS:
        raise ValueError("lexical_ranker must be 'ts_rank_cd' or 'bm25'")
    if not math.isfinite(bm25_k1) or bm25_k1 <= 0:
        raise ValueError("bm25_k1 must be a finite positive number")
    if not math.isfinite(bm25_b) or not 0 <= bm25_b <= 1:
        raise ValueError("bm25_b must be a finite number between 0 and 1")
    if bm25_idf not in BM25_IDF_VARIANTS:
        raise ValueError("bm25_idf must be 'lucene' or 'robertson'")

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
        """Retrieve candidates with the configured lexical ranker."""
        if lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                component_query,
                component_k,
                component_filters,
                k1=bm25_k1,
                b=bm25_b,
                idf=bm25_idf,
            )
        else:
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
