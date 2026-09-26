"""Exercise corpus behavior at service and HTTP boundaries."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.api.app import create_api_app
from app.api.corpus.routes import _enqueue_corpus, _source_deletion_preview
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.corpus_admin.types import AdminCommand, AdminJob
from tests.api.support import _admin, _corpus_job


def test_acquisition_api_preserves_absent_deletion_and_document_arguments():
    """New optional deletion fields must not make ordinary corpus commands invalid."""
    from app.corpus_admin.types import AdminCommand

    request = AdminCommand(kind="acquire_edgar", identifiers=("NVDA",), years=(2024,))
    service = SimpleNamespace()

    async def enqueue(command):
        """Return the accepted command through the actual dataclass serialization boundary."""
        assert command is request
        assert command.document_ids is None and command.confirm_delete is None
        return AdminJob("download", command, "queued", "queued", 0, None, "Queued")

    service.corpus = cast(RuntimeCorpusAdminService, SimpleNamespace(enqueue=enqueue))
    result = asyncio.run(_enqueue_corpus(service, request))
    assert result["command"]["kind"] == "acquire_edgar"


def test_source_deletion_preview_accepts_the_plan_lists_from_the_corpus_service():
    """The fingerprinted plan carries JSON lists; the strict resource still validates."""
    from app.api.corpus.routes import SourceDeletionRequest

    plan = {
        "token": "preview-token",
        "expires_at": 1800000000.5,
        "documents": [
            {
                "document_id": "dart-20250311001085",
                "registry": "dart",
                "issuer": "005930",
                "fiscal_year": 2024,
                "filing_id": "20250311001085",
            }
        ],
        "files": [
            {"path": "dart/005930/20250311001085/primary.xml", "byte_length": 10, "retained": False}
        ],
        "retained_inputs": 2,
        "retained_derived": True,
    }
    service = SimpleNamespace()
    service.corpus = cast(
        RuntimeCorpusAdminService,
        SimpleNamespace(preview_source_deletion=AsyncMock(return_value=plan)),
    )
    resource = asyncio.run(
        _source_deletion_preview(
            service, SourceDeletionRequest(document_ids=("dart-20250311001085",))
        )
    )
    assert resource.documents[0].document_id == "dart-20250311001085"
    assert resource.files[0].retained is False
    assert resource.retained_inputs == 2


def test_ingestion_route_requires_and_forwards_explicit_selection():
    """Require selection identity in the shared corpus job request."""
    received = []

    async def enqueue(request):
        """Record the validated operation without starting a worker."""
        received.append(request)
        return _corpus_job(request, "selection-job")

    services = _admin(corpus=SimpleNamespace(enqueue=enqueue))
    with TestClient(create_api_app(admin_services=services)) as client:
        invalid = client.post(
            "/admin/corpus/jobs", json={"kind": "ingest_manifest", "manifest": "manifest.json"}
        )
        valid = client.post(
            "/admin/corpus/jobs",
            json={
                "kind": "ingest_manifest",
                "manifest": "manifest.json",
                "selection_id": "selected",
                "document_ids": ["filing-a"],
                "years": [2024],
                "expected_documents": 1,
            },
        )
    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert isinstance(received[0], AdminCommand)
    assert received[0].selection_id == "selected"
    assert received[0].document_ids == ("filing-a",)
    assert received[0].years == (2024,)
    assert valid.json()["command"]["document_ids"] == ["filing-a"]


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "delete_sources"},
        {"kind": "delete_sources", "deletion_token": "preview", "confirm_delete": False},
        {"kind": "delete_sources", "deletion_token": "preview", "confirm_delete": "true"},
        {"kind": "delete_sources", "deletion_token": "preview", "confirm_delete": 1},
        {
            "kind": "delete_sources",
            "deletion_token": "preview",
            "confirm_delete": True,
            "identifiers": ["NVDA"],
        },
        {"kind": "rebuild_bm25", "deletion_token": "preview", "confirm_delete": True},
        {"kind": "acquire_edgar", "identifiers": ["NVDA"], "years": [1800]},
        {"kind": "acquire_dart", "identifiers": ["unsupported"], "years": [2024]},
        {"kind": "acquire_edgar", "identifiers": [], "years": [2024]},
        {"kind": "acquire_edgar", "identifiers": ["NVDA"], "years": ["2024"]},
        {"kind": "acquire_edgar", "identifiers": ["NVDA"], "years": [True]},
        {"kind": "ingest_selected", "document_ids": ["filing-a", "filing-a"]},
        {"kind": "ingest_selected", "document_ids": []},
        {"kind": "ingest_selected", "document_ids": None},
        {"kind": "ingest_selected", "document_ids": [1]},
        {"kind": "ingest_selected", "document_ids": ["filing-a"], "years": [0]},
        {"kind": "rebuild_bm25", "document_ids": ["filing-a"]},
        {"kind": "rebuild_bm25", "expected_documents": 0},
        {"kind": "rebuild_bm25", "expected_documents": True},
        {"kind": "rebuild_bm25", "unknown": True},
    ],
)
def test_corpus_route_rejects_invalid_commands_before_enqueue(payload):
    """The current command boundary rejects unsafe scope and scalar coercion over HTTP."""
    received = []

    async def enqueue(request):
        """Expose any accidental dispatch of a rejected command."""
        received.append(request)
        return _corpus_job(request)

    services = _admin(corpus=SimpleNamespace(enqueue=enqueue))
    with TestClient(create_api_app(admin_services=services)) as client:
        response = client.post("/admin/corpus/jobs", json=payload)
    assert response.status_code == 422
    assert received == []


def test_source_deletion_preview_is_admin_only_and_validates_exact_ids():
    """Only the admin route can inspect sources and it forwards explicit document IDs."""
    preview = AsyncMock(
        return_value={
            "token": "preview",
            "expires_at": 9999999999.0,
            "documents": [],
            "files": [],
            "retained_inputs": 0,
            "retained_derived": True,
        }
    )
    services = _admin(corpus=SimpleNamespace(preview_source_deletion=preview))
    with TestClient(create_api_app()) as client:
        assert (
            client.post(
                "/admin/corpus/sources/deletion-preview", json={"document_ids": ["filing"]}
            ).status_code
            == 404
        )
    with TestClient(create_api_app(admin_services=services)) as client:
        assert (
            client.post(
                "/admin/corpus/sources/deletion-preview", json={"document_ids": []}
            ).status_code
            == 422
        )
        preview.assert_not_awaited()
        response = client.post(
            "/admin/corpus/sources/deletion-preview", json={"document_ids": ["filing"]}
        )
    assert response.status_code == 200
    preview.assert_awaited_once_with(("filing",))
