"""Serialized evaluation queue, cancellation, and job-history behavior."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from app.api.admin_schemas import EvaluationPreparationResource, EvaluationRunRequest
from app.config import Settings
from app.corpus_admin import AdminCommand, CorpusStatus, OperationOutcome, RuntimeCorpusAdminService
from app.evals.admin import EvaluationAdminService, EvaluationAlreadyQueuedError
from app.operator.jobs import JobExecutionCoordinator, JobStore
from app.retrieval.embeddings import DeterministicEmbeddingProvider


@pytest.fixture
def ready_evaluation_inputs(monkeypatch):
    """Keep queue/coordinator tests independent from the separately tested input preflight."""

    async def prepared(self, request):
        """Provide a ready request before exercising scheduling and persistence behavior."""
        return EvaluationPreparationResource(
            suite_id=request.suite_id, kind="builtin", state="ready"
        )

    monkeypatch.setattr(EvaluationAdminService, "preparation", prepared)


@pytest.mark.usefixtures("ready_evaluation_inputs")
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


@pytest.mark.usefixtures("ready_evaluation_inputs")
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


@pytest.mark.usefixtures("ready_evaluation_inputs")
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

        async def corpus_runner(command, publish) -> OperationOutcome:
            """Hold the shared lock while one corpus job is active."""
            del command, publish
            events.append("corpus-start")
            await gate.wait()
            events.append("corpus-finish")
            return OperationOutcome("done")

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


@pytest.mark.parametrize("preparation_succeeds", [True, False])
@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_waiting_evaluation_deduplicates_and_rechecks_preparation(
    tmp_path, monkeypatch, preparation_succeeds
):
    """Queue behind embeddings, reject duplicates, and never measure a failed partial index."""

    async def scenario():
        """Hold the corpus turn, submit twice, then expose the actual terminal readiness."""
        coordinator = JobExecutionCoordinator()
        await coordinator.register("embedding-job", datetime.now(UTC), kind="backfill_embeddings")
        status = CorpusStatus(True, "compatible", "ok", 1, 10, 5, 5, True, True, "deterministic")
        calls = []

        async def readiness():
            """Return readiness as changed by the simulated corpus completion."""
            return status

        async def quick(job_id, request):
            """Record evaluation only after readiness has been checked."""
            calls.append(job_id)
            return 1, None, tmp_path / "result.json"

        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            execution_coordinator=coordinator,
            corpus_status=readiness,
        )
        monkeypatch.setattr(service, "_quick", quick)
        request = EvaluationRunRequest(suite_id="sec-en")
        async with coordinator.turn("embedding-job"):
            first, duplicate = await asyncio.gather(
                service.enqueue(request),
                service.enqueue(request),
                return_exceptions=True,
            )
            assert isinstance(duplicate, EvaluationAlreadyQueuedError)
            assert duplicate.job_id == first.job_id
            assert first.message == "Waiting for backfill_embeddings embedding-job to finish."
            assert len(service._jobs) == 1
            assert calls == []
            if preparation_succeeds:
                status = replace(status, pending_embeddings=0, embedded_chunks=10)
        await service._queue.join()
        result = await service.job(first.job_id)
        assert result.status == ("succeeded" if preparation_succeeds else "failed")
        assert len(calls) == int(preparation_succeeds)
        if not preparation_succeeds:
            assert "step 3" in result.message

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_evaluation_waiting_message_tracks_the_current_global_blocker(tmp_path):
    """Refresh every queued evaluation when the active corpus job advances to BM25."""

    async def scenario():
        """Advance a controlled queue without starting expensive evaluation work."""
        coordinator = JobExecutionCoordinator()
        now = datetime.now(UTC)
        await coordinator.register("embed", now, kind="backfill_embeddings")
        await coordinator.register("lexical", now, kind="rebuild_bm25")
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            execution_coordinator=coordinator,
        )
        async with coordinator.turn("embed"):
            first = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
            second = await service.enqueue(EvaluationRunRequest(suite_id="sec-ko"))
            assert "embed" in second.message
        async with coordinator.turn("lexical"):
            assert "rebuild_bm25 lexical" in (await service.job(first.job_id)).message
            assert "rebuild_bm25 lexical" in (await service.job(second.job_id)).message
            await service.cancel(first.job_id)
            await service.cancel(second.job_id)
        await service._queue.join()
        assert coordinator.busy is False
        assert coordinator.has_kind("backfill_embeddings") is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "strategy,embeddings,bm25,allowed",
    [
        ("hybrid", False, True, False),
        ("hybrid", True, False, False),
        ("vector", True, False, True),
        ("lexical", False, True, True),
    ],
)
def test_quick_evaluation_preparation_matches_the_selected_strategy(
    tmp_path, strategy, embeddings, bm25, allowed
):
    """Keep BM25 explicit while allowing vector or lexical profiles their independent ready lane."""

    async def status():
        """Return one corpus combination without provider or database work."""
        return CorpusStatus(
            True,
            "compatible",
            "ok",
            1,
            10,
            10 if embeddings else 0,
            0 if embeddings else 10,
            bm25,
            True,
            "deterministic",
        )

    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        corpus_status=status,
    )
    request = EvaluationRunRequest(
        suite_id="sec-en",
        profile={"strategy": strategy, "lexical_ranker": None if strategy == "vector" else "bm25"},
    )
    if allowed:
        asyncio.run(service._require_preparation(request, allow_pending=False))
    else:
        with pytest.raises(ValueError, match="step [34]"):
            asyncio.run(service._require_preparation(request, allow_pending=False))


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_failed_durable_enqueue_does_not_leave_a_duplicate_reservation(tmp_path):
    """Allow retry after failed ledger creation without leaving a ghost queued job."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def scenario():
        """Fail one durable create, then confirm the same request receives a real queue ticket."""
        coordinator = JobExecutionCoordinator()
        await coordinator.register("blocker", datetime.now(UTC))
        store = SimpleNamespace(
            interrupt_incomplete=AsyncMock(),
            create=AsyncMock(side_effect=[RuntimeError("offline"), None]),
            put=AsyncMock(),
            cancel=AsyncMock(),
            list=AsyncMock(return_value=()),
        )
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=cast(JobStore, store),
            execution_coordinator=coordinator,
        )
        request = EvaluationRunRequest(suite_id="sec-en")
        with pytest.raises(RuntimeError, match="offline"):
            await service.enqueue(request)
        assert not service._jobs
        job = await service.enqueue(request)
        assert service._queue.qsize() == 1
        assert list(service._jobs) == [job.job_id]
        # Cancel from the in-memory record; no retrieval or user DB is involved.
        service._job_store = None
        await service.cancel(job.job_id)
        await coordinator.cancel("blocker")
        await service._queue.join()
        await service._persister.flush(job.job_id)

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_cancel_waits_for_queued_progress_before_persisting_terminal_state(tmp_path):
    """A delayed queued message must not overwrite a cancellation in the persistent job board."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def scenario():
        """Hold a queued metadata write, request cancellation, then release the stale write."""
        started = asyncio.Event()
        release = asyncio.Event()
        written = []

        async def put(job_id, **fields):
            """Delay the first queued snapshot to reproduce an out-of-order commit."""
            if fields["status"] == "queued":
                started.set()
                await release.wait()
            written.append(fields["status"])

        store = SimpleNamespace(
            interrupt_incomplete=AsyncMock(),
            create=AsyncMock(),
            put=put,
            list=AsyncMock(return_value=()),
        )
        coordinator = JobExecutionCoordinator()
        await coordinator.register("blocker", datetime.now(UTC), kind="backfill_embeddings")
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=cast(JobStore, store),
            execution_coordinator=coordinator,
        )
        job = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        await started.wait()
        cancellation = asyncio.create_task(service.cancel(job.job_id))
        await asyncio.sleep(0)
        assert not cancellation.done()
        release.set()
        assert (await cancellation).status == "cancelled"
        await service._queue.join()
        assert written == ["queued", "cancelled"]
        await coordinator.cancel("blocker")

    asyncio.run(scenario())


def test_restart_restores_persisted_evaluation_history(tmp_path):
    """A rebuilt service lists stored succeeded and interrupted jobs with result references."""

    async def scenario():
        """Hydrate two persisted rows into the in-memory job board on first access."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from app.operator.jobs import StoredJob

        request = EvaluationRunRequest(suite_id="sec-en")
        earlier = datetime(2026, 1, 1, tzinfo=UTC)
        later = datetime(2026, 1, 2, tzinfo=UTC)
        rows = (
            StoredJob(
                job_id="eval-old",
                domain="evaluation",
                kind="quick",
                request_json=request.model_dump(mode="json"),
                status="succeeded",
                stage="complete",
                current=20,
                total=20,
                detail_current=None,
                detail_total=None,
                message="Evaluation completed",
                error_code=None,
                result_refs={
                    "result_id": 7,
                    "result_ids": [7],
                    "baseline_id": 3,
                    "artifact_paths": ["sec-en.json"],
                },
                created_at=earlier,
                started_at=earlier,
                finished_at=earlier,
                updated_at=earlier,
            ),
            StoredJob(
                job_id="eval-new",
                domain="evaluation",
                kind="matrix",
                request_json=request.model_dump(mode="json"),
                status="interrupted",
                stage="interrupted",
                current=4,
                total=20,
                detail_current=None,
                detail_total=None,
                message="Interrupted by application restart; retry explicitly.",
                error_code="process_restarted",
                result_refs={},
                created_at=later,
                started_at=later,
                finished_at=later,
                updated_at=later,
            ),
        )
        store = SimpleNamespace(
            interrupt_incomplete=AsyncMock(return_value=("eval-new",)),
            list=AsyncMock(return_value=rows),
        )
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=cast(JobStore, store),
        )

        board = await service.jobs()

        assert [job.job_id for job in board.jobs] == ["eval-new", "eval-old"]
        restored = board.jobs[1]
        assert restored.status == "succeeded"
        assert restored.request.suite_id == "sec-en"
        assert restored.result_id == 7
        assert restored.result_ids == (7,)
        assert restored.baseline_id == 3
        assert restored.artifact_paths == ("sec-en.json",)
        assert board.jobs[0].status == "interrupted"
        # A restart keeps interrupted jobs retryable without another store lookup.
        assert service._jobs["eval-new"].status == "interrupted"

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_queued_profiles_fill_unstated_bm25_values_from_settings(
    tmp_path: Path, monkeypatch
) -> None:
    """Queued evaluations record and run server BM25 values only where they state none."""

    async def scenario() -> None:
        """Queue one default and one partially stated profile and capture both runs."""
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path, bm25_k1=1.6, bm25_b=0.5, bm25_idf="robertson"),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )
        ran = {}

        async def quick(job_id, request):
            """Capture the profile a completed quick evaluation received."""
            ran[job_id] = request.profile
            return 7, 6, tmp_path / "runs" / "result.json"

        monkeypatch.setattr(service, "_quick", quick)
        inherited = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        stated = await service.enqueue(
            EvaluationRunRequest.model_validate({"suite_id": "sec-ko", "profile": {"bm25_k1": 0.9}})
        )
        await service._queue.join()

        for job, expected in (
            (inherited, (1.6, 0.5, "robertson")),
            (stated, (0.9, 0.5, "robertson")),
        ):
            recorded = job.request.profile
            assert (recorded.bm25_k1, recorded.bm25_b, recorded.bm25_idf) == expected
            profile = ran[job.job_id]
            assert (profile.bm25_k1, profile.bm25_b, profile.bm25_idf) == expected

    asyncio.run(scenario())
