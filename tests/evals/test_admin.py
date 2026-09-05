"""Golden suite metadata and serialized evaluation queue behavior."""

import asyncio
import json
from pathlib import Path

from app.api.admin_schemas import EvaluationRunRequest
from app.config import Settings
from app.corpus_admin import AdminCommand, RuntimeCorpusAdminService
import app.evals.admin as admin_module
from app.evals.admin import EvaluationAdminService
from app.operator.jobs import JobExecutionCoordinator
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def _absent_case(question: str) -> dict[str, object]:
    """Build one source-free revision case for focused resolver tests."""
    return {
        "id": "test-01",
        "question": question,
        "category": "absent",
        "facet": "policy",
        "tags": [],
        "answers": [],
        "expected_label": "NOT_IN_DOCS",
        "reference_answer": "NOT_IN_DOCS",
        "note": "Deliberate negative case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }


def test_suite_catalog_preserves_unapproved_provenance(tmp_path: Path) -> None:
    """Never present agent-curated pending cases as human-verified goldens."""
    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        artifact_dir=tmp_path / "runs",
    )

    suites = asyncio.run(service.suites())

    assert {suite.suite_id for suite in suites} == {
        "sec-en",
        "sec-ko",
        "dart-en",
        "dart-ko",
        "sec-en_v2_astra",
        "sec-ko_v2_astra",
        "sec-mixed_v2_astra",
    }
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


def test_selected_golden_revision_drives_quick_and_matrix_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    """Evaluate the selected DB payload instead of silently falling back to canonical JSON."""

    async def scenario() -> None:
        """Resolve one revision for quick mode and materialize it for matrix mode."""
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "manifest.json").write_text("[]", encoding="utf-8")
        payload = [_absent_case("Revision question?")]
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=corpus_dir),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def revision_payload(request):
            """Return the selected revision bytes without a live database."""
            assert request.golden_revision_id == 9
            return payload, "a" * 64

        captured = None

        async def run_cli(args):
            """Read the temporary matrix input while it is still present."""
            nonlocal captured
            captured = (args, json.loads(args.golden.read_text(encoding="utf-8")))
            return {"persisted": [], "artifacts": []}

        monkeypatch.setattr(service, "_golden_revision_payload", revision_payload)
        monkeypatch.setattr(admin_module, "_run_cli", run_cli)
        request = EvaluationRunRequest(suite_id="sec-en", golden_revision_id=9)

        cases, sha256 = await service._evaluation_cases(request)
        await service._matrix(request.model_copy(update={"mode": "matrix"}))

        assert cases[0].question == "Revision question?"
        assert sha256 == "a" * 64
        assert captured is not None
        args, written = captured
        assert written == payload
        assert not args.golden.exists()

    asyncio.run(scenario())


def test_queued_evaluation_can_be_cancelled_before_execution(tmp_path: Path, monkeypatch) -> None:
    """Keep cancellation cost-free by allowing it only before evaluation starts."""

    async def scenario() -> None:
        """Hold one active evaluation and cancel its queued successor."""
        gate = asyncio.Event()
        calls = 0
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def quick(job_id, request):
            """Block the first evaluation and record that the second never ran."""
            nonlocal calls
            del job_id, request
            calls += 1
            await gate.wait()
            return 1, None, tmp_path / "runs" / "result.json"

        monkeypatch.setattr(service, "_quick", quick)
        await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        second = await service.enqueue(EvaluationRunRequest(suite_id="sec-ko"))
        await asyncio.sleep(0)
        cancelled = await service.cancel(second.job_id)
        gate.set()
        await service._queue.join()

        assert calls == 1
        assert cancelled.status == "cancelled"
        assert (await service.job(second.job_id)).status == "cancelled"

    asyncio.run(scenario())


def test_corpus_and_evaluation_workers_share_one_execution_lock(
    tmp_path: Path, monkeypatch
) -> None:
    """Keep heavy corpus and evaluation work serialized across domain queues."""

    async def scenario() -> None:
        """Hold corpus work and prove evaluation remains queued until release."""
        lock = asyncio.Lock()
        coordinator = JobExecutionCoordinator()
        gate = asyncio.Event()
        events: list[str] = []

        async def corpus_runner(command, publish) -> str:
            """Hold the shared lock while one corpus job is active."""
            del command, publish
            events.append("corpus-start")
            await gate.wait()
            events.append("corpus-finish")
            return "done"

        corpus = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=corpus_runner,
            execution_lock=lock,
            execution_coordinator=coordinator,
        )
        evaluation = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
            execution_lock=lock,
            execution_coordinator=coordinator,
        )

        async def quick(job_id, request):
            """Record evaluation start only after corpus releases the lock."""
            del job_id, request
            events.append("evaluation-start")
            return 1, None, tmp_path / "runs" / "result.json"

        monkeypatch.setattr(evaluation, "_quick", quick)
        await corpus.enqueue(AdminCommand("rebuild_bm25"))
        evaluation_job = await evaluation.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        await asyncio.sleep(0)
        assert events == ["corpus-start"]
        assert (await evaluation.job(evaluation_job.job_id)).status == "queued"

        gate.set()
        await corpus._queue.join()
        await evaluation._queue.join()
        assert events == ["corpus-start", "corpus-finish", "evaluation-start"]

    asyncio.run(scenario())
