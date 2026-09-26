"""Evaluation jobs, golden datasets, and immutable snapshot boundary values."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from app.config import LexicalRanker
from app.contracts.validation import (
    FiniteFloat,
    NonBlank,
    NonNegativeInt,
    PositiveInt,
    StrictSchema,
    tuple_from_json_array,
)
from app.evals.golden.binding import SourceCheck
from app.evals.golden.models import GoldenSpan
from app.retrieval.search.plan import RetrievalStrategy
from app.retrieval.search.profiles import RetrievalProfile

JsonObject = dict[str, JsonValue]

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


class EvaluationPreparationResource(StrictSchema):
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


class GoldenSuiteResource(StrictSchema):
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


class GoldenRevisionResource(StrictSchema):
    """One independent user dataset file with its content identity."""

    revision_id: PositiveInt
    filename: str
    file_content: dict[str, object] = Field(default_factory=dict)
    completion: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    suite_id: GoldenSuiteId
    status: Literal["draft", "validated"]
    payload: tuple[dict[str, object], ...]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    created_at: datetime
    updated_at: datetime


class GoldenCanonicalResource(StrictSchema):
    """Validated read-only canonical JSON for one golden suite."""

    suite_id: GoldenSuiteId
    filename: str
    payload: tuple[dict[str, object], ...]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GoldenDraftRequest(StrictSchema):
    """Create a named JSON file, empty or copied from a selected dataset."""

    filename: str
    empty: bool = False
    parent_id: PositiveInt | None = None


class GoldenCaseUpdateRequest(StrictSchema):
    """Optimistically replace one case inside a draft revision."""

    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    case: dict[str, object]


class GoldenRevisionActionRequest(StrictSchema):
    """Apply one state transition only to the expected revision bytes."""

    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SnapshotCreateRequest(StrictSchema):
    """Create one immutable snapshot from a persisted evaluation result."""

    label: Annotated[str, Field(min_length=1, max_length=128)]
    eval_result_id: PositiveInt
    public: StrictBool = False


class SnapshotVisibilityRequest(StrictSchema):
    """Change only whether a ready snapshot is publicly listable."""

    public: StrictBool


class EvaluationRunRequest(StrictSchema):
    """Queue one quick live-index run or isolated retrieval matrix."""

    suite_id: GoldenSuiteId
    golden_revision_id: PositiveInt | None = None
    mode: EvaluationMode = "quick"
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    target_tokens: Annotated[
        tuple[PositiveInt, ...],
        BeforeValidator(tuple_from_json_array),
    ] = (1024, 2048)
    strategies: Annotated[
        tuple[RetrievalStrategy, ...],
        BeforeValidator(tuple_from_json_array),
    ] = ("lexical", "vector", "hybrid")
    lexical_rankers: Annotated[
        tuple[LexicalRanker, ...],
        BeforeValidator(tuple_from_json_array),
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


class EvaluationResultSummaryResource(StrictSchema):
    """Recorded inputs for one result, including individual matrix configurations."""

    result_id: PositiveInt
    created_at: datetime
    config: dict[str, Any]


class EvaluationJobResource(StrictSchema):
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


class EvaluationJobsResponse(StrictSchema):
    """Newest-first bounded evaluation job collection."""

    jobs: tuple[EvaluationJobResource, ...]


class EvaluationMetricDelta(StrictSchema):
    """One candidate metric and its signed change from a baseline."""

    name: str
    baseline: StrictFloat
    candidate: StrictFloat
    delta: StrictFloat


class EvaluationCaseDelta(StrictSchema):
    """One golden case's rank and citation movement between two runs."""

    case_id: str
    question: str
    baseline_rank: PositiveInt | None
    candidate_rank: PositiveInt | None
    transition: Literal["stable_hit", "stable_miss", "miss_to_hit", "hit_to_miss"]
    rank_delta: StrictInt | None
    baseline_citations: tuple[str, ...]
    candidate_citations: tuple[str, ...]


class EvaluationComparisonResponse(StrictSchema):
    """Metric and case-level comparison between compatible stored artifacts."""

    baseline_id: PositiveInt
    candidate_id: PositiveInt
    suite: str
    metrics: tuple[EvaluationMetricDelta, ...]
    cases: tuple[EvaluationCaseDelta, ...]


class EvaluationCaseSummary(StrictSchema):
    """One bounded absolute case result from a persisted evaluation artifact."""

    case_id: str
    question: str
    first_relevant_rank: PositiveInt | None
    citations: tuple[str, ...]


class EvaluationResultDetailResponse(StrictSchema):
    """Absolute metrics, configuration, and bounded cases for one result."""

    result_id: PositiveInt
    suite: str
    config: dict[str, object]
    metrics: dict[str, StrictFloat]
    cases: tuple[EvaluationCaseSummary, ...]
    raw_artifact_path: str
    created_at: datetime


class GoldenEvidenceChunk(StrictSchema):
    """One selectable chunk with exact original-source coordinates."""

    chunk_id: PositiveInt
    doc_id: str
    source_sha256: str
    start_char: NonNegativeInt
    end_char: PositiveInt
    item: str | None
    kind: str
    body: str
    citation: str


class GoldenEvidencePage(StrictSchema):
    """A bounded page for choosing evidence without running retrieval or a model."""

    chunks: tuple[GoldenEvidenceChunk, ...]
    next_after: int | None = None


class EvalResultResource(StrictSchema):
    """One persisted retrieval evaluation result."""

    result_id: PositiveInt
    suite: NonBlank
    config: JsonObject
    metrics: dict[NonBlank, FiniteFloat]
    raw_artifact_path: NonBlank
    created_at: datetime


class SnapshotResource(StrictSchema):
    """One immutable evaluation snapshot safe for public comparison."""

    snapshot_id: PositiveInt
    label: NonBlank
    status: Literal["ready", "archived"]
    public: StrictBool
    corpus_fingerprint: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    profile: JsonObject
    eval_result: EvalResultResource
    suite_title: NonBlank | None = None
    document_count: NonNegativeInt
    created_at: datetime


class SnapshotListResponse(StrictSchema):
    """Newest-first immutable evaluation snapshots."""

    snapshots: tuple[SnapshotResource, ...]


class SnapshotMetricDelta(StrictSchema):
    """One side-by-side metric with an optional comparable delta."""

    name: NonBlank
    baseline: FiniteFloat
    candidate: FiniteFloat
    delta: FiniteFloat | None


class SnapshotCaseComparison(StrictSchema):
    """One common stored case shown side by side across two snapshots."""

    case_id: NonBlank
    baseline_question: NonBlank
    candidate_question: NonBlank
    baseline_rank: PositiveInt | None
    candidate_rank: PositiveInt | None
    transition: Literal["stable_hit", "stable_miss", "miss_to_hit", "hit_to_miss"]
    rank_delta: StrictInt | None


class SnapshotComparisonResponse(StrictSchema):
    """Read-only comparison that never starts an evaluation."""

    baseline_id: PositiveInt
    candidate_id: PositiveInt
    directly_comparable: StrictBool
    warning: NonBlank | None
    metrics: tuple[SnapshotMetricDelta, ...]
    common_case_count: NonNegativeInt = 0
    cases: tuple[SnapshotCaseComparison, ...] = ()


class PublicGoldenCase(BaseModel):
    """Question and expected evidence without internal curation notes."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    question: str
    category: str
    facet: str
    tags: tuple[str, ...]
    answers: tuple[GoldenSpan, ...]
    expected_label: str
    reference_answer: str


class PublicSnapshotDataset(BaseModel):
    """One filtered page from the exact cases evaluated by a published snapshot."""

    snapshot_id: int
    suite: str
    golden_sha256: str
    total: int
    offset: int
    limit: int
    cases: tuple[PublicGoldenCase, ...]


class PublicEvaluationCase(BaseModel):
    """Recorded case metrics; no retrieval is performed when reading them."""

    case_id: str
    question: str
    latency_ms: float
    first_relevant_rank: int | None = None
    recall_at_k: float | None = None
    hit_at_k: float | None = None
    reciprocal_rank: float | None = None


class PublicSnapshotEvaluation(BaseModel):
    """One filtered page of a published evaluation's recorded evidence."""

    snapshot_id: int
    eval_result_id: int
    suite: str
    created_at: datetime
    config: dict[str, str | int | float | bool | None]
    metrics: dict[str, float]
    total: int
    offset: int
    limit: int
    cases: tuple[PublicEvaluationCase, ...]
