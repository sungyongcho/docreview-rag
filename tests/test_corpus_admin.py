"""Deterministic corpus administrator service and job-queue tests."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

from pydantic import SecretStr
import pytest

from app.config import Settings
import app.corpus_admin as corpus_admin
from app.corpus_admin import (
    AdminCommand,
    CannedCorpusAdminService,
    RuntimeCorpusAdminService,
)
from app.ingestion.progress import OperationProgress
from app.operator.jobs import JobDomain, JobStatus, JobStore, StoredJob
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingBackfillResult,
)
from tests.live_postgres import live_postgres_unavailable


def test_canned_snapshot_is_read_only_filterable_and_db_free() -> None:
    """Expose representative SEC/DART state without any live dependency."""
    service = CannedCorpusAdminService()

    snapshot = asyncio.run(service.snapshot(registry="dart"))
    detail = asyncio.run(service.document_detail("005930-FY2024"))

    assert service.read_only is True
    assert snapshot.mode == "canned"
    assert snapshot.status.database_connected is False
    assert snapshot.status.writable is False
    assert [document.registry for document in snapshot.documents] == ["dart"]
    assert [(item.registry, item.sources_present) for item in snapshot.manifests] == [
        ("sec", 20),
        ("dart", 2),
    ]
    assert detail is not None
    assert len(detail.chunks) == 1
    assert len(detail.chunks[0].body) <= 1_000


def test_canned_service_refuses_every_operation() -> None:
    """Keep the public portfolio fixture unable to reach any mutation path."""
    service = CannedCorpusAdminService()

    with pytest.raises(PermissionError, match="Read-only"):
        asyncio.run(service.enqueue(AdminCommand("rebuild_bm25")))


@pytest.mark.parametrize(
    "command",
    [
        lambda: AdminCommand("acquire_edgar"),
        lambda: AdminCommand("acquire_dart", identifiers=("005930",), years=(1800,)),
        lambda: AdminCommand("ingest_manifest", manifest=""),
        lambda: AdminCommand("ingest_manifest", manifest="manifest.json", expected_documents=0),
    ],
)
def test_admin_commands_reject_incomplete_or_unsafe_inputs(command) -> None:
    """Reject hidden defaults and invalid counts before an operation is queued."""
    with pytest.raises(ValueError):
        command()


def test_runtime_queue_is_fifo_and_reports_progress(tmp_path: Path) -> None:
    """Run one job at a time and preserve submission order in bounded history."""

    async def scenario() -> None:
        """Queue two jobs and verify FIFO execution and history."""
        gate = asyncio.Event()
        calls: list[str] = []

        async def runner(command, publish) -> str:
            """Record order while keeping the first job active long enough to queue another."""
            calls.append(command.kind)
            publish(OperationProgress("work", 1, 2, f"running {command.kind}"))
            if len(calls) == 1:
                await gate.wait()
            publish(OperationProgress("work", 2, 2, f"finished {command.kind}"))
            return f"completed {command.kind}"

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
        )
        first = await service.enqueue(AdminCommand("rebuild_bm25"))
        second = await service.enqueue(AdminCommand("backfill_embeddings"))
        await asyncio.sleep(0)
        board = await service.jobs()
        assert board.active is not None
        assert board.active.job_id == first.job_id
        assert [job.job_id for job in board.queued] == [second.job_id]

        gate.set()
        await service._queue.join()
        board = await service.jobs()

        assert calls == ["rebuild_bm25", "backfill_embeddings"]
        assert board.active is None
        assert [job.status for job in board.history] == ["succeeded", "succeeded"]
        assert [job.command.kind for job in board.history] == [
            "backfill_embeddings",
            "rebuild_bm25",
        ]

    asyncio.run(scenario())


def test_failed_job_is_redacted_and_retryable(tmp_path: Path) -> None:
    """Remove server credentials from failure history and permit a bounded retry."""

    async def scenario() -> None:
        """Fail once with a secret, then retry successfully."""
        attempts = 0
        secret = "dart-test-secret-123"

        async def runner(command, publish) -> str:
            """Fail once with a secret-bearing message, then succeed."""
            nonlocal attempts
            del command, publish
            attempts += 1
            if attempts == 1:
                raise RuntimeError(f"provider rejected {secret}")
            return "retry succeeded"

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path, dart_api_key=SecretStr(secret)),
            operation_runner=runner,
        )
        failed = await service.enqueue(AdminCommand("backfill_embeddings"))
        await service._queue.join()
        board = await service.jobs()
        assert board.history[0].status == "failed"
        assert secret not in board.history[0].message
        assert "[REDACTED]" in board.history[0].message

        retried = await service.retry(failed.job_id)
        await service._queue.join()
        board = await service.jobs()
        assert retried.job_id != failed.job_id
        assert board.history[0].status == "succeeded"
        assert board.history[0].result_refs["retry_of"] == failed.job_id

    asyncio.run(scenario())


def test_queued_job_can_be_cancelled_without_running(tmp_path: Path) -> None:
    """Remove queued work at dispatch time while allowing the active job to finish."""

    async def scenario() -> None:
        """Hold the first job, cancel the second, and inspect terminal history."""
        gate = asyncio.Event()
        calls: list[str] = []

        async def runner(command, publish) -> str:
            """Block the first command long enough to cancel its successor."""
            del publish
            calls.append(command.kind)
            await gate.wait()
            return "done"

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
        )
        first = await service.enqueue(AdminCommand("rebuild_bm25"))
        second = await service.enqueue(AdminCommand("backfill_embeddings"))
        await asyncio.sleep(0)
        cancelled = await service.cancel(second.job_id)
        gate.set()
        await service._queue.join()
        board = await service.jobs()

        assert calls == [first.command.kind]
        assert cancelled.status == "cancelled"
        assert {job.status for job in board.history} == {"succeeded", "cancelled"}

    asyncio.run(scenario())


def test_running_backfill_cancels_at_the_next_batch_boundary(tmp_path: Path) -> None:
    """Cooperatively stop only a running operation with a declared safe boundary."""

    async def scenario() -> None:
        """Request cancellation while a fake embedding batch is in flight."""
        gate = asyncio.Event()

        async def runner(command, publish) -> str:
            """Publish once, wait, then hit the cancellation-aware boundary."""
            assert command.kind == "backfill_embeddings"
            publish(OperationProgress("embedding", 1, 2, "first batch"))
            await gate.wait()
            publish(OperationProgress("embedding", 2, 2, "second batch"))
            return "unexpected completion"

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
        )
        job = await service.enqueue(AdminCommand("backfill_embeddings"))
        await asyncio.sleep(0)
        cancelled = await service.cancel(job.job_id)
        gate.set()
        await service._queue.join()
        board = await service.jobs()

        assert cancelled.status == "cancelled"
        assert board.history[0].status == "cancelled"
        assert board.history[0].message == "Cancelled by operator."

    asyncio.run(scenario())


def test_backfill_refuses_false_success_when_committed_count_does_not_change(
    monkeypatch, tmp_path: Path
) -> None:
    """Fail the job when an UPDATE reports rows but the database postcondition disagrees."""

    class FakeSession:
        """Minimal async context used by monkeypatched count and backfill boundaries."""

        async def __aenter__(self):
            """Return the fake session."""
            return self

        async def __aexit__(self, *args):
            """Close without suppressing errors."""
            return False

    states = iter(((0, 3), (0, 3)))

    async def fake_state(session, provider):
        """Report no committed change before or after the claimed update."""
        del session, provider
        return next(states)

    async def fake_embed(session, provider, *, on_batch):
        """Claim three stored rows without changing persistence."""
        del session, provider, on_batch
        return EmbeddingBackfillResult(selected=3, embedded=3, skipped_stale=0, batches=1)

    async def fake_bootstrap(engine):
        """Avoid database setup in the focused postcondition test."""
        del engine

    async def fake_writable(self):
        """Treat the focused fake schema as writable."""
        del self

    monkeypatch.setattr(corpus_admin, "_embedding_state", fake_state)
    monkeypatch.setattr(corpus_admin, "embed_missing_chunks", fake_embed)
    monkeypatch.setattr(corpus_admin, "bootstrap_schema", fake_bootstrap)
    monkeypatch.setattr(RuntimeCorpusAdminService, "_assert_writable_schema", fake_writable)
    service = RuntimeCorpusAdminService(
        settings=Settings(corpus_dir=tmp_path),
        session_factory=FakeSession,
        embedding_provider=DeterministicEmbeddingProvider(),
    )

    with pytest.raises(RuntimeError, match="reported rows were not committed"):
        asyncio.run(
            service._run_operation(
                AdminCommand("backfill_embeddings"),
                lambda progress: None,
            )
        )


def test_manifest_resolution_is_confined_to_valid_root_entries(tmp_path: Path) -> None:
    """Accept enumerated manifests and reject traversal or arbitrary JSON files."""
    (tmp_path / "manifest.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "notes.json").write_text("[]\n", encoding="utf-8")
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    assert service._resolve_manifest("manifest.json") == tmp_path / "manifest.json"
    with pytest.raises(ValueError, match="corpus root"):
        service._resolve_manifest("../outside.json")
    with pytest.raises(ValueError, match="selectable"):
        service._resolve_manifest("notes.json")


class _LedgerStore(JobStore):
    """In-memory job ledger whose writes can be made to fail a set number of times."""

    def __init__(self, failures: int = 0) -> None:
        super().__init__()
        self.rows: dict[str, StoredJob] = {}
        self.failures = failures
        self.puts: list[str] = []

    async def create(
        self,
        *,
        job_id: str,
        domain: JobDomain,
        kind: str,
        request_json: dict[str, object],
        message: str = "Queued",
        created_at: datetime | None = None,
        result_refs: dict[str, object] | None = None,
    ) -> StoredJob:
        """Insert one queued row."""
        now = created_at or datetime.now(UTC)
        row = StoredJob(
            job_id=job_id,
            domain=domain,
            kind=kind,
            request_json=dict(request_json),
            status="queued",
            stage="queued",
            current=0,
            total=None,
            detail_current=None,
            detail_total=None,
            message=message,
            error_code=None,
            result_refs=dict(result_refs or {}),
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
        self.rows[job_id] = row
        return row

    async def put(
        self,
        job_id: str,
        *,
        status: JobStatus,
        stage: str,
        current: int,
        total: int | None,
        detail_current: int | None,
        detail_total: int | None,
        message: str,
        started_at: datetime | None,
        finished_at: datetime | None,
        error_code: str | None = None,
        result_refs: dict[str, object] | None = None,
    ) -> StoredJob:
        """Replace one row, raising while failures remain."""
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("ledger unavailable")
        row = self.rows[job_id]
        updated = replace(
            row,
            status=status,
            stage=stage,
            current=current,
            total=total,
            detail_current=detail_current,
            detail_total=detail_total,
            message=message,
            started_at=started_at,
            finished_at=finished_at,
            error_code=error_code,
            result_refs={**row.result_refs, **(result_refs or {})},
            updated_at=datetime.now(UTC),
        )
        self.rows[job_id] = updated
        self.puts.append(status)
        return updated

    async def get(self, job_id: str) -> StoredJob | None:
        """Return one row."""
        return self.rows.get(job_id)

    async def list(
        self, *, domain: JobDomain | None = None, limit: int = 100
    ) -> tuple[StoredJob, ...]:
        """Return newest-first rows."""
        rows = sorted(
            self.rows.values(), key=lambda row: (row.created_at, row.job_id), reverse=True
        )
        return tuple(row for row in rows if domain is None or row.domain == domain)[:limit]

    async def interrupt_incomplete(self, domain: JobDomain) -> tuple[str, ...]:
        """Nothing is stale in a fresh in-memory ledger."""
        del domain
        return ()


def test_worker_survives_ledger_failures_and_lands_the_terminal_state(tmp_path: Path) -> None:
    """Keep the queue alive when ledger writes fail, coalesce progress, and persist success last."""

    async def scenario() -> None:
        """Fail the first two writes, then require succeeded rows and a live worker."""
        store = _LedgerStore(failures=2)

        async def runner(command, publish) -> str:
            """Publish a burst of progress in one turn, then finish."""
            for step in range(1, 6):
                publish(OperationProgress("work", step, 5, f"{command.kind} {step}"))
            await asyncio.sleep(0)
            return f"completed {command.kind}"

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
            job_store=store,
        )
        first = await service.enqueue(AdminCommand("rebuild_bm25"))
        await service._queue.join()
        second = await service.enqueue(AdminCommand("backfill_embeddings"))
        await service._queue.join()

        assert store.rows[first.job_id].status == "succeeded"
        assert store.rows[second.job_id].status == "succeeded"
        assert store.rows[second.job_id].current == 5
        # Ten progress events became at most one running write per job, and the
        # succeeded write is always the last one for each job.
        assert store.puts.count("running") <= 2
        assert store.puts[-1] == "succeeded"
        assert [job.status for job in (await service.jobs()).history] == ["succeeded", "succeeded"]

    asyncio.run(scenario())


def test_manifest_summaries_report_registry_and_sources_on_disk(tmp_path: Path) -> None:
    """Count listed sources that exist on disk and name each manifest's registry."""
    present = tmp_path / "present.html"
    present.write_text("<html></html>", encoding="utf-8")
    entries = [
        {"ticker": "NVDA", "file": str(present)},
        {"ticker": "AMD", "file": str(tmp_path / "missing.html")},
    ]
    (tmp_path / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
    (tmp_path / "dart-manifest.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "broken-manifest.json").write_text("{", encoding="utf-8")
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    summaries = {item.name: item for item in service._manifest_summaries()}

    assert summaries["manifest.json"].registry == "sec"
    assert summaries["manifest.json"].documents == 2
    assert summaries["manifest.json"].sources_present == 1
    assert summaries["dart-manifest.json"].registry is None
    assert summaries["dart-manifest.json"].sources_present == 0
    assert summaries["broken-manifest.json"].valid is False
    assert summaries["broken-manifest.json"].registry is None
    assert summaries["broken-manifest.json"].sources_present is None


@pytest.mark.live_postgres
def test_live_postgres_admin_snapshot_reports_schema_state() -> None:
    """Inspect the real configured database without mutating its corpus or schema."""
    try:
        snapshot = asyncio.run(RuntimeCorpusAdminService().snapshot())
    except Exception as error:  # noqa: BLE001 - shared live-test availability policy
        live_postgres_unavailable(str(error))

    if not snapshot.status.database_connected:
        live_postgres_unavailable(snapshot.status.schema_message)
    assert snapshot.status.schema_status in {"compatible", "empty", "drifted"}
    if snapshot.status.schema_status == "drifted":
        assert snapshot.status.writable is False
        assert "DROP TABLE" not in snapshot.status.schema_message
