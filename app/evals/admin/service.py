"""Local-only golden-suite evaluation service: queue, preparation, and job history.

The suite catalog lives in :mod:`app.evals.golden.catalog`, stored-result reading in
:mod:`app.evals.results.comparison`, and the per-run helpers in :mod:`app.evals.admin.execution`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
import logging
from pathlib import Path
from typing import Final, cast
from uuid import uuid4

from app.config import Settings, get_settings
from app.corpus_admin.types import CorpusStatus
from app.db.session_factory import SessionFactory, default_session_factory
from app.evals.admin.execution import run_matrix_request, run_quick
from app.evals.admin.preparation import prepare_evaluation
from app.evals.contracts import (
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationPreparationResource,
    EvaluationResultDetailResponse,
    EvaluationRunRequest,
    GoldenSuiteResource,
)
from app.evals.golden.catalog import suite_resources
from app.evals.results.comparison import compare_stored_results, stored_result_detail
from app.operator.jobs.execution import (
    JobExecutionCoordinator,
    JobPersistenceError,
    JobTurnCancelledError,
    ProgressPersister,
)
from app.operator.jobs.store import JobStore, StoredJob
from app.retrieval.embedding.provider import EmbeddingProvider, get_embedding_provider
from app.retrieval.search.profiles import ServerBM25, with_server_bm25

MAX_EVALUATION_JOBS: Final[int] = 20
MAX_QUEUED_EVALUATIONS: Final[int] = 8
logger = logging.getLogger(__name__)


class EvaluationAlreadyQueuedError(ValueError):
    """Identify an active equivalent quick evaluation for authoritative duplicate feedback."""

    def __init__(self, job_id: str) -> None:
        """Attach the already registered job to the duplicate response."""
        self.job_id = job_id
        super().__init__(f"The same evaluation is already queued: {job_id}. Open Jobs to view it.")


class EvaluationNotReadyError(ValueError):
    """Reject a request before creating any job when its evaluation inputs are not prepared."""

    def __init__(self, preparation: EvaluationPreparationResource) -> None:
        self.preparation = preparation
        super().__init__("; ".join(preparation.blockers) or preparation.state)


class EvaluationAdminService:
    """Run evaluations serially while the shared ledger owns their visible history."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: SessionFactory = default_session_factory,
        provider: EmbeddingProvider | None = None,
        artifact_dir: Path | None = None,
        job_store: JobStore | None = None,
        execution_coordinator: JobExecutionCoordinator | None = None,
        corpus_status: Callable[[], Awaitable[CorpusStatus]] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._provider = provider or get_embedding_provider(self._settings)
        self._golden_dir = Path(__file__).resolve().parents[3] / "data" / "golden"
        self._artifact_dir = (
            artifact_dir or Path(__file__).resolve().parents[3] / "data" / "eval_runs"
        ).resolve()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUED_EVALUATIONS)
        self._jobs: dict[str, EvaluationJobResource] = {}
        self._worker: asyncio.Task[None] | None = None
        self._job_store = job_store or JobStore(session_factory=session_factory)
        self._execution_coordinator = execution_coordinator or JobExecutionCoordinator()
        self._enqueue_lock = asyncio.Lock()
        self._corpus_status = corpus_status
        self._persister = ProgressPersister(self._persist_current_job)

    async def suites(self) -> tuple[GoldenSuiteResource, ...]:
        """Inspect all suite contracts while reporting missing source readiness safely."""
        return await suite_resources(self._golden_dir, self._settings.corpus_dir)

    async def preparation(self, request: EvaluationRunRequest) -> EvaluationPreparationResource:
        """Report whether the requested dataset and current index can be evaluated."""
        return await prepare_evaluation(
            request,
            golden_dir=self._golden_dir,
            corpus_dir=self._settings.corpus_dir,
            session_factory=self._session_factory,
            corpus_status=self._corpus_status,
        )

    async def enqueue(
        self, request: EvaluationRunRequest, *, retry_of: str | None = None
    ) -> EvaluationJobResource:
        """Atomically deduplicate and queue a request, including concurrent callers."""
        server = ServerBM25(self._settings.bm25_k1, self._settings.bm25_b, self._settings.bm25_idf)
        request = request.model_copy(update={"profile": with_server_bm25(request.profile, server)})
        async with self._enqueue_lock:
            return await self._enqueue(request, retry_of=retry_of)

    def _waiting_message(self, job_id: str, message: str) -> None:
        """Refresh a pending evaluation when the shared queue's preceding job changes."""
        job = self._jobs[job_id]
        if job.status == "queued" and job.message != message:
            self._jobs[job_id] = job.model_copy(update={"message": message})
            self._persister.schedule(job_id)

    async def _enqueue(
        self, request: EvaluationRunRequest, *, retry_of: str | None = None
    ) -> EvaluationJobResource:
        """Reserve one request under the enqueue lock before durable registration."""
        await self.recover_jobs()
        if request.mode == "quick":
            for existing in self._jobs.values():
                other = existing.request
                if (
                    existing.status in {"queued", "running"}
                    and other.mode == "quick"
                    and other.suite_id == request.suite_id
                    and other.golden_revision_id == request.golden_revision_id
                    and other.profile == request.profile
                    and set(other.strategies) == set(request.strategies)
                ):
                    raise EvaluationAlreadyQueuedError(existing.job_id)
        preparation = await self.preparation(request)
        if preparation.state != "ready":
            raise EvaluationNotReadyError(preparation)
        if self._queue.full():
            raise RuntimeError("evaluation queue is full")
        job_id = f"eval-{uuid4().hex}"
        job = EvaluationJobResource(
            job_id=job_id,
            request=request,
            status="queued",
            stage="queued",
            message="Queued",
            created_at=datetime.now(UTC),
        )
        await self._job_store.create(
            job_id=job_id,
            domain="evaluation",
            kind=request.mode,
            request_json=request.model_dump(mode="json"),
            created_at=job.created_at,
            result_refs={"retry_of": retry_of} if retry_of is not None else {},
        )
        self._jobs[job_id] = job
        self._persister.start(job_id)
        await self._execution_coordinator.register(
            job_id,
            job.created_at,
            kind=request.mode,
            on_wait=lambda message: self._waiting_message(job_id, message),
        )
        self._queue.put_nowait(job_id)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="evaluation-admin-worker")
        return self._jobs[job_id]

    async def jobs(self) -> EvaluationJobsResponse:
        """Project currently visible persisted evaluations in newest-first order."""
        await self.recover_jobs()
        rows = await self._job_store.list(domain="evaluation", limit=MAX_EVALUATION_JOBS)
        return EvaluationJobsResponse(jobs=tuple(self._job_resource(row) for row in rows))

    @staticmethod
    def _job_resource(row: StoredJob) -> EvaluationJobResource:
        """Decode a current evaluation request and its persisted result references."""
        refs = row.result_refs
        return EvaluationJobResource(
            job_id=row.job_id,
            request=EvaluationRunRequest.model_validate(row.request_json),
            status=row.status,
            stage=row.stage,
            message=row.message,
            current=row.current,
            total=row.total,
            result_id=cast("int | None", refs.get("result_id")),
            result_ids=tuple(cast("list[int]", refs.get("result_ids", []))),
            baseline_id=cast("int | None", refs.get("baseline_id")),
            artifact_paths=tuple(cast("list[str]", refs.get("artifact_paths", []))),
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    async def retry(self, job_id: str) -> EvaluationJobResource:
        """Create a new evaluation from one failed or interrupted persisted request."""
        await self.recover_jobs()
        stored = await self._job_store.get(job_id)
        if stored is None or stored.result_refs.get("__history_archived") is True:
            raise ValueError(
                "Restore archived history before retrying; deleted jobs cannot be retried."
            )
        if stored.domain != "evaluation" or stored.status not in {"failed", "interrupted"}:
            raise ValueError("only failed or interrupted evaluations can be retried")
        return await self.enqueue(
            EvaluationRunRequest.model_validate(stored.request_json), retry_of=job_id
        )

    async def cancel(self, job_id: str) -> EvaluationJobResource:
        """Cancel one queued evaluation before provider or corpus work begins."""
        await self.recover_jobs()
        job = self._jobs.get(job_id)
        if job is None or job.status != "queued":
            raise ValueError("only a queued evaluation can be cancelled")
        cancelled = job.model_copy(
            update={
                "status": "cancelled",
                "stage": "cancelled",
                "message": "Cancelled by operator.",
                "finished_at": datetime.now(UTC),
            }
        )
        self._jobs[job_id] = cancelled
        await self._execution_coordinator.cancel(job_id)
        await self._persister.write_final(
            job_id, lambda: self._persist_job(cancelled, error_code="cancelled")
        )
        return cancelled

    async def recover_jobs(self) -> None:
        """Reconcile final writes and interrupt previous-process jobs before exposing history."""
        await self._persister.retry_pending()
        await self._job_store.recover("evaluation")

    async def _persist_job(
        self,
        job: EvaluationJobResource,
        *,
        error_code: str | None = None,
    ) -> None:
        """Persist the newest evaluation state and result references."""
        await self._job_store.put(
            job.job_id,
            status=job.status,
            stage=job.stage,
            current=job.current,
            total=job.total,
            detail_current=None,
            detail_total=None,
            message=job.message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_code=error_code,
            result_refs={
                "result_id": job.result_id,
                "result_ids": list(job.result_ids),
                "baseline_id": job.baseline_id,
                "artifact_paths": list(job.artifact_paths),
            },
        )

    async def _persist_current_job(self, job_id: str) -> None:
        """Persist only the latest in-memory state when progress tasks run out of order."""
        job = self._jobs.get(job_id)
        if job is not None:
            await self._persist_job(job)

    def _publish(
        self,
        job_id: str,
        *,
        stage: str,
        message: str,
        current: int = 0,
        total: int | None = None,
    ) -> None:
        """Replace one running job with a progress snapshot."""
        self._jobs[job_id] = self._jobs[job_id].model_copy(
            update={"stage": stage, "message": message, "current": current, "total": total}
        )
        self._persister.schedule(job_id)

    async def _execute_job(self, job_id: str) -> None:
        """Execute one evaluation while it owns the shared execution turn."""
        job = self._jobs[job_id].model_copy(
            update={
                "status": "running",
                "stage": "starting",
                "message": "Starting",
                "started_at": datetime.now(UTC),
            }
        )
        self._jobs[job_id] = job
        self._persister.schedule(job_id)
        error_code = None
        try:
            preparation = await self.preparation(job.request)
            if preparation.state != "ready":
                raise EvaluationNotReadyError(preparation)
            if job.request.mode == "quick":
                result_id, baseline_id, artifact_path = await run_quick(
                    job.request,
                    settings=self._settings,
                    session_factory=self._session_factory,
                    provider=self._provider,
                    golden_dir=self._golden_dir,
                    artifact_dir=self._artifact_dir,
                    publish=partial(self._publish, job_id),
                )
                updates = {
                    "result_id": result_id,
                    "result_ids": (result_id,),
                    "baseline_id": baseline_id,
                    "artifact_paths": (str(artifact_path),),
                }
            else:
                self._publish(job_id, stage="matrix", message="Running isolated matrix")
                payload = await run_matrix_request(
                    job.request,
                    settings=self._settings,
                    golden_dir=self._golden_dir,
                    artifact_dir=self._artifact_dir,
                )
                persisted = tuple(
                    int(item["result_id"])
                    for item in payload.get("persisted", [])
                    if isinstance(item, dict) and item.get("result_id") is not None
                )
                updates = {
                    "result_id": persisted[0] if persisted else None,
                    "result_ids": persisted,
                    "artifact_paths": tuple(str(path) for path in payload.get("artifacts", [])),
                }
        except Exception as error:  # noqa: BLE001 - terminal job boundary
            error_code = type(error).__name__.lower()
            finished = self._jobs[job_id].model_copy(
                update={
                    "status": "failed",
                    "stage": "failed",
                    "message": f"{type(error).__name__}: {error}",
                    "finished_at": datetime.now(UTC),
                }
            )
        else:
            finished = self._jobs[job_id].model_copy(
                update={
                    **updates,
                    "status": "succeeded",
                    "stage": "complete",
                    "message": "Evaluation completed",
                    "finished_at": datetime.now(UTC),
                }
            )
        self._jobs[job_id] = finished
        await self._persister.write_final(
            job_id, lambda: self._persist_job(finished, error_code=error_code)
        )

    async def _abandon_job(self, job_id: str, error: Exception) -> None:
        """Record a worker-level failure so a broken evaluation never stays running."""
        current = self._jobs.get(job_id)
        if current is not None and current.status in {"queued", "running"}:
            finished = current.model_copy(
                update={
                    "status": "failed",
                    "stage": "failed",
                    "message": f"{type(error).__name__}: {error}",
                    "finished_at": datetime.now(UTC),
                }
            )
            self._jobs[job_id] = finished
            await self._persister.write_final(
                job_id, lambda: self._persist_job(finished, error_code="worker_error")
            )

    async def _work(self) -> None:
        """Execute evaluations serially and release state after pending writes finish."""
        while not self._queue.empty():
            job_id = await self._queue.get()
            try:
                if self._jobs[job_id].status == "cancelled":
                    continue
                async with self._execution_coordinator.turn(job_id):
                    if self._jobs[job_id].status != "cancelled":
                        try:
                            await self._execute_job(job_id)
                        except JobPersistenceError:
                            raise
                        except Exception as error:  # noqa: BLE001 - the worker outlives one job
                            await self._abandon_job(job_id, error)
            except JobTurnCancelledError:
                pass
            except JobPersistenceError as error:
                logger.error("%s (%s)", error, type(error.__cause__).__name__)
            finally:
                await self._persister.flush(job_id)
                self._jobs.pop(job_id, None)
                self._queue.task_done()

    async def compare(self, candidate_id: int, baseline_id: int) -> EvaluationComparisonResponse:
        """Compare compatible stored artifacts at metric and golden-case level."""
        return await compare_stored_results(
            self._session_factory, self._artifact_dir, candidate_id, baseline_id
        )

    async def result_detail(self, result_id: int) -> EvaluationResultDetailResponse | None:
        """Return absolute metrics and bounded case summaries for one result."""
        return await stored_result_detail(self._session_factory, self._artifact_dir, result_id)
