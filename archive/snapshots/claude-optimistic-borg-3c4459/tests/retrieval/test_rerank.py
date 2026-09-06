"""Dependency-free optional reranking tests."""

import asyncio
import math

import pytest

from app.retrieval import rerank
from tests.retrieval.support import hit


def test_provider_receives_full_index_text_and_rescores_without_mutating_hits():
    """Rescore full indexed text without mutating candidate hits."""
    calls = []

    class Provider(rerank.RerankProvider):
        async def score(self, query, documents):
            calls.append((query, list(documents)))
            return [0.1, 0.9]

    hits = [hit(1, 99.0), hit(2, 1.0)]
    original_scores = [candidate.score for candidate in hits]
    reranked = asyncio.run(
        rerank.rerank_hits("research expense", hits, provider=Provider(), top_k=2)
    )

    assert calls == [("research expense", [candidate.index_text for candidate in hits])]
    assert [candidate.chunk_id for candidate in reranked] == [2, 1]
    assert [candidate.score for candidate in reranked] == [0.9, 0.1]
    assert [candidate.score for candidate in hits] == original_scores


def test_no_provider_keeps_shared_deterministic_order_and_truncates():
    """Use shared deterministic ordering when no provider is supplied."""
    hits = [
        hit(3, 0.5, doc_id="B"),
        hit(2, 0.5, doc_id="A"),
        hit(1, 0.9, doc_id="Z"),
    ]

    ordered = asyncio.run(rerank.rerank_hits("query", hits, top_k=2))

    assert [candidate.chunk_id for candidate in ordered] == [1, 2]


@pytest.mark.parametrize(
    "scores, message",
    [
        ([1.0], "scores"),
        ([0.0, math.nan], "non-finite"),
        ([0.0, True], "nonnumeric"),
    ],
)
def test_provider_scores_must_match_count_and_be_finite_numeric(scores, message):
    """Reject provider scores with invalid count, type, or finiteness."""

    class Provider(rerank.RerankProvider):
        async def score(self, _query, _documents):
            return scores

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            rerank.rerank_hits(
                "query",
                [hit(1, 0.5), hit(2, 0.4)],
                provider=Provider(),
            )
        )


def test_empty_candidates_and_zero_limit_do_not_call_provider():
    """Avoid provider calls for empty candidates or a zero result limit."""

    class Provider(rerank.RerankProvider):
        async def score(self, _query, _documents):
            raise AssertionError("provider should not be called")

    assert asyncio.run(rerank.rerank_hits("query", [], provider=Provider())) == []
    assert (
        asyncio.run(rerank.rerank_hits("query", [hit(1, 0.5)], provider=Provider(), top_k=0)) == []
    )


@pytest.mark.parametrize(("query", "top_k"), [("", 1), ("   ", 1), ("query", -1)])
def test_reranking_rejects_blank_queries_and_negative_limits(query, top_k):
    """Reject blank queries and negative result limits."""
    with pytest.raises(ValueError):
        asyncio.run(rerank.rerank_hits(query, [hit(1, 0.5)], top_k=top_k))
