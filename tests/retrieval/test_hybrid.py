"""Reciprocal rank fusion tests."""

import pytest

from app.retrieval import hybrid
from tests.retrieval.support import hit


def test_rrf_rewards_cross_list_agreement_and_ignores_source_score_scales():
    """Reward cross-list agreement without mixing native score scales."""
    vector = [hit(1, 0.99), hit(2, 0.01)]
    lexical = [hit(2, 9_000.0), hit(3, 8_000.0)]

    fused = hybrid.fuse_ranked_lists((vector, lexical), 3, rrf_k=60)

    assert [result.chunk_id for result in fused] == [2, 1, 3]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1].score == pytest.approx(1 / 61)
    assert fused[2].score == pytest.approx(1 / 62)
    assert all(result.score not in {0.99, 0.01, 9_000.0, 8_000.0} for result in fused)


def test_rrf_keys_identity_by_chunk_id_and_counts_a_list_only_once():
    """Deduplicate each ranking while fusing shared chunk identities."""
    duplicate = hit(7, 100.0)
    other_source_instance = duplicate.model_copy(update={"score": -100.0})

    fused = hybrid.fuse_ranked_lists(([duplicate, duplicate], [other_source_instance]), 1, rrf_k=10)

    assert len(fused) == 1
    assert fused[0].chunk_id == 7
    assert fused[0].score == pytest.approx(2 / 11)


def test_rrf_uses_shared_stable_tie_breakers_and_truncates():
    """Apply stable source tie-breakers before truncating fused results."""
    fused = hybrid.fuse_ranked_lists(([hit(2, 0.2, doc_id="B"), hit(1, 0.1, doc_id="A")], []), 1)
    assert [result.chunk_id for result in fused] == [2]

    tied = hybrid.fuse_ranked_lists(([hit(2, 0.2, doc_id="B")], [hit(1, 0.1, doc_id="A")]), 2)
    assert [result.chunk_id for result in tied] == [1, 2]


@pytest.mark.parametrize(("k", "rrf_k"), [(0, 60), (-1, 60), (1, 0), (1, -1)])
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
