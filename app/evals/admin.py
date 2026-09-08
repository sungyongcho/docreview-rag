"""Local-only golden-suite execution, persistence, and comparison services."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tempfile
from typing import Any, Final, Literal, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    EvaluationCaseDelta,
    EvaluationCaseSummary,
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationMetricDelta,
    EvaluationPreparationResource,
    EvaluationResultDetailResponse,
    EvaluationRunRequest,
    GoldenSuiteId,
    GoldenSuiteResource,
    RetrievalProfile,
)
from app.config import Settings, get_settings
from app.corpus_admin import CorpusStatus
from app.db.models import Chunk, EvalResult
from app.evals.arms import Retriever, make_retriever
from app.evals.artifacts import read_strict_json
from app.evals.drafts import DraftInputError, executable_cases
from app.evals.identity import artifact_filename
from app.evals.index_identity import index_fingerprint
from app.evals.loader import (
    GOLDEN_CASES,
    GoldenDataError,
    encode_golden_payload,
)
from app.evals.retrieval_eval import (
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.run import _run_cli, arguments
from app.evals.source_binding import BoundGolden, bind_golden, matrix_scope
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
            checks = ()
            try:
                bound = await asyncio.to_thread(
                    bind_golden, payload, manifest_path, definition.registry
                )
                checks = bound.sources
                source_ready = bound.ready
                failed = [source for source in checks if source.state != "ready"]
                if failed:
                    source_error_code = (
                        "source_invalid"
                        if any(source.state == "source_invalid" for source in failed)
                        else "source_missing"
                    )
                    source_error = "; ".join(
                        f"{source.issuer} FY{source.fiscal_year}: {source.detail}"
                        for source in failed
                    )
            except (GoldenDataError, OSError, ValueError) as error:
                source_ready = False
                source_error = str(error)
                source_error_code = "source_invalid"
            positive = sum(bool(case.answers) for case in cases)
            resources.append(
                GoldenSuiteResource(
                    filename=golden_path.name,
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
                    source_checks=checks,
                    source_error=source_error,
                    source_error_code=source_error_code,
                )
            )
        return tuple(resources)

    async def _bound_golden(self, request: EvaluationRunRequest) -> tuple[BoundGolden, str]:
        """Bind the exact canonical file or selected user revision to current official sources."""
        golden_path, manifest_path = self._suite_paths(request.suite_id)
        if request.golden_revision_id is None:
            payload = read_strict_json(golden_path, error=GoldenDataError)
            digest = self._golden_sha256(golden_path)
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

    def _dataset_provenance(self, request: EvaluationRunRequest, digest: str) -> dict[str, Any]:
        """Freeze the filename and content identity used by this evaluation."""
        from app.evals.golden_admin import GoldenAdminService

        filename = (
            self._definition(request.suite_id).golden_name
            if request.golden_revision_id is None
            else GoldenAdminService(golden_dir=self._golden_dir)
            .get(request.golden_revision_id)
            .filename
        )
        return {
            "filename": filename,
            "dataset_id": f"builtin:{request.suite_id}"
            if request.golden_revision_id is None
            else f"file:{request.golden_revision_id}",
            "kind": "builtin" if request.golden_revision_id is None else "user",
            "verification_status": "pending_review",
            "golden_sha256": digest,
            "golden_revision_id": request.golden_revision_id,
        }

    async def _golden_revision_payload(
        self, request: EvaluationRunRequest
    ) -> tuple[list[dict[str, object]], str]:
        """Load one exact user dataset file bound to the requested suite."""
        assert request.golden_revision_id is not None
        from app.evals.golden_admin import GoldenAdminService

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
                    "golden_provenance": self._dataset_provenance(request, golden_sha256),
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
        definition = self._definition(request.suite_id)
        _golden_path, manifest_path = self._suite_paths(request.suite_id)
        cases, _golden_sha = await self._evaluation_cases(request)
        scope = await asyncio.to_thread(matrix_scope, manifest_path, definition.registry)
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.NamedTemporaryFile(
                mode="w", prefix=".evaluation-scope-", suffix=".json", dir=manifest_path.parent
            ) as scope_file,
            tempfile.NamedTemporaryFile(
                mode="wb", prefix=".golden-bound-", suffix=".json", dir=self._artifact_dir
            ) as golden_file,
        ):
            scope_file.write(scope.model_dump_json())
            scope_file.flush()
            golden_file.write(
                encode_golden_payload([case.model_dump(mode="json") for case in cases])
            )
            golden_file.flush()
            golden_path = Path(golden_file.name)
            argv = [
                "--suite",
                request.suite_id,
                "--golden",
                str(golden_path),
                "--manifest-name",
                scope_file.name,
                "--selection-id",
                "evaluation-scope",
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
            parsed.admin_metadata = {
                "golden_provenance": self._dataset_provenance(request, _golden_sha),
                "search_scope": {
                    "registry": definition.registry,
                    "document_ids": sorted(document.document_id for document in scope.documents),
                    "manifest_sha256": hashlib.sha256(scope.model_dump_json().encode()).hexdigest(),
                },
            }
            return await _run_cli(parsed)

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
