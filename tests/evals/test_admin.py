"""Golden suite metadata and serialized evaluation queue behavior."""

import asyncio
from pathlib import Path

from app.api.admin_schemas import EvaluationRunRequest
from app.config import Settings
import app.evals.admin as admin_module
from app.evals.admin import EvaluationAdminService
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_suite_catalog_preserves_unapproved_provenance(tmp_path: Path) -> None:
    """Never present agent-curated pending cases as human-verified goldens."""
    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        artifact_dir=tmp_path / "runs",
    )

    suites = asyncio.run(service.suites())

    assert {suite.suite_id for suite in suites} == {"sec-en", "sec-ko", "dart-en", "dart-ko"}
    assert all(suite.approval_status == "pending-author-approval" for suite in suites)
    assert all(suite.human_verified is False for suite in suites)
    assert all(suite.source_ready is False for suite in suites)


def test_evaluation_queue_runs_one_job_to_completion(tmp_path: Path, monkeypatch) -> None:
    """Keep evaluation execution serial and retain its terminal artifact identity."""

    async def scenario() -> None:
        """Queue one evaluation and inspect its completed state."""
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def quick(job_id, request):
            """Stand in for one completed quick evaluation."""
            del job_id, request
            artifact = tmp_path / "runs" / "result.json"
            return 7, 6, artifact

        monkeypatch.setattr(service, "_quick", quick)
        job = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        await service._queue.join()
        completed = await service.job(job.job_id)

        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.result_id == 7
        assert completed.baseline_id == 6

    asyncio.run(scenario())


def test_matrix_forwards_dart_manifest_and_profile_parameters(tmp_path: Path, monkeypatch) -> None:
    """Bind isolated DART runs to their own manifest and explicit BM25 values."""

    async def scenario() -> None:
        """Capture one matrix invocation and verify its explicit parameters."""
        captured = None
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def run_cli(args):
            """Capture the parsed matrix namespace without corpus or database work."""
            nonlocal captured
            captured = args
            return {"persisted": [], "artifacts": []}

        monkeypatch.setattr(admin_module, "_run_cli", run_cli)
        request = EvaluationRunRequest(
            suite_id="dart-ko",
            mode="matrix",
            profile={"bm25_k1": 1.5, "bm25_b": 0.6},
        )
        await service._matrix(request)

        assert captured is not None
        assert captured.manifest_name == "dart-manifest.json"
        assert captured.bm25_k1 == 1.5
        assert captured.bm25_b == 0.6

    asyncio.run(scenario())
