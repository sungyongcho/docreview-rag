"""Strict local-administrator retrieval and evaluation request contracts."""

from pydantic import ValidationError
import pytest

from app.api.admin_schemas import (
    AcquisitionDraftResource,
    EvaluationRunRequest,
    RetrievalPreviewResponse,
    RetrievalProfile,
    SourceInventoryResource,
)
from app.retrieval.service import ComponentRankings


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


def test_retrieval_preview_carries_per_language_component_rankings() -> None:
    """Accept the routed per-language rank lists the retrieval service records."""
    rankings = ComponentRankings(
        vector=(1, 2),
        lexical=(),
        lexical_by_language={"ko": (3,), "en": (2, 1)},
    )

    response = RetrievalPreviewResponse(
        query="메모리 사업 위험",
        profile=RetrievalProfile(route_by_language=True),
        score_stage="rrf",
        component_rankings=rankings.model_dump(mode="python"),
        results=(),
    )

    assert response.component_rankings["vector"] == (1, 2)
    assert response.component_rankings["lexical_by_language"] == {"ko": (3,), "en": (2, 1)}


@pytest.mark.parametrize("can_redownload", [False, True])
def test_source_download_recovery_is_a_strict_boolean(can_redownload):
    """Expose recovery independently of physical presence without accepting truthy strings."""
    values = {
        "manifest": "manifest.json",
        "document_id": "NVDA-FY2024",
        "filing_id": "0001045810-24-000029",
        "registry": "sec",
        "issuer": "NVDA",
        "name": "NVIDIA",
        "fiscal_year": 2024,
        "on_disk": True,
        "ready": False,
        "can_redownload": can_redownload,
    }
    resource = SourceInventoryResource.model_validate(values)
    assert resource.on_disk and resource.can_redownload is can_redownload
    with pytest.raises(ValidationError):
        SourceInventoryResource.model_validate({**values, "can_redownload": str(can_redownload)})


@pytest.mark.parametrize("field", ["filing_id", "ready", "can_redownload"])
@pytest.mark.parametrize("missing", [False, True])
def test_source_inventory_requires_current_identity_and_state_fields(field, missing):
    """Reject missing or null current-source fields instead of inventing readiness defaults."""
    values = {
        "manifest": "manifest.json",
        "document_id": "NVDA-FY2024",
        "filing_id": "0001045810-24-000029",
        "registry": "sec",
        "issuer": "NVDA",
        "name": "NVIDIA",
        "fiscal_year": 2024,
        "on_disk": True,
        "ready": True,
        "can_redownload": False,
    }
    if missing:
        del values[field]
    else:
        values[field] = None
    with pytest.raises(ValidationError):
        SourceInventoryResource.model_validate(values)


def test_acquisition_draft_requires_explicit_pairs_and_revision():
    """Reject older draft shapes while keeping the exact empty current draft valid."""
    values = {"identifiers": [], "years": [], "pairs": [], "revision": "reset-a"}
    assert AcquisitionDraftResource.model_validate(values).pairs == ()
    for field in ("pairs", "revision"):
        with pytest.raises(ValidationError):
            AcquisitionDraftResource.model_validate({k: v for k, v in values.items() if k != field})
