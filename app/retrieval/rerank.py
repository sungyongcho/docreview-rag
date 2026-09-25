"""Async reranking behind a dependency-free provider boundary."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.retrieval.types import ChunkHit, finite_float, sort_hits


class RerankProvider(ABC):
    """Provider boundary for scoring query/document pairs."""

    @abstractmethod
    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Return one relevance score per document in caller order."""


def _scores(values: Sequence[float], *, expected_count: int) -> list[float]:
    """Validate provider scores before replacing immutable hit scores."""
    if len(values) != expected_count:
        raise ValueError(f"reranker returned {len(values)} scores for {expected_count} hits")
    return [
        finite_float(
            value,
            nonnumeric="reranker returned a nonnumeric score",
            nonfinite="reranker returned a non-finite score",
        )
        for value in values
    ]


async def rerank_hits(
    query: str,
    hits: Sequence[ChunkHit],
    *,
    provider: RerankProvider,
    top_k: int = 5,
) -> list[ChunkHit]:
    """Rescore candidates through a provider and return deterministic top-k hits.

    Parameters
    ----------
    query : str
        Nonblank query passed to the provider.
    hits : Sequence[ChunkHit]
        Candidate evidence in retrieval order.
    provider : RerankProvider
        External scoring boundary.
    top_k : int
        Maximum number of reranked hits to return.

    Returns
    -------
    list[ChunkHit]
        Deterministically ordered provider-rescored evidence.

    Raises
    ------
    ValueError
        If the query is blank, ``top_k`` is negative, or provider scores violate the
        count, numeric-type, or finiteness contract.

    Notes
    -----
    All provider scores are validated before top-k selection, and the immutable inputs
    are not changed.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("rerank query must be nonempty")
    if top_k < 0:
        raise ValueError("rerank top_k must not be negative")
    if top_k == 0 or not hits:
        return []

    scores = _scores(
        await provider.score(query, [hit.index_text for hit in hits]),
        expected_count=len(hits),
    )
    rescored = [
        hit.model_copy(update={"score": score}) for hit, score in zip(hits, scores, strict=True)
    ]
    return sort_hits(rescored)[:top_k]
