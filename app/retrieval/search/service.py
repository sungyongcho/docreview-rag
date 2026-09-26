"""Compose normalized vector and lexical retrieval into inspectable fused evidence.

Both database components share one ``AsyncSession`` sequentially, native scores remain
inside their retrieval lanes, and optional reranking changes only the final hit scores.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.validation import PositiveInt
from app.db.models import (
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    SnapshotBM25CorpusStat,
    SnapshotChunk,
)
from app.query.language import LEXICAL_PLANS, detect_query_languages, lexical_plan
from app.retrieval.embedding.provider import EmbeddingProvider, get_embedding_provider
from app.retrieval.indexing.embeddings import matching_embedding, matching_snapshot_embedding
from app.retrieval.ranking.fusion import fuse_ranked_lists
from app.retrieval.ranking.reranker import RerankProvider, rerank_hits
from app.retrieval.search.bm25 import bm25_search
from app.retrieval.search.lexical import lexical_search
from app.retrieval.search.plan import SearchPlan
from app.retrieval.search.vector import vector_search
from app.retrieval.types import ChunkHit, RetrievalFilters

ScoreStage = Literal["rrf", "reranker"]
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

    vector: tuple[PositiveInt, ...]
    vector_by_language: dict[str, tuple[PositiveInt, ...]] = Field(default_factory=dict)
    lexical: tuple[PositiveInt, ...]
    lexical_by_language: dict[str, tuple[PositiveInt, ...]] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Immutable fused evidence with the component ranks that produced it.

    ``score_stage`` identifies whether final hit scores came from fusion or reranking,
    while ``component_rankings`` preserves the pre-fusion proposal order independently
    of those scores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
    candidates: tuple[ChunkHit, ...]
    score_stage: ScoreStage
    component_rankings: ComponentRankings


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    plan: SearchPlan | None = None,
    provider: EmbeddingProvider | None = None,
    query_variants: dict[str, str] | None = None,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    reranker: RerankProvider | None = None,
) -> RetrievalResult:
    """Search each selected language lane, fuse its proposals, and optionally rerank.

    The resolved plan owns ranking choices; ``k`` is the caller's current evidence
    depth. All reads use the supplied session, and component provenance retains the
    original proposals even when fusion or reranking removes them from the result.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    active_plan = plan or SearchPlan()
    limit = active_plan.candidate_limit(k)

    normalized_query = normalize_query(query)
    active_filters = filters or RetrievalFilters()
    # An empty filter is unrestricted: both lanes cover every corpus language, in the
    # declaration order of the plan table so the lane order is fixed by the table rather
    # than by the query. A pinned filter keeps exactly the languages it names.
    corpus_languages = active_filters.languages or tuple(LEXICAL_PLANS)
    query_languages = set(detect_query_languages(normalized_query))

    active_provider = provider
    if active_plan.strategy != "lexical":
        active_provider = provider if provider is not None else get_embedding_provider()

    vector_hits: list[ChunkHit] = []
    vector_by_language: dict[str, tuple[PositiveInt, ...]] = {}
    lexical_hits: list[ChunkHit] = []
    lexical_by_language: dict[str, tuple[PositiveInt, ...]] = {}

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
        if (
            active_plan.route_by_language
            and language not in query_languages
            and language not in (query_variants or {})
        ):
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
        if active_plan.lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                lexical_query,
                limit,
                component_filters,
                k1=active_plan.bm25_k1,
                b=active_plan.bm25_b,
                idf=active_plan.bm25_idf,
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

    if active_plan.strategy in {"vector", "hybrid"} and query_variants:
        # One lane per corpus language, each embedded with the query written in that
        # language (its variant, or the query itself), so an unrestricted filter still
        # reaches every corpus instead of being narrowed to the first language.
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
    elif active_plan.strategy in {"vector", "hybrid"}:
        lane = await vector_component(normalized_query, limit, active_filters)
        vector_ranked = [lane]
    else:
        vector_ranked = []
    lexical_ranked = (
        [await lexical_component(language) for language in corpus_languages]
        if active_plan.strategy in {"lexical", "hybrid"}
        else []
    )
    fused = fuse_ranked_lists((*vector_ranked, *lexical_ranked), limit, rrf_k=active_plan.rrf_k)
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


class SearchNotReadyError(ValueError):
    """The selected corpus or immutable snapshot lacks a required search index."""

    def __init__(self, code: str, message: str) -> None:
        """Retain a transport-independent error code and actionable explanation."""
        super().__init__(message)
        self.code = code
        self.message = message


async def prepare_search(
    session: AsyncSession,
    provider: EmbeddingProvider | None,
    plan: SearchPlan,
    filters: RetrievalFilters,
) -> None:
    """Pin the transaction before SQL and reject incomplete indexes before model calls.

    A snapshot filter is judged on the snapshot's own tables: rebuilding the live
    indexes cannot repair a snapshot frozen without the vectors or the BM25 statistics
    a preset needs, so the answer names the snapshot rather than the rebuild.
    """
    if not session.in_transaction():
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    if filters.snapshot_id is not None:
        await _prepare_snapshot_search(session, provider, plan, filters.snapshot_id)
        return
    if not await session.scalar(select(select(Chunk.id).exists())):
        raise SearchNotReadyError(
            "corpus_not_ready", "No parsed documents are ready. Run parsing and chunking first."
        )
    if plan.strategy != "lexical":
        assert provider is not None
        matching = (
            select(ChunkEmbedding.chunk_id).where(matching_embedding(provider.identity)).exists()
        )
        if await session.scalar(select(select(Chunk.id).where(~matching).exists())):
            raise SearchNotReadyError(
                "embeddings_not_ready",
                "Embeddings need updating. Complete embedding preparation first.",
            )
    if plan.strategy != "vector" and plan.lexical_ranker == "bm25":
        if not await session.scalar(select(select(BM25CorpusStat.language).exists())):
            raise SearchNotReadyError(
                "bm25_not_ready", "The keyword index needs updating. Rebuild BM25 first."
            )


async def _prepare_snapshot_search(
    session: AsyncSession,
    provider: EmbeddingProvider | None,
    plan: SearchPlan,
    snapshot_id: int,
) -> None:
    """Reject a snapshot that lacks the vectors or statistics the strategy reads."""
    if plan.strategy != "lexical":
        assert provider is not None
        unmatched = (
            select(SnapshotChunk.chunk_id)
            .where(
                SnapshotChunk.snapshot_id == snapshot_id,
                ~matching_snapshot_embedding(provider.identity),
            )
            .exists()
        )
        if await session.scalar(select(unmatched)):
            raise SearchNotReadyError(
                "embeddings_not_ready",
                "This snapshot has no vectors for the current embedding configuration. "
                "Choose a keyword-only preset or a snapshot frozen with this configuration.",
            )
    if plan.strategy != "vector" and plan.lexical_ranker == "bm25":
        statistics = (
            select(SnapshotBM25CorpusStat.language)
            .where(SnapshotBM25CorpusStat.snapshot_id == snapshot_id)
            .exists()
        )
        if not await session.scalar(select(statistics)):
            raise SearchNotReadyError(
                "bm25_not_ready",
                "This snapshot was frozen without BM25 statistics. "
                "Choose a preset that does not rank with BM25.",
            )


async def consistent_retrieve(
    session: AsyncSession,
    query: str,
    *,
    plan: SearchPlan | None = None,
    provider: EmbeddingProvider | None = None,
    query_variants: dict[str, str] | None = None,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    reranker: RerankProvider | None = None,
) -> RetrievalResult:
    """Pin readiness and candidate reads to one database transaction snapshot."""
    active_plan = plan or SearchPlan()
    active_provider = provider
    if active_provider is None and active_plan.strategy != "lexical":
        active_provider = get_embedding_provider()
    await prepare_search(session, active_provider, active_plan, filters or RetrievalFilters())
    return await retrieve(
        session,
        query,
        plan=active_plan,
        provider=active_provider,
        query_variants=query_variants,
        k=k,
        filters=filters,
        reranker=reranker,
    )
