"""BM25 precedence: stated request values, then server settings, then built-in defaults."""

from app.api.admin_schemas import RetrievalProfile
from app.api.review_profile import (
    CustomRetrievalProfile,
    ReviewSessionProfile,
    ServerBM25,
    resolve_retrieval_profile,
    with_server_bm25,
)

TUNED_SERVER = ServerBM25(k1=1.6, b=0.5, idf="robertson")


def bm25(plan) -> tuple[float, float, str]:
    """Project one plan onto its applied BM25 values."""
    return plan.bm25_k1, plan.bm25_b, plan.bm25_idf


def test_stated_custom_values_win_and_omitted_values_inherit():
    """Custom values a request states are kept even when they equal the defaults."""
    stated = ReviewSessionProfile(
        retrieval_preset="custom",
        custom_retrieval=CustomRetrievalProfile(bm25_k1=1.2, bm25_b=0.75, bm25_idf="lucene"),
    )
    partial = ReviewSessionProfile.model_validate(
        {"retrieval_preset": "custom", "custom_retrieval": {"bm25_k1": 2.0}}
    )

    assert bm25(resolve_retrieval_profile(stated, TUNED_SERVER)) == (1.2, 0.75, "lucene")
    assert bm25(resolve_retrieval_profile(partial, TUNED_SERVER)) == (2.0, 0.5, "robertson")
    assert bm25(resolve_retrieval_profile(partial)) == (2.0, 0.75, "lucene")


def test_administrator_profiles_follow_the_same_precedence():
    """Preview and evaluation plans fill only the BM25 values they leave unstated."""
    stated = RetrievalProfile.model_validate({"bm25_b": 0.3})

    assert bm25(with_server_bm25(RetrievalProfile(), TUNED_SERVER)) == (1.6, 0.5, "robertson")
    assert bm25(with_server_bm25(stated, TUNED_SERVER)) == (1.6, 0.3, "robertson")
    assert with_server_bm25(stated, TUNED_SERVER).model_dump(exclude={"bm25_k1", "bm25_idf"}) == (
        stated.model_dump(exclude={"bm25_k1", "bm25_idf"})
    )
