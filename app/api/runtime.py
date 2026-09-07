"""Production database composition for synchronous M5 HTTP resources."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Literal, Protocol, cast
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import ApiServices
from app.api.document_catalog import DocumentCatalog
from app.api.errors import ApiProblemError, bad_request, translate_runtime_errors, unavailable
from app.api.evidence import (
    CandidateSnapshotCodec,
    EvidenceSnapshotError,
    select_evidence,
)
from app.api.review_profile import (
    ResolvedRetrievalProfile,
    ReviewSessionProfile,
    resolve_retrieval_profile,
)
from app.api.schemas import (
    CandidateComponentRank,
    DocumentResource,
    EvalResultResource,
    EvidenceCandidate,
    EvidenceHit,
    IngestRequest,
    RetrieveRequest,
    RetrieveResponse,
    ReviewRequest,
    SnapshotComparisonResponse,
    SnapshotResource,
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
from app.db.models import Chunk, Document, EvalResult, EvaluationSnapshot, Run, Trace
from app.db.queries import join_current_parse
from app.evals.snapshots import SnapshotService
from app.ingestion.company_names import CompanyNames, read_company_names
from app.ingestion.seed import (
    ManifestError,
    SeedResult,
    load_seed_batch,
    persist_seed_batch_with_stats,
)
from app.llm.local import LocalLLMProvider
from app.llm.local_connection import LocalConnectionManager
from app.llm.local_engine import build_local_provider
from app.llm.local_inventory import LocalModelInventory
from app.llm.local_runtime import build_local_runtime
from app.llm.provider import LLMProvider
from app.llm.schemas import Prompt, ProviderBudget, TokenPricing
from app.observability.persistence import (
    persist_run_records,
    record_to_step,
    records_to_report,
    report_to_records,
)
from app.observability.stages import (
    capture_stages,
    routing_cache,
    stage,
    stage_metadata,
)
from app.observability.trace import step_trace_from_provider_result
from app.observability.types import JsonObject, RunReport, StepTrace, WorkflowNode, build_run_report
from app.observability.usage import provider_identity
from app.openai_models import resolve_openai_model
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    EmbeddingProvider,
    get_embedding_provider,
)
from app.retrieval.language import detect_query_language
from app.retrieval.rerank import RerankProvider
from app.retrieval.scope import (
    ManifestScopeIndex,
    QueryScopeError,
    ResolvedQueryScope,
    resolve_query_scope,
)
from app.retrieval.service import ComponentRankings, RetrievalResult, RetrievalStrategy, retrieve
from app.retrieval.translate import QueryTranslationError, route_query
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.settings_sources import DEFAULT_LOCAL_TIMEOUT_S
from app.workflow.gate import (
    CASUAL_CUES,
    FILING_CUES,
    ChatReply,
    ConversationDecision,
    ConversationTurn,
    IntentClassification,
    deterministic_decision,
    is_filing_followup,
)
from app.workflow.runner import NodeObserver, run_workflow
from app.workflow.types import WorkflowRequest, WorkflowState

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


@dataclass
class _LocalRequest:
    """Hold one endpoint and provider for a complete request across asynchronous stages."""

    inventory: LocalModelInventory | None
    provider: LocalLLMProvider | None = None
    model: str | None = None
    model_digest: str | None = None


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
        embedding_provider: EmbeddingProvider,
        llm_provider: LLMProvider | None = None,
        provider_budget: ProviderBudget | None = None,
        llm_providers: dict[str, LLMProvider] | None = None,
        provider_budgets: dict[str, ProviderBudget] | None = None,
        local_inventory: LocalModelInventory | None = None,
        local_connection: LocalConnectionManager | None = None,
        allow_local_engine: bool = True,
        local_timeout_s: float = DEFAULT_LOCAL_TIMEOUT_S,
        retrieval_service: RetrievalService = retrieve,
        workflow_service: WorkflowService = run_workflow,
        run_persister: RunPersister = persist_run_records,
        run_id_factory: Callable[[], str] | None = None,
        secret_values: Iterable[str] = (),
        credential_slot: str | None = None,
        route_by_language: bool = False,
        lexical_ranker: LexicalRanker = "ts_rank_cd",
        bm25_k1: float = DEFAULT_BM25_K1,
        bm25_b: float = DEFAULT_BM25_B,
        bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
        corpus_root: Path | None = None,
        scope_index: ManifestScopeIndex | None = None,
        snapshot_codec: CandidateSnapshotCodec | None = None,
        intent_classifier_enabled: bool = False,
        query_routing_enabled: bool = False,
        allow_custom_prompt_policy: bool = True,
        snapshot_service: SnapshotService | None = None,
        allow_snapshot_query: bool = True,
    ) -> None:
        if (llm_provider is None) != (provider_budget is None):
            raise ValueError("llm_provider and provider_budget must be configured together")
        if (llm_providers is None) != (provider_budgets is None):
            raise ValueError("llm provider and budget registries must be configured together")
        self._session_factory = session_factory
        self._database_engine = database_engine
        self._embedding_provider = embedding_provider
        self._llm_provider = llm_provider
        self._provider_budget = provider_budget
        self._llm_providers = dict(llm_providers or {})
        self._provider_budgets = dict(provider_budgets or {})
        self._local_inventory = local_inventory
        self.local_connection = local_connection
        self._allow_local_engine = allow_local_engine
        self._local_request: ContextVar[_LocalRequest | None] = ContextVar(
            "local_request", default=None
        )
        self._local_timeout_s = local_timeout_s
        if (
            local_inventory is not None or local_connection is not None and local_connection.enabled
        ) and "local" not in self._provider_budgets:
            raise ValueError("local discovery requires an explicit local provider budget")
        if llm_provider is not None and provider_budget is not None:
            self._llm_providers.setdefault("openai", llm_provider)
            self._provider_budgets.setdefault("openai", provider_budget)
        self._retrieval_service = retrieval_service
        self._workflow_service = workflow_service
        self._run_persister = run_persister
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")
        self._secret_values = tuple(secret_values)
        self._credential_slot = credential_slot
        self._route_by_language = route_by_language
        self._lexical_ranker: LexicalRanker = lexical_ranker
        self._bm25_k1 = bm25_k1
        self._bm25_b = bm25_b
        self._bm25_idf: BM25Idf = bm25_idf
        self._corpus_root = corpus_root
        self._scope_index = scope_index
        self._snapshot_codec = snapshot_codec or CandidateSnapshotCodec(secrets.token_bytes(32))
        self._intent_classifier_enabled = intent_classifier_enabled
        self._query_routing_enabled = query_routing_enabled
        self._allow_custom_prompt_policy = allow_custom_prompt_policy
        self._snapshots = snapshot_service or SnapshotService(session_factory=session_factory)
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
        if not self._allow_local_engine:
            return None
        if self.local_connection is not None:
            return self.local_connection.current.inventory
        return self._local_inventory

    @asynccontextmanager
    async def _request_connection(self, profile: ReviewSessionProfile) -> AsyncIterator[None]:
        """Pin the endpoint before the first await and close request-owned HTTP resources."""
        self._validate_session_profile(profile)
        context = _LocalRequest(self.local_inventory)
        token = self._local_request.set(context)
        try:
            yield
        finally:
            self._local_request.reset(token)
            if context.provider is not None:
                await context.provider.aclose()

    def _validate_session_profile(self, profile: ReviewSessionProfile) -> None:
        """Reject developer controls before either retrieval or any model classification."""
        if profile.engine == "local" and not self._allow_local_engine:
            raise ApiProblemError(
                status_code=403,
                code="disabled_in_prod",
                message="Local LLM is disabled in production.",
            )
        if not self._allow_custom_prompt_policy and (
            profile.prompt_policy != type(profile.prompt_policy)()
            or profile.retrieval_preset == "custom"
        ):
            raise ApiProblemError(
                status_code=403,
                code="capability_disabled",
                message="Custom prompt, retrieval, and run policies are available only in Dev.",
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
        plan = profile or resolve_retrieval_profile(ReviewSessionProfile())
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
            reranker=CrossEncoderReranker() if plan.reranker else None,
            route_by_language=plan.route_by_language,
            lexical_ranker=plan.lexical_ranker or self._lexical_ranker,
            bm25_k1=plan.bm25_k1,
            bm25_b=plan.bm25_b,
            bm25_idf=plan.bm25_idf,
        )

    def _manifest_scope_index(self) -> ManifestScopeIndex:
        """Return the injected or lazily loaded committed manifest scope index."""
        if self._scope_index is None:
            root = (self._corpus_root or get_settings().corpus_dir).resolve()
            paths = (root / "manifest.json",)
            try:
                self._scope_index = ManifestScopeIndex.from_paths(paths)
            except (OSError, ValueError, TypeError) as error:
                raise unavailable(
                    "query_scope_unavailable",
                    f"Query scope metadata is unavailable ({type(error).__name__}).",
                ) from error
        return self._scope_index

    def _resolved_request(
        self,
        query: str,
        session_profile: ReviewSessionProfile,
    ) -> tuple[ResolvedRetrievalProfile, ResolvedQueryScope]:
        """Resolve the session profile and its explicit query scope."""
        profile = resolve_retrieval_profile(session_profile)
        explicit_filters = session_profile.explicit_filters()
        if session_profile.snapshot_id is not None and explicit_filters.snapshot_id is None:
            explicit_filters = explicit_filters.model_copy(
                update={"snapshot_id": session_profile.snapshot_id}
            )
        try:
            scope = resolve_query_scope(
                query,
                self._manifest_scope_index(),
                corpus_scope=session_profile.corpus_scope,
                explicit_filters=explicit_filters,
            )
        except QueryScopeError as error:
            raise ApiProblemError(
                status_code=422,
                code=error.code,
                message=error.message,
            ) from error
        return profile, scope

    def _history(self, request: ReviewRequest | RetrieveRequest) -> tuple[ConversationTurn, ...]:
        """Apply the server's history policy, including an explicit zero-turn limit."""
        limit = request.session_profile.prompt_policy.history_turns
        return request.conversation_history[-limit:] if limit else ()

    def _followup_query(self, request: ReviewRequest | RetrieveRequest) -> tuple[str | None, str]:
        """Carry filing topics forward while newer issuer and year references replace older ones."""
        index = self._manifest_scope_index()
        prior = None
        for turn in self._history(request):
            if turn.role != "user":
                continue
            if FILING_CUES.search(turn.text):
                prior = turn.text
            elif prior and (is_filing_followup(turn.text) or index.match(turn.text)):
                prior = self._combine_followup(prior, turn.text)
            else:
                prior = None
        follows = prior and (is_filing_followup(request.query) or index.match(request.query))
        if prior is not None and follows and not CASUAL_CUES.search(request.query):
            return prior, self._combine_followup(prior, request.query)
        return None, request.query

    def _combine_followup(self, prior: str, query: str) -> str:
        """Keep the prior topic but remove superseded issuer aliases and fiscal years."""
        index = self._manifest_scope_index()
        if index.match(query):
            for match in index.match(prior):
                prior = re.sub(re.escape(match.alias), "", prior, flags=re.IGNORECASE)
        if re.search(r"(?:19|20)\d{2}", query):
            prior = re.sub(r"(?:19|20)\d{2}년?", "", prior)
        return f"{prior.strip()} — {query}"

    async def _path_decision(
        self, request: ReviewRequest | RetrieveRequest
    ) -> tuple[ConversationDecision, JsonObject]:
        """Decide once per request and expose the bounded context used before retrieval."""
        cache = routing_cache()
        key = hashlib.sha256(
            json.dumps(
                {
                    "query": request.query,
                    "profile": request.session_profile.model_dump(mode="json"),
                    "history": [turn.model_dump(mode="json") for turn in self._history(request)],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if key in cache:
            saved = cache[key]
            return ConversationDecision.model_validate(saved["decision"]), dict(
                cast("JsonObject", saved["path"])
            )
        async with stage("gate") as measurement:
            prior, query = self._followup_query(request)
            decision = deterministic_decision(
                request.query,
                has_issuer_alias=bool(self._manifest_scope_index().match(request.query)),
                prior_filing_query=prior,
            )
            if decision is None and prior:
                decision = ConversationDecision(
                    intent="document_review",
                    source="deterministic",
                    matched_rule="filing_followup",
                    rationale="An issuer follow-up continues the bounded filing context.",
                )
            if decision is None and self._intent_classifier_enabled:
                decision = await self._classify_intent(
                    ReviewRequest(
                        query=request.query,
                        session_profile=request.session_profile,
                        conversation_history=self._history(request),
                    )
                )
            if decision is None:
                decision = ConversationDecision(
                    intent="document_review",
                    source="deterministic",
                    matched_rule="review_default",
                    rationale="Unclassified input defaults to evidence review.",
                )
            path: JsonObject = {
                "intent": decision.intent,
                "source": decision.source,
                "matched_rule": decision.matched_rule,
                "rationale": decision.rationale,
                "history_turns": len(self._history(request)),
                "selected_scope": request.session_profile.corpus_scope,
                "resolved_scope": None,
                "routing_queries": {},
                "retrieval_query": query,
                "scope_outcome": "not_applicable"
                if decision.intent == "casual_chat"
                else "resolved",
                "stopping_reason": None,
                "suggested_scope": None,
            }
            measurement.path_decision = path
            cache[key] = {"decision": decision.model_dump(mode="json"), "path": dict(path)}
            return decision, path

    def _path_scope(
        self, request: ReviewRequest | RetrieveRequest, path: JsonObject
    ) -> tuple[ResolvedRetrievalProfile, ResolvedQueryScope]:
        """Attach actionable scope failures before retrieval rather than producing NOT_IN_DOCS."""
        query = cast("str", path["retrieval_query"])
        try:
            profile, scope = self._resolved_request(query, request.session_profile)
            if query != request.query and not scope.filters.fiscal_years:
                years = tuple(sorted({int(year) for year in re.findall(r"(?:19|20)\d{2}", query)}))
                scope = scope.model_copy(
                    update={"filters": scope.filters.model_copy(update={"fiscal_years": years})}
                )
            path["resolved_scope"] = scope.model_dump(mode="json")
            filters = scope.filters
            if request.session_profile.snapshot_id is None and not any(
                (not filters.registries or doc.registry in filters.registries)
                and (not filters.issuers or doc.issuer in filters.issuers)
                and (not filters.languages or doc.language in filters.languages)
                and (not filters.fiscal_years or doc.fiscal_year in filters.fiscal_years)
                for doc in self._manifest_scope_index().documents.values()
            ):
                raise ApiProblemError(
                    status_code=422,
                    code="query_scope_empty",
                    message=(
                        "No corpus documents match the resolved scope. "
                        "Switch scope to Auto or change the issuer/year filters."
                    ),
                )
            return profile, scope
        except ApiProblemError as error:
            if error.error.code in {
                "query_scope_conflict",
                "profile_scope_conflict",
                "query_scope_empty",
                "unknown_issuer",
            }:
                path["scope_outcome"] = (
                    "empty" if error.error.code == "query_scope_empty" else "conflict"
                )
                path["stopping_reason"] = error.error.code
                path["suggested_scope"] = "auto"
                raise ApiProblemError(
                    status_code=error.status_code,
                    code=error.error.code,
                    message=error.error.message,
                    path_decision=path,
                ) from error
            raise

    @staticmethod
    def _component_ranks(
        chunk_id: int,
        result: RetrievalResult,
    ) -> tuple[CandidateComponentRank, ...]:
        """Return every component rank that contributed one candidate."""
        ranks: list[CandidateComponentRank] = []
        if chunk_id in result.component_rankings.vector:
            ranks.append(
                CandidateComponentRank(
                    lane="vector",
                    rank=result.component_rankings.vector.index(chunk_id) + 1,
                )
            )
        for language, ids in result.component_rankings.lexical_by_language.items():
            if chunk_id in ids:
                ranks.append(
                    CandidateComponentRank(
                        lane="lexical",
                        language=cast("Literal['en', 'ko']", language),
                        rank=ids.index(chunk_id) + 1,
                    )
                )
        return tuple(ranks)

    def _registry_name(self, doc_id: str) -> str | None:
        """Return the publishing registry of an indexed document, or ``None`` when unknown."""
        metadata = self._manifest_scope_index().documents.get(doc_id)
        return None if metadata is None else metadata.registry

    def _candidate_resource(
        self,
        hit: ChunkHit,
        *,
        rank: int,
        result: RetrievalResult,
    ) -> EvidenceCandidate:
        """Combine one hit with manifest filing and component-rank provenance."""
        metadata = self._manifest_scope_index().documents.get(hit.doc_id)
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
                request = request.model_copy(
                    update={"session_profile": await self._local_profile(request.session_profile)}
                )
                gate, path = await self._path_decision(request)
                if gate is not None and gate.intent == "casual_chat":
                    return RetrieveResponse(
                        query=request.query,
                        results=(),
                        candidates=(),
                        candidate_token=None,
                        candidate_expires_at=0,
                        score_stage="rrf",
                        component_rankings={},
                        resolved_profile=resolve_retrieval_profile(request.session_profile),
                        resolved_scope=None,
                        path_decision=path,
                    )
                async with stage("route") as routing_stage:
                    routing_stage.path_decision = path
                    profile, scope = self._path_scope(request, path)
                    routing_stage.resolved_scope = scope.model_dump(mode="json")
                retrieval_query = cast("str", path["retrieval_query"])
                routed_queries: dict[str, str] = {}
                if self._query_routing_enabled and profile.route_by_language:
                    source_language = detect_query_language(retrieval_query)
                    for language in scope.filters.languages or ("en",):
                        if language == source_language:
                            continue
                        provider, budget = await self._engine(request)
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
                selection_id=request.selection_id,
                embedding_provider=self._embedding_provider,
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
            request = request.model_copy(
                update={"session_profile": await self._local_profile(request.session_profile)}
            )
            decision, path = await self._path_decision(request)
            if decision.intent == "casual_chat":
                return await self._casual_report(request, decision, path)
            return await self._review(request, on_node=on_node, retrieval_override=None, path=path)

    async def _local_profile(self, profile: ReviewSessionProfile) -> ReviewSessionProfile:
        """Pin one discovered model without replacing an explicit unavailable selection."""
        if profile.engine != "local":
            return profile
        self._validate_session_profile(profile)
        context = self._local_request.get()
        if context is not None and context.model is not None:
            return profile.model_copy(update={"local_model": context.model})
        inventory = context.inventory if context is not None else self.local_inventory
        if inventory is None:
            raise unavailable("local_model_unavailable", "The local model server is disconnected.")
        snapshot = await inventory.snapshot()
        available = snapshot.available_models
        if snapshot.reason is not None or not available:
            raise unavailable(
                "local_model_unavailable", "No answer model is available on the local server."
            )
        selected = profile.local_model
        if selected is None:
            if len(available) != 1:
                raise bad_request(
                    "local_model_required", "Choose a local answer model before sending a question."
                )
            selected = available[0]
        if selected not in available:
            raise unavailable(
                "local_model_unavailable", "The selected local model is no longer available."
            )
        if context is not None:
            context.model = selected
            context.model_digest = inventory.model_digest(selected)
        return profile.model_copy(update={"local_model": selected})

    async def _engine(
        self, request: ReviewRequest | RetrieveRequest
    ) -> tuple[LLMProvider, ProviderBudget]:
        """Resolve a request-specific provider without changing any other conversation."""
        profile = await self._local_profile(request.session_profile)
        engine = profile.engine
        budget = self._provider_budgets.get(engine)
        context = self._local_request.get()
        inventory = context.inventory if context is not None else self.local_inventory
        if engine == "local" and inventory is not None and budget is not None:
            if context is not None and context.provider is not None:
                return context.provider, budget
            assert profile.local_model is not None
            provider = build_local_provider(
                base_url=inventory.base_url,
                model_name=profile.local_model,
                protocol=inventory.protocol,
                api_key=inventory.api_key,
                timeout_s=self._local_timeout_s,
                context_window=budget.max_input_tokens + budget.max_output_tokens,
            )
            if context is not None:
                context.provider = provider
            return provider, budget
        provider = self._llm_providers.get(engine)
        if provider is None or budget is None:
            raise unavailable(
                "provider_unavailable",
                f"Review engine {engine!r} is not configured.",
            )
        return provider, budget

    async def _classify_intent(self, request: ReviewRequest) -> ConversationDecision:
        """Classify only an input the deterministic gate cannot decide."""
        provider, budget = await self._engine(request)
        result = await provider.complete(
            Prompt(
                system=(
                    "Classify whether the user asks to review SEC or DART filing evidence, "
                    "or is having casual conversation. Do not answer the user."
                ),
                user=json.dumps(
                    {
                        "history": [
                            turn.model_dump(mode="json") for turn in self._history(request)
                        ],
                        "message": request.query,
                    },
                    ensure_ascii=False,
                ),
            ),
            IntentClassification,
            budget,
        )
        if result.status != "ok" or result.parsed is None:
            raise unavailable(
                "provider_unavailable",
                f"Intent classification failed ({result.status}).",
            )
        return ConversationDecision(
            intent=result.parsed.intent,
            source="classifier",
            matched_rule="structured_classifier",
            rationale=result.parsed.reason,
        )

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
        context = self._local_request.get()
        inventory = context.inventory if context is not None else self.local_inventory
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
                model_digest=context.model_digest if context is not None else None,
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
        """Persist a retrieval-free canned or selected-engine conversation response."""
        run_id = self._run_id_factory()
        traces: tuple[StepTrace, ...] = ()
        source = "canned"
        answer = decision.canned_answer
        provider = None
        budget = None
        if answer is None:
            provider, budget = await self._engine(request)
            history = [turn.model_dump(mode="json") for turn in self._history(request)]
            async with stage("chat"):
                result = await provider.complete(
                    Prompt(
                        system=(
                            "Reply briefly and conversationally. Do not claim to have searched "
                            "filing "
                            "evidence, do not invent citations, and do not output NOT_IN_DOCS."
                        ),
                        user=json.dumps(
                            {"history": history, "message": request.query},
                            ensure_ascii=False,
                        ),
                    ),
                    ChatReply,
                    budget,
                )
                if result.status != "ok" or result.parsed is None:
                    raise unavailable(
                        "provider_unavailable",
                        f"Conversation reply failed ({result.status}).",
                    )
                answer = result.parsed.answer
                traces = (step_trace_from_provider_result(result, step=1, node="chat"),)
                source = "engine"
        report = build_run_report(
            run_id=run_id,
            status="ok",
            total_time_seconds=0.0,
            system_prompt="Retrieval-free conversation gate.",
            node_path=("gate", "chat", "report") if traces else ("gate", "report"),
            steps=traces,
            report={
                "report_kind": "conversation",
                "answer": answer,
                "response_source": source,
            },
            request_context={
                **await self._execution_context(provider, budget, request, chat_only=True),
                "stage_results": [{"node": "gate", "intent": decision.model_dump(mode="json")}],
                "routing_queries": {},
                "intent": decision.model_dump(mode="json"),
                "path_decision": path,
                "engine": request.session_profile.engine,
                "history_turns": len(self._history(request)),
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
        request = request.model_copy(
            update={"session_profile": await self._local_profile(request.session_profile)}
        )
        llm_provider, provider_budget = await self._engine(request)
        engine = request.session_profile.engine
        if request.session_profile.snapshot_id is not None:
            async with self._session_factory() as validation_session:
                selected_snapshot = await validation_session.get(
                    EvaluationSnapshot, request.session_profile.snapshot_id
                )
            if selected_snapshot is None or selected_snapshot.status != "ready":
                raise bad_request("snapshot_unavailable", "Selected snapshot is not ready.")
        if path is None:
            _, path = await self._path_decision(request)
        async with stage("route") as routing_stage:
            routing_stage.path_decision = path
            profile, scope = self._path_scope(request, path)
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
        routed_queries: dict[str, str] = dict(snapshot.routing_queries or {}) if snapshot else {}
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
                            self._manifest_scope_index().documents[hit.doc_id].language,
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

                report = await self._workflow_service(
                    workflow_request,
                    retriever=retrieve_for_workflow,
                    provider=llm_provider,
                    on_node=record_node,
                )
                execution = await self._execution_context(llm_provider, provider_budget, request)
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
                            "requested_profile": request.session_profile.model_dump(mode="json"),
                            "resolved_profile": profile.model_dump(mode="json"),
                            "resolved_scope": scope.model_dump(mode="json"),
                            "routing_queries": routed_queries
                            if snapshot is None or snapshot.routing_queries is not None
                            else None,
                            "selection": (
                                {
                                    "candidate_snapshot_sha256": hashlib.sha256(
                                        request.evidence_selection.candidate_token.encode("utf-8")
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
    providers: dict[str, LLMProvider] = {}
    budgets: dict[str, ProviderBudget] = {}
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
        providers["openai"] = llm_provider
        budgets["openai"] = provider_budget
    local_connection, local_budget = build_local_runtime(
        environment=configured.environment,
        base_url=configured.local_llm_base_url,
        protocol=configured.local_llm_protocol,
        source=configured.local_llm_source,
        api_key=configured.local_llm_api_key.get_secret_value()
        if configured.local_llm_api_key
        else None,
        max_input_tokens=configured.local_llm_max_input_tokens,
        max_output_tokens=configured.local_llm_max_output_tokens,
    )
    if local_budget is not None:
        budgets["local"] = local_budget
    secret_values = tuple(
        secret.get_secret_value()
        for secret in (
            configured.openai_api_key,
            configured.dart_api_key,
            configured.local_llm_api_key,
        )
        if secret is not None and secret.get_secret_value().strip()
    )
    return RuntimeApiServices(
        embedding_provider=get_embedding_provider(configured),
        llm_provider=llm_provider,
        provider_budget=provider_budget,
        llm_providers=providers,
        provider_budgets=budgets,
        local_connection=local_connection,
        allow_local_engine=configured.environment != "prod",
        local_timeout_s=configured.local_llm_timeout_s,
        secret_values=secret_values,
        credential_slot=configured.openai_key_slot,
        route_by_language=configured.query_language_routing,
        lexical_ranker=configured.lexical_ranker,
        bm25_k1=configured.bm25_k1,
        bm25_b=configured.bm25_b,
        bm25_idf=configured.bm25_idf,
        corpus_root=configured.corpus_dir,
        intent_classifier_enabled=True,
        query_routing_enabled=True,
    )
