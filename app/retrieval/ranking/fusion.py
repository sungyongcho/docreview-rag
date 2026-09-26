"""Rank-only reciprocal rank fusion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import heapq

from app.retrieval.types import ChunkHit, hit_order_key_for_score

DEFAULT_RRF_K = 60


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
