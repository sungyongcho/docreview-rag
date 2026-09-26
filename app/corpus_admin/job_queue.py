"""Queue corpus operations and run them one at a time under the shared execution turn.

Corpus and evaluation jobs share one first-come execution turn, because both load the
database heavily. A job holds searches off only while it rewrites what search reads.
The shared ledger records job state, so a restart can report interrupted work and an
operator can retry it. The worker keeps a local snapshot while publishing progress.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
import logging
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.corpus_admin.types import (
    MAX_QUEUED_JOBS,
    AdminCommand,
    AdminJob,
    OperationOutcome,
    command_from_stored,
    command_payload,
)
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.ingestion.sources.deletion import SourceDeletion
from app.ingestion.sources.selection import record_selection
from app.observability.usage import LEDGER_KIND, USAGE_KEY, UsageSink, merge_usage
from app.operator.corpus_access import CorpusAccess, JobCancelledError
from app.operator.jobs.execution import (
    JobExecutionCoordinator,
    JobPersistenceError,
    JobTurnCancelledError,
    ProgressPersister,
)
from app.operator.jobs.progress import advance_progress, finish_progress, start_progress
from app.operator.jobs.store import JobStore

#: Kinds that rewrite chunks, vectors or BM25 statistics, which search reads.
#: ``enqueue`` turns ``ingest_selected`` into ``ingest_manifest``, so it never runs here.
_SEARCH_CHANGING_KINDS = frozenset({"ingest_manifest", "backfill_embeddings", "rebuild_bm25"})
logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return one timezone-aware job timestamp."""
    return datetime.now(UTC)


def _cancelled(job: AdminJob) -> AdminJob:
    """Return the terminal record of a job the operator cancelled."""
    return replace(
        job,
        status="cancelled",
        stage="cancelled",
        message="Cancelled by operator.",
        error_code="cancelled",
        finished_at=_utc_now(),
    )


def _error_code(error: Exception) -> str:
    """Name a failure for the job board; every broken postcondition shares one code."""
    if "postcondition failed" in str(error):
        return "postcondition_failed"
    return type(error).__name__.lower()


class OperationExecutor(Protocol):
    """Run one queued command, publishing progress and recording provider usage."""

    def __call__(
        self,
        command: AdminCommand,
        publish: OperationProgressCallback,
        on_usage: UsageSink | None = None,
    ) -> Awaitable[OperationOutcome]:
        """Return the outcome once the operation finishes."""
        ...


class CorpusJobQueue:
    """Queue corpus operations and run them serially through the shared execution turn.

    Parameters
    ----------
    corpus_root : Path
        Corpus directory where a selected ingestion records its exact selection.
    source_deletion : SourceDeletion
        Deletion approvals that a queued deletion reserves.
    run_operation : OperationExecutor
        Runs one command once its job holds the execution turn.
    redact : Callable[[str], str]
        Removes server credentials from every message a job records.
    invalidate_status : Callable[[], None]
        Drops the memoized corpus status once a job has changed the corpus.
    job_store : JobStore
        Shared persistent job ledger.
    corpus_access : CorpusAccess
        Gate that holds searches off while a job rewrites what search reads.
    execution_coordinator : JobExecutionCoordinator
        First-come turn order shared with evaluation jobs.
    """

    def __init__(
        self,
        *,
        corpus_root: Path,
        source_deletion: SourceDeletion,
        run_operation: OperationExecutor,
        redact: Callable[[str], str],
        invalidate_status: Callable[[], None],
        job_store: JobStore,
        corpus_access: CorpusAccess,
        execution_coordinator: JobExecutionCoordinator,
    ) -> None:
        self._corpus_root = corpus_root
        self._source_deletion = source_deletion
        self._run_operation = run_operation
        self._redact = redact
        self._invalidate_status = invalidate_status
        self._job_store = job_store
        self.corpus_access = corpus_access
        self._execution_coordinator = execution_coordinator
        self._queue: asyncio.Queue[AdminJob] = asyncio.Queue(maxsize=MAX_QUEUED_JOBS)
        self._jobs: dict[str, AdminJob] = {}
        self._worker: asyncio.Task[None] | None = None
        self._enqueue_lock = asyncio.Lock()
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._persister = ProgressPersister(self._persist_current_job)

    async def enqueue(self, command: AdminCommand, *, retry_of: str | None = None) -> AdminJob:
        """Serialize capacity checks and registration before starting the worker."""
        async with self._enqueue_lock:
            return await self._enqueue(command, retry_of=retry_of)

    async def _enqueue(self, command: AdminCommand, *, retry_of: str | None) -> AdminJob:
        """Admit one command while this domain's registration lock is held."""
        await self.recover_jobs()
        if self._queue.full():
            raise RuntimeError(f"administrator queue is full ({MAX_QUEUED_JOBS})")
        if command.kind == "ingest_selected":
            assert command.document_ids is not None
            manifest, selection_id = record_selection(
                self._corpus_root, command.identifiers, command.years, command.document_ids
            )
            command = replace(
                command, kind="ingest_manifest", manifest=manifest, selection_id=selection_id
            )
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
        await self._job_store.create(
            job_id=job.job_id,
            domain="corpus",
            kind=command.kind,
            request_json=command_payload(command),
            created_at=job.created_at,
            result_refs=job.result_refs,
        )
        self._jobs[job.job_id] = job
        self._cancel_events[job.job_id] = asyncio.Event()
        self._persister.start(job.job_id)
        await self._execution_coordinator.register(job.job_id, job.created_at, kind=command.kind)
        self._queue.put_nowait(job)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="corpus-admin-worker")
        return job

    async def retry(self, job_id: str) -> AdminJob:
        """Requeue the command from one failed or interrupted operation only."""
        await self.recover_jobs()
        record = await self._job_store.get(job_id)
        if record is not None and record.kind == LEDGER_KIND:
            raise ValueError("Usage ledger entries cannot be executed or retried.")
        if record is None or record.result_refs.get("__history_archived") is True:
            raise ValueError(
                "Restore archived history before retrying; deleted jobs cannot be retried."
            )
        if record.domain != "corpus" or record.status not in {"failed", "interrupted"}:
            raise ValueError("only a known failed or interrupted job can be retried")
        if record.kind == "delete_sources":
            raise ValueError(
                "Source deletion requires a fresh preview and confirmation; it cannot be retried."
            )
        return await self.enqueue(command_from_stored(record), retry_of=job_id)

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
        cancelled = _cancelled(job)
        self._jobs[job_id] = cancelled
        await self._persister.write_final(job_id, partial(self._persist_job, cancelled))
        return cancelled

    async def recover_jobs(self) -> None:
        """Reconcile final writes and interrupt previous-process jobs before exposing history."""
        await self._persister.retry_pending()
        await self._job_store.recover("corpus")

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
            message=self._redact(progress.message),
            detail_current=progress.detail_current,
            detail_total=progress.detail_total,
            result_refs=advance_progress(job.command.kind, job.result_refs, progress, _utc_now()),
        )
        self._persister.schedule(job_id)

    async def _record_usage(self, job_id: str, record: dict[str, object]) -> None:
        """Persist cumulative batch usage without stale progress overwriting it."""
        current = self._jobs[job_id]
        refs = dict(current.result_refs or {})
        previous = refs.get(USAGE_KEY, [])
        if not isinstance(previous, list) or any(not isinstance(row, dict) for row in previous):
            raise ValueError("Persisted embedding usage ledger is invalid")
        refs[USAGE_KEY] = merge_usage([*previous, record])
        self._jobs[job_id] = replace(current, result_refs=refs)
        await self._persister.write_current(job_id)

    async def _persist_current_job(self, job_id: str) -> None:
        """Persist the latest in-memory state, collapsing stale progress callbacks."""
        if job_id not in self._jobs:
            return
        await self._persist_job(self._jobs[job_id])

    async def _persist_job(self, job: AdminJob) -> None:
        """Persist one immutable snapshot, even after the worker releases its local state."""
        await self._job_store.put(
            job.job_id,
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
        """Execute one corpus job while it owns the shared execution turn."""
        job_id = queued.job_id
        self._jobs[job_id] = replace(
            queued,
            status="running",
            stage="starting",
            message="Starting",
            started_at=_utc_now(),
            result_refs=start_progress(queued.command.kind, queued.result_refs, _utc_now()),
        )
        self._persister.schedule(job_id)
        try:
            outcome = await self._run_operation(
                queued.command,
                partial(self._publish, job_id),
                on_usage=partial(self._record_usage, job_id),
            )
        except JobCancelledError:
            finished = _cancelled(self._jobs[job_id])
        except Exception as error:  # noqa: BLE001 - job boundary records typed safe failure
            finished = self._failed(self._jobs[job_id], error)
        else:
            finished = self._succeeded(self._jobs[job_id], outcome)
        self._jobs[job_id] = finished
        self._invalidate_status()
        await self._persister.write_final(job_id, partial(self._persist_job, finished))

    def _failed(self, job: AdminJob, error: Exception) -> AdminJob:
        """Return the terminal record of a job whose operation raised."""
        return replace(
            job,
            status="failed",
            stage="failed",
            message=self._redact(f"{type(error).__name__}: {error}"),
            error_code=_error_code(error),
            finished_at=_utc_now(),
        )

    def _succeeded(self, job: AdminJob, outcome: OperationOutcome) -> AdminJob:
        """Return the terminal record of a finished job with its summary and provenance."""
        provenance: dict[str, str | None] = {}
        if outcome.manifest is not None:
            provenance = {"manifest": outcome.manifest, "selection_id": outcome.selection_id}
        summary = self._redact(outcome.summary)
        return replace(
            job,
            status="succeeded",
            stage="complete",
            message=summary,
            finished_at=_utc_now(),
            result_refs={**finish_progress(job.result_refs), **provenance, "summary": summary},
        )

    async def _abandon_job(self, queued: AdminJob, error: Exception) -> None:
        """Record a worker-level failure so a broken job never stays running."""
        current = self._jobs.get(queued.job_id, queued)
        if current.status in {"queued", "running"}:
            self._jobs[queued.job_id] = replace(
                current,
                status="failed",
                stage="failed",
                message=self._redact(f"{type(error).__name__}: {error}"),
                error_code="worker_error",
                finished_at=_utc_now(),
            )
            await self._persister.write_final(
                queued.job_id, partial(self._persist_job, self._jobs[queued.job_id])
            )
        self._invalidate_status()

    async def _work(self) -> None:
        """Run jobs serially; retain unsaved final snapshots for explicit reconciliation."""
        while not self._queue.empty():
            queued = await self._queue.get()
            try:
                await self._run_in_turn(queued)
            except JobTurnCancelledError:
                # Cancellation already wrote the terminal state before removing its turn.
                pass
            except JobPersistenceError as error:
                logger.error("%s (%s)", error, type(error.__cause__).__name__)
            finally:
                await self._persister.flush(queued.job_id)
                self._jobs.pop(queued.job_id, None)
                self._cancel_events.pop(queued.job_id, None)
                self._queue.task_done()

    async def _run_in_turn(self, queued: AdminJob) -> None:
        """Wait for the shared execution turn, skipping jobs cancelled while waiting."""
        if self._is_cancelled(queued):
            return
        async with self._execution_coordinator.turn(queued.job_id):
            if not self._is_cancelled(queued):
                await self._execute_guarded(queued)

    async def _execute_guarded(self, queued: AdminJob) -> None:
        """Execute one admitted job; a failure outside the operation fails only this job."""
        try:
            async with self._search_guard(queued):
                await self._execute_job(queued)
        except JobPersistenceError:
            raise
        except Exception as error:  # noqa: BLE001 - the worker outlives one job
            await self._abandon_job(queued, error)

    def _search_guard(self, job: AdminJob) -> AbstractAsyncContextManager[None]:
        """Hold searches off only while this job rewrites what search reads."""
        if job.command.kind not in _SEARCH_CHANGING_KINDS:
            return nullcontext()
        return self.corpus_access.update(cancelled=self._cancel_events.get(job.job_id))

    def _is_cancelled(self, queued: AdminJob) -> bool:
        """Tell whether the operator cancelled this job before it started."""
        return self._jobs.get(queued.job_id, queued).status == "cancelled"
