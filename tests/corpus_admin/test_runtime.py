"""End-to-end corpus administrator tests through the runtime service."""

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from app.config import Settings
from app.corpus_admin.job_queue import CorpusJobQueue
import app.corpus_admin.operations as operations
from app.corpus_admin.operations import CorpusOperations
from app.corpus_admin.runtime import RuntimeCorpusAdminService
from app.corpus_admin.types import AdminCommand
from app.db.session_factory import SessionFactory
from app.ingestion.progress import OperationProgress
from app.operator.jobs import JobStore
from app.operator.progress import stored_progress
from app.retrieval.bm25 import TermStatCounts
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.corpus_admin.support import LedgerStore, write_manifest
from tests.live_postgres import live_postgres_unavailable


@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
def test_bm25_job_reports_completion_only_after_rebuild(tmp_path: Path, monkeypatch, fails) -> None:
    """Persist complete progress only after the actual BM25 operation succeeds."""
    events = []

    class FakeSession:
        """Replace the database session without replacing the operation dispatcher."""

        async def __aenter__(self):
            """Return the fake session."""
            return self

        async def __aexit__(self, *args):
            """Propagate rebuild errors."""
            return False

    async def fake_bootstrap(engine):
        """Avoid schema changes in this progress regression."""
        del engine

    async def fake_writable(self):
        """Allow the isolated operation through its schema gate."""
        del self

    async def fake_rebuild(session):
        """Require an opening tick before completing or failing the rebuild."""
        assert isinstance(session, FakeSession)
        assert [(event.current, event.total) for event in events] == [(0, 1)]
        if fails:
            raise RuntimeError("BM25 rebuild failed")
        return TermStatCounts(terms=4, chunks=2, lexemes=3)

    original_publish = CorpusJobQueue._publish

    def record_publish(self, job_id, progress):
        """Observe real progress publication while retaining service behavior."""
        events.append(progress)
        original_publish(self, job_id, progress)

    monkeypatch.setattr(operations, "bootstrap_schema", fake_bootstrap)
    monkeypatch.setattr(operations, "backfill_term_stats", fake_rebuild)
    monkeypatch.setattr(CorpusOperations, "_assert_writable_schema", fake_writable)
    monkeypatch.setattr(CorpusJobQueue, "_publish", record_publish)

    async def scenario():
        """Run the real queued operation and inspect its terminal ledger record."""
        store = LedgerStore()
        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            session_factory=cast(SessionFactory, FakeSession),
            job_store=store,
        )
        job = await service.enqueue(AdminCommand("rebuild_bm25"))
        await service._job_queue._queue.join()
        finished = (await service.jobs()).history[0]
        expected_status = "failed" if fails else "succeeded"
        expected_current = 0 if fails else 1
        assert finished.status == store.rows[job.job_id].status == expected_status
        assert (finished.current, finished.total) == (expected_current, 1)
        assert (store.rows[job.job_id].current, store.rows[job.job_id].total) == (
            expected_current,
            1,
        )
        assert [(event.current, event.total) for event in events] == (
            [(0, 1)] if fails else [(0, 1), (1, 1)]
        )

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_ingest_leaves_bm25_for_explicit_rebuild_and_preserves_progress(tmp_path, monkeypatch):
    """Exercise actual index writes only against an explicitly named disposable fixture database."""
    import os

    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.bootstrap import bootstrap_schema
    from app.db.models import BM25CorpusStat
    from app.evals.corpus import temporary_corpus_session
    from tests.ingestion.seed.support import sample_batch

    raw_url = os.getenv("DOCREVIEW_PIPELINE_TEST_URL")
    if not raw_url:
        live_postgres_unavailable(
            "Set DOCREVIEW_PIPELINE_TEST_URL to a disposable pipeline_test_ DB."
        )
    url = make_url(raw_url)
    if url.host not in {"127.0.0.1", "localhost"} or not (url.database or "").startswith(
        "pipeline_test_"
    ):
        pytest.fail("The pipeline integration fixture requires a loopback pipeline_test_ database.")
    write_manifest(tmp_path)
    batch = sample_batch()

    def load(*args, on_progress, **kwargs):
        """Supply an already-parsed fixture while retaining the real persistence pipeline."""
        on_progress(OperationProgress("prepare", 0, 1, "Parsing fixture"))
        on_progress(OperationProgress("prepare", 1, 1, "Parsed fixture"))
        return batch

    monkeypatch.setattr(operations, "load_seed_batch", load)

    async def scenario():
        """Inspect readiness, history and isolated evaluation statistics after serial jobs."""
        engine = create_async_engine(url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        provider = DeterministicEmbeddingProvider()
        try:
            await bootstrap_schema(engine)
            store = JobStore(session_factory=factory)
            # `_env_file` is a pydantic-settings init option the synthesized signature omits.
            without_dotenv: dict[str, Any] = {"_env_file": None}
            service = RuntimeCorpusAdminService(
                settings=Settings(corpus_dir=tmp_path, **without_dotenv),
                session_factory=factory,
                engine=engine,
                embedding_provider=provider,
                job_store=store,
            )
            events = []
            publish = service._job_queue._publish

            def capture(job_id, progress):
                """Observe the actual operation stages without replacing their persistence."""
                events.append(progress.stage)
                publish(job_id, progress)

            monkeypatch.setattr(service._job_queue, "_publish", capture)
            command = AdminCommand(
                "ingest_manifest", manifest="manifest.json", selection_id="selected"
            )
            first = await service.enqueue(command)
            await service._job_queue._queue.join()
            record = await store.get(first.job_id)
            assert record is not None
            assert record.status == "succeeded", record.message
            assert list(dict.fromkeys(events)) == [
                "prepare",
                "schema",
                "documents",
                "chunks",
                "cleanup",
            ]
            progress = stored_progress(record.result_refs)
            assert progress is not None
            assert progress.overall_current == 100
            assert progress.progress_stage == "cleanup"
            assert (await service.status()).bm25_ready is False
            rebuilt = await service.enqueue(AdminCommand("rebuild_bm25"))
            await service._job_queue._queue.join()
            rebuilt_record = await store.get(rebuilt.job_id)
            assert rebuilt_record is not None
            assert rebuilt_record.status == "succeeded"
            assert (await service.status()).bm25_ready is True
            await service.enqueue(command)
            await service._job_queue._queue.join()
            status = await service.status()
            assert status.bm25_ready is False
            assert status.bm25_rebuild_recorded is True
            assert (await service.snapshot()).status.bm25_rebuild_recorded is True
            async with temporary_corpus_session(
                engine,
                batch,
                provider,
                target_tokens=1024,
                embedding_provider="deterministic",
            ) as (session, _measurement):
                stat_rows = await session.scalar(select(func.count()).select_from(BM25CorpusStat))
                assert stat_rows is not None
                assert stat_rows > 0
            assert (await service.status()).bm25_ready is False
        finally:
            await engine.dispose()

    asyncio.run(scenario())
