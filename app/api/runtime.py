"""Production database composition for synchronous M5 HTTP resources."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
import json
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from openai import OpenAIError
from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import ApiServices
from app.api.errors import ApiProblemError, bad_request
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.db.bootstrap import bootstrap_schema
from app.db.models import Chunk, Document, EvalResult, Run, Trace
from app.ingestion.seed import SeedResult, persist_seed_batch, prepare_seed_batch
from app.llm.provider import LLMProvider
from app.llm.schemas import ProviderBudget
from app.observability.persistence import persist_run_report, report_to_records
from app.observability.types import RunReport, RunStatus, StepTrace, WorkflowNode
from app.retrieval.embeddings import DeterministicEmbeddingProvider, EmbeddingProvider
from app.retrieval.service import RetrievalResult, retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.workflow.runner import NodeObserver, run_workflow
from app.workflow.types import WorkflowRequest

type ParseStatus = Literal["parsed", "needs_profile_update"]

_PARSE_STATUS = TypeAdapter(ParseStatus)
_RUN_STATUS = TypeAdapter(RunStatus)
_WORKFLOW_NODE = TypeAdapter(WorkflowNode)


def _default_session_factory() -> AsyncSession:
    """Create a session lazily so importing the API does not build an engine."""
    from app.db.session import Session

    return Session()


def _default_database_engine() -> AsyncEngine:
    """Resolve the process engine only for an operation that requires schema access."""
    from app.db.session import engine

    return engine


class SessionFactory(Protocol):
    """Build one caller-owned async session context."""

    def __call__(self) -> AsyncSession:
        """Return one caller-owned async session."""
        ...


class RetrievalService(Protocol):
    """M2 retrieval call shape used by both retrieve and review resources."""

    def __call__(
        self,
        session: AsyncSession,
        query: str,
        *,
        provider: EmbeddingProvider | None,
        k: int,
        filters: RetrievalFilters,
    ) -> Awaitable[RetrievalResult]:
        """Return one asynchronous retrieval result."""
        ...


class WorkflowService(Protocol):
    """M4 workflow call shape used by the review resource."""

    def __call__(
        self,
        request: WorkflowRequest,
        *,
        retriever: Callable[
            [str, int, RetrievalFilters],
            Awaitable[RetrievalResult | Sequence[ChunkHit]],
        ],
        provider: LLMProvider,
        on_node: NodeObserver | None = None,
    ) -> Awaitable[RunReport]:
        """Return one asynchronous guarded workflow report."""
        ...


class RunPersister(Protocol):
    """M4 persistence call shape used after a workflow completes."""

    def __call__(
        self,
        session: AsyncSession,
        report: RunReport,
        *,
        secret_values: Iterable[str],
    ) -> Awaitable[Run]:
        """Persist one report within the caller-owned transaction."""
        ...


def _unavailable(code: str, message: str) -> ApiProblemError:
    """Build the typed 503 an unconfigured dependency answers with."""
    return ApiProblemError(status_code=503, code=code, message=message)


def _document_resource(document: Document, chunk_count: int) -> DocumentResource:
    """Project one stored document and its chunk count onto the resource."""
    return DocumentResource(
        doc_id=document.doc_id,
        registry=document.registry,
        issuer=document.issuer,
        issuer_id=document.issuer_id,
        fiscal_year=document.fiscal_year,
        form=document.form,
        filing_date=document.filing_date,
        report_period=document.report_period,
        filing_id=document.filing_id,
        source_url=document.source_url,
        parse_status=_PARSE_STATUS.validate_python(document.parse_status, strict=True),
        source_length=document.source_length,
        source_sha256=document.source_sha256,
        chunk_count=chunk_count,
    )


def _step_trace(trace: Trace) -> StepTrace:
    """Rebuild one stored trace row as the strict step it was recorded from."""
    return StepTrace(
        step=trace.step,
        node=_WORKFLOW_NODE.validate_python(trace.node, strict=True),
        model_name=trace.model_name,
        api_url=trace.api_url,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        request_time_ms=trace.request_time_ms,
        llm_output=trace.llm_output,
        retries=trace.retries,
        error=trace.error,
    )


def _run_report(run: Run, traces: Sequence[Trace]) -> RunReport:
    """Rebuild one stored run and its traces as the report the API returns."""
    return RunReport(
        run_id=run.run_id,
        status=_RUN_STATUS.validate_python(run.status, strict=True),
        iterations=run.iterations,
        total_requests=run.total_requests,
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
        total_time_seconds=run.total_time_seconds,
        system_prompt=run.system_prompt,
        node_path=tuple(
            _WORKFLOW_NODE.validate_python(node, strict=True) for node in run.node_path
        ),
        report=run.report,
        steps=tuple(_step_trace(trace) for trace in traces),
    )


class RuntimeApiServices(ApiServices):
    """Compose API resources over one session per synchronous request.

    Retrieval defaults to the deterministic provider unless one is injected. Review is
    fail-closed until an LLM provider and its explicit budget are injected; construction
    never creates the process database engine or starts a paid call.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = _default_session_factory,
        database_engine: AsyncEngine | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        llm_provider: LLMProvider | None = None,
        provider_budget: ProviderBudget | None = None,
        retrieval_service: RetrievalService = retrieve,
        workflow_service: WorkflowService = run_workflow,
        run_persister: RunPersister = persist_run_report,
        run_id_factory: Callable[[], str] | None = None,
        secret_values: Iterable[str] = (),
    ) -> None:
        if (llm_provider is None) != (provider_budget is None):
            raise ValueError("llm_provider and provider_budget must be configured together")
        self._session_factory = session_factory
        self._database_engine = database_engine
        self._embedding_provider = (
            DeterministicEmbeddingProvider() if embedding_provider is None else embedding_provider
        )
        self._llm_provider = llm_provider
        self._provider_budget = provider_budget
        self._retrieval_service = retrieval_service
        self._workflow_service = workflow_service
        self._run_persister = run_persister
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")
        self._secret_values = tuple(secret_values)

    async def _retrieve_with_session(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        """Retrieve against an open session, so caller and workflow share one."""
        return await self._retrieval_service(
            session,
            query,
            provider=self._embedding_provider,
            k=k,
            filters=filters,
        )

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
        """Call retrieval through one request-owned database session.

        Parameters
        ----------
        request : RetrieveRequest
            Validated query, result limit, and filters.

        Returns
        -------
        RetrievalResult
            Ranked source-cited evidence.

        Raises
        ------
        ApiProblemError
            If the embedding provider or database is unavailable.
        """
        try:
            async with self._session_factory() as session:
                return await self._retrieve_with_session(
                    session,
                    request.query,
                    request.k,
                    request.filters,
                )
        except OpenAIError as error:
            raise _unavailable(
                "provider_unavailable",
                f"Embedding provider is unavailable ({type(error).__name__}).",
            ) from error
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return filing resources with deterministic chunk counts.

        Returns
        -------
        Sequence[DocumentResource]
            Documents ordered by issuer, fiscal year, and document id.

        Raises
        ------
        ApiProblemError
            If the database query fails.
        """
        statement = (
            select(Document, func.count(Chunk.id).label("chunk_count"))
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .group_by(Document.doc_id)
            .order_by(Document.issuer, Document.fiscal_year, Document.doc_id)
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).all()
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(_document_resource(document, count) for document, count in rows)

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Prepare a local manifest off-loop and atomically persist it.

        Parameters
        ----------
        request : IngestRequest
            Explicit server-local manifest and bounded batch settings.

        Returns
        -------
        SeedResult
            Committed document and chunk counts.

        Raises
        ------
        ApiProblemError
            If the manifest is invalid or the database is unavailable.

        Notes
        -----
        CPU and file parsing run in a worker thread; the M1 persister retains
        transaction ownership.
        """
        path = Path(request.manifest_path)
        if not path.is_file():
            raise bad_request("manifest_not_found", f"Manifest file was not found: {path}")
        try:
            batch = await asyncio.to_thread(
                prepare_seed_batch,
                path,
                expected_documents=request.expected_documents,
            )
        except json.JSONDecodeError as error:
            raise bad_request(
                "invalid_manifest_json",
                f"Manifest is not valid JSON at line {error.lineno} column {error.colno}.",
            ) from error
        except UnicodeDecodeError as error:
            raise bad_request(
                "invalid_manifest_encoding",
                "Manifest must be UTF-8 text.",
            ) from error
        except FileNotFoundError as error:
            raise bad_request(
                "corpus_file_not_found",
                f"Corpus file was not found: {error.filename}",
            ) from error
        except ValueError as error:
            raise bad_request("invalid_manifest", str(error)) from error

        try:
            database_engine = (
                self._database_engine
                if self._database_engine is not None
                else _default_database_engine()
            )
            await bootstrap_schema(database_engine)
            async with self._session_factory() as session:
                return await persist_seed_batch(
                    session,
                    batch,
                    chunk_batch_size=request.chunk_batch_size,
                )
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def review(self, request: ReviewRequest) -> RunReport:
        """Run, redact, persist, and return one terminal workflow report."""
        return await self._review(request, on_node=None)

    async def review_stream(
        self,
        request: ReviewRequest,
        on_node: NodeObserver,
    ) -> RunReport:
        """Run one review while reporting each committed node transition."""
        return await self._review(request, on_node=on_node)

    async def _review(
        self,
        request: ReviewRequest,
        *,
        on_node: NodeObserver | None,
    ) -> RunReport:
        """Compose retrieval, provider work, redaction, and persistence.

        Parameters
        ----------
        request : ReviewRequest
            Validated public review request.
        on_node : NodeObserver | None
            Optional streaming observer.

        Returns
        -------
        RunReport
            Secret-safe terminal report identical to the persisted representation.

        Raises
        ------
        ApiProblemError
            If required provider configuration or an external dependency is unavailable.

        Notes
        -----
        Retrieval transactions end before provider work, and persistence starts a new
        short transaction after the report has been sanitized.
        """
        if self._llm_provider is None or self._provider_budget is None:
            raise _unavailable(
                "provider_unavailable",
                "Review requires an explicitly configured LLM provider and budget.",
            )
        workflow_request = WorkflowRequest(
            run_id=self._run_id_factory(),
            query=request.query,
            k=request.k,
            filters=request.filters,
            budget=request.budget,
            provider_budget=self._provider_budget,
            max_context_chars=request.max_context_chars,
        )
        try:
            async with self._session_factory() as session:

                async def retrieve_for_workflow(
                    query: str,
                    k: int,
                    filters: RetrievalFilters,
                ) -> RetrievalResult:
                    """Retrieve on the session this run already holds."""
                    result = await self._retrieve_with_session(session, query, k, filters)
                    if session.in_transaction():
                        await session.rollback()
                    return result

                report = await self._workflow_service(
                    workflow_request,
                    retriever=retrieve_for_workflow,
                    provider=self._llm_provider,
                    on_node=on_node,
                )
                safe_run, safe_traces = report_to_records(
                    report,
                    secret_values=self._secret_values,
                )
                safe_report = _run_report(safe_run, safe_traces)
                if session.in_transaction():
                    await session.rollback()
                async with session.begin():
                    await self._run_persister(
                        session,
                        safe_report,
                        secret_values=self._secret_values,
                    )
                return safe_report
        except OpenAIError as error:
            raise _unavailable(
                "provider_unavailable",
                f"LLM provider is unavailable ({type(error).__name__}).",
            ) from error
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def _trace_rows(self, session: AsyncSession, run_id: str) -> tuple[Trace, ...]:
        """Read this run's traces in recorded step order."""
        rows = await session.scalars(
            select(Trace).where(Trace.run_id == run_id).order_by(Trace.step)
        )
        return tuple(rows)

    async def get_run(self, run_id: str) -> RunReport | None:
        """Load one run and ordered traces without executing workflow code."""
        try:
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return _run_report(run, traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Load ordered traces only when their parent run exists."""
        try:
            async with self._session_factory() as session:
                if await session.get(Run, run_id) is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return tuple(_step_trace(trace) for trace in traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Load newest evaluation records through their strict public schema."""
        statement = select(EvalResult).order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        try:
            async with self._session_factory() as session:
                rows = tuple(await session.scalars(statement.limit(limit)))
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(
            EvalResultResource(
                result_id=row.id,
                suite=row.suite,
                config=row.config,
                metrics={name: float(value) for name, value in row.metrics.items()},
                raw_artifact_path=row.raw_artifact_path,
                created_at=row.created_at,
            )
            for row in rows
        )
