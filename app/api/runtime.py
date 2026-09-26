"""Production database composition for synchronous M5 HTTP resources."""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
import hashlib
from pathlib import Path
import secrets
from typing import Literal, Protocol, cast
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversation import ConversationRouter, bounded_history
from app.api.deps import ApiServices
from app.api.document_catalog import DocumentCatalog
from app.api.errors import ApiProblemError, bad_request, translate_runtime_errors, unavailable
from app.api.evidence import (
    CandidateSnapshotCodec,
    EvidenceSnapshotError,
    select_evidence,
)
from app.api.review_engines import ReviewEngines
from app.api.review_profile import (
    ResolvedRetrievalProfile,
    ReviewSessionProfile,
    ServerBM25,
    public_custom_retrieval_violation,
    resolve_retrieval_profile,
)
from app.api.schemas import (
    CandidateComponentRank,
    DocumentResource,
    EvalResultResource,
    EvidenceCandidate,
    EvidenceHit,
    RetrieveRequest,
    RetrieveResponse,
    ReviewRequest,
    SnapshotComparisonResponse,
    SnapshotResource,
)
from app.api.scope_resolution import ScopeResolver
from app.api.search_consistency import consistent_retrieve
from app.config import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_IDF,
    DEFAULT_BM25_K1,
    BM25Idf,
    LexicalRanker,
    get_settings,
)
from app.db.models import Chunk, Document, EvalResult, EvaluationSnapshot, Run, Trace
from app.db.queries import join_current_parse
from app.evals.snapshots import SnapshotService
from app.ingestion.company_names import CompanyNames, read_company_names
from app.llm.local_connection import LocalConnectionManager
from app.llm.local_inventory import LocalModelInventory
from app.llm.openai_limits import OpenAILimitsManager
from app.llm.provider import LLMProvider
from app.llm.schemas import ProviderBudget
from app.observability.persistence import (
    persist_run_records,
    record_to_step,
    records_to_report,
    report_to_records,
)
from app.observability.stages import capture_stages, stage, stage_metadata
from app.observability.types import JsonObject, RunReport, StepTrace, WorkflowNode, build_run_report
from app.observability.usage import provider_identity
from app.operator.corpus_access import CorpusAccess, CorpusUpdatingError
from app.operator.jobs import _default_session_factory
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.language import detect_query_language
from app.retrieval.rerank import RerankProvider
from app.retrieval.scope import ManifestScopeIndex
from app.retrieval.service import ComponentRankings, RetrievalResult, RetrievalStrategy
from app.retrieval.translate import QueryTranslationError, route_query
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.settings_sources import DEFAULT_LOCAL_TIMEOUT_S
from app.workflow.gate import ConversationDecision
from app.workflow.runner import BilledRunAllowanceError, NodeObserver, run_workflow
from app.workflow.types import WorkflowRequest, WorkflowState

type ParseStatus = Literal["parsed", "needs_profile_update"]

_PARSE_STATUS = TypeAdapter[ParseStatus](ParseStatus)


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
        strategy: RetrievalStrategy = "hybrid",
        query_variants: dict[str, str] | None = None,
        k: int,
        candidate_k: int | None = None,
        filters: RetrievalFilters,
        rrf_k: int = 60,
        reranker: RerankProvider | None = None,
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
        parse_status=_PARSE_STATUS.validate_python(
            document.current_parse.structure.parse_status, strict=True
        ),
        source_length=document.current_parse.structure.source_length,
        source_sha256=document.current_parse.structure.source_sha256,
        chunk_count=chunk_count,
    )


class RuntimeApiServices(ApiServices):
    """Compose API resources over one session per synchronous request.

    Retrieval defaults to the deterministic provider unless one is injected. Review is
    fail-closed until the provider and budget registries carry an engine's provider and
    its explicit budget; construction never creates the process database engine or
    starts a paid call.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = _default_session_factory,
        embedding_provider: EmbeddingProvider,
        llm_providers: dict[str, LLMProvider] | None = None,
        provider_budgets: dict[str, ProviderBudget] | None = None,
        local_inventory: LocalModelInventory | None = None,
        local_connection: LocalConnectionManager | None = None,
        openai_limits: OpenAILimitsManager | None = None,
        allow_local_engine: bool = True,
        local_timeout_s: float = DEFAULT_LOCAL_TIMEOUT_S,
        retrieval_service: RetrievalService = consistent_retrieve,
        workflow_service: WorkflowService = run_workflow,
        run_persister: RunPersister = persist_run_records,
        run_id_factory: Callable[[], str] | None = None,
        secret_values: Iterable[str] = (),
        credential_slot: str | None = None,
        bm25_k1: float = DEFAULT_BM25_K1,
        bm25_b: float = DEFAULT_BM25_B,
        bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
        corpus_root: Path | None = None,
        scope_index: ManifestScopeIndex | None = None,
        intent_classifier_enabled: bool = False,
        query_routing_enabled: bool = False,
        allow_custom_prompt_policy: bool = True,
        allow_snapshot_query: bool = True,
    ) -> None:
        if (llm_providers is None) != (provider_budgets is None):
            raise ValueError("llm provider and budget registries must be configured together")
        self.corpus_access = CorpusAccess()
        self._session_factory = session_factory
        self._embedding_provider = embedding_provider
        self._llm_providers = dict(llm_providers or {})
        self._provider_budgets = dict(provider_budgets or {})
        self.local_connection = local_connection
        self.openai_limits = openai_limits
        if (
            local_inventory is not None or local_connection is not None and local_connection.enabled
        ) and "local" not in self._provider_budgets:
            raise ValueError("local discovery requires an explicit local provider budget")
        self._engines = ReviewEngines(
            llm_providers=self._llm_providers,
            provider_budgets=self._provider_budgets,
            local_inventory=local_inventory,
            local_connection=local_connection,
            openai_limits=openai_limits,
            allow_local_engine=allow_local_engine,
            local_timeout_s=local_timeout_s,
        )
        self._retrieval_service = retrieval_service
        self._workflow_service = workflow_service
        self._run_persister = run_persister
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")
        self._secret_values = tuple(secret_values)
        self._credential_slot = credential_slot
        self._bm25_k1 = bm25_k1
        self._bm25_b = bm25_b
        self._bm25_idf: BM25Idf = bm25_idf
        self._corpus_root = corpus_root
        self._scope = ScopeResolver(
            corpus_root=corpus_root,
            scope_index=scope_index,
            session_factory=session_factory,
            bm25=self.bm25_parameters,
            developer=allow_custom_prompt_policy,
            secret_values=self._secret_values,
        )
        self._conversation = ConversationRouter(
            scope=self._scope,
            engines=self._engines,
            classifier_enabled=intent_classifier_enabled,
        )
        self._snapshot_codec = CandidateSnapshotCodec(secrets.token_bytes(32))
        self._query_routing_enabled = query_routing_enabled
        self._allow_custom_prompt_policy = allow_custom_prompt_policy
        self._snapshots = SnapshotService(session_factory=session_factory)
        self._allow_snapshot_query = allow_snapshot_query

    @property
    def published_documents(self) -> DocumentCatalog:
        """Expose current identities explicitly included in ready public snapshots."""
        return DocumentCatalog(
            self.session_factory,
            public_only=True,
            company_names=self.company_names,
            embedding_identity=self._embedding_provider.identity,
        )

    def company_names(self) -> CompanyNames:
        """Read current optional company labels from the configured corpus metadata."""
        return read_company_names(self._corpus_root or get_settings().corpus_dir)

    @property
    def local_inventory(self) -> LocalModelInventory | None:
        """Expose current discovery for readiness while request work captures its own copy."""
        return self._engines.local_inventory

    @asynccontextmanager
    async def _request_connection(self, profile: ReviewSessionProfile) -> AsyncIterator[None]:
        """Pin the endpoint before the first await and close request-owned HTTP resources.

        Session controls are validated first, so a refused request never pins a local
        endpoint or waits for search admission.
        """
        self._validate_session_profile(profile)
        async with self._engines.pin_request(), self.search_access():
            yield

    @asynccontextmanager
    async def search_access(self) -> AsyncIterator[None]:
        """Expose a typed admission failure shared by public and administrator searches."""
        try:
            async with self.corpus_access.search():
                yield
        except CorpusUpdatingError as error:
            raise unavailable("corpus_updating", str(error)) from error

    def _validate_session_profile(self, profile: ReviewSessionProfile) -> None:
        """Reject developer controls before either retrieval or any model classification."""
        self._engines.reject_disabled_engine(profile)
        if not self._allow_custom_prompt_policy:
            if profile.prompt_policy != type(profile.prompt_policy)():
                raise ApiProblemError(
                    status_code=403,
                    code="capability_disabled",
                    message="Custom prompt and run policies are available only in Dev.",
                )
            if profile.custom_retrieval is not None:
                violation = public_custom_retrieval_violation(
                    profile.custom_retrieval.model_dump(mode="python")
                )
                if violation is not None:
                    raise ApiProblemError(
                        status_code=403, code="capability_disabled", message=violation
                    )
        if profile.snapshot_id is not None and not self._allow_snapshot_query:
            raise ApiProblemError(
                status_code=403,
                code="capability_disabled",
                message="Snapshot queries are available only in Dev.",
            )

    @property
    def session_factory(self) -> SessionFactory:
        """Expose the configured session boundary to local composed services."""
        return self._session_factory

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """Expose the server-selected provider without exposing its credentials."""
        return self._embedding_provider

    @property
    def bm25_parameters(self) -> ServerBM25:
        """Expose the configured BM25 values that fill what a retrieval plan leaves unstated."""
        return ServerBM25(self._bm25_k1, self._bm25_b, self._bm25_idf)

    async def _retrieve_with_session(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: RetrievalFilters,
        profile: ResolvedRetrievalProfile | None = None,
        query_variants: dict[str, str] | None = None,
    ) -> RetrievalResult:
        """Retrieve against an open session, forwarding the configured ranking plan."""
        plan = profile or resolve_retrieval_profile(ReviewSessionProfile(), self.bm25_parameters)
        return await self._retrieval_service(
            session,
            query,
            provider=self._embedding_provider,
            strategy=plan.strategy,
            query_variants=query_variants,
            k=k,
            candidate_k=max(plan.candidate_k, k),
            filters=filters,
            rrf_k=plan.rrf_k,
            reranker=CrossEncoderReranker.shared() if plan.reranker else None,
            route_by_language=plan.route_by_language,
            lexical_ranker=plan.lexical_ranker or "ts_rank_cd",
            bm25_k1=plan.bm25_k1,
            bm25_b=plan.bm25_b,
            bm25_idf=plan.bm25_idf,
        )

    @staticmethod
    def _component_ranks(
        chunk_id: int,
        result: RetrievalResult,
    ) -> tuple[CandidateComponentRank, ...]:
        """Return every component rank that contributed one candidate.

        A rank is the candidate's 1-based position inside the lane that proposed it.
        When the service ran one vector lane per corpus language, those lanes are
        reported tagged with their language, so a chunk ranked first in the Korean lane
        is rank 1 rather than its offset inside the concatenated ``vector`` tuple. The
        flat tuple is consulted only when no per-language lanes exist.
        """
        rankings = result.component_rankings
        ranks: list[CandidateComponentRank] = []

        def record(lane: str, language: str | None, ids: tuple[int, ...]) -> None:
            """Record the candidate's rank inside one lane when that lane proposed it."""
            if chunk_id in ids:
                ranks.append(
                    CandidateComponentRank.model_validate(
                        {"lane": lane, "language": language, "rank": ids.index(chunk_id) + 1}
                    )
                )

        if rankings.vector_by_language:
            for language, ids in rankings.vector_by_language.items():
                record("vector", language, ids)
        else:
            record("vector", None, rankings.vector)
        for language, ids in rankings.lexical_by_language.items():
            record("lexical", language, ids)
        return tuple(ranks)

    def _registry_name(self, doc_id: str) -> str | None:
        """Return the publishing registry of an indexed document, or ``None`` when unknown."""
        metadata = self._scope.manifest_index().documents.get(doc_id)
        return None if metadata is None else metadata.registry

    def _candidate_resource(
        self,
        hit: ChunkHit,
        *,
        rank: int,
        result: RetrievalResult,
    ) -> EvidenceCandidate:
        """Combine one hit with manifest filing and component-rank provenance."""
        metadata = self._scope.manifest_index().documents.get(hit.doc_id)
        if metadata is None:
            raise unavailable(
                "evidence_metadata_unavailable",
                f"Retrieved document {hit.doc_id} has no corpus metadata.",
            )
        base = EvidenceHit.from_chunk_hit(hit, registry=metadata.registry).model_dump(mode="python")
        return EvidenceCandidate(
            **base,
            rank=rank,
            registry=metadata.registry,
            language=metadata.language,
            issuer=metadata.issuer,
            fiscal_year=metadata.fiscal_year,
            form=metadata.form,
            score_stage=result.score_stage,
            rank_score=hit.score,
            component_ranks=self._component_ranks(hit.chunk_id, result),
        )

    @capture_stages
    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
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
        async with self._request_connection(request.session_profile):
            async with translate_runtime_errors():
                pinned_profile = await self._engines.pin_local_model(request.session_profile)
                request = request.model_copy(update={"session_profile": pinned_profile})
                gate, path = await self._conversation.decide_path(request)
                if gate is not None and gate.intent == "service_help":
                    return RetrieveResponse(
                        query=request.query,
                        results=(),
                        candidates=(),
                        candidate_token=None,
                        candidate_expires_at=0,
                        score_stage="rrf",
                        component_rankings={},
                        resolved_profile=resolve_retrieval_profile(
                            request.session_profile, self.bm25_parameters
                        ),
                        resolved_scope=None,
                        path_decision=path,
                    )
                async with stage("route") as routing_stage:
                    routing_stage.path_decision = path
                    profile, scope = self._scope.path_scope(request.session_profile, path)
                    routing_stage.resolved_scope = scope.model_dump(mode="json")
                retrieval_query = cast("str", path["retrieval_query"])
                routed_queries: dict[str, str] = {}
                if self._query_routing_enabled and profile.route_by_language:
                    source_language = detect_query_language(retrieval_query)
                    for language in scope.filters.languages or ("en",):
                        if language == source_language:
                            continue
                        provider, budget = await self._engines.resolve_engine(request)
                        try:
                            async with stage("route"):
                                routed = await route_query(
                                    retrieval_query,
                                    target_language=cast("Literal['en', 'ko']", language),
                                    llm_provider=provider,
                                    provider_budget=budget,
                                )
                        except QueryTranslationError as error:
                            raise unavailable(
                                "query_routing_failed",
                                f"Query routing failed for {language} ({type(error).__name__}).",
                            ) from error
                        routed_queries[language] = routed.translated_query
                async with stage("retrieve"), self._session_factory() as session:
                    result = await self._retrieve_with_session(
                        session,
                        retrieval_query,
                        profile.k,
                        scope.filters,
                        profile,
                        routed_queries or None,
                    )
                path["routing_queries"] = dict(routed_queries)
                token, snapshot = self._snapshot_codec.issue(
                    query=retrieval_query,
                    profile=profile,
                    filters=scope.filters,
                    candidates=result.candidates,
                    routing_queries=routed_queries,
                )
                return RetrieveResponse(
                    query=request.query,
                    results=tuple(
                        EvidenceHit.from_chunk_hit(hit, registry=self._registry_name(hit.doc_id))
                        for hit in result.hits
                    ),
                    candidates=tuple(
                        self._candidate_resource(hit, rank=rank, result=result)
                        for rank, hit in enumerate(result.candidates, start=1)
                    ),
                    candidate_token=token,
                    candidate_expires_at=snapshot.expires_at,
                    score_stage=result.score_stage,
                    component_rankings=result.component_rankings.model_dump(mode="json"),
                    resolved_profile=profile,
                    resolved_scope=scope,
                    path_decision=path,
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
        statement = join_current_parse(statement, load=True, grouped=True)
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).all()
        return tuple(_document_resource(document, count) for document, count in rows)

    @capture_stages
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
        async with self._request_connection(request.session_profile):
            pinned_profile = await self._engines.pin_local_model(request.session_profile)
            request = request.model_copy(update={"session_profile": pinned_profile})
            decision, path = await self._conversation.decide_path(request)
            if decision.intent == "service_help":
                return await self._casual_report(request, decision, path)
            return await self._review(request, on_node=on_node, retrieval_override=None, path=path)

    async def _execution_context(
        self,
        provider: LLMProvider | None,
        budget: ProviderBudget | None,
        request: ReviewRequest,
        *,
        chat_only: bool = False,
    ) -> JsonObject:
        """Capture the actual provider and applied limits without credential values."""
        identity = provider_identity(
            api_url=provider.api_url if provider is not None else None,
            credential_slot=self._credential_slot
            if request.session_profile.engine == "openai"
            else "none",
        )
        inventory = self._engines.pinned_inventory()
        if identity["local"] is True:
            identity["credential_slot"] = (
                "explicit" if inventory is not None and inventory.api_key else "none"
            )
        metadata = stage_metadata()
        calls = metadata.get("model_calls", [])
        assert isinstance(calls, list)
        for call in calls:
            assert isinstance(call, dict)
            if (
                call.get("provider") == identity["provider"]
                and call.get("local") == identity["local"]
            ):
                call["credential_slot"] = identity["credential_slot"]
        limits = request.session_profile.prompt_policy.workflow_budget
        effective = budget.model_dump(mode="json") if budget is not None else None
        sources = None
        if effective is not None and not chat_only:
            sources = {}
            for name in ("max_input_tokens", "max_output_tokens"):
                configured = effective[name]
                requested = getattr(limits, name)
                effective[name] = min(configured, requested)
                sources[name] = (
                    "provider_budget"
                    if configured < requested
                    else "run_limits"
                    if requested < configured
                    else "provider_budget_and_run_limits"
                )
        placement = None
        if provider is not None and identity["provider"] == "ollama" and inventory is not None:
            placement = await inventory.placement(provider.model_name)
            inventory.record_cpu_performance(
                provider.model_name,
                placement,
                calls,
                model_digest=self._engines.pinned_model_digest(),
            )
        return {
            **metadata,
            "provider_identity": identity if provider is not None else None,
            "local_placement": placement,
            "effective_settings": {
                "engine": request.session_profile.engine,
                "model": provider.model_name if provider is not None else None,
                "retrieval_applicable": not chat_only,
                "retrieval": None,
                "provider_budget": budget.model_dump(mode="json") if budget else None,
                "effective_provider_budget": effective,
                "run_limits": None if chat_only else limits.model_dump(mode="json"),
                "budget_sources": sources,
                "run_limits_source": None
                if chat_only
                else (
                    "request"
                    if "workflow_budget" in request.session_profile.prompt_policy.model_fields_set
                    else "application_default"
                ),
                "provider_budget_source": "server_configuration" if budget else None,
            },
        }

    async def _casual_report(
        self,
        request: ReviewRequest,
        decision: ConversationDecision,
        path: JsonObject,
    ) -> RunReport:
        """Persist bounded service guidance without a free-form provider reply."""
        run_id = self._run_id_factory()
        traces: tuple[StepTrace, ...] = ()
        answer = decision.canned_answer
        if answer is None:
            raise ValueError("service guidance requires a fixed response")
        report = build_run_report(
            run_id=run_id,
            status="ok",
            total_time_seconds=0.0,
            system_prompt="Retrieval-free conversation gate.",
            node_path=("gate",),
            steps=traces,
            report={
                "report_kind": "conversation",
                "answer": answer,
                "response_source": "canned",
            },
            request_context={
                **await self._execution_context(None, None, request, chat_only=True),
                "stage_results": [{"node": "gate", "intent": decision.model_dump(mode="json")}],
                "routing_queries": {},
                "intent": decision.model_dump(mode="json"),
                "path_decision": path,
                "engine": request.session_profile.engine,
                "history_turns": len(bounded_history(request)),
            },
        )
        safe_run, safe_traces = report_to_records(report, secret_values=self._secret_values)
        async with self._session_factory() as session:
            async with session.begin():
                await self._run_persister(session, safe_run, safe_traces)
        return records_to_report(safe_run, safe_traces)

    @capture_stages
    async def review_with_retrieval(
        self,
        request: ReviewRequest,
        retrieval: SessionRetrievalService,
        on_node: NodeObserver | None = None,
    ) -> RunReport:
        """Run one review with an explicit request-scoped retrieval implementation."""
        async with self._request_connection(request.session_profile):
            return await self._review(request, on_node=on_node, retrieval_override=retrieval)

    async def _review(
        self,
        request: ReviewRequest,
        *,
        on_node: NodeObserver | None,
        retrieval_override: SessionRetrievalService | None,
        path: JsonObject | None = None,
    ) -> RunReport:
        """Execute, sanitize, and persist one public or administrator review."""
        policy = request.session_profile.prompt_policy
        if not self._allow_custom_prompt_policy and policy != type(policy)():
            raise ApiProblemError(
                status_code=403,
                code="capability_disabled",
                message="Custom prompt and run policies are available only in Dev.",
            )
        if request.session_profile.snapshot_id is not None and not self._allow_snapshot_query:
            raise ApiProblemError(
                status_code=403,
                code="capability_disabled",
                message="Snapshot queries are available only in Dev.",
            )
        pinned_profile = await self._engines.pin_local_model(request.session_profile)
        request = request.model_copy(update={"session_profile": pinned_profile})
        llm_provider, provider_budget = await self._engines.resolve_engine(request)
        engine = request.session_profile.engine
        if request.session_profile.snapshot_id is not None:
            async with self._session_factory() as validation_session:
                selected_snapshot = await validation_session.get(
                    EvaluationSnapshot, request.session_profile.snapshot_id
                )
            if selected_snapshot is None or selected_snapshot.status != "ready":
                raise bad_request("snapshot_unavailable", "Selected snapshot is not ready.")
        if path is None:
            _, path = await self._conversation.decide_path(request)
        async with stage("route") as routing_stage:
            routing_stage.path_decision = path
            profile, scope = self._scope.path_scope(request.session_profile, path)
            routing_stage.resolved_scope = scope.model_dump(mode="json")
        retrieval_query = cast("str", path["retrieval_query"])
        snapshot = None
        if request.evidence_selection is not None:
            try:
                snapshot = self._snapshot_codec.verify(
                    request.evidence_selection.candidate_token,
                    query=retrieval_query,
                    profile=profile,
                    filters=scope.filters,
                )
            except EvidenceSnapshotError as error:
                raise ApiProblemError(
                    status_code=error.status_code,
                    code=error.code,
                    message=error.message,
                ) from error
        routed_queries: dict[str, str] = dict(snapshot.routing_queries) if snapshot else {}
        if snapshot is None and self._query_routing_enabled and profile.route_by_language:
            source_language = detect_query_language(retrieval_query)
            for language in scope.filters.languages or ("en",):
                if language == source_language:
                    continue
                try:
                    async with stage("route"):
                        routed = await route_query(
                            retrieval_query,
                            target_language=cast("Literal['en', 'ko']", language),
                            llm_provider=llm_provider,
                            provider_budget=provider_budget,
                        )
                except QueryTranslationError as error:
                    raise unavailable(
                        "query_routing_failed",
                        f"Query routing failed for {language} ({type(error).__name__}).",
                    ) from error
                routed_queries[language] = routed.translated_query
        path["routing_queries"] = dict(routed_queries)
        workflow_request = WorkflowRequest(
            run_id=self._run_id_factory(),
            query=retrieval_query,
            original_query=request.query,
            k=profile.k,
            filters=scope.filters,
            budget=policy.workflow_budget,
            provider_budget=provider_budget,
            max_context_chars=policy.max_context_chars,
            evidence_overfetch=policy.evidence_overfetch,
            max_hits_per_document=(
                profile.k if snapshot is not None else policy.max_hits_per_document
            ),
            routing_queries=routed_queries,
            system_prompt=policy.system_prompt,
        )
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                selected_result: RetrievalResult | None = None
                snapshot_candidates: list[JsonValue] | None = None
                if snapshot is not None and request.evidence_selection is not None:
                    ids = tuple(candidate.chunk_id for candidate in snapshot.candidates)
                    rows = tuple(await session.scalars(select(Chunk).where(Chunk.id.in_(ids))))
                    models = {row.id: row for row in rows}
                    ordered_hits = tuple(
                        ChunkHit(
                            chunk_id=item.chunk_id,
                            doc_id=models[item.chunk_id].doc_id,
                            item=models[item.chunk_id].item,
                            kind=cast("Literal['text', 'table']", models[item.chunk_id].kind),
                            citation=models[item.chunk_id].citation,
                            start_char=models[item.chunk_id].start_char,
                            end_char=models[item.chunk_id].end_char,
                            source_sha256=models[item.chunk_id].source_sha256,
                            body=models[item.chunk_id].body,
                            context_header=models[item.chunk_id].context_header,
                            index_text=models[item.chunk_id].index_text,
                            score=1.0 / rank,
                        )
                        for rank, item in enumerate(snapshot.candidates, start=1)
                        if item.chunk_id in models
                    )
                    try:
                        selected = select_evidence(
                            snapshot,
                            request.evidence_selection,
                            ordered_hits,
                            k=profile.k,
                            max_context_chars=policy.max_context_chars,
                        )
                    except EvidenceSnapshotError as error:
                        raise ApiProblemError(
                            status_code=error.status_code,
                            code=error.code,
                            message=error.message,
                        ) from error
                    snapshot_candidates = [
                        {
                            "chunk_id": item.chunk_id,
                            "doc_id": models[item.chunk_id].doc_id,
                            "citation": models[item.chunk_id].citation,
                            "rank": rank,
                            "score": item.score,
                        }
                        for rank, item in enumerate(snapshot.candidates, 1)
                    ]
                    ids_by_language: dict[str, list[int]] = {}
                    for hit in selected:
                        ids_by_language.setdefault(
                            self._scope.manifest_index().documents[hit.doc_id].language,
                            [],
                        ).append(hit.chunk_id)
                    selected_result = RetrievalResult(
                        hits=selected,
                        candidates=selected,
                        score_stage="rrf",
                        component_rankings=ComponentRankings(
                            vector=(),
                            lexical=(),
                            lexical_by_language={
                                language: tuple(chunk_ids)
                                for language, chunk_ids in ids_by_language.items()
                            },
                        ),
                    )

                async def retrieve_for_workflow(
                    query: str,
                    k: int,
                    filters: RetrievalFilters,
                ) -> RetrievalResult:
                    """Retrieve on the session this run already holds."""
                    result = (
                        selected_result
                        if selected_result is not None
                        else await self._retrieve_with_session(
                            session,
                            query,
                            k,
                            filters,
                            profile,
                            routed_queries or None,
                        )
                        if retrieval_override is None
                        else await retrieval_override(session, query, k, filters)
                    )
                    if session.in_transaction():
                        await session.rollback()
                    return result

                stage_results: list[JsonValue] = []

                async def record_node(node: WorkflowNode, state: WorkflowState) -> None:
                    """Retain actual stage outputs, including failed and repeated stages."""
                    stage_results.append(
                        {
                            "node": node,
                            "candidates": snapshot_candidates
                            if snapshot_candidates is not None
                            else [
                                {
                                    "chunk_id": hit.chunk_id,
                                    "doc_id": hit.doc_id,
                                    "citation": hit.citation,
                                    "rank": rank,
                                    "score": hit.score,
                                }
                                for rank, hit in enumerate(state.retrieved_hits, 1)
                            ],
                            "evidence_chunk_ids": [hit.chunk_id for hit in state.evidence],
                            "kept_chunk_ids": list(state.relevant_chunk_ids)
                            if node in {"grade", "check", "report"} and state.failure is None
                            else None,
                            "rejected_chunk_ids": [
                                hit.chunk_id
                                for hit in state.evidence
                                if hit.chunk_id not in state.relevant_chunk_ids
                            ]
                            if node in {"grade", "check", "report"} and state.failure is None
                            else None,
                            "decision": state.decision.model_dump(mode="json")
                            if state.decision
                            else None,
                            "reasons": [reason.model_dump(mode="json") for reason in state.reasons],
                            "failure": state.failure.model_dump(mode="json")
                            if state.failure
                            else None,
                        }
                    )
                    if on_node is not None:
                        await on_node(node, state)

                async def persist(report: RunReport) -> RunReport:
                    """Attach the execution context, redact, and record one finished run."""
                    execution = await self._execution_context(
                        llm_provider, provider_budget, request
                    )
                    report = report.model_copy(
                        update={
                            "request_context": {
                                **execution,
                                "path_decision": path,
                                "stage_results": stage_results,
                                "effective_settings": {
                                    **cast("JsonObject", execution["effective_settings"]),
                                    "engine": engine,
                                    "retrieval": profile.model_dump(mode="json"),
                                    "resolved_scope": scope.model_dump(mode="json"),
                                    "provider_budget": provider_budget.model_dump(mode="json"),
                                    "run_limits": workflow_request.budget.model_dump(mode="json"),
                                    "max_context_chars": workflow_request.max_context_chars,
                                    "model": llm_provider.model_name,
                                },
                                "engine": engine,
                                "requested_profile": request.session_profile.model_dump(
                                    mode="json"
                                ),
                                "resolved_profile": profile.model_dump(mode="json"),
                                "resolved_scope": scope.model_dump(mode="json"),
                                "routing_queries": routed_queries,
                                "selection": (
                                    {
                                        "candidate_snapshot_sha256": hashlib.sha256(
                                            request.evidence_selection.candidate_token.encode(
                                                "utf-8"
                                            )
                                        ).hexdigest(),
                                        "pinned_chunk_ids": list(
                                            request.evidence_selection.pinned_chunk_ids
                                        ),
                                        "excluded_chunk_ids": list(
                                            request.evidence_selection.excluded_chunk_ids
                                        ),
                                    }
                                    if request.evidence_selection is not None
                                    else None
                                ),
                            }
                        }
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

                try:
                    report = await self._workflow_service(
                        workflow_request,
                        retriever=retrieve_for_workflow,
                        provider=llm_provider,
                        on_node=record_node,
                    )
                except BilledRunAllowanceError as denial:
                    # Calls were billed before the denial: keep that run on record,
                    # then let the denial reach the caller's 429 mapping unchanged.
                    await persist(denial.report)
                    raise
                return await persist(report)

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
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return tuple(
                    record_to_step(trace, request_context=run.request_context) for trace in traces
                )

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

    async def list_snapshots(self, *, public_only: bool) -> Sequence[SnapshotResource]:
        """Return immutable evaluation snapshots through the shared DB boundary."""
        return await self._snapshots.list(public_only=public_only)

    async def compare_snapshots(
        self, baseline_id: int, candidate_id: int
    ) -> SnapshotComparisonResponse:
        """Compare two stored snapshots without starting an evaluation."""
        return await self._snapshots.compare(baseline_id, candidate_id, public_only=True)
