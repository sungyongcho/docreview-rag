"""Local-only golden-suite execution, persistence, and comparison services."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
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
from app.db.models import Document, EvalResult
from app.evals.arms import Retriever, make_retriever
from app.evals.artifacts import read_strict_json
from app.evals.identity import artifact_filename
from app.evals.loader import GOLDEN_CASES, GoldenDataError, load_golden_cases
from app.evals.retrieval_eval import (
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.run import _run_cli, arguments
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
    question_language: Literal["en", "ko"]
    corpus_language: Literal["en", "ko"]
    golden_name: str
    manifest_name: str


SUITES: Final[dict[GoldenSuiteId, GoldenSuiteDefinition]] = {
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
        "dart-manifest.json",
    ),
    "dart-ko": GoldenSuiteDefinition(
        "dart-ko",
        "DART · Korean",
        "dart",
        "ko",
        "ko",
        "dart_retrieval_ko.json",
        "dart-manifest.json",
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
            try:
                load_golden_cases(golden_path, manifest_path=manifest_path)
            except (GoldenDataError, OSError) as error:
                source_ready = False
                source_error = str(error)
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
                )
            )
        return tuple(resources)

    async def enqueue(self, request: EvaluationRunRequest) -> EvaluationJobResource:
        """Queue one quick or matrix evaluation on the single worker."""
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
        self._queue.put_nowait(job_id)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="evaluation-admin-worker")
        return job

    async def jobs(self) -> EvaluationJobsResponse:
        """Return active, queued, and completed jobs in newest-first order."""
        return EvaluationJobsResponse(
            jobs=tuple(sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True))
        )

    async def job(self, job_id: str) -> EvaluationJobResource | None:
        """Return one job without exposing internal task objects."""
        return self._jobs.get(job_id)

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

    async def _corpus_fingerprint(self, session: AsyncSession) -> str:
        """Hash current document identities and source snapshots in deterministic order."""
        rows = (
            await session.execute(
                select(Document.doc_id, Document.source_sha256).order_by(Document.doc_id)
            )
        ).all()
        if not rows:
            raise RuntimeError("evaluation requires an ingested corpus")
        digest = hashlib.sha256()
        for doc_id, source_sha256 in rows:
            digest.update(f"{doc_id}:{source_sha256}\n".encode())
        return digest.hexdigest()

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

    async def _quick(
        self, job_id: str, request: EvaluationRunRequest
    ) -> tuple[int, int | None, Path]:
        """Evaluate one profile against the current populated index and persist evidence."""
        definition = self._definition(request.suite_id)
        golden_path, manifest_path = self._suite_paths(request.suite_id)
        self._publish(
            job_id, stage="golden", message="Validating golden sources", current=0, total=4
        )
        cases = await asyncio.to_thread(
            load_golden_cases,
            golden_path,
            manifest_path=manifest_path,
        )
        filters = RetrievalFilters(languages=(definition.corpus_language,))
        recorded_at = datetime.now(UTC)
        golden_sha256 = self._golden_sha256(golden_path)
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
                        "corpus_fingerprint": corpus_fingerprint,
                    },
                    "retrieval_profile": request.profile.model_dump(mode="json"),
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
        golden_path, _manifest_path = self._suite_paths(request.suite_id)
        argv = [
            "--suite",
            request.suite_id,
            "--golden",
            str(golden_path),
            "--manifest-name",
            definition.manifest_name,
            "--artifact-dir",
            str(self._artifact_dir),
            "--provider",
            self._settings.embedding_provider,
            "--target-text-chars",
            *(str(value) for value in request.target_text_chars),
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

    async def _work(self) -> None:
        """Execute queued evaluations serially and retain safe terminal state."""
        while not self._queue.empty():
            job_id = await self._queue.get()
            job = self._jobs[job_id].model_copy(
                update={
                    "status": "running",
                    "stage": "starting",
                    "message": "Starting",
                    "started_at": datetime.now(UTC),
                }
            )
            self._jobs[job_id] = job
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
            self._history.append(job_id)
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
        if candidate.config.get("_scoring", {}).get("k") != baseline.config.get("_scoring", {}).get(
            "k"
        ):
            raise ValueError("evaluation cutoffs are not compatible")
        candidate_payload = read_strict_json(self._artifact_path(candidate.raw_artifact_path))
        baseline_payload = read_strict_json(self._artifact_path(baseline.raw_artifact_path))
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
        payload = read_strict_json(self._artifact_path(result.raw_artifact_path))
        if not isinstance(payload, dict):
            raise ValueError("evaluation artifact root must be an object")
        raw_metrics = payload.get("metrics")
        if not isinstance(raw_metrics, dict):
            raise ValueError("evaluation artifact metrics must be an object")
        cases: list[EvaluationCaseSummary] = []
        for item in payload.get("cases", [])[:50]:
            if not isinstance(item, dict) or not isinstance(item.get("golden"), dict):
                continue
            score = item.get("score") if isinstance(item.get("score"), dict) else {}
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
