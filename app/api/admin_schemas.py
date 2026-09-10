"""Strict API contracts for local corpus and retrieval experimentation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from app.api.schemas import EvidenceHit, RunResponse
from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf, LexicalRanker
from app.evals.source_binding import SourceCheck
from app.llm.local_connection import ConnectionSource, LocalProtocol, validate_base_url
from app.llm.openai_limits import OpenAICallLimits
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.types import RetrievalFilters

type RetrievalStrategy = Literal["vector", "lexical", "hybrid"]
type RerankerName = Literal["cross_encoder"]
type GoldenSuiteId = Literal[
    "sec-en",
    "sec-ko",
    "dart-en",
    "dart-ko",
    "sec-en_v2_astra",
    "sec-ko_v2_astra",
    "sec-mixed_v2_astra",
]
type EvaluationMode = Literal["quick", "matrix"]
type EvaluationJobStatus = Literal[
    "queued", "running", "succeeded", "failed", "interrupted", "cancelled"
]
type CorpusOperationKind = Literal[
    "acquire_edgar",
    "acquire_dart",
    "ingest_manifest",
    "ingest_selected",
    "delete_sources",
    "backfill_embeddings",
    "rebuild_bm25",
]
type DocumentSort = Literal[
    "doc_id",
    "issuer",
    "fiscal_year",
    "filing_date",
    "chunk_count",
    "embedding_coverage",
]
type DocumentEmbeddingStatus = Literal["complete", "partial", "missing"]

PositiveInt = Annotated[StrictInt, Field(gt=0)]
FinitePositive = Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)]
UnitFloat = Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]


def _tuple_from_json_array(value: object) -> object:
    """Normalize the JSON array representation without coercing child values."""
    return tuple(value) if isinstance(value, list) else value


class StrictAdminModel(BaseModel):
    """Forbid coercion and unknown fields at the local administrator boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RetrievalProfile(StrictAdminModel):
    """One explicit retrieval plan that never mutates process-wide settings."""

    strategy: RetrievalStrategy = "hybrid"
    k: Annotated[StrictInt, Field(gt=0, le=100)] = 5
    candidate_k: Annotated[StrictInt, Field(gt=0, le=500)] = 20
    rrf_k: Annotated[StrictInt, Field(gt=0, le=10_000)] = DEFAULT_RRF_K
    lexical_ranker: LexicalRanker | None = "ts_rank_cd"
    bm25_k1: FinitePositive = DEFAULT_BM25_K1
    bm25_b: UnitFloat = DEFAULT_BM25_B
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF
    route_by_language: StrictBool = False
    reranker: RerankerName | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        """Reject contradictory lanes, depths, routing, and reranking."""
        if self.candidate_k < self.k:
            raise ValueError("candidate_k must be at least k")
        if self.strategy == "vector" and self.lexical_ranker is not None:
            raise ValueError("vector strategy must not name a lexical ranker")
        if self.strategy != "vector" and self.lexical_ranker is None:
            raise ValueError("lexical and hybrid strategies require a lexical ranker")
        if self.route_by_language and self.strategy != "hybrid":
            raise ValueError("language routing requires the hybrid strategy")
        if self.reranker is not None and self.strategy != "hybrid":
            raise ValueError("reranking requires the hybrid strategy")
        return self


class EvaluationPreparationResource(StrictAdminModel):
    """Separate golden provenance from readiness of the currently requested corpus and index."""

    suite_id: GoldenSuiteId
    kind: Literal["builtin", "user"]
    verification_status: Literal["pending_review", "verified"] = "pending_review"
    state: Literal[
        "ready",
        "source_missing",
        "source_invalid",
        "draft_incomplete",
        "parsing_required",
        "index_update_required",
        "unavailable",
    ]
    source_checks: tuple[SourceCheck, ...] = ()
    next_step: Literal["filings", "index", "embeddings", "lexical", "setup"] | None = None
    blockers: tuple[str, ...] = ()
    golden_sha256: str | None = None


class GoldenSuiteResource(StrictAdminModel):
    """One immutable golden suite exposed to the experiment selector."""

    suite_id: GoldenSuiteId
    label: str
    title: str
    filename: str
    registry: Literal["sec", "dart"]
    question_language: Literal["en", "ko", "mixed"]
    corpus_language: Literal["en", "ko"]
    case_count: PositiveInt
    scored_positive_cases: PositiveInt
    absent_cases: Annotated[StrictInt, Field(ge=0)]
    curation_status: Literal["agent-curated"]
    approval_status: Literal["pending-author-approval"]
    human_verified: Literal[False]
    golden_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_ready: StrictBool
    source_checks: tuple[SourceCheck, ...] = ()
    source_error: str | None = None
    source_error_code: Literal["source_missing", "source_invalid"] | None = None


class GoldenRevisionResource(StrictAdminModel):
    """One independent user dataset file with its content identity."""

    revision_id: PositiveInt
    filename: str
    file_content: dict[str, object] = Field(default_factory=dict)
    completion: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    suite_id: GoldenSuiteId
    version: PositiveInt
    status: Literal["draft", "validated", "published"]
    payload: tuple[dict[str, object], ...]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    parent_id: PositiveInt | None
    created_at: datetime
    updated_at: datetime


class GoldenCanonicalResource(StrictAdminModel):
    """Validated read-only canonical JSON for one golden suite."""

    suite_id: GoldenSuiteId
    filename: str
    payload: tuple[dict[str, object], ...]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GoldenDraftRequest(StrictAdminModel):
    """Create a named JSON file, empty or copied from a selected dataset."""

    filename: str
    empty: bool = False
    parent_id: PositiveInt | None = None


class GoldenCaseUpdateRequest(StrictAdminModel):
    """Optimistically replace one case inside a draft revision."""

    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    case: dict[str, object]


class GoldenRevisionActionRequest(StrictAdminModel):
    """Apply one state transition only to the expected revision bytes."""

    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SnapshotCreateRequest(StrictAdminModel):
    """Create one immutable snapshot from a persisted evaluation result."""

    label: Annotated[str, Field(min_length=1, max_length=128)]
    eval_result_id: PositiveInt
    golden_revision_id: PositiveInt | None = None
    public: StrictBool = False


class SnapshotVisibilityRequest(StrictAdminModel):
    """Change only whether a ready snapshot is publicly listable."""

    public: StrictBool


class EvaluationRunRequest(StrictAdminModel):
    """Queue one quick live-index run or isolated retrieval matrix."""

    suite_id: GoldenSuiteId
    golden_revision_id: PositiveInt | None = None
    mode: EvaluationMode = "quick"
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    target_tokens: Annotated[
        tuple[PositiveInt, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = (1024, 2048)
    strategies: Annotated[
        tuple[RetrievalStrategy, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = ("lexical", "vector", "hybrid")
    lexical_rankers: Annotated[
        tuple[LexicalRanker, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = ("ts_rank_cd", "bm25")

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        """Require unique nonempty matrix axes while keeping quick runs singular."""
        if not self.target_tokens or len(set(self.target_tokens)) != len(self.target_tokens):
            raise ValueError("target_tokens must be nonempty and unique")
        if not self.strategies or len(set(self.strategies)) != len(self.strategies):
            raise ValueError("strategies must be nonempty and unique")
        if not self.lexical_rankers or len(set(self.lexical_rankers)) != len(self.lexical_rankers):
            raise ValueError("lexical_rankers must be nonempty and unique")
        if self.mode == "matrix" and (
            self.profile.reranker is not None or self.profile.route_by_language
        ):
            raise ValueError("matrix runs do not support reranking or language routing")
        return self


class CorpusOperationRequest(StrictAdminModel):
    """One safe corpus operation accepted by the local operator API."""

    kind: CorpusOperationKind
    document_ids: Annotated[tuple[str, ...] | None, BeforeValidator(_tuple_from_json_array)] = None
    deletion_token: str | None = None
    confirm_delete: StrictBool | None = None
    identifiers: Annotated[
        tuple[str, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = ()
    years: Annotated[
        tuple[PositiveInt, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = ()
    manifest: str | None = None
    selection_id: str | None = None
    expected_documents: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        """Require exact source selections and explicit deletion confirmation."""
        if self.kind == "delete_sources":
            if not self.deletion_token or self.confirm_delete is not True:
                raise ValueError(
                    "Source deletion requires a preview token and explicit confirmation."
                )
            if (
                self.identifiers
                or self.years
                or self.manifest
                or self.selection_id
                or self.document_ids
            ):
                raise ValueError("Deletion targets must come from the confirmed preview.")
        elif self.deletion_token is not None or self.confirm_delete is not None:
            raise ValueError("Deletion confirmation applies only to source deletion.")
        if self.kind == "ingest_selected" and (
            not self.document_ids or len(set(self.document_ids)) != len(self.document_ids)
        ):
            raise ValueError("ingest_selected requires nonempty unique document_ids")
        if self.kind == "ingest_manifest" and (
            not (self.manifest or "").strip() or not (self.selection_id or "").strip()
        ):
            raise ValueError("ingestion requires a manifest and selection_id")
        return self


class ProcessingSelectionResource(StrictAdminModel):
    """One exact document selection available for processing."""

    selection_id: str
    document_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    sources_present: NonnegativeInt


class ManifestIssuerResource(StrictAdminModel):
    """A company and source registry available before ingestion."""

    registry: Literal["sec", "dart"]
    issuer: str
    name: str


class ManifestResource(StrictAdminModel):
    """A common corpus catalog and its available processing selections."""

    name: str
    corpus_id: str | None
    documents: NonnegativeInt | None
    valid: StrictBool
    registries: tuple[Literal["sec", "dart"], ...]
    sources_present: NonnegativeInt | None
    selections: tuple[ProcessingSelectionResource, ...]
    issuers: tuple[ManifestIssuerResource, ...] = ()


class CorpusStatusResource(StrictAdminModel):
    """Current preparation state shared by CLI and web."""

    database_connected: StrictBool
    schema_status: Literal["compatible", "empty", "drifted", "unavailable"]
    schema_message: str
    documents: NonnegativeInt
    chunks: NonnegativeInt
    embedded_chunks: NonnegativeInt
    pending_embeddings: NonnegativeInt
    bm25_ready: StrictBool
    bm25_rebuild_recorded: StrictBool | None = None
    writable: StrictBool = Field(
        description=(
            "Source directory write permission, independent of database schema compatibility."
        )
    )
    provider: str


class CorpusDocumentResource(StrictAdminModel):
    """An ingested filing summarized in preparation state."""

    doc_id: str
    registry: str
    language: str
    issuer: str
    issuer_name: str | None = None
    issuer_id: str
    fiscal_year: StrictInt
    form: str
    parse_status: str
    filing_date: str
    report_period: str
    filing_id: str
    source_url: str
    source_length: NonnegativeInt
    source_sha256: str
    chunk_count: NonnegativeInt


class SourceDeletionRequest(StrictAdminModel):
    """Preview the exact acquired filing identities selected in step one."""

    document_ids: Annotated[
        tuple[str, ...],
        BeforeValidator(_tuple_from_json_array),
        Field(min_length=1, max_length=200),
    ]


class SourceDeletionDocument(StrictAdminModel):
    """Show the official filing identity before original-file deletion is confirmed."""

    document_id: str
    registry: Literal["sec", "dart"]
    issuer: str
    fiscal_year: int
    filing_id: str


class SourceDeletionFile(StrictAdminModel):
    """Distinguish current files to remove from inputs retained for other recorded scopes."""

    path: str
    byte_length: NonnegativeInt
    retained: StrictBool


class SourceDeletionPreviewResource(StrictAdminModel):
    """A short-lived confirmation bound to exact files and the current catalog."""

    token: str
    expires_at: float
    documents: tuple[SourceDeletionDocument, ...]
    files: tuple[SourceDeletionFile, ...]
    retained_inputs: NonnegativeInt
    retained_derived: Literal[True] = True


class SourceInventoryResource(StrictAdminModel):
    """Downloaded source identity independent of database rows."""

    manifest: str
    document_id: str
    registry: Literal["sec", "dart"]
    issuer: str
    name: str
    fiscal_year: int
    filing_id: str
    on_disk: StrictBool
    ready: StrictBool
    blocker: str | None = None
    can_redownload: StrictBool


class AcquisitionPairResource(StrictAdminModel):
    """Preserve an exact intended filing without a mixed-registry cross product."""

    registry: Literal["sec", "dart"]
    issuer: str
    year: StrictInt


class AcquisitionDraftResource(StrictAdminModel):
    """Server-provided initial company and fiscal-year selection."""

    pairs: Annotated[tuple[AcquisitionPairResource, ...], BeforeValidator(_tuple_from_json_array)]
    revision: str

    identifiers: Annotated[tuple[str, ...], BeforeValidator(_tuple_from_json_array)]
    years: Annotated[tuple[int, ...], BeforeValidator(_tuple_from_json_array)]


class CorpusSnapshotResource(StrictAdminModel):
    """Atomic typed preparation state with explicit source selections."""

    mode: Literal["live", "canned"]
    status: CorpusStatusResource
    manifests: tuple[ManifestResource, ...]
    documents: tuple[CorpusDocumentResource, ...]
    sources: tuple[SourceInventoryResource, ...] = ()
    acquisition_draft: AcquisitionDraftResource | None = None
    acquisition_companies: tuple[ManifestIssuerResource, ...] = ()


class CorpusJobResource(StrictAdminModel):
    """The same corpus job snapshot returned to CLI and web clients."""

    job_id: str
    command: CorpusOperationRequest
    status: Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]
    stage: str
    current: NonnegativeInt
    total: NonnegativeInt | None
    message: str
    detail_current: NonnegativeInt | None
    detail_total: NonnegativeInt | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    result_refs: dict[str, object] | None


class CorpusJobsResource(StrictAdminModel):
    """Current and terminal snapshots of the shared corpus job queue."""

    active: CorpusJobResource | None
    queued: tuple[CorpusJobResource, ...]
    history: tuple[CorpusJobResource, ...]


class AdminDocumentResource(StrictAdminModel):
    """One filing row with current chunk and embedding coverage."""

    doc_id: str
    registry: str
    language: str
    issuer: str
    issuer_name: str | None = None
    issuer_id: str
    fiscal_year: StrictInt
    form: str
    filing_date: str
    report_period: str
    filing_id: str
    source_url: str
    parse_status: str
    source_length: PositiveInt
    source_sha256: str
    chunk_count: NonnegativeInt
    embedded_chunks: NonnegativeInt
    text_chunks: NonnegativeInt
    table_chunks: NonnegativeInt
    embedding_status: DocumentEmbeddingStatus
    snapshot_count: NonnegativeInt


class DocumentInventoryResponse(StrictAdminModel):
    """One filtered deterministic document page."""

    documents: tuple[AdminDocumentResource, ...]
    total: NonnegativeInt
    next_cursor: str | None


class DocumentFacetValue(StrictAdminModel):
    """One filter value and its document count."""

    value: str
    count: PositiveInt
    label: str | None = None


class DocumentFacetsResponse(StrictAdminModel):
    """Available document facets computed from live rows."""

    registries: tuple[DocumentFacetValue, ...]
    issuers: tuple[DocumentFacetValue, ...]
    years: tuple[DocumentFacetValue, ...]
    languages: tuple[DocumentFacetValue, ...]
    forms: tuple[DocumentFacetValue, ...]
    sections: tuple[DocumentFacetValue, ...] = ()
    parse_statuses: tuple[DocumentFacetValue, ...]
    embedding_statuses: tuple[DocumentFacetValue, ...]
    snapshots: tuple[DocumentFacetValue, ...]


class DocumentMetadataResource(StrictAdminModel):
    """Immutable filing metadata for one selected document."""

    doc_id: str
    registry: str
    language: str
    issuer: str
    issuer_name: str | None = None
    issuer_id: str
    fiscal_year: StrictInt
    form: str
    parse_status: str
    filing_date: str
    report_period: str
    filing_id: str
    source_url: str
    source_length: PositiveInt
    source_sha256: str
    chunk_count: NonnegativeInt


class DocumentChunkPreviewResource(StrictAdminModel):
    """One bounded source-cited chunk preview."""

    chunk_id: PositiveInt
    ordinal: NonnegativeInt
    citation: str
    span: str
    source_sha256: str
    body: str


class DocumentItemCountResource(StrictAdminModel):
    """Chunk count for one filing section identity."""

    item: str
    count: PositiveInt


class DocumentEmbeddingIdentityResource(StrictAdminModel):
    """Embedding identity and coverage for one selected filing."""

    provider: str
    model: str
    dimensions: PositiveInt
    tokenizer: str
    count: PositiveInt


class DocumentSnapshotMembershipResource(StrictAdminModel):
    """One immutable snapshot revision containing the selected filing."""

    snapshot_id: PositiveInt
    label: str
    status: Literal["ready", "archived"]
    public: StrictBool
    created_at: datetime


class DocumentDetailResponse(StrictAdminModel):
    """Structured filing identity, index coverage, and source previews."""

    document: DocumentMetadataResource
    chunks: tuple[DocumentChunkPreviewResource, ...]
    text_chunks: NonnegativeInt
    table_chunks: NonnegativeInt
    embedded_chunks: NonnegativeInt
    item_counts: tuple[DocumentItemCountResource, ...]
    embedding_identities: tuple[DocumentEmbeddingIdentityResource, ...]
    snapshot_memberships: tuple[DocumentSnapshotMembershipResource, ...]


class EvaluationResultSummaryResource(StrictAdminModel):
    """Recorded inputs for one result, including individual matrix configurations."""

    result_id: PositiveInt
    created_at: datetime
    config: dict[str, Any]


class EvaluationJobResource(StrictAdminModel):
    """One background evaluation job and its bounded safe output."""

    job_id: str
    request: EvaluationRunRequest
    status: EvaluationJobStatus
    stage: str
    message: str
    current: Annotated[StrictInt, Field(ge=0)] = 0
    total: Annotated[StrictInt, Field(ge=0)] | None = None
    result_id: PositiveInt | None = None
    result_ids: tuple[PositiveInt, ...] = ()
    result_summaries: tuple[EvaluationResultSummaryResource, ...] = ()
    baseline_id: PositiveInt | None = None
    artifact_paths: tuple[str, ...] = ()
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EvaluationJobsResponse(StrictAdminModel):
    """Newest-first bounded evaluation job collection."""

    jobs: tuple[EvaluationJobResource, ...]


class OperatorJobResource(StrictAdminModel):
    """One persisted corpus or evaluation job with queue and progress state."""

    job_id: str
    domain: Literal["corpus", "evaluation"]
    kind: str
    request: dict[str, object]
    status: Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]
    stage: str
    current: NonnegativeInt
    total: NonnegativeInt | None
    detail_current: NonnegativeInt | None
    detail_total: NonnegativeInt | None
    overall_current: NonnegativeInt | None = None
    overall_total: NonnegativeInt | None = None
    stage_index: PositiveInt | None = None
    stage_count: PositiveInt | None = None
    stage_started_at: datetime | None = None
    progress_stage: str | None = None
    message: str
    error_code: str | None
    result_refs: dict[str, object]
    queue_position: PositiveInt | None
    can_cancel: StrictBool
    can_retry: StrictBool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class OperatorJobsResponse(StrictAdminModel):
    """Newest persisted jobs plus active and queued summary counts."""

    jobs: tuple[OperatorJobResource, ...]
    active_count: NonnegativeInt
    queued_count: NonnegativeInt


class UsageModelResource(StrictAdminModel):
    """One model's locally recorded token and estimated-cost totals."""

    model_name: str
    provider: str = "unknown"
    local: StrictBool | None = None
    credential_slot: str = "unknown"
    role: str = "unknown"
    estimated_input_tokens: NonnegativeInt = 0
    unreported_input_requests: NonnegativeInt = 0
    unreported_cost_requests: NonnegativeInt = 0
    requests: NonnegativeInt
    input_tokens: NonnegativeInt
    cached_input_tokens: NonnegativeInt
    cache_write_input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    reasoning_tokens: NonnegativeInt
    estimated_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)


class UsageProviderResource(StrictAdminModel):
    """One provider/credential group with exact subtotals of its model-role rows."""

    provider: str
    local: StrictBool | None
    credential_slot: str
    requests: NonnegativeInt
    input_tokens: NonnegativeInt
    cached_input_tokens: NonnegativeInt
    cache_write_input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    reasoning_tokens: NonnegativeInt
    estimated_input_tokens: NonnegativeInt
    unreported_input_requests: NonnegativeInt
    unreported_cost_requests: NonnegativeInt
    estimated_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    models: tuple[UsageModelResource, ...]


class UsageResponse(StrictAdminModel):
    """Locally accounted provider usage without an OpenAI account API call."""

    runs: NonnegativeInt
    requests: NonnegativeInt
    input_tokens: NonnegativeInt
    cached_input_tokens: NonnegativeInt
    cache_write_input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    reasoning_tokens: NonnegativeInt
    estimated_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    latest_run_at: datetime | None
    models: tuple[UsageModelResource, ...]
    providers: tuple[UsageProviderResource, ...] = ()
    estimated_input_tokens: NonnegativeInt = 0
    unreported_input_requests: NonnegativeInt = 0
    unreported_cost_requests: NonnegativeInt = 0


class RetrievalPreviewRequest(StrictAdminModel):
    """One query evaluated through an explicit session-scoped retrieval profile."""

    query: Annotated[str, Field(min_length=1, max_length=10_000)]
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class RetrievalPreviewResponse(StrictAdminModel):
    """Ranked evidence plus component provenance for API inspection."""

    query: str
    profile: RetrievalProfile
    score_stage: Literal["rrf", "reranker"]
    # `vector`/`lexical` hold one rank list each; the `*_by_language` entries nest one
    # list per routed query language, mirroring `ComponentRankings`.
    component_rankings: dict[str, tuple[PositiveInt, ...] | dict[str, tuple[PositiveInt, ...]]]
    results: tuple[EvidenceHit, ...]


class ReviewPreviewRequest(StrictAdminModel):
    """One evidence-checked review using a session-scoped retrieval profile."""

    query: Annotated[str, Field(min_length=1, max_length=10_000)]
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class ReviewPreviewResponse(StrictAdminModel):
    """Review output paired with the retrieval profile that produced its evidence."""

    profile: RetrievalProfile
    run: RunResponse


class EvaluationMetricDelta(StrictAdminModel):
    """One candidate metric and its signed change from a baseline."""

    name: str
    baseline: StrictFloat
    candidate: StrictFloat
    delta: StrictFloat


class EvaluationCaseDelta(StrictAdminModel):
    """One golden case's rank and citation movement between two runs."""

    case_id: str
    question: str
    baseline_rank: PositiveInt | None
    candidate_rank: PositiveInt | None
    transition: Literal["stable_hit", "stable_miss", "miss_to_hit", "hit_to_miss"]
    rank_delta: StrictInt | None
    baseline_citations: tuple[str, ...]
    candidate_citations: tuple[str, ...]


class EvaluationComparisonResponse(StrictAdminModel):
    """Metric and case-level comparison between compatible stored artifacts."""

    baseline_id: PositiveInt
    candidate_id: PositiveInt
    suite: str
    metrics: tuple[EvaluationMetricDelta, ...]
    cases: tuple[EvaluationCaseDelta, ...]


class EvaluationCaseSummary(StrictAdminModel):
    """One bounded absolute case result from a persisted evaluation artifact."""

    case_id: str
    question: str
    first_relevant_rank: PositiveInt | None
    citations: tuple[str, ...]


class EvaluationResultDetailResponse(StrictAdminModel):
    """Absolute metrics, configuration, and bounded cases for one result."""

    result_id: PositiveInt
    suite: str
    config: dict[str, object]
    metrics: dict[str, StrictFloat]
    cases: tuple[EvaluationCaseSummary, ...]
    raw_artifact_path: str
    created_at: datetime


class LocalConnectionRequest(BaseModel):
    """A candidate endpoint entered in the developer connection settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str = Field(min_length=1, max_length=2048)
    protocol: LocalProtocol = "auto"

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        """Reject credentials and non-HTTP addresses before any server request."""
        return validate_base_url(value)


class LocalModelPrepareRequest(BaseModel):
    """Name an installed model on the already selected server, never an arbitrary endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str = Field(min_length=1, max_length=256)


class LocalConnectionResponse(BaseModel):
    """Private settings state and safe model metadata for the developer UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str | None
    initial_base_url: str
    protocol: LocalProtocol
    source: ConnectionSource
    error: str | None
    local: dict[str, Any]
    servers: tuple[LocalServerResource, ...]
    selected_server_id: str | None


class LocalServerResource(BaseModel):
    """A named private endpoint, including the runtime-resolved Default entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    base_url: str
    protocol: LocalProtocol
    is_default: bool


class OpenAILimitsRequest(BaseModel):
    """Working per-call caps for Dev; each value must stay at or below the ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_input_tokens: int = Field(ge=1, le=100_000)
    max_output_tokens: int = Field(ge=1, le=4_000)
    max_cost_usd: Decimal = Field(gt=0, le=1)


class OpenAILimitsResponse(OpenAICallLimits):
    """Effective caps, their ceiling and where to raise the ceiling outside the web."""

    ceiling_env_keys: dict[str, str]
    file_path: str


class LocalServerRequest(LocalConnectionRequest):
    """Register and connect a named server without editing environment configuration."""

    name: str = Field(min_length=1, max_length=80)


class LocalServerSelectionRequest(BaseModel):
    """Select one registered server or the built-in Default identifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    server_id: str = Field(min_length=1, max_length=80)


class LocalDiagnosticsRequest(BaseModel):
    """Choose the active connection, a registered server, or one unsaved draft to inspect."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    server_id: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    protocol: LocalProtocol = "auto"

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        """Reject secret-bearing addresses before a diagnostic metadata probe."""
        return validate_base_url(value) if value is not None else None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Require one unambiguous target so a draft cannot override a selected identifier."""
        if self.server_id is not None and self.base_url is not None:
            raise ValueError("Choose a registered server or a draft URL, not both.")
        return self


class LocalDiagnosticCheck(BaseModel):
    """One nonsecret status and its predefined remediation identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Literal["configuration", "connection", "models"]
    status: Literal["passed", "failed", "blocked", "unknown"]
    code: str
    remediation: tuple[str, ...]


class LocalDiagnosticsResponse(BaseModel):
    """Metadata-only diagnostic evidence without raw errors, paths, or credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    checked_at: str
    server_id: str | None
    server_name: str
    protocol: LocalProtocol
    reachable: bool | None
    available: bool
    model_count: int | None
    answer_model_count: int | None
    models: tuple[dict[str, Any], ...]
    checks: tuple[LocalDiagnosticCheck, ...]


class JobHistorySummaryResource(StrictAdminModel):
    """Terminal history counts and protected active jobs."""

    visible: NonnegativeInt
    archived: NonnegativeInt
    active: NonnegativeInt


class JobHistoryRequest(StrictAdminModel):
    """An explicit history operation against a reviewed eligible count."""

    action: Literal["archive", "restore", "delete"]
    expected_count: NonnegativeInt
    confirmation: str = ""


class JobHistoryResultResource(StrictAdminModel):
    """Confirmed history changes and a private backup reference."""

    action: Literal["archive", "restore", "delete"]
    changed_count: NonnegativeInt
    backup_id: str | None
    summary: JobHistorySummaryResource


class GoldenEvidenceChunk(StrictAdminModel):
    """One selectable chunk with exact original-source coordinates."""

    chunk_id: PositiveInt
    doc_id: str
    source_sha256: str
    start_char: NonnegativeInt
    end_char: PositiveInt
    item: str | None
    kind: str
    body: str
    citation: str


class GoldenEvidencePage(StrictAdminModel):
    """A bounded page for choosing evidence without running retrieval or a model."""

    chunks: tuple[GoldenEvidenceChunk, ...]
    next_after: int | None = None
