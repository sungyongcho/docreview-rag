"""Strict local-administrator retrieval and evaluation request contracts."""

from pydantic import ValidationError
import pytest

from app.api.admin_schemas import EvaluationRunRequest, RetrievalProfile


def test_default_profile_is_explicit_hybrid_ts_rank() -> None:
    """Expose every session parameter without inheriting hidden process state."""
    profile = RetrievalProfile()

    assert profile.strategy == "hybrid"
    assert profile.lexical_ranker == "ts_rank_cd"
    assert profile.k == 5
    assert profile.candidate_k == 20
    assert profile.rrf_k == 60


@pytest.mark.parametrize(
    "values",
    [
        {"strategy": "vector", "lexical_ranker": "bm25"},
        {"strategy": "lexical", "lexical_ranker": None},
        {"strategy": "lexical", "route_by_language": True},
        {"strategy": "vector", "lexical_ranker": None, "reranker": "cross_encoder"},
        {"k": 10, "candidate_k": 5},
    ],
)
def test_profile_rejects_contradictory_retrieval_plans(values) -> None:
    """Reject mislabeled retrieval paths before database or provider access."""
    with pytest.raises(ValidationError):
        RetrievalProfile(**values)


def test_matrix_axes_must_be_unique_and_nonempty() -> None:
    """Refuse a matrix whose repeated axes would duplicate artifacts."""
    with pytest.raises(ValidationError, match="target_text_chars"):
        EvaluationRunRequest(
            suite_id="sec-en",
            mode="matrix",
            target_text_chars=(500, 500),
        )
