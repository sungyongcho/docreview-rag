"""Local-only golden-suite evaluation service: queue, preparation, and job history.

The suite catalog lives in :mod:`app.evals.suites`, stored-result reading in
:mod:`app.evals.admin_results`, and the per-run helpers in :mod:`app.evals.admin_runs`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import Any, Final, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationPreparationResource,
    EvaluationResultDetailResponse,
    EvaluationRunRequest,
    GoldenSuiteId,
    GoldenSuiteResource,
)
from app.api.review_profile import ServerBM25, with_server_bm25
from app.config import Settings, get_settings
from app.corpus_admin.types import CorpusStatus
from app.db.models import Chunk
from app.db.session_factory import SessionFactory
from app.evals.admin_results import (
    compare_stored_results,
    compatible_baseline,
    stored_result_detail,
)
from app.evals.admin_runs import dataset_provenance, quick_retriever, run_isolated_matrix
from app.evals.artifacts import read_strict_json
from app.evals.drafts import DraftInputError, executable_cases
from app.evals.golden_admin import GoldenAdminService
from app.evals.identity import artifact_filename
from app.evals.index_identity import index_fingerprint
from app.evals.loader import GoldenDataError
from app.evals.retrieval_eval import (
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.source_binding import BoundGolden, bind_golden, matrix_scope
from app.evals.suites import (
    SUITES,
    GoldenSuiteDefinition,
    golden_file_sha256,
    suite_paths,
    suite_resources,
)
from app.evals.types import GoldenCase
from app.operator.jobs import (
    JobExecutionCoordinator,
    JobStore,
    JobTurnCancelledError,
    ProgressPersister,
    _default_session_factory,
)
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.types import RetrievalFilters

MAX_EVALUATION_JOBS: Final[int] = 20
MAX_QUEUED_EVALUATIONS: Final[int] = 8


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
    """Run golden evaluations serially and retain bounded in-process job state."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: SessionFactory = _default_session_factory,
        provider: EmbeddingProvider | None = None,
        artifact_dir: Path | None = None,
        job_store: JobStore | None = None,
        execution_lock: asyncio.Lock | None = None,
        execution_coordinator: JobExecutionCoordinator | None = None,
        corpus_status: Callable[[], Awaitable[CorpusStatus]] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._provider = provider or get_embedding_provider(self._settings)
        self._golden_dir = Path(__file__).resolve().parents[2] / "data" / "golden"
        self._artifact_dir = (
            artifact_dir or Path(__file__).resolve().parents[2] / "data" / "eval_runs"
        ).resolve()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUED_EVALUATIONS)
        self._jobs: dict[str, EvaluationJobResource] = {}
        self._history: deque[str] = deque(maxlen=MAX_EVALUATION_JOBS)
        self._worker: asyncio.Task[None] | None = None
        self._job_store = job_store
        self._execution_lock = execution_lock or asyncio.Lock()
        self._execution_coordinator = execution_coordinator or JobExecutionCoordinator()
        self._recovered_jobs = False
        self._enqueue_lock = asyncio.Lock()
        self._corpus_status = corpus_status
        self._persister = ProgressPersister(self._persist_current_job)

    def _definition(self, suite_id: GoldenSuiteId) -> GoldenSuiteDefinition:
        """Resolve one validated suite identifier."""
        return SUITES[suite_id]

    def _suite_paths(self, suite_id: GoldenSuiteId) -> tuple[Path, Path]:
        """Return golden and corpus manifest paths for one suite."""
        return suite_paths(
            suite_id, golden_dir=self._golden_dir, corpus_dir=self._settings.corpus_dir
        )

    async def suites(self) -> tuple[GoldenSuiteResource, ...]:
        """Inspect all suite contracts while reporting missing source readiness safely."""
        return await suite_resources(self._golden_dir, self._settings.corpus_dir)

    async def _bound_golden(self, request: EvaluationRunRequest) -> tuple[BoundGolden, str]:
        """Bind the exact canonical file or selected user revision to current official sources."""
        golden_path, manifest_path = self._suite_paths(request.suite_id)
        if request.golden_revision_id is None:
            payload = read_strict_json(golden_path, error=GoldenDataError)
            digest = golden_file_sha256(golden_path)
        else:
            payload, digest = await self._golden_revision_payload(request)
        if not payload:
            raise GoldenDataError("Add at least one question before evaluating")
        bound = await asyncio.to_thread(
            bind_golden, payload, manifest_path, self._definition(request.suite_id).registry
        )
        return bound, digest

    async def preparation(self, request: EvaluationRunRequest) -> EvaluationPreparationResource:
        """Check sources, exact parsed-source identities, and only the requested search indexes."""
        base: dict[str, Any] = {
            "suite_id": request.suite_id,
            "kind": "builtin" if request.golden_revision_id is None else "user",
        }
        try:
            bound, digest = await self._bound_golden(request)
        except DraftInputError as error:
            return EvaluationPreparationResource(
                **base,
                state="draft_incomplete",
                blockers=tuple(issue.message for issue in error.issues),
            )
        except (OSError, ValueError) as error:
            return EvaluationPreparationResource(
                **base, state="source_invalid", next_step="filings", blockers=(str(error),)
            )
        except SQLAlchemyError:
            return EvaluationPreparationResource(
                **base,
                state="unavailable",
                next_step="setup",
                blockers=("Evaluation preparation status is unavailable.",),
            )
        base.update(source_checks=bound.sources, golden_sha256=digest)
        failed = [source for source in bound.sources if source.state != "ready"]
        if failed:
            return EvaluationPreparationResource(
                **base,
                state="source_invalid"
                if any(source.state == "source_invalid" for source in failed)
                else "source_missing",
                next_step="filings",
                blockers=tuple(
                    f"{source.issuer} FY{source.fiscal_year}: {source.detail}" for source in failed
                ),
            )
        # Matrix builds its own indexes but still requires verified source bytes.
        if request.mode == "matrix":
            if self._corpus_status is None:
                return EvaluationPreparationResource(
                    **base,
                    state="unavailable",
                    next_step="setup",
                    blockers=("Evaluation preparation status is unavailable.",),
                )
            try:
                matrix_status = await self._corpus_status()
                if (
                    not matrix_status.database_connected
                    or matrix_status.schema_status != "compatible"
                    or not matrix_status.writable
                ):
                    return EvaluationPreparationResource(
                        **base,
                        state="unavailable",
                        next_step="setup",
                        blockers=(
                            "Evaluation requires a compatible database "
                            "and writable source storage.",
                        ),
                    )
                await asyncio.to_thread(
                    matrix_scope,
                    self._suite_paths(request.suite_id)[1],
                    self._definition(request.suite_id).registry,
                )
            except (OSError, ValueError) as error:
                return EvaluationPreparationResource(
                    **base, state="source_invalid", next_step="filings", blockers=(str(error),)
                )
            except SQLAlchemyError:
                return EvaluationPreparationResource(
                    **base,
                    state="unavailable",
                    next_step="setup",
                    blockers=("Evaluation preparation status is unavailable.",),
                )
            return EvaluationPreparationResource(**base, state="ready")
        if self._corpus_status is None:
            return EvaluationPreparationResource(
                **base,
                state="unavailable",
                next_step="setup",
                blockers=("Evaluation preparation status is unavailable.",),
            )
        status = None
        try:
            status = await self._corpus_status()
            if not status.database_connected or status.schema_status != "compatible":
                return EvaluationPreparationResource(
                    **base,
                    state="unavailable",
                    next_step="setup",
                    blockers=("Evaluation requires a compatible database.",),
                )
            if not status.chunks:
                return EvaluationPreparationResource(
                    **base,
                    state="parsing_required",
                    next_step="index",
                    blockers=("Parse and chunk the required originals before evaluation.",),
                )
            missing = await self._missing_parsed_sources(bound.cases)
            if missing:
                return EvaluationPreparationResource(
                    **base,
                    state="parsing_required",
                    next_step="index",
                    blockers=tuple(
                        f"Parse and chunk the required original: {doc_id}"
                        for doc_id, _ in sorted(missing)
                    ),
                )
            await self._require_preparation(request, allow_pending=False)
        except ValueError as error:
            if status is None:
                return EvaluationPreparationResource(
                    **base,
                    state="unavailable",
                    next_step="setup",
                    blockers=("Evaluation preparation status is unavailable.",),
                )
            return EvaluationPreparationResource(
                **base, state="index_update_required", blockers=(str(error),)
            )
        except SQLAlchemyError, OSError:
            return EvaluationPreparationResource(
                **base,
                state="unavailable",
                next_step="setup",
                blockers=("Evaluation preparation status is unavailable.",),
            )
        return EvaluationPreparationResource(**base, state="ready")

    async def _missing_parsed_sources(self, cases: tuple[GoldenCase, ...]) -> set[tuple[str, str]]:
        """Require indexed chunks of each exact evidence-document source version."""
        expected = {
            (answer.doc_id, str(answer.source_sha256)) for case in cases for answer in case.answers
        }
        if not expected:
            return set()
        async with self._session_factory() as session:
            found = set(
                (
                    await session.execute(
                        select(Chunk.doc_id, Chunk.source_sha256)
                        .where(Chunk.doc_id.in_({doc_id for doc_id, _ in expected}))
                        .distinct()
                    )
                ).all()
            )
        return expected - found

    async def enqueue(
        self, request: EvaluationRunRequest, *, retry_of: str | None = None
    ) -> EvaluationJobResource:
        """Atomically deduplicate and queue a request, including concurrent callers."""
        server = ServerBM25(self._settings.bm25_k1, self._settings.bm25_b, self._settings.bm25_idf)
        request = request.model_copy(update={"profile": with_server_bm25(request.profile, server)})
        async with self._enqueue_lock:
            return await self._enqueue(request, retry_of=retry_of)

    async def _require_preparation(
        self, request: EvaluationRunRequest, *, allow_pending: bool
    ) -> None:
        """Require the selected quick profile's index, optionally waiting for explicit prep jobs."""
        if request.mode != "quick" or self._corpus_status is None:
            return
        status = await self._corpus_status()
        if not status.database_connected or status.schema_status != "compatible":
            raise ValueError(f"Evaluation requires a compatible database: {status.schema_message}")
        if not status.writable:
            raise ValueError("Evaluation requires writable source storage.")
        if status.chunks == 0 and not (
            allow_pending and self._execution_coordinator.has_kind("ingest_manifest")
        ):
            raise ValueError("Parse and chunk sources before evaluation (step 2).")
        needed = []
        if request.profile.strategy in {"hybrid", "vector"} and (
            status.pending_embeddings > 0 or status.chunks == 0
        ):
            needed.append(
                ("backfill_embeddings", "Complete embeddings before evaluation (step 3).")
            )
        if (
            request.profile.strategy in {"hybrid", "lexical"}
            and request.profile.lexical_ranker == "bm25"
            and not status.bm25_ready
        ):
            needed.append(("rebuild_bm25", "Compute BM25 before evaluation (step 4)."))
        for kind, message in needed:
            if not (allow_pending and self._execution_coordinator.has_kind(kind)):
                raise ValueError(message)

    def _waiting_message(self, job_id: str, message: str) -> None:
        """Refresh a pending evaluation when the shared queue's preceding job changes."""
        job = self._jobs[job_id]
        if job.status == "queued" and job.message != message:
            self._jobs[job_id] = job.model_copy(update={"message": message})
            if self._job_store is not None:
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
        if self._job_store is not None:
            await self._job_store.create(
                job_id=job_id,
                domain="evaluation",
                kind=request.mode,
                request_json=request.model_dump(mode="json"),
                created_at=job.created_at,
                result_refs={"retry_of": retry_of} if retry_of is not None else {},
            )
        self._jobs[job_id] = job
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
        """Return active, queued, and completed jobs in newest-first order."""
        await self.recover_jobs()
        visible = None
        if self._job_store is not None:
            visible = {
                row.job_id
                for row in await self._job_store.list(
                    domain="evaluation", limit=MAX_EVALUATION_JOBS
                )
            }
        return EvaluationJobsResponse(
            jobs=tuple(
                sorted(
                    (
                        job
                        for job in self._jobs.values()
                        if visible is None or job.job_id in visible
                    ),
                    key=lambda job: job.created_at,
                    reverse=True,
                )
            )
        )

    async def job(self, job_id: str) -> EvaluationJobResource | None:
        """Return one job without exposing internal task objects."""
        return self._jobs.get(job_id)

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

    async def retry(self, job_id: str) -> EvaluationJobResource:
        """Create a new evaluation from one failed or interrupted persisted request."""
        await self.recover_jobs()
        if self._job_store is not None:
            record = await self._job_store.get(job_id)
            if record is None or record.result_refs.get("__history_archived") is True:
                raise ValueError(
                    "Restore archived history before retrying; deleted jobs cannot be retried."
                )
        current = self._jobs.get(job_id)
        if current is not None:
            if current.status not in {"failed", "interrupted"}:
                raise ValueError("only failed or interrupted evaluations can be retried")
            return await self.enqueue(current.request, retry_of=job_id)
        if self._job_store is None:
            raise ValueError("evaluation job does not exist")
        stored = await self._job_store.get(job_id)
        if (
            stored is None
            or stored.domain != "evaluation"
            or stored.status
            not in {
                "failed",
                "interrupted",
            }
        ):
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
        if self._job_store is not None:
            await self._persister.write_final(
                job_id, lambda: self._persist_job(cancelled, error_code="cancelled")
            )
        return cancelled

    async def recover_jobs(self) -> None:
        """Interrupt stale process-owned evaluations once before accepting work."""
        if self._recovered_jobs:
            return
        if self._job_store is not None:
            await self._job_store.interrupt_incomplete("evaluation")
            await self._hydrate_jobs()
        self._recovered_jobs = True

    async def _hydrate_jobs(self) -> None:
        """Restore persisted evaluation history so a restart keeps prior jobs visible."""
        assert self._job_store is not None
        stored = await self._job_store.list(domain="evaluation", limit=MAX_EVALUATION_JOBS)
        for row in stored:
            if row.job_id in self._jobs:
                continue
            try:
                request = EvaluationRunRequest.model_validate(row.request_json)
            except TypeError, ValueError:
                logging.getLogger(__name__).warning(
                    "Skipping persisted evaluation with an unreadable request: %s",
                    row.job_id,
                )
                continue
            refs = row.result_refs
            self._jobs[row.job_id] = EvaluationJobResource(
                job_id=row.job_id,
                request=request,
                status=row.status,
                stage=row.stage,
                message=row.message,
                current=row.current,
                total=row.total,
                result_id=cast("int | None", refs.get("result_id")),
                result_ids=tuple(cast("list[int]", refs.get("result_ids") or [])),
                baseline_id=cast("int | None", refs.get("baseline_id")),
                artifact_paths=tuple(cast("list[str]", refs.get("artifact_paths") or [])),
                created_at=row.created_at,
                started_at=row.started_at,
                finished_at=row.finished_at,
            )
            if row.job_id not in self._history:
                self._history.append(row.job_id)

    async def _persist_job(
        self,
        job: EvaluationJobResource,
        *,
        error_code: str | None = None,
    ) -> None:
        """Persist the newest evaluation state and result references."""
        if self._job_store is None:
            return
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
        if self._job_store is not None:
            self._persister.schedule(job_id)

    async def _corpus_fingerprint(self, session: AsyncSession) -> str:
        """Bind evaluation to exact current inputs and the configured vector space."""
        return await index_fingerprint(session, self._provider.identity)

    async def _golden_revision_payload(
        self, request: EvaluationRunRequest
    ) -> tuple[list[dict[str, object]], str]:
        """Load one exact user dataset file bound to the requested suite."""
        assert request.golden_revision_id is not None
        revision = GoldenAdminService(golden_dir=self._golden_dir).get(request.golden_revision_id)
        if revision.suite_id != request.suite_id:
            raise ValueError("golden revision does not belong to the requested suite")
        executable_cases(revision.payload)
        return [dict(item) for item in revision.payload], revision.sha256

    async def _evaluation_cases(
        self, request: EvaluationRunRequest
    ) -> tuple[list[GoldenCase], str]:
        """Resolve built-in or user-file cases and their exact content identity."""
        bound, digest = await self._bound_golden(request)
        if not bound.ready:
            raise GoldenDataError(
                "; ".join(
                    source.detail or source.state
                    for source in bound.sources
                    if source.state != "ready"
                )
            )
        return list(bound.cases), digest

    async def _quick(
        self, job_id: str, request: EvaluationRunRequest
    ) -> tuple[int, int | None, Path]:
        """Evaluate one profile against the current populated index and persist evidence."""
        definition = self._definition(request.suite_id)
        self._publish(
            job_id, stage="golden", message="Validating golden sources", current=0, total=4
        )
        cases, golden_sha256 = await self._evaluation_cases(request)
        filters = RetrievalFilters(
            registries=(definition.registry,), languages=(definition.corpus_language,)
        )
        recorded_at = datetime.now(UTC)
        async with self._session_factory() as session:
            corpus_fingerprint = await self._corpus_fingerprint(session)
            baseline = await compatible_baseline(
                session,
                suite=request.suite_id,
                golden_sha256=golden_sha256,
                corpus_fingerprint=corpus_fingerprint,
                k=request.profile.k,
            )
            self._publish(
                job_id, stage="evaluate", message="Running golden queries", current=1, total=4
            )
            retriever = quick_retriever(session, request.profile, filters, provider=self._provider)
            evaluation = await evaluate_retriever(
                cases,
                retriever,
                suite=request.suite_id,
                config={
                    "admin_identity": {
                        "golden_sha256": golden_sha256,
                        "golden_revision_id": request.golden_revision_id,
                        "corpus_fingerprint": corpus_fingerprint,
                    },
                    "golden_provenance": dataset_provenance(
                        request, golden_sha256, golden_dir=self._golden_dir
                    ),
                    "search_scope": {
                        "registry": definition.registry,
                        "language": definition.corpus_language,
                        "scope": "current-index",
                    },
                    "evidence_document_ids": sorted(
                        {answer.doc_id for case in cases for answer in case.answers}
                    ),
                    "retrieval_profile": request.profile.model_dump(mode="json"),
                    "embedding": asdict(self._provider.identity),
                },
                k=request.profile.k,
                recorded_at=recorded_at,
            )
            self._artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = self._artifact_dir / artifact_filename(
                recorded_at, f"admin-{request.suite_id}"
            )
            self._publish(
                job_id, stage="artifact", message="Writing evaluation evidence", current=2, total=4
            )
            write_evaluation_artifact(artifact_path, evaluation)
            persisted = await persist_evaluation(
                session,
                evaluation,
                raw_artifact_path=artifact_path,
            )
            await session.commit()
        self._publish(
            job_id, stage="persist", message="Persisted evaluation result", current=4, total=4
        )
        return persisted.result_id, baseline.id if baseline is not None else None, artifact_path

    async def _matrix(self, request: EvaluationRunRequest) -> dict[str, Any]:
        """Run the existing isolated corpus matrix through its in-process boundary."""
        _golden_path, manifest_path = self._suite_paths(request.suite_id)
        cases, digest = await self._evaluation_cases(request)
        return await run_isolated_matrix(
            request,
            cases,
            digest,
            manifest_path=manifest_path,
            golden_dir=self._golden_dir,
            artifact_dir=self._artifact_dir,
            embedding_provider=self._settings.embedding_provider,
        )

    async def _execute_job(self, job_id: str) -> None:
        """Execute one evaluation while the shared operator lock is held."""
        job = self._jobs[job_id].model_copy(
            update={
                "status": "running",
                "stage": "starting",
                "message": "Starting",
                "started_at": datetime.now(UTC),
            }
        )
        self._jobs[job_id] = job
        if self._job_store is not None:
            self._persister.schedule(job_id)
        error_code = None
        try:
            preparation = await self.preparation(job.request)
            if preparation.state != "ready":
                raise EvaluationNotReadyError(preparation)
            if job.request.mode == "quick":
                await self._require_preparation(job.request, allow_pending=False)
                result_id, baseline_id, artifact_path = await self._quick(job_id, job.request)
                updates = {
                    "result_id": result_id,
                    "result_ids": (result_id,),
                    "baseline_id": baseline_id,
                    "artifact_paths": (str(artifact_path),),
                }
            else:
                self._publish(job_id, stage="matrix", message="Running isolated matrix")
                payload = await self._matrix(job.request)
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
        self._history.append(job_id)

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
        if job_id not in self._history:
            self._history.append(job_id)

    async def _work(self) -> None:
        """Execute evaluations serially through the shared corpus/evaluation lock."""
        while not self._queue.empty():
            job_id = await self._queue.get()
            try:
                if self._jobs[job_id].status == "cancelled":
                    self._history.append(job_id)
                    continue
                async with self._execution_coordinator.turn(job_id):
                    async with self._execution_lock:
                        if self._jobs[job_id].status != "cancelled":
                            try:
                                await self._execute_job(job_id)
                            except Exception as error:  # noqa: BLE001 - the worker outlives one job
                                await self._abandon_job(job_id, error)
                        else:
                            self._history.append(job_id)
            except JobTurnCancelledError:
                if job_id not in self._history:
                    self._history.append(job_id)
            finally:
                self._queue.task_done()

    async def compare(self, candidate_id: int, baseline_id: int) -> EvaluationComparisonResponse:
        """Compare compatible stored artifacts at metric and golden-case level."""
        return await compare_stored_results(
            self._session_factory, self._artifact_dir, candidate_id, baseline_id
        )

    async def result_detail(self, result_id: int) -> EvaluationResultDetailResponse | None:
        """Return absolute metrics and bounded case summaries for one result."""
        return await stored_result_detail(self._session_factory, self._artifact_dir, result_id)
