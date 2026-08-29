"""Public façade for baseline hybrid retrieval."""

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
from app.retrieval.service import ComponentRankings, RetrievalResult, normalize_query, retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters, sort_hits
from app.retrieval.vector import vector_search

__all__ = [
    "ChunkHit",
    "ComponentRankings",
    "DeterministicEmbeddingProvider",
    "EmbeddingBackfillResult",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "RerankProvider",
    "RetrievalFilters",
    "RetrievalResult",
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
