"""L5: reciprocal rank fusion and thin hybrid orchestration."""

import asyncio
import importlib
import os

import pytest

from app.retrieval.types import ChunkHit, RetrievalFilters
from tests.retrieval.test_01_contract import hit_values
from tests.support import need

HYBRID_MODULE_NAME = os.getenv("RETRIEVAL_HYBRID_MODULE", "app.retrieval.hybrid")
H = importlib.import_module(HYBRID_MODULE_NAME)


def hit(chunk_id: int, score: float, **changes) -> ChunkHit:
    """Build a valid hit with an identity-specific source span."""
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


def test_rrf_rewards_cross_list_agreement_and_ignores_source_score_scales():
    need(H, "rrf_fuse")
    vector = [hit(1, 0.99), hit(2, 0.01)]
    lexical = [hit(2, 9_000.0), hit(3, 8_000.0)]

    fused = H.rrf_fuse(vector, lexical, 3, rrf_k=60)

    assert [result.chunk_id for result in fused] == [2, 1, 3]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1].score == pytest.approx(1 / 61)
    assert fused[2].score == pytest.approx(1 / 62)
    assert all(result.score not in {0.99, 0.01, 9_000.0, 8_000.0} for result in fused)


def test_rrf_keys_identity_by_chunk_id_and_counts_a_list_only_once():
    need(H, "rrf_fuse")
    duplicate = hit(7, 100.0)
    other_source_instance = duplicate.model_copy(update={"score": -100.0})

    fused = H.rrf_fuse([duplicate, duplicate], [other_source_instance], 1, rrf_k=10)

    assert len(fused) == 1
    assert fused[0].chunk_id == 7
    assert fused[0].score == pytest.approx(2 / 11)


def test_rrf_uses_shared_stable_tie_breakers_and_truncates():
    need(H, "rrf_fuse")
    fused = H.rrf_fuse([hit(2, 0.2, doc_id="B"), hit(1, 0.1, doc_id="A")], [], 1)
    assert [result.chunk_id for result in fused] == [2]

    tied = H.rrf_fuse([hit(2, 0.2, doc_id="B")], [hit(1, 0.1, doc_id="A")], 2)
    assert [result.chunk_id for result in tied] == [1, 2]


@pytest.mark.parametrize(("k", "rrf_k"), [(0, 60), (-1, 60), (1, 0), (1, -1)])
def test_rrf_rejects_nonpositive_limits(k, rrf_k):
    need(H, "rrf_fuse")
    with pytest.raises(ValueError):
        H.rrf_fuse([], [], k, rrf_k=rrf_k)


def test_hybrid_search_injects_filters_and_fuses_sequential_candidate_lists():
    need(H, "hybrid_search")
    filters = RetrievalFilters(doc_ids=("NVDA-FY2024",), kinds=("text",))
    calls = []

    async def vector(query, k, received_filters):
        calls.append(("vector", query, k, received_filters))
        return [hit(1, 0.9), hit(2, 0.8)]

    async def lexical(query, k, received_filters):
        calls.append(("lexical", query, k, received_filters))
        return [hit(2, 50.0), hit(3, 40.0)]

    fused = asyncio.run(
        H.hybrid_search(
            "research expense",
            2,
            filters,
            vector_search=vector,
            lexical_search=lexical,
            candidate_k=4,
        )
    )

    assert calls == [
        ("vector", "research expense", 4, filters),
        ("lexical", "research expense", 4, filters),
    ]
    assert [result.chunk_id for result in fused] == [2, 1]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)


def test_hybrid_search_supplies_default_filters_and_validates_inputs():
    need(H, "hybrid_search")
    received = []

    async def search(query, k, filters):
        received.append((query, k, filters))
        return []

    assert (
        asyncio.run(
            H.hybrid_search(
                "query",
                2,
                vector_search=search,
                lexical_search=search,
            )
        )
        == []
    )
    assert received == [("query", 2, RetrievalFilters()), ("query", 2, RetrievalFilters())]

    with pytest.raises(ValueError, match="blank"):
        asyncio.run(H.hybrid_search(" ", 2, vector_search=search, lexical_search=search))
    with pytest.raises(ValueError, match="positive"):
        asyncio.run(H.hybrid_search("query", 0, vector_search=search, lexical_search=search))
    with pytest.raises(ValueError, match="at least k"):
        asyncio.run(
            H.hybrid_search(
                "query",
                3,
                vector_search=search,
                lexical_search=search,
                candidate_k=2,
            )
        )
