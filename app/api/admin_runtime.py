"""Local-only composition for corpus, evaluation, and profile-preview resources."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    CorpusOperationRequest,
    DocumentEmbeddingStatus,
    DocumentFacetsResponse,
    DocumentInventoryResponse,
    DocumentSort,
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationResultDetailResponse,
    EvaluationRunRequest,
    GoldenCanonicalResource,
    GoldenRevisionResource,
    GoldenSuiteId,
    GoldenSuiteResource,
    OperatorJobResource,
    OperatorJobsResponse,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    RetrievalProfile,
    ReviewPreviewRequest,
    ReviewPreviewResponse,
    SnapshotCreateRequest,
    SnapshotVisibilityRequest,
    UsageModelResource,
    UsageResponse,
)
from app.api.document_catalog import DocumentCatalog
from app.api.errors import ApiProblemError, unavailable
from app.api.runtime import RuntimeApiServices
from app.api.schemas import (
    EvidenceHit,
    ReviewRequest,
    RunResponse,
    SnapshotComparisonResponse,
    SnapshotResource,
)
from app.corpus_admin import AdminCommand, RuntimeCorpusAdminService
from app.db.models import (
    Run,
    Trace,
)
from app.evals.admin import EvaluationAdminService
from app.evals.arms import make_retriever
from app.evals.golden_admin import GoldenAdminService
from app.evals.snapshots import SnapshotService
from app.llm.local_connection import LocalConnectionError, LocalConnectionManager, LocalProtocol
from app.operator.jobs import JobExecutionCoordinator, JobStore, StoredJob
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.service import ComponentRankings, RetrievalResult, retrieve
from app.retrieval.types import RetrievalFilters


class RuntimeAdminApiServices:
    """Compose every SSH-only administrator operation without HTTP concerns."""

    def __init__(
        self,
        *,
        runtime: RuntimeApiServices,
        corpus: RuntimeCorpusAdminService | None = None,
        evaluations: EvaluationAdminService | None = None,
        golden: GoldenAdminService | None = None,
        snapshots: SnapshotService | None = None,
        job_store: JobStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._documents = DocumentCatalog(
            runtime.session_factory, public_only=False, company_names=runtime.company_names
        )
        self._job_store = job_store or JobStore(session_factory=runtime.session_factory)
        execution_lock = asyncio.Lock()
        execution_coordinator = JobExecutionCoordinator()
        self._corpus = corpus or RuntimeCorpusAdminService(
            session_factory=runtime.session_factory,
            job_store=self._job_store,
            execution_lock=execution_lock,
            execution_coordinator=execution_coordinator,
        )
        self._evaluations = evaluations or EvaluationAdminService(
            session_factory=runtime.session_factory,
            job_store=self._job_store,
            execution_lock=execution_lock,
            execution_coordinator=execution_coordinator,
        )
        self._golden = golden or GoldenAdminService()
        self._snapshots = snapshots or SnapshotService()

    def _local_connection(self) -> LocalConnectionManager:
        """Require an enabled developer connection manager, including on SSH admin routes."""
        connection = self._runtime.local_connection
        if connection is None or not connection.enabled:
            raise ApiProblemError(
                status_code=403,
                code="disabled_in_prod",
                message="Local LLM settings are available only in Dev.",
            )
        return connection

    async def local_connection_state(self) -> dict[str, Any]:
        """Read the active endpoint and model information for developer settings."""
        return await self._local_connection().state()

    async def update_local_connection(
        self,
        action: Literal["connect", "disconnect", "reset", "add", "select"],
        base_url: str = "",
        protocol: LocalProtocol = "auto",
        *,
        name: str = "",
        server_id: str = "",
    ) -> dict[str, Any]:
        """Apply one explicit configuration action and translate safe persistence failures."""
        connection = self._local_connection()
        try:
            if action == "connect":
                return await connection.connect(base_url, protocol)
            if action == "disconnect":
                return await connection.disconnect()
            if action == "add":
                return await connection.add_server(name, base_url, protocol)
            if action == "select":
                return await connection.select_server(server_id)
            return await connection.reset()
        except LocalConnectionError as error:
            raise unavailable(error.code, str(error)) from error

    async def diagnose_local_connection(
        self,
        *,
        server_id: str | None = None,
        base_url: str | None = None,
        protocol: LocalProtocol = "auto",
    ) -> dict[str, Any]:
        """Probe metadata for one explicit target without changing server selection or settings."""
        return await self._local_connection().diagnose(
            server_id=server_id, base_url=base_url, protocol=protocol
        )

    async def corpus_snapshot(self) -> dict[str, Any]:
        """Return one JSON-ready live corpus and index snapshot."""
        snapshot = asdict(await self._corpus.snapshot())
        names = self._runtime.company_names()
        for document in snapshot["documents"]:
            document["issuer_name"] = names.get((document["registry"], document["issuer"]))
        return snapshot

    async def document_detail(self, doc_id: str) -> dict[str, Any] | None:
        """Return one bounded document preview when present."""
        detail = await self._corpus.document_detail(doc_id)
        if detail is None:
            return None
        payload = asdict(detail)
        document = payload["document"]
        document["issuer_name"] = self._runtime.company_names().get(
            (document["registry"], document["issuer"])
        )
        return payload

    async def documents(
        self,
        *,
        query: str,
        registry: str,
        issuer: str,
        fiscal_year: int | None,
        language: str,
        form: str,
        parse_status: str,
        embedding_status: DocumentEmbeddingStatus | None,
        snapshot_id: int | None,
        sort: DocumentSort,
        descending: bool,
        cursor: str | None,
        limit: int,
    ) -> DocumentInventoryResponse:
        """Return one filtered, sortable, opaque-cursor document page."""
        return await self._documents.documents(
            query=query,
            registry=registry,
            issuer=issuer,
            fiscal_year=fiscal_year,
            language=language,
            form=form,
            parse_status=parse_status,
            embedding_status=embedding_status,
            snapshot_id=snapshot_id,
            sort=sort,
            descending=descending,
            cursor=cursor,
            limit=limit,
        )

    async def document_facets(self, registry: str = "") -> DocumentFacetsResponse:
        """Return deterministic live filter values and counts."""
        return await self._documents.document_facets(registry=registry)

    async def enqueue_corpus(self, request: CorpusOperationRequest) -> dict[str, Any]:
        """Queue one validated safe corpus operation."""
        job = await self._corpus.enqueue(
            AdminCommand(
                request.kind,
                identifiers=request.identifiers,
                years=request.years,
                manifest=request.manifest,
                expected_documents=request.expected_documents,
            )
        )
        return asdict(job)

    async def corpus_jobs(self) -> dict[str, Any]:
        """Return JSON-ready corpus queue and history state."""
        return asdict(await self._corpus.jobs())

    async def retry_corpus(self, job_id: str) -> dict[str, Any]:
        """Retry one known failed corpus job."""
        return asdict(await self._corpus.retry(job_id))

    async def suites(self) -> tuple[GoldenSuiteResource, ...]:
        """Return strict golden-suite metadata and source readiness."""
        return await self._evaluations.suites()

    async def golden_canonical(self, suite_id: GoldenSuiteId) -> GoldenCanonicalResource:
        """Return validated canonical JSON without creating a draft."""
        return self._golden.canonical(suite_id)

    async def golden_revisions(self, suite_id: GoldenSuiteId) -> tuple[GoldenRevisionResource, ...]:
        """Return database-backed revisions for one golden suite."""
        return await self._golden.list(suite_id)

    async def create_golden_draft(
        self, suite_id: GoldenSuiteId, parent_id: int | None
    ) -> GoldenRevisionResource:
        """Create one editable revision from canonical or parent bytes."""
        return await self._golden.create_draft(suite_id, parent_id=parent_id)

    async def replace_golden_case(
        self,
        revision_id: int,
        case_id: str,
        *,
        expected_sha256: str,
        payload: dict[str, object],
    ) -> GoldenRevisionResource:
        """Optimistically replace one strict case in a draft."""
        return await self._golden.replace_case(
            revision_id,
            case_id,
            expected_sha256=expected_sha256,
            payload=payload,
        )

    async def validate_golden_revision(
        self, revision_id: int, expected_sha256: str
    ) -> GoldenRevisionResource:
        """Validate schema, uniqueness, and exact source spans."""
        return await self._golden.validate(revision_id, expected_sha256=expected_sha256)

    async def publish_golden_revision(
        self, revision_id: int, expected_sha256: str
    ) -> GoldenRevisionResource:
        """Publish one validated revision to canonical JSON atomically."""
        return await self._golden.publish(revision_id, expected_sha256=expected_sha256)

    async def snapshots(self) -> tuple[SnapshotResource, ...]:
        """Return all local snapshots including private experiment rows."""
        return await self._snapshots.list(public_only=False)

    async def create_snapshot(self, request: SnapshotCreateRequest) -> SnapshotResource:
        """Freeze one persisted evaluation and current corpus identity."""
        return await self._snapshots.create(
            label=request.label,
            eval_result_id=request.eval_result_id,
            golden_revision_id=request.golden_revision_id,
            public=request.public,
        )

    async def set_snapshot_visibility(
        self, snapshot_id: int, request: SnapshotVisibilityRequest
    ) -> SnapshotResource:
        """Publish or hide one ready immutable snapshot."""
        return await self._snapshots.set_public(snapshot_id, public=request.public)

    async def compare_snapshot_results(
        self, baseline_id: int, candidate_id: int
    ) -> SnapshotComparisonResponse:
        """Compare private or public local snapshots without rerunning work."""
        return await self._snapshots.compare(baseline_id, candidate_id)

    async def enqueue_evaluation(self, request: EvaluationRunRequest) -> EvaluationJobResource:
        """Queue one quick or matrix evaluation."""
        return await self._evaluations.enqueue(request)

    async def evaluation_jobs(self) -> EvaluationJobsResponse:
        """Return newest-first evaluation job state."""
        return await self._evaluations.jobs()

    @staticmethod
    def _operator_resource(job: StoredJob, queue_positions: dict[str, int]) -> OperatorJobResource:
        """Project one stored job with derived queue actions and position."""
        return OperatorJobResource(
            job_id=job.job_id,
            domain=job.domain,
            kind=job.kind,
            request=job.request_json,
            status=job.status,
            stage=job.stage,
            current=job.current,
            total=job.total,
            detail_current=job.detail_current,
            detail_total=job.detail_total,
            message=job.message,
            error_code=job.error_code,
            result_refs=job.result_refs,
            queue_position=queue_positions.get(job.job_id),
            can_cancel=(
                job.status == "queued"
                or (
                    job.status == "running"
                    and job.domain == "corpus"
                    and job.kind == "backfill_embeddings"
                )
            ),
            can_retry=job.status in {"failed", "interrupted"},
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            updated_at=job.updated_at,
        )

    async def operator_jobs(self) -> OperatorJobsResponse:
        """Return the persistent unified corpus and evaluation job board."""
        await self._corpus.jobs()
        await self._evaluations.jobs()
        rows = await self._job_store.list(limit=100)
        queued = sorted(
            (job for job in rows if job.status == "queued"), key=lambda job: job.created_at
        )
        positions = {job.job_id: index for index, job in enumerate(queued, start=1)}
        resources = tuple(self._operator_resource(job, positions) for job in rows)
        return OperatorJobsResponse(
            jobs=resources,
            active_count=sum(job.status == "running" for job in rows),
            queued_count=len(queued),
        )

    async def operator_job(self, job_id: str) -> OperatorJobResource | None:
        """Return one persisted job with its current queue position."""
        board = await self.operator_jobs()
        return next((job for job in board.jobs if job.job_id == job_id), None)

    async def retry_operator_job(self, job_id: str) -> OperatorJobResource:
        """Dispatch an explicit retry to the job's owning domain."""
        stored = await self._job_store.get(job_id)
        if stored is None:
            raise ValueError("operator job does not exist")
        if stored.domain == "corpus":
            created = await self._corpus.retry(job_id)
            new_id = created.job_id
        else:
            created = await self._evaluations.retry(job_id)
            new_id = created.job_id
        resource = await self.operator_job(new_id)
        if resource is None:
            raise RuntimeError("retried job was not persisted")
        return resource

    async def cancel_operator_job(self, job_id: str) -> OperatorJobResource:
        """Dispatch a safe cancellation to the job's owning domain."""
        stored = await self._job_store.get(job_id)
        if stored is None:
            raise ValueError("operator job does not exist")
        if stored.domain == "corpus":
            await self._corpus.cancel(job_id)
        else:
            await self._evaluations.cancel(job_id)
        resource = await self.operator_job(job_id)
        if resource is None:
            raise RuntimeError("cancelled job disappeared from persistence")
        return resource

    async def usage(self) -> UsageResponse:
        """Aggregate locally persisted provider usage without contacting OpenAI."""
        async with self._runtime.session_factory() as session:
            totals = (
                await session.execute(
                    select(
                        func.count(Run.run_id),
                        func.coalesce(func.sum(Run.total_requests), 0),
                        func.coalesce(func.sum(Run.total_input_tokens), 0),
                        func.coalesce(func.sum(Run.total_cached_input_tokens), 0),
                        func.coalesce(func.sum(Run.total_cache_write_input_tokens), 0),
                        func.coalesce(func.sum(Run.total_output_tokens), 0),
                        func.coalesce(func.sum(Run.total_reasoning_tokens), 0),
                        func.coalesce(func.sum(Run.total_estimated_cost_usd), Decimal("0")),
                        func.max(Run.created_at),
                    )
                )
            ).one()
            model_rows = (
                await session.execute(
                    select(
                        Trace.model_name,
                        func.sum(1 + Trace.retries),
                        func.sum(Trace.input_tokens),
                        func.sum(Trace.cached_input_tokens),
                        func.sum(Trace.cache_write_input_tokens),
                        func.sum(Trace.output_tokens),
                        func.sum(Trace.reasoning_tokens),
                        func.sum(Trace.estimated_cost_usd),
                    )
                    .group_by(Trace.model_name)
                    .order_by(Trace.model_name)
                )
            ).all()
        models = tuple(
            UsageModelResource(
                model_name=row[0],
                requests=int(row[1] or 0),
                input_tokens=int(row[2] or 0),
                cached_input_tokens=int(row[3] or 0),
                cache_write_input_tokens=int(row[4] or 0),
                output_tokens=int(row[5] or 0),
                reasoning_tokens=int(row[6] or 0),
                estimated_cost_usd=Decimal(row[7] or 0),
            )
            for row in model_rows
        )
        return UsageResponse(
            runs=int(totals[0] or 0),
            requests=int(totals[1] or 0),
            input_tokens=int(totals[2] or 0),
            cached_input_tokens=int(totals[3] or 0),
            cache_write_input_tokens=int(totals[4] or 0),
            output_tokens=int(totals[5] or 0),
            reasoning_tokens=int(totals[6] or 0),
            estimated_cost_usd=Decimal(totals[7] or 0),
            latest_run_at=totals[8],
            models=models,
        )

    async def evaluation_job(self, job_id: str) -> EvaluationJobResource | None:
        """Return one evaluation job when known."""
        return await self._evaluations.job(job_id)

    async def evaluation_result(self, result_id: int) -> EvaluationResultDetailResponse | None:
        """Return one persisted evaluation result detail."""
        return await self._evaluations.result_detail(result_id)

    async def compare(
        self,
        candidate_id: int,
        baseline_id: int,
    ) -> EvaluationComparisonResponse:
        """Compare two compatible persisted evaluation artifacts."""
        return await self._evaluations.compare(candidate_id, baseline_id)

    async def _retrieve_profile(
        self,
        session: AsyncSession,
        query: str,
        profile: RetrievalProfile,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        """Execute one explicit profile while retaining component provenance."""
        bm25 = profile.lexical_ranker == "bm25"
        if profile.strategy == "hybrid":
            return await retrieve(
                session,
                query,
                provider=self._runtime.embedding_provider,
                k=profile.k,
                candidate_k=profile.candidate_k,
                filters=filters,
                rrf_k=profile.rrf_k,
                reranker=CrossEncoderReranker() if profile.reranker else None,
                route_by_language=profile.route_by_language,
                lexical_ranker=profile.lexical_ranker,
                bm25_k1=profile.bm25_k1,
                bm25_b=profile.bm25_b,
                bm25_idf=profile.bm25_idf,
            )
        retriever = make_retriever(
            session,
            strategy=profile.strategy,
            provider=self._runtime.embedding_provider,
            lexical_ranker=profile.lexical_ranker,
            bm25_k1=profile.bm25_k1 if bm25 else None,
            bm25_b=profile.bm25_b if bm25 else None,
            bm25_idf=profile.bm25_idf if bm25 else None,
            candidate_k=profile.candidate_k,
            rrf_k=profile.rrf_k,
            route_by_language=profile.route_by_language,
            filters=filters,
        )
        hits = tuple(await retriever(query, profile.k))
        ids = tuple(hit.chunk_id for hit in hits)
        return RetrievalResult(
            hits=hits,
            score_stage="rrf",
            component_rankings=ComponentRankings(
                vector=ids if profile.strategy == "vector" else (),
                lexical=ids if profile.strategy == "lexical" else (),
            ),
        )

    async def retrieval_preview(
        self,
        request: RetrievalPreviewRequest,
    ) -> RetrievalPreviewResponse:
        """Return evidence and component ranks for one session-scoped profile."""
        async with self._runtime.session_factory() as session:
            result = await self._retrieve_profile(
                session,
                request.query,
                request.profile,
                request.filters,
            )
        return RetrievalPreviewResponse(
            query=request.query,
            profile=request.profile,
            score_stage=result.score_stage,
            component_rankings=result.component_rankings.model_dump(mode="python"),
            results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in result.hits),
        )

    async def review_preview(self, request: ReviewPreviewRequest) -> ReviewPreviewResponse:
        """Run an evidence-checked review through one explicit retrieval profile."""

        async def retrieval_override(
            session: AsyncSession,
            query: str,
            _k: int,
            filters: RetrievalFilters,
        ) -> RetrievalResult:
            """Ignore workflow k in favor of the profile's validated cutoff."""
            return await self._retrieve_profile(session, query, request.profile, filters)

        report = await self._runtime.review_with_retrieval(
            ReviewRequest(query=request.query, k=request.profile.k, filters=request.filters),
            retrieval_override,
        )
        return ReviewPreviewResponse(
            profile=request.profile,
            run=RunResponse.from_run_report(report),
        )
