"""Reject contradictory or duplicated execution settings at the input boundary."""

from pydantic import ValidationError
import pytest

from app.retrieval.search.profiles import RetrievalProfile


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
