"""Production database composition for synchronous M5 HTTP resources."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import ApiServices
from app.api.errors import bad_request, translate_runtime_errors, unavailable
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.config import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_IDF,
    DEFAULT_BM25_K1,
    BM25Idf,
    LexicalRanker,
    Settings,
    get_settings,
)
from app.db.bootstrap import bootstrap_schema
from app.db.models import Chunk, Document, EvalResult, Run, Trace
from app.ingestion.seed import (
    ManifestError,
    SeedResult,
    load_seed_batch,
    persist_seed_batch_with_stats,
)
from app.llm.provider import LLMProvider
from app.llm.schemas import ProviderBudget, TokenPricing
from app.observability.persistence import (
    persist_run_records,
    record_to_step,
    records_to_report,
    report_to_records,
)
from app.observability.types import JsonObject, RunReport, StepTrace
from app.openai_models import resolve_openai_model
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve
from app.retrieval.types import RetrievalFilters
from app.workflow.runner import NodeObserver, run_workflow
from app.workflow.types import WorkflowRequest

type ParseStatus = Literal["parsed", "needs_profile_update"]

_PARSE_STATUS = TypeAdapter[ParseStatus](ParseStatus)


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
    """M2 retrieval call shape used by both retrieve and review resources.

    The ranking plan travels through this seam so a served request retrieves with the
    same configuration the evaluation arms measured; a boundary that cannot carry the
    plan silently pins every deployment to the defaults.
    """

    def __call__(
        self,
        session: AsyncSession,
        query: str,
        *,
        provider: EmbeddingProvider | None,
        k: int,
        filters: RetrievalFilters,
        route_by_language: bool = False,
        lexical_ranker: LexicalRanker = "ts_rank_cd",
        bm25_k1: float = DEFAULT_BM25_K1,
        bm25_b: float = DEFAULT_BM25_B,
        bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
    ) -> Awaitable[RetrievalResult]:
        """Return one asynchronous retrieval result."""
        ...


type SessionRetrievalService = Callable[
    [AsyncSession, str, int, RetrievalFilters],
    Awaitable[RetrievalResult],
]


class WorkflowService(Protocol):
    """M4 workflow call shape used by the review resource."""

    def __call__(
        self,
        request: WorkflowRequest,
        *,
        retriever: Callable[
            [str, int, RetrievalFilters],
            Awaitable[RetrievalResult],
        ],
        provider: LLMProvider,
        on_node: NodeObserver | None = None,
    ) -> Awaitable[RunReport]:
        """Return one asynchronous guarded workflow report."""
        ...


class RunPersister(Protocol):
    """M4 persistence call shape used after a workflow report is sanitized."""

    def __call__(
        self,
        session: AsyncSession,
        run: Run,
        traces: Sequence[Trace],
    ) -> Awaitable[Run]:
        """Persist already-sanitized records within the caller-owned transaction."""
        ...


def _document_resource(document: Document, chunk_count: int) -> DocumentResource:
    """Project one stored document and its chunk count onto the resource."""
    return DocumentResource(
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
        parse_status=_PARSE_STATUS.validate_python(document.parse_status, strict=True),
        source_length=document.source_length,
        source_sha256=document.source_sha256,
        chunk_count=chunk_count,
    )


class RuntimeApiServices(ApiServices):
    """Compose API resources over one session per synchronous request.

    Retrieval defaults to the deterministic provider unless one is injected. Review is
    fail-closed until an LLM provider and its explicit budget are injected; construction
    never creates the process database engine or starts a paid call. Use
    :func:`build_runtime_services` to compose from validated settings.
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
        run_persister: RunPersister = persist_run_records,
        run_id_factory: Callable[[], str] | None = None,
        secret_values: Iterable[str] = (),
        route_by_language: bool = False,
        lexical_ranker: LexicalRanker = "ts_rank_cd",
        bm25_k1: float = DEFAULT_BM25_K1,
        bm25_b: float = DEFAULT_BM25_B,
        bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
        corpus_root: Path | None = None,
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
        self._route_by_language = route_by_language
        self._lexical_ranker: LexicalRanker = lexical_ranker
        self._bm25_k1 = bm25_k1
        self._bm25_b = bm25_b
        self._bm25_idf: BM25Idf = bm25_idf
        self._corpus_root = corpus_root

    @property
    def session_factory(self) -> SessionFactory:
        """Expose the configured session boundary to local composed services."""
        return self._session_factory

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """Expose the server-selected provider without exposing its credentials."""
        return self._embedding_provider

    async def _retrieve_with_session(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        """Retrieve against an open session, forwarding the configured ranking plan."""
        return await self._retrieval_service(
            session,
            query,
            provider=self._embedding_provider,
            k=k,
            filters=filters,
            route_by_language=self._route_by_language,
            lexical_ranker=self._lexical_ranker,
            bm25_k1=self._bm25_k1,
            bm25_b=self._bm25_b,
            bm25_idf=self._bm25_idf,
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
            Typed 400 for semantically invalid input, typed 503 when the embedding
            provider or database is unavailable.
        """
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                return await self._retrieve_with_session(
                    session,
                    request.query,
                    request.k,
                    request.filters,
                )

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
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).all()
        return tuple(_document_resource(document, count) for document, count in rows)

    def _resolve_manifest_path(self, value: str) -> Path:
        """Confine the requested manifest to the configured corpus directory.

        The API is a network boundary: an unconfined path would let any caller use
        ingestion as a file-existence and parse oracle for the whole filesystem.
        """
        root = (self._corpus_root or get_settings().corpus_dir).resolve()
        candidate = Path(value)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise bad_request(
                "manifest_outside_corpus",
                "manifest_path must resolve inside the configured corpus directory.",
            )
        return resolved

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Prepare a confined local manifest off-loop and atomically persist it.

        Parameters
        ----------
        request : IngestRequest
            Explicit corpus-relative manifest and bounded batch settings.

        Returns
        -------
        SeedResult
            Committed document and chunk counts.

        Raises
        ------
        ApiProblemError
            If the manifest is invalid, escapes the corpus directory, or the database
            is unavailable.

        Notes
        -----
        CPU and file parsing run in a worker thread; the M1 persister retains
        transaction ownership, and BM25 statistics are rebuilt in the same call
        because every chunk upsert invalidates them. Schema DDL runs only when
        ``create_schema`` asks for it.
        """
        manifest_path = self._resolve_manifest_path(request.manifest_path)
        try:
            batch = await asyncio.to_thread(
                load_seed_batch,
                manifest_path,
                expected_documents=request.expected_documents,
            )
        except ManifestError as error:
            raise bad_request(error.code, error.message) from error

        async with translate_runtime_errors():
            if request.create_schema:
                database_engine = (
                    self._database_engine
                    if self._database_engine is not None
                    else _default_database_engine()
                )
                await bootstrap_schema(database_engine)
            async with self._session_factory() as session:
                return await persist_seed_batch_with_stats(
                    session,
                    batch,
                    chunk_batch_size=request.chunk_batch_size,
                )

    async def review(
        self,
        request: ReviewRequest,
        on_node: NodeObserver | None = None,
    ) -> RunReport:
        """Compose retrieval, provider work, redaction, and persistence.

        Parameters
        ----------
        request : ReviewRequest
            Validated public review request.
        on_node : NodeObserver | None
            Optional streaming observer reporting each committed node transition.

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
        Retrieval transactions end before provider work. The report is sanitized once,
        and the resulting records are both persisted and returned, so redaction cost is
        paid a single time per run.
        """
        return await self._review(request, on_node=on_node, retrieval_override=None)

    async def review_with_retrieval(
        self,
        request: ReviewRequest,
        retrieval: SessionRetrievalService,
        on_node: NodeObserver | None = None,
    ) -> RunReport:
        """Run one review with an explicit request-scoped retrieval implementation."""
        return await self._review(request, on_node=on_node, retrieval_override=retrieval)

    async def _review(
        self,
        request: ReviewRequest,
        *,
        on_node: NodeObserver | None,
        retrieval_override: SessionRetrievalService | None,
    ) -> RunReport:
        """Execute, sanitize, and persist one public or administrator review."""
        if self._llm_provider is None or self._provider_budget is None:
            raise unavailable(
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
        async with translate_runtime_errors():
            async with self._session_factory() as session:

                async def retrieve_for_workflow(
                    query: str,
                    k: int,
                    filters: RetrievalFilters,
                ) -> RetrievalResult:
                    """Retrieve on the session this run already holds."""
                    result = (
                        await self._retrieve_with_session(session, query, k, filters)
                        if retrieval_override is None
                        else await retrieval_override(session, query, k, filters)
                    )
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
                safe_report = records_to_report(safe_run, safe_traces)
                if session.in_transaction():
                    await session.rollback()
                async with session.begin():
                    await self._run_persister(session, safe_run, safe_traces)
                return safe_report

    async def _trace_rows(self, session: AsyncSession, run_id: str) -> tuple[Trace, ...]:
        """Read this run's traces in recorded step order."""
        rows = await session.scalars(
            select(Trace).where(Trace.run_id == run_id).order_by(Trace.step)
        )
        return tuple(rows)

    async def get_run(self, run_id: str) -> RunReport | None:
        """Load one run and ordered traces without executing workflow code."""
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return records_to_report(run, traces)

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Load ordered traces only when their parent run exists."""
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                exists = await session.scalar(select(Run.run_id).where(Run.run_id == run_id))
                if exists is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return tuple(record_to_step(trace) for trace in traces)

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Load newest evaluation records through their strict public schema."""
        statement = select(EvalResult).order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                rows = tuple(await session.scalars(statement.limit(limit)))
        return tuple(
            EvalResultResource(
                result_id=row.id,
                suite=row.suite,
                # JSONB deserializes to JSON values; the ORM annotation is wider.
                config=cast("JsonObject", row.config),
                metrics={name: float(value) for name, value in row.metrics.items()},
                raw_artifact_path=row.raw_artifact_path,
                created_at=row.created_at,
            )
            for row in rows
        )


def build_runtime_services(settings: Settings | None = None) -> RuntimeApiServices:
    """Compose the production service boundary from validated settings.

    This is the single lever that makes deployed configuration real: the embedding
    provider, the measured lexical plan, the review provider and budget, the corpus
    root, and the secrets the redaction pass must strip all come from one ``Settings``
    instance, exactly as the acceptance CLI reads them.

    Parameters
    ----------
    settings : Settings | None
        Validated settings, or ``None`` to load cached application settings.

    Returns
    -------
    RuntimeApiServices
        Fully configured service boundary; review stays fail-closed (typed 503)
        until ``REVIEW_MODEL`` and its pricing are configured.
    """
    configured = settings if settings is not None else get_settings()
    llm_provider: LLMProvider | None = None
    provider_budget: ProviderBudget | None = None
    if configured.review_model is not None:
        from app.llm.provider import OpenAILLMProvider

        selection = resolve_openai_model("review", configured.review_model)
        llm_provider = OpenAILLMProvider(
            model_name=selection.model,
            role="review",
            api_key=(
                configured.openai_api_key.get_secret_value()
                if configured.openai_api_key is not None
                else None
            ),
        )
        provider_budget = ProviderBudget(
            max_input_tokens=configured.review_max_input_tokens,
            max_output_tokens=configured.review_max_output_tokens,
            max_cost_usd=configured.review_max_cost_usd,
            pricing=TokenPricing(
                input_per_million_usd=selection.pricing.input_per_million_usd,
                output_per_million_usd=selection.pricing.output_per_million_usd,
                cached_input_per_million_usd=(selection.pricing.cached_input_per_million_usd),
                cache_write_input_per_million_usd=(
                    selection.pricing.cache_write_input_per_million_usd
                ),
            ),
        )
    secret_values = tuple(
        secret.get_secret_value()
        for secret in (configured.openai_api_key, configured.dart_api_key)
        if secret is not None and secret.get_secret_value().strip()
    )
    return RuntimeApiServices(
        embedding_provider=get_embedding_provider(configured),
        llm_provider=llm_provider,
        provider_budget=provider_budget,
        secret_values=secret_values,
        route_by_language=configured.query_language_routing,
        lexical_ranker=configured.lexical_ranker,
        bm25_k1=configured.bm25_k1,
        bm25_b=configured.bm25_b,
        bm25_idf=configured.bm25_idf,
        corpus_root=configured.corpus_dir,
    )
