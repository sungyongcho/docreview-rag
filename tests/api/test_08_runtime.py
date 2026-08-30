"""Runtime entrypoint, health, and the container topology it is served by."""

import os
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app, create_app


def test_runtime_factory_is_import_safe_and_creates_distinct_apps():
    """Build a fresh application per call, with the module-level one already importable."""
    first = create_app()
    second = create_app()

    assert isinstance(app, FastAPI)
    assert isinstance(first, FastAPI)
    assert first is not second


def test_runtime_import_does_not_build_the_database_engine():
    """Import cleanly under a database URL that could never be connected to."""
    environment = dict(os.environ)
    environment["DATABASE_URL"] = "not-a-valid-sqlalchemy-url"
    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print('imported')"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "imported"
    assert result.stderr == ""


def test_health_route_reports_process_liveness_without_external_services():
    """Answer the health probe without reaching a database or a provider."""
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_runtime_openapi_includes_all_m5_resources():
    """Publish health alongside every served resource."""
    paths = set(create_app().openapi()["paths"])

    assert {
        "/health",
        "/retrieve",
        "/documents",
        "/ingest",
        "/review",
        "/runs/{run_id}",
        "/runs/{run_id}/traces",
        "/eval",
    } <= paths


def test_compose_preserves_postgres_and_has_no_worker_or_redis_service():
    """Keep the database and the app, and stay free of a queue or a worker."""
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "pgvector/pgvector:pg16" in compose
    assert "postgresql+asyncpg://filing:filing@db:5432/filing" in compose
    assert "pg_data:/var/lib/postgresql/data" in compose
    assert "  app:\n" in compose
    assert "  redis:\n" not in compose
    assert "  worker:\n" not in compose
    assert "condition: service_healthy" in compose
    assert "/health" in compose


def test_container_uses_the_locked_runtime_and_nonroot_user():
    """Install from the lock file, drop to a non-root user, and declare a health check."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "uv sync --locked --no-dev --no-install-project" in dockerfile
    assert "USER appuser" in dockerfile
    assert '"app.cli", "serve"' in dockerfile
    assert "HEALTHCHECK" in dockerfile
