"""HTTP and streaming scope failures preserve the same diagnostic boundary."""

from unittest.mock import AsyncMock

import pytest

from app.api.review.runtime import RuntimeApiServices
from app.operator.jobs.store import JobStore
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider


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
