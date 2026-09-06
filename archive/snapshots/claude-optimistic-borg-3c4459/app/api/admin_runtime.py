"""Local-only composition for corpus, evaluation, and profile-preview resources."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.api.admin_schemas import (
    AdminDocumentResource,
    CorpusOperationRequest,
    DocumentEmbeddingStatus,
    DocumentFacetsResponse,
    DocumentFacetValue,
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
    Chunk,
    Document,
    EvaluationSnapshot,
    Run,
    SnapshotDocument,
    Trace,
)
from app.evals.admin import EvaluationAdminService
from app.evals.arms import make_retriever
from app.evals.golden_admin import GoldenAdminService
from app.evals.snapshots import SnapshotService
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

    async def corpus_snapshot(self) -> dict[str, Any]:
        """Return one JSON-ready live corpus and index snapshot."""
        return asdict(await self._corpus.snapshot())

    async def document_detail(self, doc_id: str) -> dict[str, Any] | None:
        """Return one bounded document preview when present."""
        detail = await self._corpus.document_detail(doc_id)
        return asdict(detail) if detail is not None else None

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
        filters = []
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(Document.doc_id.ilike(pattern) | Document.issuer.ilike(pattern))
        for column, value in (
            (Document.registry, registry),
            (Document.issuer, issuer),
            (Document.language, language),
            (Document.form, form),
            (Document.parse_status, parse_status),
        ):
            if value:
                filters.append(column == value)
        if fiscal_year is not None:
            filters.append(Document.fiscal_year == fiscal_year)
        if snapshot_id is not None:
            filters.append(
                select(SnapshotDocument.doc_id)
                .where(
                    SnapshotDocument.snapshot_id == snapshot_id,
                    SnapshotDocument.doc_id == Document.doc_id,
                    SnapshotDocument.source_sha256 == Document.source_sha256,
                )
                .exists()
            )
        offset = 0
        if cursor:
            try:
                offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
            except (ValueError, UnicodeDecodeError) as error:
                raise ValueError("document cursor is invalid") from error
        chunk_count = func.count(Chunk.id).label("chunk_count")
        embedded = func.count(Chunk.id).filter(Chunk.embedding.is_not(None)).label("embedded")
        text_chunks = func.count(Chunk.id).filter(Chunk.kind == "text").label("text_chunks")
        table_chunks = func.count(Chunk.id).filter(Chunk.kind == "table").label("table_chunks")
        snapshot_count = (
            select(func.count())
            .select_from(SnapshotDocument)
            .where(
                SnapshotDocument.doc_id == Document.doc_id,
                SnapshotDocument.source_sha256 == Document.source_sha256,
            )
            .correlate(Document)
            .scalar_subquery()
            .label("snapshot_count")
        )
        coverage = (cast(embedded, Float) / func.nullif(cast(chunk_count, Float), 0.0)).label(
            "embedding_coverage"
        )
        having = []
        if embedding_status == "complete":
            having.extend((chunk_count > 0, embedded == chunk_count))
        elif embedding_status == "partial":
            having.extend((embedded > 0, embedded < chunk_count))
        elif embedding_status == "missing":
            having.append(embedded == 0)
        sort_columns = {
            "doc_id": Document.doc_id,
            "issuer": Document.issuer,
            "fiscal_year": Document.fiscal_year,
            "filing_date": Document.filing_date,
            "chunk_count": chunk_count,
            "embedding_coverage": coverage,
        }
        order = sort_columns[sort].desc() if descending else sort_columns[sort].asc()
        statement = (
            select(
                Document,
                chunk_count,
                embedded,
                text_chunks,
                table_chunks,
                snapshot_count,
            )
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .where(*filters)
            .group_by(Document.doc_id)
            .having(*having)
            .order_by(order, Document.doc_id)
            .offset(offset)
            .limit(limit)
        )
        filtered_documents = (
            select(Document.doc_id)
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .where(*filters)
            .group_by(Document.doc_id)
            .having(*having)
            .subquery()
        )
        count_statement = select(func.count()).select_from(filtered_documents)
        async with self._runtime.session_factory() as session:
            total = int(await session.scalar(count_statement) or 0)
            rows = (await session.execute(statement)).all()
        documents = tuple(
            AdminDocumentResource(
                doc_id=document.doc_id,
                registry=document.registry,
                language=document.language,
                issuer=document.issuer,
                issuer_id=document.issuer_id,
                fiscal_year=document.fiscal_year,
                form=document.form,
                filing_date=document.filing_date,
                report_period=document.report_period,
                filing_id=document.filing_id,
                source_url=document.source_url,
                parse_status=document.parse_status,
                source_length=document.source_length,
                source_sha256=document.source_sha256,
                chunk_count=int(chunks),
                embedded_chunks=int(embedded_count),
                text_chunks=int(text_count),
                table_chunks=int(table_count),
                embedding_status=(
                    "complete"
                    if int(chunks) > 0 and int(embedded_count) == int(chunks)
                    else "partial"
                    if int(embedded_count) > 0
                    else "missing"
                ),
                snapshot_count=int(membership_count),
            )
            for (
                document,
                chunks,
                embedded_count,
                text_count,
                table_count,
                membership_count,
            ) in rows
        )
        next_offset = offset + len(documents)
        next_cursor = (
            base64.urlsafe_b64encode(str(next_offset).encode()).decode()
            if next_offset < total
            else None
        )
        return DocumentInventoryResponse(documents=documents, total=total, next_cursor=next_cursor)

    async def document_facets(self) -> DocumentFacetsResponse:
        """Return deterministic live filter values and counts."""

        async def values(
            column: InstrumentedAttribute[str | int],
        ) -> tuple[DocumentFacetValue, ...]:
            """Aggregate one safe ORM column into sorted facet values."""
            async with self._runtime.session_factory() as session:
                rows = (
                    await session.execute(
                        select(column, func.count()).group_by(column).order_by(column)
                    )
                ).all()
            return tuple(
                DocumentFacetValue(value=str(value), count=int(count)) for value, count in rows
            )

        chunk_count = func.count(Chunk.id).label("chunk_count")
        embedded = func.count(Chunk.id).filter(Chunk.embedding.is_not(None)).label("embedded")
        async with self._runtime.session_factory() as session:
            coverage_rows = (
                await session.execute(
                    select(Document.doc_id, chunk_count, embedded)
                    .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
                    .group_by(Document.doc_id)
                )
            ).all()
            snapshot_rows = (
                await session.execute(
                    select(
                        EvaluationSnapshot.id,
                        EvaluationSnapshot.label,
                        EvaluationSnapshot.status,
                        func.count(SnapshotDocument.doc_id),
                    )
                    .outerjoin(
                        SnapshotDocument,
                        SnapshotDocument.snapshot_id == EvaluationSnapshot.id,
                    )
                    .group_by(EvaluationSnapshot.id)
                    .order_by(EvaluationSnapshot.created_at.desc(), EvaluationSnapshot.id.desc())
                )
            ).all()
        status_counts = {"complete": 0, "partial": 0, "missing": 0}
        for _doc_id, chunks, embedded_count in coverage_rows:
            status = (
                "complete"
                if int(chunks) > 0 and int(embedded_count) == int(chunks)
                else "partial"
                if int(embedded_count) > 0
                else "missing"
            )
            status_counts[status] += 1
        return DocumentFacetsResponse(
            registries=await values(Document.registry),
            issuers=await values(Document.issuer),
            years=await values(Document.fiscal_year),
            languages=await values(Document.language),
            forms=await values(Document.form),
            parse_statuses=await values(Document.parse_status),
            embedding_statuses=tuple(
                DocumentFacetValue(value=status, count=count)
                for status, count in status_counts.items()
                if count > 0
            ),
            snapshots=tuple(
                DocumentFacetValue(
                    value=str(snapshot_id),
                    count=int(count),
                    label=f"{label} · {status}",
                )
                for snapshot_id, label, status, count in snapshot_rows
                if int(count) > 0
            ),
        )

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
