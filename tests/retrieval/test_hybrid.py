"""Reciprocal rank fusion tests."""

import pytest

from app.retrieval import hybrid
from tests.retrieval.support import hit


def test_rrf_uses_shared_stable_tie_breakers_and_truncates():
    """Apply stable source tie-breakers before truncating fused results."""
    fused = hybrid.fuse_ranked_lists(([hit(2, 0.2, doc_id="B"), hit(1, 0.1, doc_id="A")], []), 1)
    assert [result.chunk_id for result in fused] == [2]

    tied = hybrid.fuse_ranked_lists(([hit(2, 0.2, doc_id="B")], [hit(1, 0.1, doc_id="A")]), 2)
    assert [result.chunk_id for result in tied] == [1, 2]


@pytest.mark.parametrize(("k", "rrf_k"), [(0, 60), (1, 0)])
def test_rrf_rejects_nonpositive_limits(k, rrf_k):
    """Reject nonpositive output and rank-smoothing limits."""
    with pytest.raises(ValueError):
        hybrid.fuse_ranked_lists(([], []), k, rrf_k=rrf_k)


def test_fuse_ranked_lists_generalizes_fusion_to_n_lists():
    """Fuse three sub-question rankings with the same reciprocal-rank rules."""
    first = [hit(1, 0.9), hit(2, 0.8)]
    second = [hit(2, 0.7), hit(3, 0.6)]
    third = [hit(2, 0.5)]

    fused = hybrid.fuse_ranked_lists((first, second, third), 3, rrf_k=60)

    assert [result.chunk_id for result in fused] == [2, 1, 3]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61 + 1 / 61)
    with pytest.raises(ValueError):
        hybrid.fuse_ranked_lists((first,), 0)


def test_fuse_ranked_lists_rejects_conflicting_identity_for_one_chunk_id():
    """Refuse two lists whose shared chunk id claims different source identity."""
    original = hit(7, 0.9)
    conflicting = original.model_copy(update={"doc_id": "OTHER"})

    same_identity = original.model_copy(update={"score": -1.0})
    fused = hybrid.fuse_ranked_lists(((original, original), (same_identity,)), 1, rrf_k=10)
    assert fused[0].score == pytest.approx(2 / 11)

    with pytest.raises(ValueError, match="conflicting source identity"):
        hybrid.fuse_ranked_lists(((original,), (conflicting,)), 1)
