"""Local corpus administration over real files and PostgreSQL state."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.corpus_admin.context import CorpusAdminContext, SessionFactory
from app.corpus_admin.inspection import CorpusInspector
from app.corpus_admin.operations import CorpusOperations, OperationRunner
from app.corpus_admin.stored_jobs import command_payload, job_from_stored
from app.corpus_admin.types import (
    MAX_JOB_HISTORY,
    MAX_QUEUED_JOBS,
    AdminCommand,
    AdminJob,
    CorpusSnapshot,
    CorpusStatus,
    DocumentDetail,
    JobBoard,
)
from app.ingestion.progress import OperationProgress
from app.ingestion.source_deletion import SourceDeletion
from app.ingestion.source_selection import record_selection
from app.observability.usage import LEDGER_KIND, USAGE_KEY, merge_usage
from app.operator.corpus_access import CorpusAccess, JobCancelledError
from app.operator.jobs import (
    JobExecutionCoordinator,
    JobStore,
    JobTurnCancelledError,
    ProgressPersister,
    _default_session_factory,
)
from app.operator.progress import advance_progress, finish_progress, start_progress
from app.retrieval.embeddings import EmbeddingProvider


def _utc_now() -> datetime:
    """Return one timezone-aware job timestamp."""
    return datetime.now(UTC)


class RuntimeCorpusAdminService:
    """Local-only corpus administration over real files and PostgreSQL state."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: AsyncEngine | None = None,
        session_factory: SessionFactory = _default_session_factory,
        embedding_provider: EmbeddingProvider | None = None,
        operation_runner: OperationRunner | None = None,
        job_store: JobStore | None = None,
        corpus_access: CorpusAccess | None = None,
        execution_lock: asyncio.Lock | None = None,
        execution_coordinator: JobExecutionCoordinator | None = None,
    ) -> None:
        self._context = CorpusAdminContext(
            settings or get_settings(),
            engine=engine,
            session_factory=session_factory,
            embedding_provider=embedding_provider,
        )
        self._inspector = CorpusInspector(self._context)
        self._job_store = job_store
        self.corpus_access = corpus_access or CorpusAccess()
        self._execution_lock = execution_lock or asyncio.Lock()
        self._execution_coordinator = execution_coordinator or JobExecutionCoordinator()
        self._source_deletion = SourceDeletion(self._context.corpus_root)
        self._operations = CorpusOperations(
            self._context, self._inspector, self._source_deletion, operation_runner
        )
        self._run_operation = self._operations.run
        self._queue: asyncio.Queue[AdminJob] = asyncio.Queue(maxsize=MAX_QUEUED_JOBS)
        self._jobs: dict[str, AdminJob] = {}
        self._history: deque[str] = deque(maxlen=MAX_JOB_HISTORY)
        self._worker: asyncio.Task[None] | None = None
        self._recovered_jobs = False
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._persister = ProgressPersister(self._persist_current_job)

    async def status(self, *, max_age_s: float = 0.0) -> CorpusStatus:
        """Return the operational status alone, without document rows or file scans.

        ``max_age_s`` lets ``/ready`` reuse a recent reading; ``0.0`` always measures.
        """
        return await self._inspector.status(max_age_s=max_age_s)

    def invalidate_status(self) -> None:
        """Drop the memoized reading so the next status call measures again."""
        self._inspector.invalidate_status()

    async def snapshot(
        self,
        *,
        registry: str = "",
        issuer: str = "",
        fiscal_year: int | None = None,
        language: str = "",
        parse_status: str = "",
    ) -> CorpusSnapshot:
        """Inspect live state while failing closed on schema drift or database errors."""
        return await self._inspector.snapshot(
            registry=registry,
            issuer=issuer,
            fiscal_year=fiscal_year,
            language=language,
            parse_status=parse_status,
        )

    async def document_detail(self, doc_id: str) -> DocumentDetail | None:
        """Load one live document and no more than five bounded chunk bodies."""
        return await self._inspector.document_detail(doc_id)

    async def preview_source_deletion(self, document_ids: tuple[str, ...]) -> dict[str, Any]:
        """Read exact deletion targets in a thread without blocking service requests."""
        return await asyncio.to_thread(self._source_deletion.preview, document_ids)

    async def enqueue(self, command: AdminCommand, *, retry_of: str | None = None) -> AdminJob:
        """Queue one operation and start the persistent single worker lazily."""
        if command.kind == "ingest_selected":
            assert command.document_ids is not None
            manifest, selection_id = record_selection(
                self._context.corpus_root, command.identifiers, command.years, command.document_ids
            )
            command = replace(
                command, kind="ingest_manifest", manifest=manifest, selection_id=selection_id
            )
        await self.recover_jobs()
        if self._queue.full():
            raise RuntimeError(f"administrator queue is full ({MAX_QUEUED_JOBS})")
        if command.kind == "delete_sources":
            assert command.deletion_token is not None
            self._source_deletion.reserve(command.deletion_token)
        job = AdminJob(
            job_id=f"admin-{uuid4().hex}",
            command=command,
            status="queued",
            stage="queued",
            current=0,
            total=None,
            message="Queued",
            created_at=_utc_now(),
            result_refs={"retry_of": retry_of} if retry_of is not None else {},
        )
        self._jobs[job.job_id] = job
        self._cancel_events[job.job_id] = asyncio.Event()
        if self._job_store is not None:
            await self._job_store.create(
                job_id=job.job_id,
                domain="corpus",
                kind=command.kind,
                request_json=command_payload(command),
                created_at=job.created_at,
                result_refs=job.result_refs,
            )
        await self._execution_coordinator.register(job.job_id, job.created_at, kind=command.kind)
        self._queue.put_nowait(job)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="corpus-admin-worker")
        return job

    def forget_history(self, job_ids: tuple[str, ...]) -> None:
        """Release terminal cache records only after their persistent deletion."""
        for job_id in job_ids:
            job = self._jobs.get(job_id)
            if job is not None and job.status not in {"queued", "running"}:
                self._jobs.pop(job_id, None)
        self._history = deque(
            (job_id for job_id in self._history if job_id not in job_ids),
            maxlen=self._history.maxlen,
        )

    async def retry(self, job_id: str) -> AdminJob:
        """Requeue the command from one failed or interrupted operation only."""
        await self.recover_jobs()
        if self._job_store is not None:
            record = await self._job_store.get(job_id)
            if record is not None and record.kind == LEDGER_KIND:
                raise ValueError("Usage ledger entries cannot be executed or retried.")
            if record is None or record.result_refs.get("__history_archived") is True:
                raise ValueError(
                    "Restore archived history before retrying; deleted jobs cannot be retried."
                )
        job = self._jobs.get(job_id)
        if job is None and self._job_store is not None:
            stored = await self._job_store.get(job_id)
            job = (
                job_from_stored(stored)
                if stored is not None and stored.domain == "corpus"
                else None
            )
        if job is None or job.status not in {"failed", "interrupted"}:
            raise ValueError("only a known failed or interrupted job can be retried")
        if job.command.kind == "delete_sources":
            raise ValueError(
                "Source deletion requires a fresh preview and confirmation; it cannot be retried."
            )
        return await self.enqueue(job.command, retry_of=job_id)

    async def cancel(self, job_id: str) -> AdminJob:
        """Cancel queued work or request cooperative running-job cancellation."""
        await self.recover_jobs()
        job = self._jobs.get(job_id)
        if job is None or job.status not in {"queued", "running"}:
            raise ValueError("only a known queued or running job can be cancelled")
        if job.status == "running" and job.command.kind != "backfill_embeddings":
            raise ValueError("this running operation has no safe cancellation boundary")
        self._cancel_events.setdefault(job_id, asyncio.Event()).set()
        await self._execution_coordinator.cancel(job_id)
        cancelled = replace(
            job,
            status="cancelled",
            stage="cancelled",
            message="Cancelled by operator.",
            finished_at=_utc_now(),
            error_code="cancelled",
        )
        self._jobs[job_id] = cancelled
        if self._job_store is not None:
            await self._job_store.cancel(job_id)
        return cancelled

    async def jobs(self) -> JobBoard:
        """Return one active job, FIFO queue, and newest-first bounded history."""
        await self.recover_jobs()
        if self._job_store is not None:
            rows = await self._job_store.list(domain="corpus", limit=MAX_JOB_HISTORY + 16)
            jobs = tuple(job_from_stored(row) for row in rows if row.kind != LEDGER_KIND)
            active = next((item for item in jobs if item.status == "running"), None)
            queued = tuple(
                sorted(
                    (item for item in jobs if item.status == "queued"),
                    key=lambda item: item.created_at,
                )
            )
            history = tuple(
                item
                for item in jobs
                if item.status in {"succeeded", "failed", "interrupted", "cancelled"}
            )[:MAX_JOB_HISTORY]
            return JobBoard(active, queued, history)
        ordered = sorted(self._jobs.values(), key=lambda item: item.created_at)
        active = next((item for item in ordered if item.status == "running"), None)
        queued = tuple(item for item in ordered if item.status == "queued")
        history = tuple(self._jobs[job_id] for job_id in reversed(self._history))
        return JobBoard(active, queued, history)

    def _publish(self, job_id: str, progress: OperationProgress) -> None:
        """Replace one running job with its newest non-secret progress snapshot."""
        if self._cancel_events.get(job_id, asyncio.Event()).is_set():
            raise JobCancelledError("cancelled by operator")
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(
            job,
            stage=progress.stage,
            current=progress.current,
            total=progress.total,
            message=self._context.redact(progress.message),
            detail_current=progress.detail_current,
            detail_total=progress.detail_total,
            result_refs=advance_progress(job.command.kind, job.result_refs, progress, _utc_now()),
        )
        if self._job_store is not None:
            self._persister.schedule(job_id)

    async def recover_jobs(self) -> None:
        """Mark stale process-owned jobs interrupted once before accepting work."""
        if self._recovered_jobs:
            return
        if self._job_store is not None:
            await self._job_store.interrupt_incomplete("corpus")
        self._recovered_jobs = True

    async def _persist_current_job(self, job_id: str) -> None:
        """Persist the latest in-memory state, collapsing stale progress callbacks."""
        if self._job_store is None or job_id not in self._jobs:
            return
        job = self._jobs[job_id]
        await self._job_store.put(
            job_id,
            status=job.status,
            stage=job.stage,
            current=job.current,
            total=job.total,
            detail_current=job.detail_current,
            detail_total=job.detail_total,
            message=job.message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_code=job.error_code,
            result_refs=job.result_refs or {},
        )

    async def _execute_job(self, queued: AdminJob) -> None:
        """Execute one corpus job while the shared operator lock is held."""
        running = replace(
            queued,
            status="running",
            stage="starting",
            message="Starting",
            started_at=_utc_now(),
            result_refs=start_progress(queued.command.kind, queued.result_refs, _utc_now()),
        )
        self._jobs[queued.job_id] = running
        if self._job_store is not None:
            self._persister.schedule(queued.job_id)
        try:
            job_id = queued.job_id

            async def record_usage(record: dict[str, object]) -> None:
                """Persist cumulative batch usage without stale progress overwriting it."""
                await self._persister.flush(job_id)
                current = self._jobs[job_id]
                refs = dict(current.result_refs or {})
                previous = refs.get(USAGE_KEY, [])
                if not isinstance(previous, list) or any(
                    not isinstance(row, dict) for row in previous
                ):
                    raise ValueError("Persisted embedding usage ledger is invalid")
                refs[USAGE_KEY] = merge_usage([*previous, record])
                self._jobs[job_id] = replace(current, result_refs=refs)
                await self._persist_current_job(job_id)

            message = await self._run_operation(
                queued.command,
                lambda progress, job_id=job_id: self._publish(job_id, progress),
                on_usage=record_usage,
            )
        except JobCancelledError:
            finished = replace(
                self._jobs[queued.job_id],
                status="cancelled",
                stage="cancelled",
                message="Cancelled by operator.",
                error_code="cancelled",
                finished_at=_utc_now(),
            )
        except Exception as error:  # noqa: BLE001 - job boundary records typed safe failure
            finished = replace(
                self._jobs[queued.job_id],
                status="failed",
                stage="failed",
                message=self._context.redact(f"{type(error).__name__}: {error}"),
                error_code=(
                    "postcondition_failed"
                    if "postcondition failed" in str(error)
                    else type(error).__name__.lower()
                ),
                finished_at=_utc_now(),
            )
        else:
            result_refs = {}
            if message.manifest is not None:
                result_refs = {"manifest": message.manifest, "selection_id": message.selection_id}
            message = message.summary
            finished = replace(
                self._jobs[queued.job_id],
                status="succeeded",
                stage="complete",
                message=self._context.redact(message),
                finished_at=_utc_now(),
                result_refs={
                    **finish_progress(self._jobs[queued.job_id].result_refs),
                    **result_refs,
                    "summary": self._context.redact(message),
                },
            )
        self._jobs[queued.job_id] = finished
        await self._persister.write_final(queued.job_id)
        self.invalidate_status()
        self._history.append(queued.job_id)
        self._cancel_events.pop(queued.job_id, None)

    async def _abandon_job(self, queued: AdminJob, error: Exception) -> None:
        """Record a worker-level failure so a broken job never stays running."""
        current = self._jobs.get(queued.job_id, queued)
        if current.status in {"queued", "running"}:
            self._jobs[queued.job_id] = replace(
                current,
                status="failed",
                stage="failed",
                message=self._context.redact(f"{type(error).__name__}: {error}"),
                error_code="worker_error",
                finished_at=_utc_now(),
            )
            await self._persister.write_final(queued.job_id)
        self.invalidate_status()
        if queued.job_id not in self._history:
            self._history.append(queued.job_id)
        self._cancel_events.pop(queued.job_id, None)

    async def _work(self) -> None:
        """Run queued jobs serially through the shared corpus/evaluation lock."""
        while not self._queue.empty():
            queued = await self._queue.get()
            try:
                if self._jobs.get(queued.job_id, queued).status == "cancelled":
                    self._history.append(queued.job_id)
                    continue
                async with self._execution_coordinator.turn(queued.job_id):
                    async with self._execution_lock:
                        if self._jobs.get(queued.job_id, queued).status != "cancelled":
                            try:
                                # enqueue rewrites ingest_selected to ingest_manifest
                                # before queueing, so only these kinds reach the worker.
                                changes_search = queued.command.kind in {
                                    "ingest_manifest",
                                    "backfill_embeddings",
                                    "rebuild_bm25",
                                }
                                async with (
                                    self.corpus_access.update(
                                        cancelled=self._cancel_events.get(queued.job_id)
                                    )
                                    if changes_search
                                    else nullcontext()
                                ):
                                    await self._execute_job(queued)
                            except Exception as error:  # noqa: BLE001 - the worker outlives one job
                                await self._abandon_job(queued, error)
                        else:
                            self._history.append(queued.job_id)
            except JobTurnCancelledError:
                if queued.job_id not in self._history:
                    self._history.append(queued.job_id)
            finally:
                self._queue.task_done()
