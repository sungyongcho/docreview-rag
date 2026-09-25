"""Public runtime guards, the served resource set, and the container topology."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.api.app import create_api_app
from app.api.errors import ApiProblemError
from app.api.review_profile import PromptPolicy, ReviewSessionProfile
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


def test_public_runtime_rejects_custom_prompt_policy_before_provider_or_database() -> None:
    """Fail closed on Dev-only policy before touching any runtime dependency."""
    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), allow_custom_prompt_policy=False
    )
    request = ReviewRequest(
        query="Revenue?",
        session_profile=ReviewSessionProfile(
            prompt_policy=PromptPolicy(additional_instructions="Be concise.")
        ),
    )

    with pytest.raises(ApiProblemError) as captured:
        asyncio.run(services.review(request))

    assert captured.value.status_code == 403
    assert captured.value.error.code == "capability_disabled"


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


def test_runtime_openapi_includes_all_m5_resources():
    """Publish every served resource."""
    paths = set(create_api_app().openapi()["paths"])

    assert {
        "/retrieve",
        "/documents",
        "/review",
        "/runs/{run_id}",
        "/runs/{run_id}/traces",
        "/eval",
    } <= paths


def test_compose_preserves_postgres_and_has_no_worker_or_redis_service():
    """Keep the database and the app, and stay free of a queue or a worker."""
    compose = Path("docker/docker-compose.yml").read_text(encoding="utf-8")

    assert "pgvector/pgvector:pg16" in compose
    assert "postgresql+asyncpg://filing:filing@db:5432/filing" in compose
    assert "pg_data:/var/lib/postgresql/data" in compose
    assert "  app:\n" in compose
    assert "  redis:\n" not in compose
    assert "  worker:\n" not in compose
    assert "condition: service_healthy" in compose


def test_container_uses_the_locked_runtime_and_nonroot_user():
    """Install from the lock file, drop to a non-root user, and declare a health check."""
    dockerfile = Path("docker/Dockerfile").read_text(encoding="utf-8")

    assert "uv sync --locked --no-dev --no-install-project" in dockerfile
    assert "USER appuser" in dockerfile
    assert '"app.release.space:app"' in dockerfile
    assert "npm run build" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile
    # README churns with nearly every commit; it must stay out of the dependency layer.
    copy_lines = [line for line in dockerfile.splitlines() if line.startswith("COPY")]
    assert copy_lines and all("README" not in line for line in copy_lines)
