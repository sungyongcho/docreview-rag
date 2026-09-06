"""Rank-only reciprocal rank fusion and thin hybrid orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.retrieval.types import ChunkHit, RetrievalFilters, sort_hits

DEFAULT_RRF_K = 60

SearchCallable = Callable[[str, int, RetrievalFilters], Awaitable[list[ChunkHit]]]


@dataclass(slots=True)
class _FusedHit:
    hit: ChunkHit
    score: float = 0.0


def _unique_ranked_hits(hits: Sequence[ChunkHit]) -> list[ChunkHit]:
    """Keep the first occurrence of each chunk so one list contributes one rank."""
    seen: set[int] = set()
    unique: list[ChunkHit] = []
    for hit in hits:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            unique.append(hit)
    return unique


def rrf_fuse(
    vector_hits: Sequence[ChunkHit],
    lexical_hits: Sequence[ChunkHit],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Fuse ranked lists by reciprocal rank, keyed by database ``chunk_id``.

    Source scores are intentionally ignored because vector similarity and PostgreSQL
    FTS cover-density scores have unrelated scales. Each list contributes
    ``1 / (rrf_k + rank)`` once per chunk, where rank is one-based.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused: dict[int, _FusedHit] = {}
    for ranking in (vector_hits, lexical_hits):
        for rank, hit in enumerate(_unique_ranked_hits(ranking), start=1):
            contribution = 1.0 / (rrf_k + rank)
            entry = fused.get(hit.chunk_id)
            if entry is None:
                fused[hit.chunk_id] = _FusedHit(hit=hit, score=contribution)
            else:
                entry.score += contribution

    hits = [entry.hit.model_copy(update={"score": entry.score}) for entry in fused.values()]
    return sort_hits(hits)[:k]


async def hybrid_search(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    vector_search: SearchCallable,
    lexical_search: SearchCallable,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Retrieve two candidate lists and combine them with rank-only RRF.

    Injected callables let the production adapter close over its session, embedder,
    and vector query preparation. Calls are awaited sequentially so both adapters may
    safely share one SQLAlchemy ``AsyncSession``.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    limit = candidate_k if candidate_k is not None else k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    active_filters = filters or RetrievalFilters()

    vector_hits = await vector_search(query, limit, active_filters)
    lexical_hits = await lexical_search(query, limit, active_filters)
    return rrf_fuse(vector_hits, lexical_hits, k, rrf_k=rrf_k)
