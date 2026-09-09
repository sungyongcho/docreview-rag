"""Local-only composition for corpus, evaluation, and profile-preview resources."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    CorpusOperationRequest,
    CorpusSnapshotResource,
    DocumentEmbeddingStatus,
    DocumentFacetsResponse,
    DocumentInventoryResponse,
    DocumentSort,
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationPreparationResource,
    EvaluationResultDetailResponse,
    EvaluationResultSummaryResource,
    EvaluationRunRequest,
    GoldenCanonicalResource,
    GoldenEvidenceChunk,
    GoldenEvidencePage,
    GoldenRevisionResource,
    GoldenSuiteId,
    GoldenSuiteResource,
    JobHistoryRequest,
    JobHistoryResultResource,
    JobHistorySummaryResource,
    OperatorJobResource,
    OperatorJobsResponse,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    RetrievalProfile,
    ReviewPreviewRequest,
    ReviewPreviewResponse,
    SnapshotCreateRequest,
    SnapshotVisibilityRequest,
    SourceDeletionPreviewResource,
    SourceDeletionRequest,
    UsageModelResource,
    UsageProviderResource,
    UsageResponse,
)
from app.api.document_catalog import DocumentCatalog
from app.api.errors import ApiProblemError, unavailable
from app.api.review_profile import ReviewSessionProfile
from app.api.runtime import RuntimeApiServices
from app.api.schemas import (
    EvidenceHit,
    ReviewRequest,
    RunResponse,
    SnapshotComparisonResponse,
    SnapshotResource,
)
from app.api.search_consistency import prepare_search
from app.config import get_settings
from app.corpus_admin import AdminCommand, CorpusStatus, RuntimeCorpusAdminService
from app.db.models import (
    Chunk,
    Document,
    EvalResult,
    OperatorJob,
    Run,
    Trace,
)
from app.evals.admin import (
    EvaluationAdminService,
    EvaluationAlreadyQueuedError,
    EvaluationNotReadyError,
)
from app.evals.arms import make_retriever
from app.evals.golden_admin import GoldenAdminService
from app.evals.snapshots import SnapshotService
from app.llm.local_connection import LocalConnectionError, LocalConnectionManager, LocalProtocol
from app.llm.openai_limits import CEILING_ENV_KEYS, OpenAILimitsError, OpenAILimitsManager
from app.observability.usage import USAGE_KEY, merge_usage, review_usage
from app.operator.job_history import JobHistoryService
from app.operator.jobs import JobExecutionCoordinator, JobStore, StoredJob
from app.operator.progress import progress_fields
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.service import ComponentRankings, RetrievalResult, retrieve
from app.retrieval.types import RetrievalFilters

#: Seconds a readiness status reading may be reused between ``/ready`` calls.
READINESS_STATUS_MAX_AGE_S = 2.0
#: The same bound while a corpus or evaluation job holds or awaits the execution turn.
READINESS_STATUS_MAX_AGE_BUSY_S = 10.0


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
            runtime.session_factory,
            public_only=False,
            company_names=runtime.company_names,
            embedding_identity=runtime.embedding_provider.identity,
        )
        self._job_store = job_store or JobStore(session_factory=runtime.session_factory)
        self._job_history = JobHistoryService(
            runtime.session_factory, get_settings().corpus_dir.parent / "job-history-backups"
        )
        execution_lock = asyncio.Lock()
        execution_coordinator = JobExecutionCoordinator()
        self._execution_coordinator = execution_coordinator
        self._corpus = corpus or RuntimeCorpusAdminService(
            session_factory=runtime.session_factory,
            job_store=self._job_store,
            corpus_access=runtime.corpus_access,
            execution_lock=execution_lock,
            execution_coordinator=execution_coordinator,
        )
        self._corpus.corpus_access = runtime.corpus_access
        self._evaluations = evaluations or EvaluationAdminService(
            corpus_status=self._corpus.status,
            session_factory=runtime.session_factory,
            job_store=self._job_store,
            execution_lock=execution_lock,
            execution_coordinator=execution_coordinator,
        )
        self._golden = golden or GoldenAdminService()
        self._snapshots = snapshots or SnapshotService()

    async def readiness_status(self) -> CorpusStatus:
        """Return corpus status for ``/ready``, reusing a recent reading longer while a job runs.

        A queued or running corpus or evaluation job already loads the database and the
        invalidation trigger keeps ``bm25_ready`` false until it finishes, so re-measuring
        every poll would only add catalog sweeps to the contention it reports.
        """
        max_age = (
            READINESS_STATUS_MAX_AGE_BUSY_S
            if self._execution_coordinator.busy
            else READINESS_STATUS_MAX_AGE_S
        )
        return await self._corpus.status(max_age_s=max_age)

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

    def _openai_limits(self) -> OpenAILimitsManager:
        """Require the Dev-only per-call cap manager; production keeps the ceiling."""
        limits = self._runtime.openai_limits
        if limits is None or not limits.enabled:
            raise ApiProblemError(
                status_code=403,
                code="disabled_in_prod",
                message="OpenAI per-call caps are adjustable only in Dev.",
            )
        return limits

    def _openai_limits_payload(self, limits: OpenAILimitsManager) -> dict[str, Any]:
        """Add the environment keys and file path the web tells the user about."""
        return {
            **limits.state().model_dump(),
            "ceiling_env_keys": dict(CEILING_ENV_KEYS),
            "file_path": str(limits.path),
        }

    def openai_limits_state(self) -> dict[str, Any]:
        """Read effective and ceiling per-call caps without changing them."""
        return self._openai_limits_payload(self._openai_limits())

    async def update_openai_limits(
        self, *, max_input_tokens: int, max_output_tokens: int, max_cost_usd: Decimal
    ) -> dict[str, Any]:
        """Persist working caps below the ceiling and translate safe failures."""
        limits = self._openai_limits()
        try:
            await limits.save(
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
                max_cost_usd=max_cost_usd,
            )
        except OpenAILimitsError as error:
            if error.code in {"openai_limits_above_ceiling", "openai_limits_invalid"}:
                raise ApiProblemError(
                    status_code=422, code=error.code, message=str(error)
                ) from error
            raise unavailable(error.code, str(error)) from error
        return self._openai_limits_payload(limits)

    async def reset_openai_limits(self) -> dict[str, Any]:
        """Delete the saved caps so the ceiling applies again."""
        limits = self._openai_limits()
        try:
            await limits.reset()
        except OpenAILimitsError as error:
            raise unavailable(error.code, str(error)) from error
        return self._openai_limits_payload(limits)

    async def prepare_local_model(self, model: str) -> dict[str, Any]:
        """Prepare the selected server's installed model under the developer-only guard."""
        try:
            return await self._local_connection().prepare_model(model)
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

    async def corpus_snapshot(self) -> CorpusSnapshotResource:
        """Return one JSON-ready live corpus and index snapshot."""
        snapshot = asdict(await self._corpus.snapshot())
        names = self._runtime.company_names()
        for document in snapshot["documents"]:
            document["issuer_name"] = names.get((document["registry"], document["issuer"]))
        return CorpusSnapshotResource.model_validate(snapshot)

    async def document_detail(self, doc_id: str) -> dict[str, Any] | None:
        """Return one bounded document preview when present."""
        await self._documents.ensure_ready()
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

    async def golden_evidence_chunks(
        self, doc_id: str, query: str, after: int, limit: int
    ) -> GoldenEvidencePage:
        """Page current chunks deterministically using their exact stored source spans."""
        statement = (
            select(Chunk)
            .join(Document, Document.doc_id == Chunk.doc_id)
            .where(
                Chunk.doc_id == doc_id,
                Chunk.id > after,
            )
        )
        if query:
            statement = statement.where(Chunk.body.icontains(query, autoescape=True))
        async with self._runtime.session_factory() as session:
            rows = tuple(await session.scalars(statement.order_by(Chunk.id).limit(limit + 1)))
        return GoldenEvidencePage(
            chunks=tuple(
                GoldenEvidenceChunk(
                    chunk_id=row.id,
                    doc_id=row.doc_id,
                    source_sha256=row.source_sha256,
                    start_char=row.start_char,
                    end_char=row.end_char,
                    item=row.item,
                    kind=row.kind,
                    body=row.body,
                    citation=row.citation,
                )
                for row in rows[:limit]
            ),
            next_after=rows[limit - 1].id if len(rows) > limit else None,
        )

    async def document_facets(self, registry: str = "") -> DocumentFacetsResponse:
        """Return deterministic live filter values and counts."""
        return await self._documents.document_facets(registry=registry)

    async def source_deletion_preview(
        self, request: SourceDeletionRequest
    ) -> SourceDeletionPreviewResource:
        """Return the read-only source plan used by the confirmation dialog."""
        preview = await self._corpus.preview_source_deletion(request.document_ids)
        # The plan keeps JSON lists for its fingerprint; the strict resource wants tuples.
        return SourceDeletionPreviewResource.model_validate(
            {
                **preview,
                "documents": tuple(preview["documents"]),
                "files": tuple(preview["files"]),
            }
        )

    async def enqueue_corpus(self, request: CorpusOperationRequest) -> dict[str, Any]:
        """Queue one validated safe corpus operation."""
        job = await self._corpus.enqueue(
            AdminCommand(
                request.kind,
                document_ids=request.document_ids,
                deletion_token=request.deletion_token,
                confirm_delete=request.confirm_delete,
                identifiers=request.identifiers,
                years=request.years,
                manifest=request.manifest,
                selection_id=request.selection_id,
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
        self, suite_id: GoldenSuiteId, parent_id: int | None, filename: str, empty: bool = False
    ) -> GoldenRevisionResource:
        """Create one editable revision from canonical or parent bytes."""
        return await self._golden.create_draft(
            suite_id, parent_id=parent_id, filename=filename, empty=empty
        )

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

    async def delete_golden_case(
        self, revision_id: int, case_id: str, *, expected_sha256: str
    ) -> GoldenRevisionResource:
        """Remove one question from a draft under the optimistic digest check."""
        return await self._golden.delete_case(revision_id, case_id, expected_sha256=expected_sha256)

    async def validate_golden_revision(
        self, revision_id: int, expected_sha256: str
    ) -> GoldenRevisionResource:
        """Validate schema, uniqueness, and exact source spans."""
        return await self._golden.validate(revision_id, expected_sha256=expected_sha256)

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

    async def evaluation_preparation(
        self, request: EvaluationRunRequest
    ) -> EvaluationPreparationResource:
        """Expose the same readiness gate used by evaluation submission."""
        return await self._evaluations.preparation(request)

    async def enqueue_evaluation(self, request: EvaluationRunRequest) -> EvaluationJobResource:
        """Queue one quick or matrix evaluation."""
        try:
            return await self._evaluations.enqueue(request)
        except EvaluationNotReadyError as error:
            raise ApiProblemError(
                status_code=409,
                code="evaluation_not_ready",
                message=str(error),
                detail=error.preparation.state,
            ) from error
        except EvaluationAlreadyQueuedError as error:
            raise ApiProblemError(
                status_code=409,
                code="evaluation_already_queued",
                message=str(error),
            ) from error

    async def evaluation_jobs(self) -> EvaluationJobsResponse:
        """Return newest-first evaluation job state."""
        board = await self._evaluations.jobs()
        ids = {result_id for job in board.jobs for result_id in job.result_ids}
        if not ids:
            return board
        async with self._runtime.session_factory() as session:
            rows = tuple(await session.scalars(select(EvalResult).where(EvalResult.id.in_(ids))))
        summaries = {
            row.id: EvaluationResultSummaryResource(
                result_id=row.id, created_at=row.created_at, config=row.config
            )
            for row in rows
        }
        return board.model_copy(
            update={
                "jobs": tuple(
                    job.model_copy(
                        update={
                            "result_summaries": tuple(
                                summaries[result_id]
                                for result_id in job.result_ids
                                if result_id in summaries
                            )
                        }
                    )
                    for job in board.jobs
                )
            }
        )

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
            **progress_fields(job.result_refs),
            queue_position=queue_positions.get(job.job_id),
            can_cancel=(
                job.status == "queued"
                or (
                    job.status == "running"
                    and job.domain == "corpus"
                    and job.kind == "backfill_embeddings"
                )
            ),
            can_retry=(
                job.kind != "delete_sources"
                and job.status in {"failed", "interrupted"}
                and job.kind != "embedding_usage"
                and not (
                    job.domain == "corpus"
                    and job.kind == "ingest_manifest"
                    and not (
                        job.request_json.get("manifest") and job.request_json.get("selection_id")
                    )
                )
            ),
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            updated_at=job.updated_at,
        )

    async def job_history_summary(self) -> JobHistorySummaryResource:
        """Read history counts without changing records or running jobs."""
        return JobHistorySummaryResource(**asdict(await self._job_history.summary()))

    async def manage_job_history(self, request: JobHistoryRequest) -> JobHistoryResultResource:
        """Archive, restore or back up and delete only reviewed terminal history."""
        result = await self._job_history.apply(
            request.action, request.expected_count, request.confirmation
        )
        if result.action == "delete":
            self._corpus.forget_history(result.changed_ids)
            self._evaluations.forget_history(result.changed_ids)
        return JobHistoryResultResource(
            action=result.action,
            changed_count=len(result.changed_ids),
            backup_id=result.backup_id,
            summary=await self.job_history_summary(),
        )

    def job_history_backup(self, backup_id: str) -> Path:
        """Resolve only an owned private backup for an authenticated download."""
        return self._job_history.backup_path(backup_id)

    async def operator_jobs(self) -> OperatorJobsResponse:
        """Return the persistent unified corpus and evaluation job board."""
        await self._corpus.recover_jobs()
        await self._evaluations.recover_jobs()
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
        """Aggregate review and embedding evidence without provider calls or schema migration."""
        async with self._runtime.session_factory() as session:
            runs = (
                await session.execute(
                    select(
                        Run.run_id,
                        Run.created_at,
                        Run.request_context["model_calls"].label("model_calls"),
                        Run.request_context["provider_identity"].label("provider_identity"),
                        Run.request_context["trace_requests"].label("trace_requests"),
                    )
                )
            ).all()
            traces = (
                await session.execute(
                    select(
                        Trace.run_id,
                        Trace.step,
                        Trace.node,
                        Trace.model_name,
                        Trace.api_url,
                        Trace.retries,
                        Trace.input_tokens,
                        Trace.cached_input_tokens,
                        Trace.cache_write_input_tokens,
                        Trace.output_tokens,
                        Trace.reasoning_tokens,
                        Trace.estimated_cost_usd,
                    ).order_by(Trace.run_id, Trace.step)
                )
            ).all()
            ledgers = (
                (
                    await session.execute(
                        select(OperatorJob.result_refs[USAGE_KEY]).where(
                            OperatorJob.result_refs.op("?")(USAGE_KEY)
                        )
                    )
                )
                .scalars()
                .all()
            )
        by_run = {}
        for trace in traces:
            by_run.setdefault(trace.run_id, []).append(trace)
        records = []
        for run in runs:
            records.extend(
                review_usage(
                    {
                        "model_calls": run.model_calls,
                        "provider_identity": run.provider_identity,
                        "trace_requests": run.trace_requests,
                    },
                    by_run.get(run.run_id, []),
                )
            )
        for ledger in ledgers:
            if not isinstance(ledger, list) or any(not isinstance(row, dict) for row in ledger):
                raise ValueError("Persisted embedding usage ledger is invalid")
            records.extend(ledger)
        models = tuple(
            UsageModelResource.model_validate(
                {**row, "estimated_cost_usd": Decimal(str(row["estimated_cost_usd"]))}
            )
            for row in merge_usage(records)
        )
        grouped = {}
        for model in models:
            grouped.setdefault((model.provider, model.local, model.credential_slot), []).append(
                model
            )

        def totals(
            rows: list[UsageModelResource] | tuple[UsageModelResource, ...],
        ) -> dict[str, object]:
            """Compute all header and group totals from the same displayed model-role rows."""
            counts = {
                field: sum(getattr(row, field) for row in rows)
                for field in (
                    "requests",
                    "input_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                    "estimated_input_tokens",
                    "unreported_input_requests",
                    "unreported_cost_requests",
                )
            }
            return {
                **counts,
                "estimated_cost_usd": sum((row.estimated_cost_usd for row in rows), Decimal(0)),
            }

        providers = tuple(
            UsageProviderResource.model_validate(
                {
                    "provider": key[0],
                    "local": key[1],
                    "credential_slot": key[2],
                    "models": tuple(rows),
                    **totals(rows),
                }
            )
            for key, rows in grouped.items()
        )
        return UsageResponse.model_validate(
            {
                "runs": len(runs),
                "latest_run_at": max((run.created_at for run in runs), default=None),
                "models": models,
                "providers": providers,
                **totals(models),
            }
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
        await prepare_search(
            session,
            self._runtime.embedding_provider,
            profile.strategy,
            profile.lexical_ranker or "ts_rank_cd",
            filters,
        )
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
                lexical_ranker=profile.lexical_ranker or "ts_rank_cd",
                bm25_k1=profile.bm25_k1,
                bm25_b=profile.bm25_b,
                bm25_idf=profile.bm25_idf,
            )
        retriever = make_retriever(
            session,
            strategy=profile.strategy,
            provider=self._runtime.embedding_provider,
            lexical_ranker=profile.lexical_ranker or "ts_rank_cd",
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
            candidates=hits,
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
        async with self._runtime.search_access(), self._runtime.session_factory() as session:
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
            ReviewRequest(
                query=request.query,
                session_profile=ReviewSessionProfile.model_validate(
                    {
                        "retrieval_preset": "custom",
                        "custom_retrieval": request.profile.model_dump(),
                        "doc_ids": request.filters.doc_ids,
                        "registries": request.filters.registries,
                        "kinds": request.filters.kinds,
                        "languages": request.filters.languages,
                        "issuers": request.filters.issuers,
                        "fiscal_years": request.filters.fiscal_years,
                        "forms": request.filters.forms,
                        "sections": request.filters.items,
                        "snapshot_id": request.filters.snapshot_id,
                    }
                ),
            ),
            retrieval_override,
        )
        return ReviewPreviewResponse(
            profile=request.profile,
            run=RunResponse.from_run_report(report),
        )
