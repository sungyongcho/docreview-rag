"""Strict API contracts for local corpus and retrieval experimentation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

from app.api.schemas import EvidenceHit, RunResponse
from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf, LexicalRanker
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.types import RetrievalFilters

type RetrievalStrategy = Literal["vector", "lexical", "hybrid"]
type RerankerName = Literal["cross_encoder"]
type GoldenSuiteId = Literal["sec-en", "sec-ko", "dart-en", "dart-ko"]
type EvaluationMode = Literal["quick", "matrix"]
type EvaluationJobStatus = Literal["queued", "running", "succeeded", "failed"]
type CorpusOperationKind = Literal[
    "acquire_edgar",
    "acquire_dart",
    "ingest_manifest",
    "backfill_embeddings",
    "rebuild_bm25",
]

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


class GoldenSuiteResource(StrictAdminModel):
    """One immutable golden suite exposed to the experiment selector."""

    suite_id: GoldenSuiteId
    label: str
    registry: Literal["sec", "dart"]
    question_language: Literal["en", "ko"]
    corpus_language: Literal["en", "ko"]
    case_count: PositiveInt
    scored_positive_cases: PositiveInt
    absent_cases: Annotated[StrictInt, Field(ge=0)]
    curation_status: Literal["agent-curated"]
    approval_status: Literal["pending-author-approval"]
    human_verified: Literal[False]
    golden_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_ready: StrictBool
    source_error: str | None = None


class EvaluationRunRequest(StrictAdminModel):
    """Queue one quick live-index run or isolated retrieval matrix."""

    suite_id: GoldenSuiteId
    mode: EvaluationMode = "quick"
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    target_text_chars: Annotated[
        tuple[PositiveInt, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = (500, 1200)
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
        if not self.target_text_chars or len(set(self.target_text_chars)) != len(
            self.target_text_chars
        ):
            raise ValueError("target_text_chars must be nonempty and unique")
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
    identifiers: Annotated[
        tuple[str, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = ()
    years: Annotated[
        tuple[PositiveInt, ...],
        BeforeValidator(_tuple_from_json_array),
    ] = ()
    manifest: str | None = None
    expected_documents: PositiveInt | None = None


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
    baseline_id: PositiveInt | None = None
    artifact_paths: tuple[str, ...] = ()
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EvaluationJobsResponse(StrictAdminModel):
    """Newest-first bounded evaluation job collection."""

    jobs: tuple[EvaluationJobResource, ...]


class UsageModelResource(StrictAdminModel):
    """One model's locally recorded token and estimated-cost totals."""

    model_name: str
    requests: NonnegativeInt
    input_tokens: NonnegativeInt
    cached_input_tokens: NonnegativeInt
    cache_write_input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    reasoning_tokens: NonnegativeInt
    estimated_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)


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
    component_rankings: dict[str, tuple[PositiveInt, ...]]
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
