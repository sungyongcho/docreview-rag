"""Rank-only reciprocal rank fusion and hybrid retrieval orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
import heapq

from app.retrieval.types import ChunkHit, RetrievalFilters, hit_order_key_for_score

DEFAULT_RRF_K = 60

SearchCallable = Callable[[str, int, RetrievalFilters], Awaitable[list[ChunkHit]]]


@dataclass(slots=True)
class _FusedHit:
    """Mutable score accumulator retaining one immutable evidence hit."""

    hit: ChunkHit
    score: float = 0.0


def _unique_ranked_hits(hits: Sequence[ChunkHit]) -> list[ChunkHit]:
    """Keep the first occurrence of each chunk so one list contributes one rank.

    Parameters
    ----------
    hits : Sequence[ChunkHit]
        One component ranking in relevance order.

    Returns
    -------
    list[ChunkHit]
        First occurrences in their original order.
    """
    seen: set[int] = set()
    unique: list[ChunkHit] = []
    for hit in hits:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            unique.append(hit)
    return unique


def fuse_ranked_lists(
    ranked_lists: Sequence[Sequence[ChunkHit]],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Fuse any number of ranked lists by reciprocal rank, keyed by ``chunk_id``.

    Parameters
    ----------
    ranked_lists : Sequence[Sequence[ChunkHit]]
        Component rankings in relevance order — retrieval lanes, sub-question
        results, or any other independently ranked evidence.
    k : int
        Maximum number of fused hits to return.
    rrf_k : int
        Positive rank-smoothing constant.

    Returns
    -------
    list[ChunkHit]
        Top-k evidence hits carrying fused scores, ordered by the shared
        deterministic hit key.

    Raises
    ------
    ValueError
        If ``k`` or ``rrf_k`` is not positive, or two lists carry the same
        ``chunk_id`` with different source identity.

    Notes
    -----
    Source scores are ignored because component score scales are unrelated. Each
    list contributes ``1 / (rrf_k + rank)`` once per chunk; within one list the
    first occurrence of a chunk wins. Across lists, every field except the
    lane-specific ``score`` must agree, so corrupted or mixed-corpus inputs fail
    instead of silently keeping whichever instance arrived first.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused: dict[int, _FusedHit] = {}
    for ranking in ranked_lists:
        for rank, hit in enumerate(_unique_ranked_hits(ranking), start=1):
            contribution = 1.0 / (rrf_k + rank)
            entry = fused.get(hit.chunk_id)
            if entry is None:
                fused[hit.chunk_id] = _FusedHit(hit=hit, score=contribution)
            else:
                if entry.hit.model_dump(exclude={"score"}) != hit.model_dump(exclude={"score"}):
                    raise ValueError(f"chunk {hit.chunk_id} has conflicting source identity")
                entry.score += contribution

    selected = heapq.nsmallest(
        k,
        fused.values(),
        key=lambda entry: hit_order_key_for_score(entry.hit, entry.score),
    )
    return [entry.hit.model_copy(update={"score": entry.score}) for entry in selected]


def rrf_fuse(
    vector_hits: Sequence[ChunkHit],
    lexical_hits: Sequence[ChunkHit],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Fuse the two hybrid retrieval lanes with :func:`fuse_ranked_lists`.

    Kept as the named two-lane entry point of the M2 hybrid contract; the fusion
    rules live once, in :func:`fuse_ranked_lists`.
    """
    return fuse_ranked_lists((vector_hits, lexical_hits), k, rrf_k=rrf_k)


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

    Parameters
    ----------
    query : str
        Nonblank user query supplied to both retrieval paths.
    k : int
        Maximum number of fused hits to return.
    filters : RetrievalFilters | None
        Shared exact-match restrictions.
    vector_search : SearchCallable
        Injected vector retrieval adapter.
    lexical_search : SearchCallable
        Injected lexical retrieval adapter.
    candidate_k : int | None
        Candidate depth per path, or ``None`` to use ``k``.
    rrf_k : int
        Positive rank-smoothing constant.

    Returns
    -------
    list[ChunkHit]
        Deterministically ordered fused evidence.

    Raises
    ------
    ValueError
        If the query is blank, a limit is invalid, or ``candidate_k`` is below ``k``.

    Notes
    -----
    Calls are awaited sequentially because injected adapters may share one SQLAlchemy
    ``AsyncSession``. Provider and session details stay outside this pure composition.
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
