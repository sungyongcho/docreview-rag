"""Strict local-administrator retrieval and evaluation request contracts."""

from pydantic import ValidationError
import pytest

from app.api.admin_schemas import (
    EvaluationRunRequest,
    RetrievalProfile,
)


@pytest.mark.parametrize(
    "values",
    [
        {"strategy": "vector", "lexical_ranker": "bm25"},
        {"strategy": "lexical", "lexical_ranker": None},
        {"strategy": "lexical", "route_by_language": True},
        {"strategy": "vector", "lexical_ranker": None, "reranker": "cross_encoder"},
        {"k": 10, "candidate_k": 5},
    ],
    ids=[
        "vector_names_a_lexical_ranker",
        "lexical_without_a_ranker",
        "language_routing_without_hybrid",
        "reranking_without_hybrid",
        "candidate_depth_below_k",
    ],
)
def test_profile_rejects_contradictory_retrieval_plans(values) -> None:
    """Reject mislabeled retrieval paths before database or provider access."""
    with pytest.raises(ValidationError):
        RetrievalProfile(**values)


def test_matrix_axes_must_be_unique_and_nonempty() -> None:
    """Refuse a matrix whose repeated axes would duplicate artifacts."""
    with pytest.raises(ValidationError, match="target_tokens must be nonempty and unique"):
        EvaluationRunRequest(
            suite_id="sec-en",
            mode="matrix",
            target_tokens=(1024, 1024),
        )
