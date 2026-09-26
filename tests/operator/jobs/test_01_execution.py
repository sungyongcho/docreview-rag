"""Persistent unified operator job ledger behavior."""

import asyncio
from datetime import UTC, datetime
from functools import partial

import pytest

from app.config import Settings
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.corpus_admin.types import AdminCommand, OperationOutcome
from app.ingestion.progress import OperationProgress
from app.operator.jobs.execution import (
    JobExecutionCoordinator,
    JobPersistenceError,
    ProgressPersister,
)
from app.operator.jobs.store import JobStore
from tests.live_postgres import isolated_session_factory


@pytest.mark.parametrize("terminal", [False, True])
def test_progress_persister_coalesces_bursts_and_lands_the_terminal_write_last(terminal) -> None:
    """Write one snapshot at a time, catch up once, and let the final write land last."""

    async def scenario() -> None:
        """Block the first write, burst progress behind it, then finish the job."""
        entered = asyncio.Event()
        release = asyncio.Event()
        caught_up = asyncio.Event()
        state = "p1"
        writes: list[str] = []

        async def write(job_id: str) -> None:
            """Record the snapshot seen at write time, holding the first write of each job."""
            snapshot = state
            if snapshot == "p1":
                entered.set()
                await release.wait()
            writes.append(snapshot)
            if snapshot == "p3":
                caught_up.set()

        persister = ProgressPersister(write)
        persister.start("job")
        persister.schedule("job")
        await entered.wait()
        state = "p2"
        persister.schedule("job")
        state = "p3"
        persister.schedule("job")
        release.set()
        if terminal:
            state = "done"
            await persister.write_final("job", partial(write, "job"))
            persister.schedule("job")
        else:
            await caught_up.wait()
        await persister.flush("job")
        assert writes == ["p1", "done" if terminal else "p3"]

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_waiter", [None, "flush", "final"])
def test_terminal_write_waits_for_progress_shared_with_another_flush(cancel_waiter):
    """Concurrent or cancelled waiters must not hide a running write from finalization."""

    async def scenario():
        """Overlap waiters with an active progress write, then recover any cancellation."""
        entered = asyncio.Event()
        release = asyncio.Event()
        writes = []

        async def progress(job_id):
            """Hold the running snapshot until both waiters have started."""
            entered.set()
            await release.wait()
            writes.append("running")

        async def final():
            """Record the immutable terminal snapshot."""
            writes.append("cancelled")

        persister = ProgressPersister(progress)
        persister.start("shared")
        persister.schedule("shared")
        await entered.wait()
        waiter = asyncio.create_task(persister.flush("shared"))
        await asyncio.sleep(0)
        if cancel_waiter == "flush":
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        terminal = asyncio.create_task(persister.write_final("shared", final))
        await asyncio.sleep(0)
        if cancel_waiter == "final":
            terminal.cancel()
            with pytest.raises(asyncio.CancelledError):
                await terminal
            terminal = asyncio.create_task(persister.retry_pending())
            await asyncio.sleep(0)
        try:
            assert writes == []
        finally:
            release.set()
            await terminal
            if cancel_waiter != "flush":
                await waiter
        assert writes == ["running", "cancelled"]

    asyncio.run(scenario())


@pytest.mark.parametrize("same_job", [False, True])
def test_cancelled_terminal_waiter_keeps_its_snapshot_for_reconciliation(same_job) -> None:
    """A request cancelled behind another job's write must retain its final snapshot."""

    async def scenario():
        """Hold the first final write while cancelling the second caller."""
        entered = asyncio.Event()
        release = asyncio.Event()
        writes = []

        async def write(job_id):
            """Record final snapshots in their serialized order."""
            if job_id == "first":
                entered.set()
                await release.wait()
            writes.append(job_id)

        persister = ProgressPersister(write)
        first = asyncio.create_task(persister.write_final("first", partial(write, "first")))
        await entered.wait()
        second = asyncio.create_task(
            persister.write_final("first" if same_job else "second", partial(write, "second"))
        )
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        release.set()
        await first
        await persister.retry_pending()
        assert writes == ["first", "second"]

    asyncio.run(scenario())


def test_progress_persister_preserves_failed_terminal_writes_for_reconciliation() -> None:
    """Retry transient failures, expose permanent failure, and save the retained snapshot."""

    async def scenario() -> None:
        """Fail twice then succeed for one job; fail every time for another."""
        failures = {"flaky": 2, "broken": 99}
        calls: list[str] = []

        async def write(job_id: str) -> None:
            """Raise while the job still has failures left."""
            calls.append(job_id)
            if failures[job_id] > 0:
                failures[job_id] -= 1
                raise OSError("ledger unavailable")

        persister = ProgressPersister(write)
        persister.start("flaky")
        persister.schedule("flaky")
        await asyncio.sleep(0)
        await persister.write_final("flaky", partial(write, "flaky"))
        with pytest.raises(JobPersistenceError) as failure:
            await persister.write_final("broken", partial(write, "broken"))
        assert isinstance(failure.value.__cause__, OSError)
        assert calls.count("flaky") == 3
        assert calls.count("broken") == 3
        failures["broken"] = 0
        await persister.retry_pending()
        assert calls.count("broken") == 4
        await persister.retry_pending()
        assert calls.count("broken") == 4

    asyncio.run(scenario())


def test_terminal_programming_errors_are_not_retried() -> None:
    """An invalid write contract must remain visible without speculative retries."""

    async def scenario():
        """Reject a programming failure after exactly one write attempt."""
        calls = 0

        async def write(job_id):
            """Raise a deterministic contract error without touching persistence."""
            nonlocal calls
            calls += 1
            raise ValueError("invalid ledger payload")

        persister = ProgressPersister(write)
        with pytest.raises(JobPersistenceError) as failure:
            await persister.write_final("invalid", partial(write, "invalid"))
        assert isinstance(failure.value.__cause__, ValueError)
        assert calls == 1
        with pytest.raises(ValueError, match="invalid ledger payload"):
            await persister.write_current("usage")
        assert calls == 2

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_job_store_persists_progress_and_interrupts_stale_process_work():
    """Persist queue progress and recover interrupted work through independent DB sessions."""

    async def scenario():
        """Commit actual transitions in a disposable schema."""
        async with isolated_session_factory() as factory:
            store = JobStore(session_factory=factory)
            queued_at = datetime(2026, 9, 1, tzinfo=UTC)
            corpus = await store.create(
                job_id="admin-test-persist",
                domain="corpus",
                kind="backfill_embeddings",
                request_json={"identifiers": [], "years": []},
                created_at=queued_at,
            )
            evaluation = await store.create(
                job_id="eval-test-persist",
                domain="evaluation",
                kind="quick",
                request_json={"suite_id": "sec-en"},
                created_at=queued_at,
            )
            assert await store.queue_positions() == {corpus.job_id: 1, evaluation.job_id: 2}
            running = await store.put(
                corpus.job_id,
                status="running",
                stage="embedding",
                current=4,
                total=10,
                detail_current=None,
                detail_total=None,
                message="Embedded 4",
                started_at=datetime.now(UTC),
                finished_at=None,
            )
            assert running.current == 4
            assert await store.queue_positions() == {evaluation.job_id: 1}
            assert await store.interrupt_incomplete("corpus") == (corpus.job_id,)
            interrupted = await store.get(corpus.job_id)
            assert interrupted is not None
            assert interrupted.status == "interrupted"
            cancelled = await store.cancel(evaluation.job_id)
            assert cancelled.status == "cancelled"
            assert await store.queue_positions() == {}
            assert {
                corpus.job_id,
                evaluation.job_id,
            } <= {job.job_id for job in await store.list()}
            evaluations = await store.list(domain="evaluation")
            assert evaluation.job_id in {job.job_id for job in evaluations}
            assert corpus.job_id not in {job.job_id for job in evaluations}
            assert all(job.domain == "evaluation" for job in evaluations)

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_corpus_worker_persists_progress_and_terminal_state(tmp_path):
    """Persist real worker progress and terminal state into an isolated job ledger."""

    async def scenario():
        """Run the queue with an operation that publishes deterministic progress."""
        async with isolated_session_factory() as factory:
            store = JobStore(session_factory=factory)

            async def runner(command, publish, on_usage=None) -> OperationOutcome:
                """Publish operation progress through the real persistence lifecycle."""
                publish(OperationProgress("work", 1, 2, f"running {command.kind}"))
                publish(OperationProgress("work", 2, 2, f"finished {command.kind}"))
                return OperationOutcome("verified test completion")

            service = RuntimeCorpusAdminService(
                settings=Settings(corpus_dir=tmp_path), job_store=store
            )
            service._job_queue._run_operation = runner
            created = await service.enqueue(AdminCommand("rebuild_bm25"))
            await service._job_queue._queue.join()
            persisted = await store.get(created.job_id)
            assert persisted is not None
            assert persisted.status == "succeeded"
            assert persisted.current == 2
            assert persisted.message == "verified test completion"

    asyncio.run(scenario())


def test_coordinator_is_busy_while_a_ticket_is_pending_or_active() -> None:
    """Report busy from registration until the turn ends, and idle after a cancellation."""

    async def scenario() -> None:
        """Walk one ticket through registration, its turn and a cancelled successor."""
        coordinator = JobExecutionCoordinator()
        assert coordinator.busy is False
        await coordinator.register("job-1", datetime.now(UTC))
        assert coordinator.busy is True
        async with coordinator.turn("job-1"):
            assert coordinator.busy is True
        assert coordinator.busy is False
        await coordinator.register("job-2", datetime.now(UTC))
        assert coordinator.busy is True
        await coordinator.cancel("job-2")
        assert coordinator.busy is False

    asyncio.run(scenario())
