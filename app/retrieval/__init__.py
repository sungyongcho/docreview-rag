"""Public façade for baseline hybrid retrieval."""

from app.retrieval.bm25 import TermStatCounts, backfill_term_stats, bm25_search
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingBackfillResult,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.hybrid import hybrid_search, rrf_fuse
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.sbert import SentenceTransformerEmbeddingProvider
from app.retrieval.service import ComponentRankings, RetrievalResult, normalize_query, retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters, sort_hits
from app.retrieval.vector import vector_search

__all__ = [
    "ChunkHit",
    "ComponentRankings",
    "CrossEncoderReranker",
    "DeterministicEmbeddingProvider",
    "EmbeddingBackfillResult",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "RerankProvider",
    "RetrievalFilters",
    "RetrievalResult",
    "SentenceTransformerEmbeddingProvider",
    "TermStatCounts",
    "backfill_term_stats",
    "bm25_search",
    "embed_missing_chunks",
    "get_embedding_provider",
    "hybrid_search",
    "lexical_search",
    "normalize_query",
    "rerank_hits",
    "retrieve",
    "rrf_fuse",
    "sort_hits",
    "vector_search",
]
