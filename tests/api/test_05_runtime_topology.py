"""Public runtime import isolation and snapshot-query authorization."""

import asyncio
import os
import subprocess
import sys

import pytest

from app.api.errors import ApiProblemError
from app.api.review_profile import ReviewSessionProfile
from app.api.runtime import RuntimeApiServices
from app.api.schemas import ReviewRequest
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_runtime_import_does_not_build_the_database_engine():
    """Import the API runtime cleanly under a database URL that could never be connected to."""
    environment = dict(os.environ)
    environment["DATABASE_URL"] = "not-a-valid-sqlalchemy-url"
    result = subprocess.run(
        [sys.executable, "-c", "import app.api.runtime; print('imported')"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "imported"
    assert result.stderr == ""


def test_public_runtime_rejects_snapshot_query_before_provider_or_database() -> None:
    """Keep public snapshot access read-only and comparison-only."""
    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), allow_snapshot_query=False
    )
    request = ReviewRequest(
        query="Revenue?",
        session_profile=ReviewSessionProfile(snapshot_id=1),
    )

    with pytest.raises(ApiProblemError) as captured:
        asyncio.run(services.review(request))

    assert captured.value.status_code == 403
    assert captured.value.error.code == "capability_disabled"
