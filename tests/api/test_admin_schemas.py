"""Strict local-administrator retrieval and evaluation request contracts."""

from pydantic import ValidationError
import pytest

from app.api.admin_schemas import (
    AcquisitionDraftResource,
    CorpusOperationRequest,
    EvaluationRunRequest,
    RetrievalPreviewResponse,
    RetrievalProfile,
    SourceInventoryResource,
)
from app.retrieval.service import ComponentRankings


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


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "delete_sources"},
        {"kind": "delete_sources", "deletion_token": "preview", "confirm_delete": False},
        {"kind": "delete_sources", "deletion_token": "preview", "confirm_delete": "true"},
        {
            "kind": "delete_sources",
            "deletion_token": "preview",
            "confirm_delete": True,
            "identifiers": ["NVDA"],
        },
        {"kind": "rebuild_bm25", "deletion_token": "preview", "confirm_delete": True},
    ],
)
def test_source_deletion_requires_a_dedicated_explicit_confirmation(payload):
    """Reject coercion and a target scope that was not part of the preview."""
    from app.api.admin_schemas import CorpusOperationRequest

    with pytest.raises(ValidationError):
        CorpusOperationRequest.model_validate(payload)


@pytest.mark.parametrize("document_ids", [None, [], ["filing-a", "filing-a"]])
def test_selected_ingestion_requires_nonempty_unique_document_ids(document_ids):
    """Refuse old issuer/year-only requests before source selection can be inferred."""
    with pytest.raises(ValidationError, match="nonempty unique document_ids"):
        CorpusOperationRequest.model_validate(
            {
                "kind": "ingest_selected",
                "identifiers": ["NVDA"],
                "years": [2024],
                "document_ids": document_ids,
            }
        )


def test_exact_ingestion_and_current_cli_manifest_requests_remain_valid():
    """Require IDs only for selected-source jobs while preserving explicit manifest ingestion."""
    selected = CorpusOperationRequest(
        kind="ingest_selected", identifiers=("NVDA",), years=(2024,), document_ids=("filing-a",)
    )
    assert selected.document_ids == ("filing-a",)
    manifest = CorpusOperationRequest(
        kind="ingest_manifest", manifest="manifest.json", selection_id="selection-a"
    )
    assert manifest.document_ids is None


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
