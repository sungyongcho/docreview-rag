"""Manifest failures remain actionable and recover without providers or a user database."""

import asyncio
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.errors import ApiProblemError
from app.api.runtime import RuntimeApiServices
from app.api.schemas import RetrieveRequest
from app.api.scope_diagnostics import manifest_problem
from app.ingestion.manifest import CorpusIdentity, Manifest
from app.observability.stages import record_stages
from app.operator.jobs import JobStore
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.ingestion.support import filing_document


def valid_manifest():
    """Build one real document identity suitable for alias lookup."""
    return Manifest(
        corpus=CorpusIdentity(corpus_id="test", name="Test"), documents=(filing_document(),)
    )


@pytest.mark.parametrize(
    "cause", ["missing_file", "invalid_json", "invalid_manifest", "alias_conflict", "permission"]
)
def test_actual_manifest_failure_causes_and_recovery(tmp_path, monkeypatch, cause, caplog):
    """Every failed input retains its cause and the same service can load a repaired file."""
    path = tmp_path / "manifest.json"
    manifest = valid_manifest()
    if cause == "invalid_json":
        path.write_text("{broken")
    elif cause == "invalid_manifest":
        path.write_text(json.dumps({"unexpected": True}))
    elif cause == "alias_conflict":
        manifest.model_copy(
            update={
                "documents": (
                    manifest.documents[0].model_copy(update={"aliases": ("NVDA", "nvda")}),
                )
            }
        ).write(path)
    elif cause == "permission":
        manifest.write(path)
        monkeypatch.setattr(
            Manifest,
            "read",
            lambda _: (_ for _ in ()).throw(PermissionError("manifest permission denied")),
        )
    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), corpus_root=tmp_path
    )
    with pytest.raises(ApiProblemError) as captured:
        service._manifest_scope_index()
    error = captured.value.error
    assert error.code == "query_scope_unavailable" and error.cause == cause
    assert error.path == "manifest.json" and error.detail
    assert (
        len(
            [
                row
                for row in caplog.records
                if row.message == "Manifest scope index could not be loaded"
            ]
        )
        == 1
    )
    assert service._scope_index is None
    if cause == "permission":
        monkeypatch.undo()
    manifest.write(path)
    assert service._manifest_scope_index().match("NVDA revenue")


def test_production_omits_path_cause_detail_and_secrets(tmp_path):
    """The public payload contains the headline and stage but no diagnostic fields."""
    problem = manifest_problem(ValueError("private manifest token"), tmp_path, developer=False)
    payload = problem.error.model_dump(mode="json")
    assert payload == {
        "code": "query_scope_unavailable",
        "message": "Query scope metadata is unavailable.",
        "details": [],
        "failed_stage": "gate",
    }


def test_detail_is_bounded_redacted_and_uses_a_relative_path(tmp_path):
    """DEV diagnostics preserve the useful error while sanitizing configured secrets."""
    error = ValueError(f"{tmp_path}/manifest.json: fixture-secret " + "broken " * 1000)
    problem = manifest_problem(error, tmp_path, developer=True, secret_values=("fixture-secret",))
    assert str(tmp_path) not in problem.error.detail
    assert "fixture-secret" not in problem.error.detail
    assert len(problem.error.detail) < 1550
    assert "manifest.json" in problem.error.detail


def test_path_failure_records_stage_zero_and_recent_running_job(tmp_path, monkeypatch):
    """The decision starts before loading scope, and failure retains available job context."""
    monkeypatch.setattr(
        JobStore,
        "list",
        AsyncMock(
            return_value=(
                SimpleNamespace(
                    job_id="admin-source",
                    kind="acquire_edgar",
                    status="running",
                    result_refs={},
                    updated_at=datetime.now(UTC),
                ),
            )
        ),
    )
    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), corpus_root=tmp_path
    )
    with record_stages() as recorder, pytest.raises(ApiProblemError) as captured:
        asyncio.run(service._path_decision(RetrieveRequest(query="NVDA revenue")))
    assert captured.value.error.failed_stage == "path"
    assert captured.value.error.corpus_job == {
        "job_id": "admin-source",
        "kind": "acquire_edgar",
        "status": "running",
    }
    assert [(event.display_stage, event.status) for event in recorder.events] == [
        ("path", "failed")
    ]
    valid_manifest().write(tmp_path / "manifest.json")
    with record_stages() as recovered:
        decision, _ = asyncio.run(service._path_decision(RetrieveRequest(query="NVDA revenue")))
    assert decision.intent == "document_review"
    assert recovered.events[0].display_stage == "path" and recovered.events[0].status == "completed"


def test_unavailable_job_history_preserves_the_original_manifest_error(tmp_path, monkeypatch):
    """Secondary diagnosis cannot replace a primary manifest failure."""
    monkeypatch.setattr(
        JobStore, "list", AsyncMock(side_effect=RuntimeError("history unavailable"))
    )
    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), corpus_root=tmp_path
    )
    with pytest.raises(ApiProblemError) as captured:
        asyncio.run(service._scope_index_for_decision())
    assert captured.value.error.cause == "missing_file" and captured.value.error.corpus_job is None


@pytest.mark.parametrize("developer", [False, True])
def test_http_and_stream_keep_the_same_typed_scope_failure(
    tmp_path, monkeypatch, client_factory, developer
):
    """Transport envelopes retain stage-zero evidence and apply the same DEV boundary."""
    monkeypatch.setattr(JobStore, "list", AsyncMock(return_value=()))
    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        corpus_root=tmp_path,
        allow_custom_prompt_policy=developer,
    )
    response = client_factory(service).post("/retrieve", json={"query": "NVDA revenue"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["failed_stage"] == "path"
    assert ("cause" in error) is developer
    stream = client_factory(service).post(
        "/review/stream",
        json={"query": "NVDA revenue"},
        headers={"X-DocReview-Telemetry": "stages"},
    )
    assert stream.status_code == 200
    assert '"display_stage":"path"' in stream.text
    assert '"failed_stage":"path"' in stream.text
    assert ('"cause":"missing_file"' in stream.text) is developer
