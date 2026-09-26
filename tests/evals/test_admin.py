"""Serialized evaluation queue, cancellation, and job-history behavior."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.api.admin_schemas import (
    EvaluationJobResource,
    EvaluationPreparationResource,
    EvaluationRunRequest,
    RetrievalProfile,
)
from app.config import Settings
from app.corpus_admin.runtime import RuntimeCorpusAdminService
from app.corpus_admin.types import AdminCommand, CorpusStatus, OperationOutcome
from app.evals.admin import EvaluationAdminService, EvaluationAlreadyQueuedError
from app.operator.jobs import JobExecutionCoordinator
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.corpus_admin.support import LedgerStore


@pytest.fixture
def ready_evaluation_inputs(monkeypatch):
    """Keep queue/coordinator tests independent from the separately tested input preflight."""

    async def prepared(self, request):
        """Provide a ready request before exercising scheduling and persistence behavior."""
        return EvaluationPreparationResource(
            suite_id=request.suite_id, kind="builtin", state="ready"
        )

    monkeypatch.setattr(EvaluationAdminService, "preparation", prepared)


async def enqueued_job(service: EvaluationAdminService, job_id: str) -> EvaluationJobResource:
    """Wait for scheduled writes, then read the job through the persistent list contract."""
    await service._persister.flush(job_id)
    return next(job for job in (await service.jobs()).jobs if job.job_id == job_id)


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_evaluation_queue_runs_one_job_to_completion(tmp_path: Path, monkeypatch) -> None:
    """Keep evaluation execution serial and retain its terminal artifact identity."""

    async def scenario() -> None:
        """Queue one evaluation and inspect its completed state."""
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
            job_store=LedgerStore(),
        )

        async def quick(job_id, request):
            """Stand in for one completed quick evaluation."""
            del job_id, request
            artifact = tmp_path / "runs" / "result.json"
            return 7, 6, artifact

        monkeypatch.setattr(service, "_quick", quick)
        job = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        await service._queue.join()
        completed = await enqueued_job(service, job.job_id)

        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.result_id == 7
        assert completed.baseline_id == 6
        assert service._jobs == {}

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
            job_store=LedgerStore(),
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
        assert (await enqueued_job(service, second.job_id)).status == "cancelled"
        assert service._jobs == {}

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
            job_store=LedgerStore(),
            execution_lock=lock,
            execution_coordinator=coordinator,
        )
        evaluation = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
            execution_lock=lock,
            execution_coordinator=coordinator,
            job_store=LedgerStore(),
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
        assert (await enqueued_job(evaluation, evaluation_job.job_id)).status == "queued"

        gate.set()
        await corpus._job_queue._queue.join()
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

        async def readiness() -> CorpusStatus:
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
            job_store=LedgerStore(),
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
            assert isinstance(first, EvaluationJobResource)
            assert duplicate.job_id == first.job_id
            assert first.message == "Waiting for backfill_embeddings embedding-job to finish."
            assert len(service._jobs) == 1
            assert calls == []
            if preparation_succeeds:
                status = replace(status, pending_embeddings=0, embedded_chunks=10)
        await service._queue.join()
        result = await enqueued_job(service, first.job_id)
        assert result is not None
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
            job_store=LedgerStore(),
        )
        async with coordinator.turn("embed"):
            first = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
            second = await service.enqueue(EvaluationRunRequest(suite_id="sec-ko"))
            assert "embed" in second.message
        async with coordinator.turn("lexical"):
            assert "rebuild_bm25 lexical" in (await enqueued_job(service, first.job_id)).message
            assert "rebuild_bm25 lexical" in (await enqueued_job(service, second.job_id)).message
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
        job_store=LedgerStore(),
    )
    request = EvaluationRunRequest(
        suite_id="sec-en",
        profile=RetrievalProfile(
            strategy=strategy, lexical_ranker=None if strategy == "vector" else "bm25"
        ),
    )
    if allowed:
        asyncio.run(service._require_preparation(request, allow_pending=False))
    else:
        with pytest.raises(ValueError, match="step [34]"):
            asyncio.run(service._require_preparation(request, allow_pending=False))


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_failed_durable_enqueue_does_not_leave_a_duplicate_reservation(tmp_path, monkeypatch):
    """Allow retry after failed ledger creation without leaving a ghost queued job."""
    from unittest.mock import AsyncMock

    async def scenario():
        """Fail one durable create, then confirm the same request receives a real queue ticket."""
        coordinator = JobExecutionCoordinator()
        await coordinator.register("blocker", datetime.now(UTC))
        store = LedgerStore()
        create = store.create
        monkeypatch.setattr(store, "create", AsyncMock(side_effect=RuntimeError("offline")))
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
            execution_coordinator=coordinator,
        )
        request = EvaluationRunRequest(suite_id="sec-en")
        with pytest.raises(RuntimeError, match="offline"):
            await service.enqueue(request)
        assert not service._jobs
        assert not store.rows
        monkeypatch.setattr(store, "create", create)
        job = await service.enqueue(request)
        assert service._queue.qsize() == 1
        assert list(service._jobs) == [job.job_id]
        await service.cancel(job.job_id)
        await coordinator.cancel("blocker")
        await service._queue.join()
        assert (await enqueued_job(service, job.job_id)).status == "cancelled"
        assert service._jobs == {}

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_cancel_waits_for_queued_progress_before_persisting_terminal_state(tmp_path, monkeypatch):
    """A delayed queued message must not overwrite a cancellation in the persistent job board."""

    async def scenario():
        """Hold a queued metadata write, request cancellation, then release the stale write."""
        started = asyncio.Event()
        release = asyncio.Event()
        store = LedgerStore()
        write = store.put

        async def put(job_id, **fields):
            """Delay the first queued snapshot to reproduce an out-of-order commit."""
            if fields["status"] == "queued":
                started.set()
                await release.wait()
            return await write(job_id, **fields)

        monkeypatch.setattr(store, "put", put)
        coordinator = JobExecutionCoordinator()
        await coordinator.register("blocker", datetime.now(UTC), kind="backfill_embeddings")
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
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
        assert store.puts == ["queued", "cancelled"]
        assert (await enqueued_job(service, job.job_id)).status == "cancelled"
        assert service._jobs == {}
        await coordinator.cancel("blocker")

    asyncio.run(scenario())


def test_restored_evaluation_history_appears_without_restart(tmp_path):
    """An initially archived result reappears after ledger restoration without restarting."""

    async def scenario():
        """Change only the archive marker, as the history service does, between real reads."""
        store = LedgerStore()
        request = EvaluationRunRequest(suite_id="sec-en")
        recorded = datetime(2026, 1, 1, tzinfo=UTC)
        row = await store.create(
            job_id="restored-evaluation",
            domain="evaluation",
            kind="quick",
            request_json=request.model_dump(mode="json"),
            created_at=recorded,
            result_refs={
                "__history_archived": True,
                "result_id": 7,
                "result_ids": [7],
                "baseline_id": 3,
                "artifact_paths": ["sec-en.json"],
            },
        )
        store.rows[row.job_id] = replace(
            row,
            status="succeeded",
            stage="complete",
            message="Evaluation completed",
            current=20,
            total=20,
            started_at=recorded,
            finished_at=recorded,
        )
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
        )
        assert (await service.jobs()).jobs == ()
        restored_refs = dict(store.rows[row.job_id].result_refs)
        del restored_refs["__history_archived"]
        store.rows[row.job_id] = replace(store.rows[row.job_id], result_refs=restored_refs)

        board = await service.jobs()

        assert [job.job_id for job in board.jobs] == ["restored-evaluation"]
        restored = board.jobs[0]
        assert restored.status == "succeeded"
        assert restored.request == request
        assert (restored.current, restored.total) == (20, 20)
        assert (restored.result_id, restored.result_ids, restored.baseline_id) == (7, (7,), 3)
        assert restored.artifact_paths == ("sec-en.json",)
        assert service._jobs == {}
        assert service._worker is None
        store.rows[row.job_id] = replace(
            store.rows[row.job_id], result_refs={**restored_refs, "__history_archived": True}
        )
        assert (await service.jobs()).jobs == ()
        del store.rows[row.job_id]
        assert (await service.jobs()).jobs == ()

    asyncio.run(scenario())


def test_restart_restores_persisted_evaluation_history(tmp_path, monkeypatch):
    """A rebuilt service lists stored succeeded and interrupted jobs with result references."""

    async def scenario():
        """Project two stored rows after the normal once-per-process recovery."""
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
                kind="quick",
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
        store = LedgerStore()
        store.rows.update((row.job_id, row) for row in rows)
        recover = AsyncMock(return_value=("eval-new",))
        monkeypatch.setattr(store, "interrupt_incomplete", recover)
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
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
        # Reading stored history does not register terminal rows as active execution state.
        assert service._jobs == {}
        assert await service.jobs() == board
        recover.assert_awaited_once_with("evaluation")

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["failed", "interrupted"])
@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_evaluation_retry_uses_persisted_request_without_loading_history(
    tmp_path, monkeypatch, status
):
    """Retry eligible history directly from the ledger and retain the original result."""

    async def scenario():
        """Run the stored profile as a new job without placing historical jobs in memory."""
        store = LedgerStore()
        request = EvaluationRunRequest(
            suite_id="sec-ko",
            profile=RetrievalProfile(strategy="vector", lexical_ranker=None),
        )
        row = await store.create(
            job_id="previous-evaluation",
            domain="evaluation",
            kind="quick",
            request_json=request.model_dump(mode="json"),
        )
        original = replace(row, status=status, stage=status)
        store.rows[row.job_id] = original
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
        )
        ran = []

        async def quick(job_id, selected):
            """Record the persisted request actually used by the new evaluation."""
            ran.append(selected)
            return 8, None, tmp_path / "retry.json"

        monkeypatch.setattr(service, "_quick", quick)
        retried = await service.retry(row.job_id)
        await service._queue.join()

        assert retried.job_id != row.job_id
        assert ran == [request]
        assert store.rows[retried.job_id].result_refs["retry_of"] == row.job_id
        assert (await enqueued_job(service, retried.job_id)).status == "succeeded"
        assert store.rows[row.job_id] == original
        assert service._jobs == {}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "state,message",
    [
        ("missing", "deleted jobs cannot be retried"),
        ("archived", "Restore archived history"),
        ("corpus", "only failed or interrupted evaluations"),
        ("queued", "only failed or interrupted evaluations"),
        ("running", "only failed or interrupted evaluations"),
        ("succeeded", "only failed or interrupted evaluations"),
        ("cancelled", "only failed or interrupted evaluations"),
    ],
)
def test_evaluation_retry_rejects_ineligible_persisted_jobs(tmp_path, state, message):
    """Missing, archived, other-domain, and non-retryable records create no execution work."""

    async def scenario():
        """Keep the ledger unchanged when an operator selects an ineligible retry target."""
        store = LedgerStore()
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
        )
        await service.recover_jobs()
        if state != "missing":
            row = await store.create(
                job_id="ineligible",
                domain="corpus" if state == "corpus" else "evaluation",
                kind="quick",
                request_json=EvaluationRunRequest(suite_id="sec-en").model_dump(mode="json"),
                result_refs={"__history_archived": True} if state == "archived" else {},
            )
            store.rows[row.job_id] = replace(
                row, status="failed" if state in {"archived", "corpus"} else state
            )
        before = dict(store.rows)

        with pytest.raises(ValueError, match=message):
            await service.retry("ineligible")

        assert store.rows == before
        assert service._jobs == {}
        assert service._worker is None

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
            job_store=LedgerStore(),
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
