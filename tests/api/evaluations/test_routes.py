"""Exercise evaluations behavior at service and HTTP boundaries."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.api.app import create_api_app
from app.api.evaluations.routes import _enqueue_evaluation, _evaluation_jobs
from app.api.review.runtime import RuntimeApiServices
from app.evals.admin.service import EvaluationAdminService
from app.evals.contracts import GoldenCanonicalResource, GoldenEvidencePage
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from tests.api.support import _admin


def test_duplicate_evaluation_is_a_typed_409():
    """Expose the authoritative duplicate identity through the standard API error contract."""
    import pytest

    from app.api.errors import ApiProblemError
    from app.evals.admin.service import EvaluationAlreadyQueuedError
    from app.evals.contracts import EvaluationRunRequest

    service = SimpleNamespace()
    service.evaluations = cast(
        EvaluationAdminService,
        SimpleNamespace(
            enqueue=AsyncMock(side_effect=EvaluationAlreadyQueuedError("eval-existing"))
        ),
    )
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(_enqueue_evaluation(service, EvaluationRunRequest(suite_id="sec-en")))
    assert error.value.status_code == 409
    assert error.value.error.code == "evaluation_already_queued"
    assert "eval-existing" in error.value.error.message


@pytest.mark.live_postgres
def test_evaluation_jobs_expose_each_recorded_result_configuration():
    """Read distinct matrix-arm metadata from real PostgreSQL without reading artifact files."""
    from app.db.models import EvalResult
    from app.evals.contracts import (
        EvaluationJobResource,
        EvaluationJobsResponse,
        EvaluationRunRequest,
    )
    from tests.live_postgres import isolated_session_factory

    async def exercise():
        """Compose only the read boundary against an explicitly disposable database."""
        async with isolated_session_factory() as factory:
            async with factory.begin() as session:
                rows = [
                    EvalResult(
                        suite="dart-en",
                        config={
                            "golden_provenance": {
                                "filename": "recorded.json",
                                "golden_sha256": "a" * 64,
                            },
                            "strategy": strategy,
                            "k": 5,
                        },
                        metrics={},
                        raw_artifact_path="not-read.json",
                    )
                    for strategy in ["lexical", "hybrid"]
                ]
                session.add_all(rows)
            board = EvaluationJobsResponse(
                jobs=(
                    EvaluationJobResource(
                        job_id="matrix-fixture",
                        request=EvaluationRunRequest(suite_id="dart-en", mode="matrix"),
                        status="succeeded",
                        stage="done",
                        message="Done",
                        created_at=rows[0].created_at,
                        result_id=rows[0].id,
                        result_ids=tuple(row.id for row in rows),
                    ),
                )
            )
            service = SimpleNamespace()
            service.runtime = cast(RuntimeApiServices, SimpleNamespace(session_factory=factory))
            service.evaluations = cast(
                EvaluationAdminService, SimpleNamespace(jobs=AsyncMock(return_value=board))
            )
            result = await _evaluation_jobs(service)
            assert [item.config["strategy"] for item in result.jobs[0].result_summaries] == [
                "lexical",
                "hybrid",
            ]
            assert all(
                item.config["golden_provenance"]["filename"] == "recorded.json"
                for item in result.jobs[0].result_summaries
            )

    asyncio.run(exercise())


def test_golden_canonical_route_is_read_only_and_typed():
    """Read the canonical dataset without asking the store to create a draft."""
    golden = SimpleNamespace(
        canonical=lambda _: GoldenCanonicalResource(
            suite_id="sec-en",
            filename="retrieval.json",
            payload=(),
            sha256="a" * 64,
        )
    )
    with TestClient(create_api_app(admin_services=_admin(golden=golden))) as client:
        response = client.get("/admin/golden/sec-en/canonical")
    assert response.status_code == 200
    assert response.json()["filename"] == "retrieval.json"
    assert response.json()["sha256"] == "a" * 64


def test_evaluation_preparation_and_submission_share_a_typed_blocker(tmp_path):
    """Missing sources produce read-only readiness and a 409 without any registered job."""
    from app.config import Settings
    from app.evals.admin.service import EvaluationAdminService
    from tests.corpus_admin.support import LedgerStore

    store = LedgerStore()
    evaluations = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        job_store=store,
    )
    services = _admin(evaluations=evaluations)
    with TestClient(create_api_app(admin_services=services)) as client:
        request = {"suite_id": "dart-ko", "mode": "quick"}
        preparation = client.post("/admin/evaluations/preparation", json=request)
        assert preparation.status_code == 200
        assert preparation.json()["state"] == "source_missing"
        assert preparation.json()["verification_status"] == "pending_review"
        rejected = client.post("/admin/evaluations/runs", json=request)
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "evaluation_not_ready"
        assert evaluations._jobs == {}
        assert store.rows == {}


def test_golden_field_errors_are_structured_and_evidence_pages_are_bounded():
    """Return safe domain validation details and reject excessive evidence page sizes."""
    from app.evals.golden.models import DraftFieldIssue, DraftInputError

    replace_case = AsyncMock(
        side_effect=DraftInputError(
            (
                DraftFieldIssue(
                    location=("tags", 0),
                    code="string_type",
                    message="Enter a tag.",
                ),
            )
        )
    )
    evidence = AsyncMock(return_value=GoldenEvidencePage(chunks=(), next_after=None))
    services = _admin(
        golden=SimpleNamespace(replace_case=replace_case),
        documents=SimpleNamespace(golden_evidence_chunks=evidence),
    )
    with TestClient(create_api_app(admin_services=services)) as client:
        response = client.put(
            "/admin/golden/revisions/1/cases/q-1",
            json={"expected_sha256": "a" * 64, "case": {"id": "q-1", "tags": [123]}},
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "golden_input_invalid"
        assert error["details"] == [
            {"location": ["tags", 0], "message": "Enter a tag.", "error_type": "string_type"}
        ]
        assert "input_value" not in response.text
        assert client.get("/admin/documents/ACME/golden-evidence?limit=51").status_code == 422
        evidence.assert_not_awaited()
        assert client.get("/admin/documents/ACME/golden-evidence?limit=20").status_code == 200
    evidence.assert_awaited_once_with("ACME", "", 0, 20)
