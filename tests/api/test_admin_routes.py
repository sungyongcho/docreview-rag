"""Administrator route injection and public-surface isolation."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from fastapi.testclient import TestClient

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.admin_schemas import (
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationRunRequest,
    UsageResponse,
)
from app.api.app import create_api_app


class FakeAdminServices:
    """Small route-level administrator service fixture."""

    async def corpus_snapshot(self):
        """Return one schema-compatible empty corpus."""
        return {"mode": "live", "status": {"schema_status": "compatible"}}

    async def document_detail(self, doc_id):
        """Return no detail for unknown documents."""
        return None

    async def enqueue_corpus(self, request):
        """Echo one safe operation kind."""
        return {"job_id": "corpus-1", "kind": request.kind}

    async def corpus_jobs(self):
        """Return an empty queue."""
        return {"active": None, "queued": [], "history": []}

    async def retry_corpus(self, job_id):
        """Return one retry identity."""
        return {"job_id": job_id}

    async def suites(self):
        """Return no suites for this route fixture."""
        return ()

    async def enqueue_evaluation(self, request: EvaluationRunRequest):
        """Return one queued evaluation."""
        return EvaluationJobResource(
            job_id="eval-1",
            request=request,
            status="queued",
            stage="queued",
            message="Queued",
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )

    async def evaluation_jobs(self):
        """Return an empty evaluation job list."""
        return EvaluationJobsResponse(jobs=())

    async def evaluation_job(self, job_id):
        """Return no job for this route fixture."""
        return None

    async def usage(self):
        """Return one empty local usage ledger."""
        return UsageResponse(
            runs=0,
            requests=0,
            input_tokens=0,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            estimated_cost_usd=Decimal("0"),
            latest_run_at=None,
            models=(),
        )

    async def compare(self, candidate_id, baseline_id):
        """Leave comparison unused in this focused route test."""
        raise AssertionError((candidate_id, baseline_id))

    async def retrieval_preview(self, request):
        """Leave preview unused in this focused route test."""
        raise AssertionError(request)

    async def review_preview(self, request):
        """Leave review unused in this focused route test."""
        raise AssertionError(request)


def test_admin_routes_are_absent_without_explicit_composition() -> None:
    """Keep the stable public OpenAPI surface free of administrator operations."""
    with TestClient(create_api_app()) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert not any(path.startswith("/admin") for path in paths)


def test_admin_routes_are_injected_and_typed() -> None:
    """Expose local routes only with one explicit administrator service override."""
    services = cast(RuntimeAdminApiServices, FakeAdminServices())
    with TestClient(create_api_app(admin_services=services)) as client:
        corpus = client.get("/admin/corpus")
        queued = client.post(
            "/admin/evaluations/runs",
            json={
                "suite_id": "sec-en",
                "mode": "quick",
                "profile": {},
                "target_text_chars": [500, 1200],
                "strategies": ["lexical", "vector", "hybrid"],
                "lexical_rankers": ["ts_rank_cd", "bm25"],
            },
        )
        corpus_job = client.post(
            "/admin/corpus/jobs",
            json={
                "kind": "acquire_edgar",
                "identifiers": ["NVDA"],
                "years": [2024],
            },
        )
        missing = client.get("/admin/jobs/missing")
        usage = client.get("/admin/usage")

    assert corpus.status_code == 200
    assert corpus.json()["status"]["schema_status"] == "compatible"
    assert queued.status_code == 200
    assert queued.json()["job_id"] == "eval-1"
    assert corpus_job.status_code == 200
    assert corpus_job.json()["kind"] == "acquire_edgar"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "evaluation_job_not_found"
    assert usage.status_code == 200
    assert usage.json()["estimated_cost_usd"] == "0"
