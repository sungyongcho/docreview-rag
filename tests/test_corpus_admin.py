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
    OperationOutcome,
    RuntimeCorpusAdminService,
)
from app.ingestion.progress import OperationProgress
from app.operator.jobs import JobDomain, JobStatus, JobStore, StoredJob
from app.retrieval.bm25 import TermStatCounts
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
    assert [(item.registries, item.sources_present) for item in snapshot.manifests] == [
        (("sec", "dart"), 2),
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

        async def runner(command, publish) -> OperationOutcome:
            """Record order while keeping the first job active long enough to queue another."""
            calls.append(command.kind)
            publish(OperationProgress("work", 1, 2, f"running {command.kind}"))
            if len(calls) == 1:
                await gate.wait()
            publish(OperationProgress("work", 2, 2, f"finished {command.kind}"))
            return OperationOutcome(f"completed {command.kind}")

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

        async def runner(command, publish) -> OperationOutcome:
            """Fail once with a secret-bearing message, then succeed."""
            nonlocal attempts
            del command, publish
            attempts += 1
            if attempts == 1:
                raise RuntimeError(f"provider rejected {secret}")
            return OperationOutcome("retry succeeded")

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

        async def runner(command, publish) -> OperationOutcome:
            """Block the first command long enough to cancel its successor."""
            del publish
            calls.append(command.kind)
            await gate.wait()
            return OperationOutcome("done")

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

        async def runner(command, publish) -> OperationOutcome:
            """Publish once, wait, then hit the cancellation-aware boundary."""
            assert command.kind == "backfill_embeddings"
            publish(OperationProgress("embedding", 1, 2, "first batch"))
            await gate.wait()
            publish(OperationProgress("embedding", 2, 2, "second batch"))
            return OperationOutcome("unexpected completion")

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
        assert (board.history[0].current, board.history[0].total) == (1, 2)

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

    async def fake_state(session, provider, document_ids):
        """Report no committed change before or after the claimed update."""
        del session, provider, document_ids
        return next(states)

    async def fake_embed(session, provider, *, on_batch, document_ids, on_usage=None):
        """Claim three stored rows without changing persistence."""
        del session, provider, on_batch, document_ids
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
    _write_manifest(tmp_path)
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

    original_publish = RuntimeCorpusAdminService._publish

    def record_publish(self, job_id, progress):
        """Observe real progress publication while retaining service behavior."""
        events.append(progress)
        original_publish(self, job_id, progress)

    monkeypatch.setattr(corpus_admin, "bootstrap_schema", fake_bootstrap)
    monkeypatch.setattr(corpus_admin, "backfill_term_stats", fake_rebuild)
    monkeypatch.setattr(RuntimeCorpusAdminService, "_assert_writable_schema", fake_writable)
    monkeypatch.setattr(RuntimeCorpusAdminService, "_publish", record_publish)

    async def scenario():
        """Run the real queued operation and inspect its terminal ledger record."""
        store = _LedgerStore()
        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            session_factory=FakeSession,
            job_store=store,
        )
        job = await service.enqueue(AdminCommand("rebuild_bm25"))
        await service._queue.join()
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


def test_worker_survives_ledger_failures_and_lands_the_terminal_state(tmp_path: Path) -> None:
    """Keep the queue alive when ledger writes fail, coalesce progress, and persist success last."""

    async def scenario() -> None:
        """Fail the first two writes, then require succeeded rows and a live worker."""
        store = _LedgerStore(failures=2)

        async def runner(command, publish) -> OperationOutcome:
            """Publish a burst of progress in one turn, then finish."""
            for step in range(1, 6):
                publish(OperationProgress("work", step, 5, f"{command.kind} {step}"))
            await asyncio.sleep(0)
            return OperationOutcome(f"completed {command.kind}")

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
    """Expose exact selection identities from the common catalog."""
    _write_manifest(tmp_path)
    (tmp_path / "broken-manifest.json").write_text("{")
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    summaries = {item.name: item for item in service._manifest_summaries()}
    summary = summaries["manifest.json"]
    assert summary.registries == ("sec",)
    assert summary.documents == 1
    assert summary.sources_present == 1
    assert summary.selections[0].document_ids == ("nvda-2024",)
    assert summary.selections[0].artifact_ids == ("nvda-source",)
    assert summary.selections[0].sources_present == 1
    assert summaries["broken-manifest.json"].valid is False


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
        assert isinstance(snapshot.status.writable, bool)
        assert "DROP TABLE" not in snapshot.status.schema_message


def test_selection_payload_survives_retry_provenance():
    """Persist the exact selection alongside its canonical manifest."""
    command = AdminCommand("ingest_manifest", manifest="manifest.json", selection_id="selected")
    payload = corpus_admin._command_payload(command)
    assert payload["selection_id"] == "selected"
    assert payload["manifest"] == "manifest.json"


def _write_manifest(root: Path) -> None:
    """Write a small common catalog with one exact acquired selection."""
    import hashlib

    raw = b"report"
    (root / "report.html").write_bytes(raw)
    payload = {
        "corpus": {"corpus_id": "test", "name": "Test"},
        "documents": [
            {
                "document_id": "nvda-2024",
                "registry": "sec",
                "language": "en",
                "issuer": "NVDA",
                "issuer_id": "0001045810",
                "filing_id": "0001045810-24-000001",
                "fiscal_year": 2024,
                "form": "10-K",
                "filing_date": "2024-02-01",
                "report_period": "2024-01-01",
                "source_url": "https://example.org/report",
                "sec": {
                    "cik": "0001045810",
                    "accession": "0001045810-24-000001",
                    "primary_document": "report.html",
                },
            }
        ],
        "artifacts": [
            {
                "artifact_id": "nvda-source",
                "document_id": "nvda-2024",
                "role": "primary",
                "path": "report.html",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_length": len(raw),
                "encoding": "utf-8",
                "acquisition": {
                    "acquired_at": "2024-02-01T00:00:00Z",
                    "url": "https://example.org/report",
                    "media_type": "text/html",
                },
            }
        ],
        "selections": [{"selection_id": "selected", "artifact_ids": ["nvda-source"]}],
    }
    (root / "manifest.json").write_text(json.dumps(payload))


def test_acquisition_result_keeps_selection_in_completed_job(tmp_path):
    """Keep machine-readable acquisition provenance on the shared job board."""

    async def scenario():
        """Complete an injected operation through the production queue."""

        async def runner(command, publish):
            """Return the same structured result as acquisition adapters."""
            return OperationOutcome("Fetched 1 filing", "manifest.json", "selected")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path), operation_runner=runner
        )
        await service.enqueue(AdminCommand("acquire_edgar", identifiers=("NVDA",), years=(2024,)))
        await service._queue.join()
        job = (await service.jobs()).history[0]
        assert job.status == "succeeded"
        assert job.result_refs == {
            "manifest": "manifest.json",
            "selection_id": "selected",
            "summary": "Fetched 1 filing",
        }

    asyncio.run(scenario())


def test_ingestion_rejects_unknown_selection_before_parsing(tmp_path, monkeypatch):
    """Reject an unlisted selection before invoking any parser or persistence."""
    _write_manifest(tmp_path)
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    async def writable():
        """Isolate manifest validation from live database readiness."""
        return None

    monkeypatch.setattr(service, "_assert_writable_schema", writable)
    with pytest.raises(ValueError, match="unknown processing selection"):
        asyncio.run(
            service._run_operation(
                AdminCommand("ingest_manifest", manifest="manifest.json", selection_id="missing"),
                lambda progress: None,
            )
        )


def test_selection_command_restores_from_stored_job(tmp_path):
    """Restore the identical selection when retrying a persisted operation."""

    async def scenario():
        """Create the ledger row without starting any database work."""
        store = _LedgerStore()
        command = AdminCommand("ingest_manifest", manifest="manifest.json", selection_id="selected")
        row = await store.create(
            job_id="selection",
            domain="corpus",
            kind=command.kind,
            request_json=corpus_admin._command_payload(command),
        )
        assert corpus_admin._command_from_stored(row) == command

    asyncio.run(scenario())


@pytest.mark.parametrize("registry", ["sec", "dart"])
def test_acquisition_returns_common_manifest_selection(tmp_path, monkeypatch, registry):
    """Forward adapter provenance without creating a second catalog."""
    from types import SimpleNamespace

    service = RuntimeCorpusAdminService(
        settings=Settings(corpus_dir=tmp_path, dart_api_key=SecretStr("test"))
    )

    async def writable():
        """Isolate acquisition dispatch from database readiness."""
        return None

    async def acquire(*args, **kwargs):
        """Return the canonical acquisition contract without a network call."""
        return SimpleNamespace(
            fetched=(object(),),
            archived=(object(),),
            manifest="manifest.json",
            selection_id="selected",
        )

    monkeypatch.setattr(service, "_assert_writable_schema", writable)
    monkeypatch.setattr(
        corpus_admin, "acquire_edgar" if registry == "sec" else "acquire_dart", acquire
    )
    result = asyncio.run(
        service._run_operation(
            AdminCommand(
                "acquire_edgar" if registry == "sec" else "acquire_dart",
                identifiers=("NVDA",),
                years=(2024,),
            ),
            lambda progress: None,
        )
    )
    assert result.manifest == "manifest.json"
    assert result.selection_id == "selected"
    assert list(tmp_path.iterdir()) == []


def test_backfill_uses_the_exact_selected_document_ids(tmp_path, monkeypatch):
    """Constrain counting and embedding to the same explicit processing selection."""
    from contextlib import asynccontextmanager

    _write_manifest(tmp_path)
    calls = []
    states = iter(((0, 1), (1, 0)))

    @asynccontextmanager
    async def sessions():
        """Isolate operation dispatch from database persistence."""
        yield object()

    async def writable():
        """Bypass schema I/O for the argument-contract test."""
        return None

    async def bootstrap(engine):
        """Keep the schema boundary free of database calls."""
        return None

    async def state(session, provider, document_ids):
        """Record exactly the documents whose readiness is measured."""
        calls.append(document_ids)
        return next(states)

    async def embed(session, provider, *, on_batch, document_ids, on_usage=None):
        """Verify the backfill uses the identical selection."""
        assert document_ids == ("nvda-2024",)
        return EmbeddingBackfillResult(selected=1, embedded=1, skipped_stale=0, batches=1)

    service = RuntimeCorpusAdminService(
        settings=Settings(corpus_dir=tmp_path),
        session_factory=sessions,
        embedding_provider=DeterministicEmbeddingProvider(),
    )
    monkeypatch.setattr(service, "_assert_writable_schema", writable)
    monkeypatch.setattr(corpus_admin, "bootstrap_schema", bootstrap)
    monkeypatch.setattr(corpus_admin, "_embedding_state", state)
    monkeypatch.setattr(corpus_admin, "embed_missing_chunks", embed)
    result = asyncio.run(
        service._run_operation(
            AdminCommand("backfill_embeddings", manifest="manifest.json", selection_id="selected"),
            lambda progress: None,
        )
    )
    assert "Embedded 1" in result.summary
    assert calls == [("nvda-2024",), ("nvda-2024",)]


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("rebuild_bm25", {"identifiers": "NVDA"}),
        ("rebuild_bm25", {"years": ["2024"]}),
        ("rebuild_bm25", {"expected_documents": True}),
        ("rebuild_bm25", {"manifest": []}),
        ("unsupported", {}),
    ],
)
def test_stored_command_rejects_invalid_json_types(kind, payload):
    """Reject malformed persisted commands instead of coercing retry inputs."""

    async def scenario():
        """Validate one in-memory ledger row without starting an operation."""
        store = _LedgerStore()
        row = await store.create(job_id="invalid", domain="corpus", kind=kind, request_json=payload)
        with pytest.raises(ValueError):
            corpus_admin._command_from_stored(row)

    asyncio.run(scenario())


def test_schema_drift_does_not_misreport_source_permissions(tmp_path, monkeypatch):
    """A schema mismatch must not masquerade as an unwritable corpus directory."""
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    async def drifted():
        """Report only the database mismatch."""
        return "drifted", "Missing source relationship columns", set()

    monkeypatch.setattr(service, "_schema_state", drifted)
    snapshot = asyncio.run(service.snapshot())
    assert snapshot.status.schema_status == "drifted"
    assert snapshot.status.writable is True


def test_acquisition_is_independent_of_corpus_schema_writes(tmp_path, monkeypatch):
    """File acquisition can proceed while incompatible corpus indexing stays blocked."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    blocked = AsyncMock(side_effect=RuntimeError("schema blocked"))
    acquire = AsyncMock(
        return_value=SimpleNamespace(
            fetched=("filing",), manifest="manifest.json", selection_id="selected"
        )
    )
    monkeypatch.setattr(service, "_assert_writable_schema", blocked)
    monkeypatch.setattr(corpus_admin, "acquire_edgar", acquire)
    result = asyncio.run(
        service._run_operation(
            AdminCommand("acquire_edgar", identifiers=("NVDA",), years=(2024,)),
            lambda progress: None,
        )
    )
    assert result.selection_id == "selected"
    blocked.assert_not_awaited()
    with pytest.raises(RuntimeError, match="schema blocked"):
        asyncio.run(service._run_operation(AdminCommand("rebuild_bm25"), lambda progress: None))


def test_manifest_file_counts_do_not_count_archives_as_extra_filings(tmp_path):
    """A primary source and its archive represent one available filing."""
    _write_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text())
    artifact = dict(payload["artifacts"][0])
    artifact.update(artifact_id="archive-copy", role="archive", path="archive.zip", encoding=None)
    (tmp_path / "archive.zip").write_bytes(b"archive")
    payload["artifacts"].append(artifact)
    path.write_text(json.dumps(payload))
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    summary = service._manifest_summaries()[0]
    assert summary.valid is True
    assert summary.sources_present == 1
    assert summary.documents == 1


def test_manifest_companies_are_available_before_source_download(tmp_path):
    """Project source registry and company labels without requiring ingested rows or bytes."""
    _write_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text())
    payload["documents"][0]["aliases"] = ["NVDA", "NVIDIA"]
    path.write_text(json.dumps(payload))
    (tmp_path / "report.html").unlink()
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    summary = service._manifest_summaries()[0]
    assert summary.sources_present == 0
    assert [(item.registry, item.issuer, item.name) for item in summary.issuers] == [
        ("sec", "NVDA", "NVIDIA")
    ]


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
def test_embedding_usage_survives_job_transitions(tmp_path, outcome):
    """Preserve charged usage through progress, failure and cancellation writes."""
    from decimal import Decimal

    from app.observability.usage import USAGE_KEY, provider_identity, usage_record

    async def scenario():
        """Use the bounded in-memory ledger to exercise real worker transition code."""
        store = _LedgerStore()
        service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path), job_store=store)

        async def operation(command, publish, on_usage=None):
            """Record two provider responses before selecting the terminal outcome."""
            record = usage_record(
                identity=provider_identity(
                    provider="openai_embeddings", local=False, credential_slot="dev"
                ),
                model_name="text-embedding-3-large",
                role="embedding",
                input_tokens=12,
                estimated_cost_usd=Decimal("0.0001"),
            )
            await on_usage(record)
            publish(OperationProgress("embedding", 1, 2, "first batch"))
            await on_usage(record)
            if outcome == "failed":
                raise ValueError("fixture failed after provider response")
            if outcome == "cancelled":
                raise corpus_admin.JobCancelledError("fixture cancellation")
            return OperationOutcome("completed")

        service._run_operation = operation
        job = await service.enqueue(AdminCommand("backfill_embeddings"))
        await service._queue.join()
        stored = store.rows[job.job_id]
        assert stored.status == outcome
        assert stored.result_refs[USAGE_KEY][0]["requests"] == 2
        assert stored.result_refs[USAGE_KEY][0]["input_tokens"] == 24

    asyncio.run(scenario())


def test_restored_embedding_usage_ledger_cannot_be_retried_or_read_as_a_command(tmp_path):
    """An archived usage event stays non-executable even if history is restored manually."""

    async def scenario():
        """Use a restored terminal ledger without reaching a database or provider."""
        store = _LedgerStore()
        row = await store.create(
            job_id="usage-ledger",
            domain="corpus",
            kind="embedding_usage",
            request_json={"executable": False},
        )
        store.rows[row.job_id] = replace(row, status="failed")
        service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path), job_store=store)
        assert not (await service.jobs()).history
        with pytest.raises(ValueError, match="cannot be executed"):
            await service.retry(row.job_id)

    asyncio.run(scenario())


def _status_service(tmp_path, monkeypatch, *, tables=None):
    """Build a service whose schema and count probes are counted and never load documents."""
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    calls = {"schema": 0, "counts": 0}
    present = tables if tables is not None else {"documents", "chunks", "bm25_corpus_stats"}

    async def compatible():
        """Report one compatible schema and count the measurement."""
        calls["schema"] += 1
        return "compatible", "ok", set(present)

    async def counts(_tables):
        """Report fixed counts and count the measurement."""
        calls["counts"] += 1
        return 3, 30, 30, True

    async def documents(_tables):
        """Fail if the status path ever loads document rows."""
        raise AssertionError("status must not load document rows")

    monkeypatch.setattr(service, "_schema_state", compatible)
    monkeypatch.setattr(service, "_counts", counts)
    monkeypatch.setattr(service, "_documents", documents)
    return service, calls


def test_status_reuses_a_fresh_probe_and_never_loads_document_rows(tmp_path, monkeypatch):
    """Two status reads inside the window measure once and skip document rows entirely."""
    service, calls = _status_service(tmp_path, monkeypatch)

    async def scenario():
        """Read the status twice within one two-second window."""
        first = await service.status(max_age_s=2.0)
        second = await service.status(max_age_s=2.0)
        return first, second

    first, second = asyncio.run(scenario())
    assert (first.documents, first.chunks, first.embedded_chunks, first.bm25_ready) == (
        3,
        30,
        30,
        True,
    )
    assert first.pending_embeddings == 0
    assert first.writable is True
    assert second == first
    assert calls == {"schema": 1, "counts": 1}


def test_status_recomputes_after_the_max_age_and_on_invalidation(tmp_path, monkeypatch):
    """A reading older than the window, an invalidation, or a zero window measures again."""
    service, calls = _status_service(tmp_path, monkeypatch)
    clock = {"now": 100.0}
    monkeypatch.setattr(corpus_admin.time, "monotonic", lambda: clock["now"])

    async def scenario():
        """Age the memo past the window, invalidate it, then demand a fresh reading."""
        await service.status(max_age_s=2.0)
        clock["now"] += 1.0
        await service.status(max_age_s=2.0)
        clock["now"] += 2.0
        await service.status(max_age_s=2.0)
        service.invalidate_status()
        await service.status(max_age_s=2.0)
        await service.status(max_age_s=0.0)

    asyncio.run(scenario())
    assert calls["schema"] == 4


def test_snapshot_refreshes_the_status_memo(tmp_path, monkeypatch):
    """snapshot() always measures and its reading serves the next status() in the window."""
    service, calls = _status_service(tmp_path, monkeypatch)

    async def documents(_tables):
        """Return no document rows for the administrator table."""
        return ()

    monkeypatch.setattr(service, "_documents", documents)

    async def scenario():
        """Take a snapshot, a cached status, then a second fresh snapshot."""
        snapshot = await service.snapshot()
        status = await service.status(max_age_s=2.0)
        await service.snapshot()
        return snapshot, status

    snapshot, status = asyncio.run(scenario())
    assert status == snapshot.status
    assert calls["schema"] == 2


@pytest.mark.live_postgres
def test_live_postgres_admin_status_matches_snapshot_status() -> None:
    """The status path reports the same non-secret status as the full snapshot."""
    service = RuntimeCorpusAdminService()

    async def both():
        """Take one full snapshot and one fresh status reading on this event loop."""
        # The shared engine may hold connections opened by an earlier asyncio.run loop;
        # recycle them so this reading measures the database, not a stale pool.
        from app.db.session import engine

        await engine.dispose()
        return await service.snapshot(), await service.status(max_age_s=0.0)

    try:
        snapshot, status = asyncio.run(both())
    except Exception as error:  # noqa: BLE001 - shared live-test availability policy
        live_postgres_unavailable(str(error))

    if not status.database_connected:
        live_postgres_unavailable(status.schema_message)
    assert status == snapshot.status
