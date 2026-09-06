"""Persistent unified operator job ledger behavior."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.corpus_admin import AdminCommand, OperationOutcome, RuntimeCorpusAdminService
from app.db.models import OperatorJob
from app.ingestion.progress import OperationProgress
from app.operator.jobs import JobExecutionCoordinator, JobStore, ProgressPersister
from tests.live_postgres import live_postgres_unavailable


def test_progress_persister_coalesces_bursts_and_lands_the_terminal_write_last() -> None:
    """Write one snapshot at a time, catch up once, and let the final write land last."""

    async def scenario() -> None:
        """Block the first write, burst progress behind it, then finish the job."""
        gate = asyncio.Event()
        states = {"catch-up": "p1", "final": "p1"}
        writes: list[tuple[str, str]] = []

        async def write(job_id: str) -> None:
            """Record the snapshot seen at write time, holding the first write of each job."""
            snapshot = states[job_id]
            if snapshot == "p1":
                await gate.wait()
            writes.append((job_id, snapshot))

        persister = ProgressPersister(write)
        for job_id in states:
            persister.schedule(job_id)
        await asyncio.sleep(0)
        for job_id in states:
            states[job_id] = "p2"
            persister.schedule(job_id)
            states[job_id] = "p3"
            persister.schedule(job_id)
        states["final"] = "done"
        gate.set()
        assert await persister.write_final("final") is True
        await persister.flush("catch-up")
        persister.schedule("final")
        await asyncio.sleep(0)

        final_writes = [snapshot for job_id, snapshot in writes if job_id == "final"]
        catch_up_writes = [snapshot for job_id, snapshot in writes if job_id == "catch-up"]
        assert final_writes == ["p1", "done"]
        assert catch_up_writes == ["p1", "p3"]

    asyncio.run(scenario())


def test_progress_persister_retries_the_terminal_write_and_never_raises() -> None:
    """Retry a failing terminal write a bounded number of times and report the outcome."""

    async def scenario() -> None:
        """Fail twice then succeed for one job; fail every time for another."""
        failures = {"flaky": 2, "broken": 99}
        calls: list[str] = []

        async def write(job_id: str) -> None:
            """Raise while the job still has failures left."""
            calls.append(job_id)
            if failures[job_id] > 0:
                failures[job_id] -= 1
                raise RuntimeError("ledger unavailable")

        persister = ProgressPersister(write)
        persister.schedule("flaky")
        await asyncio.sleep(0)
        assert await persister.write_final("flaky") is True
        assert await persister.write_final("broken") is False
        assert calls.count("flaky") == 3
        assert calls.count("broken") == 3

    asyncio.run(scenario())


async def _exercise() -> tuple[bool, str]:
    """Exercise persistence and restart recovery inside one rolled-back connection."""
    engine = create_async_engine(make_url(get_settings().database_url), poolclass=NullPool)
    connection = None
    try:
        try:
            connection = await engine.connect()
        except Exception as error:
            return False, str(error)
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        store = JobStore(session_factory=factory)
        try:
            corpus = await store.create(
                job_id="admin-test-persist",
                domain="corpus",
                kind="backfill_embeddings",
                request_json={"identifiers": [], "years": []},
            )
            evaluation = await store.create(
                job_id="eval-test-persist",
                domain="evaluation",
                kind="quick",
                request_json={"suite_id": "sec-en"},
            )
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
            assert await store.interrupt_incomplete("corpus") == (corpus.job_id,)
            interrupted = await store.get(corpus.job_id)
            assert interrupted is not None
            assert interrupted.status == "interrupted"
            cancelled = await store.cancel(evaluation.job_id)
            assert cancelled.status == "cancelled"
            assert {
                corpus.job_id,
                evaluation.job_id,
            } <= {job.job_id for job in await store.list()}
        finally:
            await transaction.rollback()
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


@pytest.mark.live_postgres
def test_job_store_persists_progress_and_interrupts_stale_process_work():
    """Require PostgreSQL for transactional queue recovery evidence."""
    reachable, detail = asyncio.run(_exercise())
    if not reachable:
        live_postgres_unavailable(detail)


async def _exercise_corpus_worker(tmp_path) -> tuple[bool, str]:
    """Persist one real worker lifecycle through the shared job store."""
    engine = create_async_engine(make_url(get_settings().database_url), poolclass=NullPool)
    created_id: str | None = None
    try:
        try:
            async with engine.connect() as connection:
                await connection.execute(select(OperatorJob.job_id).limit(1))
        except Exception as error:
            return False, str(error)
        factory = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
        )
        store = JobStore(session_factory=factory)

        async def runner(command, publish) -> OperationOutcome:
            """Publish synthetic progress through the real persistent job lifecycle."""
            publish(OperationProgress("work", 1, 2, f"running {command.kind}"))
            publish(OperationProgress("work", 2, 2, f"finished {command.kind}"))
            return OperationOutcome("verified test completion")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
            job_store=store,
        )
        try:
            created = await service.enqueue(AdminCommand("rebuild_bm25"))
            created_id = created.job_id
            await service._queue.join()
            await asyncio.sleep(0.1)
            board = await service.jobs()
            persisted = await store.get(created.job_id)
            assert board.history[0].status == "succeeded"
            assert persisted is not None
            assert persisted.status == "succeeded"
            assert persisted.current == 2
            assert persisted.message == "verified test completion"
        finally:
            if created_id is not None:
                async with factory() as session:
                    await session.execute(
                        delete(OperatorJob).where(OperatorJob.job_id == created_id)
                    )
                    await session.commit()
        return True, ""
    finally:
        await engine.dispose()


@pytest.mark.live_postgres
def test_corpus_worker_persists_progress_and_terminal_state(tmp_path):
    """Require PostgreSQL evidence for queue-to-history persistence."""
    reachable, detail = asyncio.run(_exercise_corpus_worker(tmp_path))
    if not reachable:
        live_postgres_unavailable(detail)


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
