"""Persistent unified operator job ledger behavior."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.corpus_admin import AdminCommand, RuntimeCorpusAdminService
from app.db.models import OperatorJob
from app.ingestion.progress import OperationProgress
from app.operator.jobs import JobStore
from tests.live_postgres import live_postgres_unavailable


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

        async def runner(command, publish) -> str:
            """Publish committed-looking progress without external work."""
            publish(OperationProgress("work", 1, 2, f"running {command.kind}"))
            publish(OperationProgress("work", 2, 2, f"finished {command.kind}"))
            return "verified test completion"

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
