"""L6: dependency-free optional reranking boundary."""

import asyncio
import importlib
import math
import os

import pytest

from app.retrieval.types import ChunkHit
from tests.retrieval.test_01_contract import hit_values
from tests.support import need

RERANK_MODULE_NAME = os.getenv("RETRIEVAL_RERANK_MODULE", "app.retrieval.rerank")
R = importlib.import_module(RERANK_MODULE_NAME)


def hit(chunk_id: int, score: float, **changes) -> ChunkHit:
    """Build one valid, identity-specific hit."""
    start = changes.pop("start_char", chunk_id * 100)
    return ChunkHit(
        **hit_values(
            chunk_id=chunk_id,
            score=score,
            start_char=start,
            end_char=start + 50,
            **changes,
        )
    )


def test_provider_receives_full_index_text_and_rescores_without_mutating_hits():
    need(R, "RerankProvider", "rerank_hits")
    calls = []

    class Provider(R.RerankProvider):
        async def score(self, query, documents):
            calls.append((query, list(documents)))
            return [0.1, 0.9]

    hits = [hit(1, 99.0), hit(2, 1.0)]
    original_scores = [candidate.score for candidate in hits]
    reranked = asyncio.run(R.rerank_hits("research expense", hits, provider=Provider(), top_k=2))

    assert calls == [("research expense", [candidate.index_text for candidate in hits])]
    assert [candidate.chunk_id for candidate in reranked] == [2, 1]
    assert [candidate.score for candidate in reranked] == [0.9, 0.1]
    assert [candidate.score for candidate in hits] == original_scores


def test_no_provider_keeps_shared_deterministic_order_and_truncates():
    need(R, "rerank_hits")
    hits = [
        hit(3, 0.5, doc_id="B"),
        hit(2, 0.5, doc_id="A"),
        hit(1, 0.9, doc_id="Z"),
    ]

    ordered = asyncio.run(R.rerank_hits("query", hits, top_k=2))

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
    need(R, "RerankProvider", "rerank_hits")

    class Provider(R.RerankProvider):
        async def score(self, _query, _documents):
            return scores

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            R.rerank_hits(
                "query",
                [hit(1, 0.5), hit(2, 0.4)],
                provider=Provider(),
            )
        )


def test_empty_candidates_and_zero_limit_do_not_call_provider():
    need(R, "RerankProvider", "rerank_hits")

    class Provider(R.RerankProvider):
        async def score(self, _query, _documents):
            raise AssertionError("provider should not be called")

    assert asyncio.run(R.rerank_hits("query", [], provider=Provider())) == []
    assert asyncio.run(R.rerank_hits("query", [hit(1, 0.5)], provider=Provider(), top_k=0)) == []


@pytest.mark.parametrize(("query", "top_k"), [("", 1), ("   ", 1), ("query", -1)])
def test_reranking_rejects_blank_queries_and_negative_limits(query, top_k):
    need(R, "rerank_hits")
    with pytest.raises(ValueError):
        asyncio.run(R.rerank_hits(query, [hit(1, 0.5)], top_k=top_k))
