"""Production composition for deterministic hybrid retrieval."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf, LexicalRanker, get_settings
from app.db.models import DIM
from app.retrieval.bm25 import BM25_IDF_VARIANTS, bm25_search
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.language import detect_query_language
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

RankedChunkId = Annotated[int, Field(gt=0)]
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def _normalize_query(query: str) -> str:
    """Expand the common R&D abbreviation for embedding and PostgreSQL FTS parity."""
    return RESEARCH_AND_DEVELOPMENT.sub("research development", query)


class ComponentRankings(BaseModel):
    """Ranked chunk identities from each retrieval component, without raw scores."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vector: tuple[RankedChunkId, ...]
    lexical: tuple[RankedChunkId, ...]


class RetrievalResult(BaseModel):
    """Fused evidence plus inspectable rank-only component provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
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
    route_by_language: bool | None = None,
    lexical_ranker: LexicalRanker | None = None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
) -> RetrievalResult:
    """Run vector then lexical search through one session and fuse their ranks.

    The component adapters close over the same ``AsyncSession``. They are awaited
    sequentially by ``hybrid_search`` because concurrent use of one session is unsafe.
    Component scores stay inside their native lanes; only ranked chunk identities are
    exposed beside the fused hits. An omitted candidate limit expands to
    ``max(20, 4 * k)`` at this production boundary.

    With no reranker the fused list is truncated to ``k`` by fusion itself, which is
    the M2.7 behaviour. Supplying one turns the request into two stages: fusion keeps
    the full candidate list, and the reranker rescores it and returns the top ``k``.
    Retrieval therefore goes wide cheaply first, then narrow expensively.

    Reranked hits carry cross-encoder scores rather than fusion scores. Component
    rankings are unaffected because they record what each retriever proposed, not
    what survived reranking.

    ``route_by_language`` resolves from ``Settings.query_language_routing`` when it is
    omitted. With routing on and a Korean query, the lexical component is skipped and
    ranking is vector-only. The lexical index is built with the ``english`` text-search
    configuration, so that component contributes nothing for Korean anyway; asking it
    anyway costs a database round trip and, worse, gives fusion a component whose
    silence is indistinguishable from a considered "no candidates". A skipped component
    is visible instead: ``ComponentRankings.lexical`` is empty, so the taken route can
    be read off the result rather than inferred from the configuration.
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

    settings = get_settings()
    active_lexical_ranker = settings.lexical_ranker if lexical_ranker is None else lexical_ranker
    active_bm25_k1 = settings.bm25_k1 if bm25_k1 is None else bm25_k1
    active_bm25_b = settings.bm25_b if bm25_b is None else bm25_b
    if active_lexical_ranker not in ("ts_rank_cd", "bm25"):
        raise ValueError("lexical_ranker must be 'ts_rank_cd' or 'bm25'")
    if active_bm25_k1 <= 0:
        raise ValueError("bm25_k1 must be positive")
    if not 0 <= active_bm25_b <= 1:
        raise ValueError("bm25_b must be between 0 and 1")
    active_bm25_idf = settings.bm25_idf if bm25_idf is None else bm25_idf
    if active_bm25_idf not in BM25_IDF_VARIANTS:
        raise ValueError("bm25_idf must be 'lucene' or 'robertson'")
    normalized_query = _normalize_query(query)
    active_routing = (
        settings.query_language_routing if route_by_language is None else route_by_language
    )
    skip_lexical = active_routing and detect_query_language(normalized_query) == "ko"

    active_provider = provider or get_embedding_provider()
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
        if skip_lexical:
            return []
        if active_lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                component_query,
                component_k,
                component_filters,
                k1=active_bm25_k1,
                b=active_bm25_b,
                idf=active_bm25_idf,
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
        limit if reranker is not None else k,
        filters,
        vector_search=vector_component,
        lexical_search=lexical_component,
        candidate_k=limit,
        rrf_k=rrf_k,
    )
    if reranker is not None:
        fused = await rerank_hits(
            normalized_query,
            fused,
            provider=reranker,
            top_k=k,
        )
    return RetrievalResult(
        hits=tuple(fused),
        component_rankings=ComponentRankings(
            vector=tuple(hit.chunk_id for hit in vector_hits),
            lexical=tuple(hit.chunk_id for hit in lexical_hits),
        ),
    )
