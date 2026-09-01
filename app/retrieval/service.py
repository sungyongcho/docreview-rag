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
from app.retrieval.hybrid import DEFAULT_RRF_K, fuse_ranked_lists
from app.retrieval.korean import lexical_plan
from app.retrieval.language import detect_query_languages
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

# Kept as a patchable compatibility seam for older focused tests and callers. The
# service now fans out language lanes and fuses them directly with fuse_ranked_lists.
hybrid_search = None

RankedChunkId = Annotated[StrictInt, Field(gt=0)]
ScoreStage = Literal["rrf", "reranker"]
RetrievalStrategy = Literal["vector", "lexical", "hybrid"]
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
    vector_by_language: dict[str, tuple[RankedChunkId, ...]] = Field(default_factory=dict)
    lexical: tuple[RankedChunkId, ...]
    lexical_by_language: dict[str, tuple[RankedChunkId, ...]] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Immutable fused evidence with the component ranks that produced it.

    ``score_stage`` identifies whether final hit scores came from fusion or reranking,
    while ``component_rankings`` preserves the pre-fusion proposal order independently
    of those scores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
    candidates: tuple[ChunkHit, ...] = ()
    score_stage: ScoreStage
    component_rankings: ComponentRankings

    @property
    def candidate_pool(self) -> tuple[ChunkHit, ...]:
        """Return the full ranked pool, falling back for legacy injected results."""
        return self.candidates or self.hits


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    query_variants: dict[str, str] | None = None,
    strategy: RetrievalStrategy = "hybrid",
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    reranker: RerankProvider | None = None,
    route_by_language: bool = False,
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
    route_by_language : bool, optional
        Whether a query in a different language than the corpus skips the lexical
        component. Callers decide; the service never reads ``Settings``, so a
        measured arm cannot inherit a query path it did not declare.
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
    The corpus language comes from ``filters.languages`` alone — never from the
    script of the query — and selects the lexical tokenization: a single ``"ko"``
    filter parses the query with the same n-gram tokenizer the Korean rows were
    indexed with. A filter mixing corpus languages is rejected because one lexical
    statement cannot parse a query under two configurations at once.

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
    active_filters = filters or RetrievalFilters()
    corpus_languages = active_filters.languages or ("en",)
    query_languages = set(detect_query_languages(normalized_query))

    if strategy not in {"vector", "lexical", "hybrid"}:
        raise ValueError("strategy must be vector, lexical, or hybrid")
    active_provider = provider
    if strategy != "lexical":
        active_provider = provider if provider is not None else get_embedding_provider()
        if active_provider.dimensions != DIM:
            raise ValueError(
                f"embedding provider dimension {active_provider.dimensions} does not match "
                f"database dimension {DIM}"
            )

    vector_hits: list[ChunkHit] = []
    vector_by_language: dict[str, tuple[RankedChunkId, ...]] = {}
    lexical_hits: list[ChunkHit] = []
    lexical_by_language: dict[str, tuple[RankedChunkId, ...]] = {}

    async def vector_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        """Embed and retrieve vector candidates through the shared session."""
        if active_provider is None:
            raise AssertionError("vector retrieval requires an embedding provider")
        query_vector = await active_provider.embed_query(component_query)
        hits = await vector_search(
            session,
            query_vector,
            k=component_k,
            filters=component_filters,
            identity=active_provider.identity,
        )
        vector_hits.extend(hits)
        return hits

    async def lexical_component(language: str) -> list[ChunkHit]:
        """Retrieve one corpus-language lane with its matching tokenizer."""
        if route_by_language and language not in query_languages:
            lexical_by_language[language] = ()
            return []
        plan = lexical_plan(language)
        lane_query = (query_variants or {}).get(language, normalized_query)
        lexical_query = plan.query_transform(lane_query)
        text_search_config = plan.text_search_config
        if not lexical_query.strip():
            lexical_by_language[language] = ()
            return []
        component_filters = active_filters.model_copy(update={"languages": (language,)})
        if lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                lexical_query,
                limit,
                component_filters,
                k1=bm25_k1,
                b=bm25_b,
                idf=bm25_idf,
                text_search_config=text_search_config,
            )
        else:
            hits = await lexical_search(
                session,
                lexical_query,
                limit,
                component_filters,
                text_search_config=text_search_config,
            )
        lexical_hits.extend(hits)
        lexical_by_language[language] = tuple(hit.chunk_id for hit in hits)
        return hits

    if strategy in {"vector", "hybrid"} and query_variants:
        vector_ranked = []
        for language in corpus_languages:
            lane_filters = active_filters.model_copy(update={"languages": (language,)})
            lane = await vector_component(
                query_variants.get(language, normalized_query),
                limit,
                lane_filters,
            )
            vector_by_language[language] = tuple(hit.chunk_id for hit in lane)
            vector_ranked.append(lane)
    elif strategy in {"vector", "hybrid"}:
        lane = await vector_component(normalized_query, limit, active_filters)
        vector_ranked = [lane]
    else:
        vector_ranked = []
    lexical_ranked = (
        [await lexical_component(language) for language in corpus_languages]
        if strategy in {"lexical", "hybrid"}
        else []
    )
    fused = fuse_ranked_lists((*vector_ranked, *lexical_ranked), limit, rrf_k=rrf_k)
    if reranker is not None:
        fused = await rerank_hits(
            query,
            fused,
            provider=reranker,
            top_k=limit,
        )
    return RetrievalResult(
        hits=tuple(fused[:k]),
        candidates=tuple(fused),
        score_stage="reranker" if reranker is not None else "rrf",
        component_rankings=ComponentRankings(
            vector=tuple(hit.chunk_id for hit in vector_hits),
            vector_by_language=vector_by_language,
            lexical=tuple(hit.chunk_id for hit in lexical_hits),
            lexical_by_language=lexical_by_language,
        ),
    )
