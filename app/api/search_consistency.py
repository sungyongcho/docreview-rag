"""Consistent, strategy-aware reads for live HTTP retrieval."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import unavailable
from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf, LexicalRanker
from app.db.models import (
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    SnapshotBM25CorpusStat,
    SnapshotChunk,
)
from app.retrieval.embeddings import (
    EmbeddingProvider,
    get_embedding_provider,
    matching_embedding,
    matching_snapshot_embedding,
)
from app.retrieval.rerank import RerankProvider
from app.retrieval.service import RetrievalResult, RetrievalStrategy, retrieve
from app.retrieval.types import RetrievalFilters


async def prepare_search(
    session: AsyncSession,
    provider: EmbeddingProvider,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker,
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
        await _prepare_snapshot_search(
            session, provider, strategy, lexical_ranker, filters.snapshot_id
        )
        return
    if not await session.scalar(select(select(Chunk.id).exists())):
        raise unavailable(
            "corpus_not_ready", "No parsed documents are ready. Run parsing and chunking first."
        )
    if strategy != "lexical":
        matching = (
            select(ChunkEmbedding.chunk_id).where(matching_embedding(provider.identity)).exists()
        )
        if await session.scalar(select(select(Chunk.id).where(~matching).exists())):
            raise unavailable(
                "embeddings_not_ready",
                "Embeddings need updating. Complete embedding preparation first.",
            )
    if strategy != "vector" and lexical_ranker == "bm25":
        if not await session.scalar(select(select(BM25CorpusStat.language).exists())):
            raise unavailable(
                "bm25_not_ready", "The keyword index needs updating. Rebuild BM25 first."
            )


async def _prepare_snapshot_search(
    session: AsyncSession,
    provider: EmbeddingProvider,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker,
    snapshot_id: int,
) -> None:
    """Reject a snapshot that lacks the vectors or statistics the strategy reads."""
    if strategy != "lexical":
        unmatched = (
            select(SnapshotChunk.chunk_id)
            .where(
                SnapshotChunk.snapshot_id == snapshot_id,
                ~matching_snapshot_embedding(provider.identity),
            )
            .exists()
        )
        if await session.scalar(select(unmatched)):
            raise unavailable(
                "embeddings_not_ready",
                "This snapshot has no vectors for the current embedding configuration. "
                "Choose a keyword-only preset or a snapshot frozen with this configuration.",
            )
    if strategy != "vector" and lexical_ranker == "bm25":
        statistics = (
            select(SnapshotBM25CorpusStat.language)
            .where(SnapshotBM25CorpusStat.snapshot_id == snapshot_id)
            .exists()
        )
        if not await session.scalar(select(statistics)):
            raise unavailable(
                "bm25_not_ready",
                "This snapshot was frozen without BM25 statistics. "
                "Choose a preset that does not rank with BM25.",
            )


async def consistent_retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    query_variants: dict[str, str] | None = None,
    strategy: RetrievalStrategy = "hybrid",
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = 60,
    reranker: RerankProvider | None = None,
    route_by_language: bool = False,
    lexical_ranker: LexicalRanker = "ts_rank_cd",
    bm25_k1: float = DEFAULT_BM25_K1,
    bm25_b: float = DEFAULT_BM25_B,
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
) -> RetrievalResult:
    """Use one database snapshot for readiness, vector candidates, and lexical candidates."""
    active_provider = provider or get_embedding_provider()
    await prepare_search(
        session, active_provider, strategy, lexical_ranker, filters or RetrievalFilters()
    )
    return await retrieve(
        session,
        query,
        provider=active_provider,
        strategy=strategy,
        query_variants=query_variants,
        k=k,
        candidate_k=candidate_k,
        filters=filters,
        rrf_k=rrf_k,
        reranker=reranker,
        route_by_language=route_by_language,
        lexical_ranker=lexical_ranker,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        bm25_idf=bm25_idf,
    )
