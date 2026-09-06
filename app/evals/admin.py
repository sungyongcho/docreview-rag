"""Local-only golden-suite execution, persistence, and comparison services."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tempfile
from typing import Any, Final, Literal, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    EvaluationCaseDelta,
    EvaluationCaseSummary,
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationMetricDelta,
    EvaluationResultDetailResponse,
    EvaluationRunRequest,
    GoldenSuiteId,
    GoldenSuiteResource,
    RetrievalProfile,
)
from app.config import Settings, get_settings
from app.db.models import EvalResult, GoldenRevision
from app.evals.arms import Retriever, make_retriever
from app.evals.artifacts import read_strict_json
from app.evals.identity import artifact_filename
from app.evals.index_identity import index_fingerprint
from app.evals.loader import (
    GOLDEN_CASES,
    GoldenDataError,
    SourceMissingError,
    encode_golden_payload,
    load_golden_cases,
    validate_golden_payload,
)
from app.evals.retrieval_eval import (
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.run import _run_cli, arguments
from app.evals.types import GoldenCase
from app.operator.jobs import (
    JobExecutionCoordinator,
    JobStore,
    JobTurnCancelledError,
    ProgressPersister,
)
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.service import retrieve
from app.retrieval.types import RetrievalFilters

MAX_EVALUATION_JOBS: Final[int] = 20
MAX_QUEUED_EVALUATIONS: Final[int] = 8


def _default_session_factory() -> AsyncSession:
    """Create one process-configured session for an evaluation operation."""
    from app.db.session import Session

    return Session()


class SessionFactory(Protocol):
    """Build one caller-owned asynchronous database session."""

    def __call__(self) -> AsyncSession:
        """Return one asynchronous session context manager."""
        ...


@dataclass(frozen=True, slots=True)
class GoldenSuiteDefinition:
    """Filesystem and corpus-language binding for one public suite identity."""

    suite_id: GoldenSuiteId
    label: str
    registry: Literal["sec", "dart"]
    question_language: Literal["en", "ko", "mixed"]
    corpus_language: Literal["en", "ko"]
    golden_name: str
    manifest_name: str

    @property
    def selection_id(self) -> str:
        """Bind the suite to its committed registry evaluation selection."""
        return f"{self.registry}-evaluation"


SUITES: Final[dict[GoldenSuiteId, GoldenSuiteDefinition]] = {
    "sec-en_v2_astra": GoldenSuiteDefinition(
        "sec-en_v2_astra",
        "SEC 10-K · English _v2_astra",
        "sec",
        "en",
        "en",
        "sec_en_v2_astra.json",
        "manifest.json",
    ),
    "sec-ko_v2_astra": GoldenSuiteDefinition(
        "sec-ko_v2_astra",
        "SEC 10-K · Korean _v2_astra",
        "sec",
        "ko",
        "en",
        "sec_ko_v2_astra.json",
        "manifest.json",
    ),
    "sec-mixed_v2_astra": GoldenSuiteDefinition(
        "sec-mixed_v2_astra",
        "SEC 10-K · Mixed EN/KO _v2_astra",
        "sec",
        "mixed",
        "en",
        "sec_mixed_v2_astra.json",
        "manifest.json",
    ),
    "sec-en": GoldenSuiteDefinition(
        "sec-en", "SEC 10-K · English", "sec", "en", "en", "retrieval.json", "manifest.json"
    ),
    "sec-ko": GoldenSuiteDefinition(
        "sec-ko",
        "SEC 10-K · Korean questions",
        "sec",
        "ko",
        "en",
        "retrieval_ko.json",
        "manifest.json",
    ),
    "dart-en": GoldenSuiteDefinition(
        "dart-en",
        "DART · English questions",
        "dart",
        "en",
        "ko",
        "dart_retrieval.json",
        "manifest.json",
    ),
    "dart-ko": GoldenSuiteDefinition(
        "dart-ko",
        "DART · Korean",
        "dart",
        "ko",
        "ko",
        "dart_retrieval_ko.json",
        "manifest.json",
    ),
}


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
        self._persister = ProgressPersister(self._persist_current_job)

    def _definition(self, suite_id: GoldenSuiteId) -> GoldenSuiteDefinition:
        """Resolve one validated suite identifier."""
        return SUITES[suite_id]

    def _suite_paths(self, suite_id: GoldenSuiteId) -> tuple[Path, Path]:
        """Return golden and corpus manifest paths for one suite."""
        definition = self._definition(suite_id)
        return (
            self._golden_dir / definition.golden_name,
            self._settings.corpus_dir / definition.manifest_name,
        )

    def _golden_sha256(self, path: Path) -> str:
        """Hash the exact golden JSON bytes used by a run."""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    async def suites(self) -> tuple[GoldenSuiteResource, ...]:
        """Inspect all suite contracts while reporting missing source readiness safely."""
        resources: list[GoldenSuiteResource] = []
        for definition in SUITES.values():
            golden_path, manifest_path = self._suite_paths(definition.suite_id)
            payload = read_strict_json(golden_path, error=GoldenDataError)
            cases = GOLDEN_CASES.validate_python(payload)
            source_ready = True
            source_error = None
            source_error_code = None
            try:
                load_golden_cases(
                    golden_path, manifest_path=manifest_path, selection_id=definition.selection_id
                )
            except (GoldenDataError, OSError) as error:
                source_ready = False
                source_error = str(error)
                source_error_code = (
                    "source_missing" if isinstance(error, SourceMissingError) else "source_invalid"
                )
            positive = sum(bool(case.answers) for case in cases)
            resources.append(
                GoldenSuiteResource(
                    suite_id=definition.suite_id,
                    label=definition.label,
                    registry=definition.registry,
                    question_language=definition.question_language,
                    corpus_language=definition.corpus_language,
                    case_count=len(cases),
                    scored_positive_cases=positive,
                    absent_cases=len(cases) - positive,
                    curation_status="agent-curated",
                    approval_status="pending-author-approval",
                    human_verified=False,
                    golden_sha256=self._golden_sha256(golden_path),
                    source_ready=source_ready,
                    source_error=source_error,
                    source_error_code=source_error_code,
                )
            )
        return tuple(resources)

    async def enqueue(
        self, request: EvaluationRunRequest, *, retry_of: str | None = None
    ) -> EvaluationJobResource:
        """Queue one quick or matrix evaluation on the single worker."""
        await self.recover_jobs()
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
        self._jobs[job_id] = job
        if self._job_store is not None:
            await self._job_store.create(
                job_id=job_id,
                domain="evaluation",
                kind=request.mode,
                request_json=request.model_dump(mode="json"),
                created_at=job.created_at,
                result_refs={"retry_of": retry_of} if retry_of is not None else {},
            )
        await self._execution_coordinator.register(job_id, job.created_at)
        self._queue.put_nowait(job_id)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="evaluation-admin-worker")
        return job

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
            await self._job_store.cancel(job_id)
        return cancelled

    async def recover_jobs(self) -> None:
        """Interrupt stale process-owned evaluations once before accepting work."""
        if self._recovered_jobs:
            return
        if self._job_store is not None:
            await self._job_store.interrupt_incomplete("evaluation")
        self._recovered_jobs = True

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

    def _quick_retriever(
        self,
        session: AsyncSession,
        profile: RetrievalProfile,
        filters: RetrievalFilters,
    ) -> Retriever:
        """Bind one explicit live-index retrieval profile to the active session."""
        bm25 = profile.lexical_ranker == "bm25"
        if profile.reranker is None:
            return make_retriever(
                session,
                strategy=profile.strategy,
                provider=self._provider,
                lexical_ranker=profile.lexical_ranker,
                bm25_k1=profile.bm25_k1 if bm25 else None,
                bm25_b=profile.bm25_b if bm25 else None,
                bm25_idf=profile.bm25_idf if bm25 else None,
                candidate_k=profile.candidate_k,
                rrf_k=profile.rrf_k,
                route_by_language=profile.route_by_language,
                filters=filters,
            )
        reranker = CrossEncoderReranker()

        async def run(query: str, k: int) -> list[Any]:
            """Retrieve and rerank one query with the bound profile."""
            result = await retrieve(
                session,
                query,
                provider=self._provider,
                k=k,
                candidate_k=profile.candidate_k,
                filters=filters,
                rrf_k=profile.rrf_k,
                reranker=reranker,
                route_by_language=profile.route_by_language,
                lexical_ranker=profile.lexical_ranker or "ts_rank_cd",
                bm25_k1=profile.bm25_k1,
                bm25_b=profile.bm25_b,
                bm25_idf=profile.bm25_idf,
            )
            return list(result.hits)

        return run

    async def _compatible_baseline(
        self,
        session: AsyncSession,
        *,
        suite: str,
        golden_sha256: str,
        corpus_fingerprint: str,
        k: int,
    ) -> EvalResult | None:
        """Return the newest run sharing suite, source corpus, golden bytes, and cutoff."""
        rows = tuple(
            await session.scalars(
                select(EvalResult)
                .where(EvalResult.suite == suite)
                .order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
                .limit(100)
            )
        )
        for row in rows:
            identity = row.config.get("admin_identity", {})
            scoring = row.config.get("_scoring", {})
            if (
                isinstance(identity, dict)
                and identity.get("golden_sha256") == golden_sha256
                and identity.get("corpus_fingerprint") == corpus_fingerprint
                and isinstance(scoring, dict)
                and scoring.get("k") == k
            ):
                return row
        return None

    async def _golden_revision_payload(
        self, request: EvaluationRunRequest
    ) -> tuple[list[dict[str, object]], str]:
        """Load one exact DB revision after binding it to the requested suite."""
        assert request.golden_revision_id is not None
        async with self._session_factory() as session:
            revision = await session.get(GoldenRevision, request.golden_revision_id)
        if revision is None:
            raise ValueError("golden revision does not exist")
        if revision.suite_id != request.suite_id:
            raise ValueError("golden revision does not belong to the requested suite")
        return [dict(item) for item in revision.payload], revision.sha256

    async def _evaluation_cases(
        self, request: EvaluationRunRequest
    ) -> tuple[list[GoldenCase], str]:
        """Resolve canonical or DB-revision cases and their exact byte identity."""
        golden_path, manifest_path = self._suite_paths(request.suite_id)
        if request.golden_revision_id is None:
            cases = await asyncio.to_thread(
                load_golden_cases,
                golden_path,
                manifest_path=manifest_path,
                selection_id=self._definition(request.suite_id).selection_id,
            )
            return cases, self._golden_sha256(golden_path)
        payload, sha256 = await self._golden_revision_payload(request)
        cases = await asyncio.to_thread(
            validate_golden_payload,
            payload,
            manifest_path=manifest_path,
            selection_id=self._definition(request.suite_id).selection_id,
            label=f"golden revision {request.golden_revision_id}",
        )
        return cases, sha256

    async def _quick(
        self, job_id: str, request: EvaluationRunRequest
    ) -> tuple[int, int | None, Path]:
        """Evaluate one profile against the current populated index and persist evidence."""
        definition = self._definition(request.suite_id)
        self._publish(
            job_id, stage="golden", message="Validating golden sources", current=0, total=4
        )
        cases, golden_sha256 = await self._evaluation_cases(request)
        filters = RetrievalFilters(languages=(definition.corpus_language,))
        recorded_at = datetime.now(UTC)
        async with self._session_factory() as session:
            corpus_fingerprint = await self._corpus_fingerprint(session)
            baseline = await self._compatible_baseline(
                session,
                suite=request.suite_id,
                golden_sha256=golden_sha256,
                corpus_fingerprint=corpus_fingerprint,
                k=request.profile.k,
            )
            self._publish(
                job_id, stage="evaluate", message="Running golden queries", current=1, total=4
            )
            retriever = self._quick_retriever(session, request.profile, filters)
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
        definition = self._definition(request.suite_id)
        golden_path, manifest_path = self._suite_paths(request.suite_id)
        temporary_path: Path | None = None
        if request.golden_revision_id is not None:
            payload, _sha256 = await self._golden_revision_payload(request)
            await asyncio.to_thread(
                validate_golden_payload,
                payload,
                manifest_path=manifest_path,
                selection_id=self._definition(request.suite_id).selection_id,
                label=f"golden revision {request.golden_revision_id}",
            )
            self._artifact_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".golden-revision-",
                suffix=".json",
                dir=self._artifact_dir,
                delete=False,
            ) as temporary:
                temporary.write(encode_golden_payload(payload))
                temporary_path = Path(temporary.name)
            golden_path = temporary_path
        try:
            argv = [
                "--suite",
                request.suite_id,
                "--golden",
                str(golden_path),
                "--manifest-name",
                definition.manifest_name,
                "--selection-id",
                definition.selection_id,
                "--artifact-dir",
                str(self._artifact_dir),
                "--provider",
                self._settings.embedding_provider,
                "--target-tokens",
                *(str(value) for value in request.target_tokens),
                "--strategies",
                *request.strategies,
                "--lexical-rankers",
                *request.lexical_rankers,
                "-k",
                str(request.profile.k),
                "--candidate-k",
                str(request.profile.candidate_k),
                "--rrf-k",
                str(request.profile.rrf_k),
                "--bm25-k1",
                str(request.profile.bm25_k1),
                "--bm25-b",
                str(request.profile.bm25_b),
                "--bm25-idf",
                request.profile.bm25_idf,
                "--persist-results",
            ]
            parsed: argparse.Namespace = arguments(argv)
            return await _run_cli(parsed)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

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
            if job.request.mode == "quick":
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

    def _artifact_path(self, raw: str) -> Path:
        """Confine persisted artifact reads to the configured evaluation directory."""
        path = Path(raw).resolve()
        if path.parent != self._artifact_dir:
            raise ValueError("evaluation artifact is outside the configured directory")
        return path

    async def compare(self, candidate_id: int, baseline_id: int) -> EvaluationComparisonResponse:
        """Compare compatible stored artifacts at metric and golden-case level."""
        async with self._session_factory() as session:
            candidate = await session.get(EvalResult, candidate_id)
            baseline = await session.get(EvalResult, baseline_id)
        if candidate is None or baseline is None:
            raise ValueError("evaluation result was not found")
        if candidate.suite != baseline.suite:
            raise ValueError("evaluation suites are not compatible")
        if candidate.config.get("admin_identity") != baseline.config.get("admin_identity"):
            raise ValueError("evaluation corpus or golden identity is not compatible")
        candidate_scoring = candidate.config.get("_scoring", {})
        baseline_scoring = baseline.config.get("_scoring", {})
        if not isinstance(candidate_scoring, dict) or not isinstance(baseline_scoring, dict):
            raise ValueError("evaluation scoring metadata must be an object")
        if candidate_scoring.get("k") != baseline_scoring.get("k"):
            raise ValueError("evaluation cutoffs are not compatible")
        candidate_payload = read_strict_json(
            self._artifact_path(candidate.raw_artifact_path), error=ValueError
        )
        baseline_payload = read_strict_json(
            self._artifact_path(baseline.raw_artifact_path), error=ValueError
        )
        if not isinstance(candidate_payload, dict) or not isinstance(baseline_payload, dict):
            raise ValueError("evaluation artifact root must be an object")
        metric_names = ("recall_at_k", "hit_rate_at_k", "mrr", "mean_latency_ms")
        candidate_metrics = candidate_payload.get("metrics", {})
        baseline_metrics = baseline_payload.get("metrics", {})
        metrics = tuple(
            EvaluationMetricDelta(
                name=name,
                baseline=float(baseline_metrics[name]),
                candidate=float(candidate_metrics[name]),
                delta=float(candidate_metrics[name]) - float(baseline_metrics[name]),
            )
            for name in metric_names
        )

        def cases_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
            """Index artifact case objects by their strict golden identity."""
            return {
                str(item["golden"]["id"]): item
                for item in payload.get("cases", [])
                if isinstance(item, dict) and isinstance(item.get("golden"), dict)
            }

        baseline_cases = cases_by_id(baseline_payload)
        candidate_cases = cases_by_id(candidate_payload)
        case_deltas: list[EvaluationCaseDelta] = []
        for case_id in sorted(set(baseline_cases) & set(candidate_cases)):
            before = baseline_cases[case_id]
            after = candidate_cases[case_id]
            before_score = before.get("score") or {}
            after_score = after.get("score") or {}
            before_rank = before_score.get("first_relevant_rank")
            after_rank = after_score.get("first_relevant_rank")
            if before_rank is None and after_rank is None:
                transition = "stable_miss"
            elif before_rank is None:
                transition = "miss_to_hit"
            elif after_rank is None:
                transition = "hit_to_miss"
            else:
                transition = "stable_hit"
            rank_delta = (
                int(after_rank) - int(before_rank)
                if before_rank is not None and after_rank is not None
                else None
            )
            case_deltas.append(
                EvaluationCaseDelta(
                    case_id=case_id,
                    question=str(after["golden"]["question"]),
                    baseline_rank=before_rank,
                    candidate_rank=after_rank,
                    transition=transition,
                    rank_delta=rank_delta,
                    baseline_citations=tuple(
                        str(hit["citation"]) for hit in before.get("hits", [])[:5]
                    ),
                    candidate_citations=tuple(
                        str(hit["citation"]) for hit in after.get("hits", [])[:5]
                    ),
                )
            )
        return EvaluationComparisonResponse(
            baseline_id=baseline_id,
            candidate_id=candidate_id,
            suite=candidate.suite,
            metrics=metrics,
            cases=tuple(case_deltas),
        )

    async def result_detail(self, result_id: int) -> EvaluationResultDetailResponse | None:
        """Return absolute metrics and bounded case summaries for one result."""
        async with self._session_factory() as session:
            result = await session.get(EvalResult, result_id)
        if result is None:
            return None
        payload = read_strict_json(self._artifact_path(result.raw_artifact_path), error=ValueError)
        if not isinstance(payload, dict):
            raise ValueError("evaluation artifact root must be an object")
        raw_metrics = payload.get("metrics")
        if not isinstance(raw_metrics, dict):
            raise ValueError("evaluation artifact metrics must be an object")
        cases: list[EvaluationCaseSummary] = []
        for item in payload.get("cases", [])[:50]:
            if not isinstance(item, dict) or not isinstance(item.get("golden"), dict):
                continue
            raw_score = item.get("score")
            score = raw_score if isinstance(raw_score, dict) else {}
            cases.append(
                EvaluationCaseSummary(
                    case_id=str(item["golden"].get("id", "unknown")),
                    question=str(item["golden"].get("question", "")),
                    first_relevant_rank=score.get("first_relevant_rank"),
                    citations=tuple(
                        str(hit.get("citation", ""))
                        for hit in item.get("hits", [])[:5]
                        if isinstance(hit, dict)
                    ),
                )
            )
        return EvaluationResultDetailResponse(
            result_id=result.id,
            suite=result.suite,
            config=dict(result.config),
            metrics={name: float(value) for name, value in raw_metrics.items()},
            cases=tuple(cases),
            raw_artifact_path=result.raw_artifact_path,
            created_at=result.created_at,
        )
