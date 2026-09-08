"""Strict conversation-level review settings and server-owned retrieval presets."""

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
)
from pydantic.functional_validators import model_validator

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf, LexicalRanker
from app.observability.types import Budget
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.scope import CorpusScope
from app.retrieval.types import RetrievalFilters
from app.workflow.types import DEFAULT_SYSTEM_PROMPT

type ReviewEngine = Literal["openai", "local"]
type RetrievalPreset = Literal["balanced", "korean", "accuracy", "custom"]
type RetrievalStrategy = Literal["vector", "lexical", "hybrid"]
type RerankerName = Literal["cross_encoder"]


def _tuple_from_json_array(value: object) -> object:
    """Accept JSON arrays at the boundary while preserving strict child values."""
    return tuple(value) if isinstance(value, list) else value


class StrictProfileModel(BaseModel):
    """Reject unknown or coercible values at the profile boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CustomRetrievalProfile(StrictProfileModel):
    """One explicit bounded retrieval plan used only by the Custom preset."""

    strategy: RetrievalStrategy = "hybrid"
    k: Annotated[StrictInt, Field(gt=0, le=100)] = 5
    candidate_k: Annotated[StrictInt, Field(gt=0, le=500)] = 20
    rrf_k: Annotated[StrictInt, Field(gt=0, le=10_000)] = DEFAULT_RRF_K
    lexical_ranker: LexicalRanker | None = "ts_rank_cd"
    bm25_k1: Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)] = DEFAULT_BM25_K1
    bm25_b: Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)] = DEFAULT_BM25_B
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF
    route_by_language: StrictBool = False
    reranker: RerankerName | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        """Reject contradictory strategy, lexical, routing, and depth settings."""
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


class PromptPolicy(StrictProfileModel):
    """Developer-controlled additions around the immutable evidence guard."""

    additional_instructions: Annotated[str, Field(max_length=8_000)] = ""
    history_turns: Annotated[StrictInt, Field(ge=0, le=6)] = 6
    max_context_chars: Annotated[StrictInt, Field(ge=1_000, le=100_000)] = 12_000
    evidence_overfetch: Annotated[StrictInt, Field(ge=1, le=10)] = 3
    max_hits_per_document: Annotated[StrictInt, Field(ge=1, le=100)] = 2
    workflow_budget: Budget = Field(default_factory=Budget)

    @property
    def system_prompt(self) -> str:
        """Append optional instructions without allowing removal of the guard."""
        extra = self.additional_instructions.strip()
        return DEFAULT_SYSTEM_PROMPT if not extra else f"{DEFAULT_SYSTEM_PROMPT}\n\n{extra}"

    @model_validator(mode="after")
    def validate_workflow_ceiling(self) -> Self:
        """Keep browser-configurable workflow limits inside server safety ceilings."""
        budget = self.workflow_budget
        if budget.max_iterations > 20:
            raise ValueError("max_iterations must not exceed 20")
        if budget.max_input_tokens > 100_000:
            raise ValueError("max_input_tokens must not exceed 100000")
        if budget.max_output_tokens > 4_000:
            raise ValueError("max_output_tokens must not exceed 4000")
        if not 1 <= budget.max_wall_clock_s <= 600:
            raise ValueError("max_wall_clock_s must be in 1..600")
        return self


class ReviewSessionProfile(StrictProfileModel):
    """Conversation settings persisted by the browser and revalidated by the server."""

    engine: ReviewEngine = "openai"
    local_model: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    corpus_scope: CorpusScope = "auto"
    doc_ids: Annotated[tuple[str, ...], BeforeValidator(_tuple_from_json_array)] = ()
    registries: Annotated[tuple[str, ...], BeforeValidator(_tuple_from_json_array)] = ()
    kinds: Annotated[
        tuple[Literal["text", "table"], ...], BeforeValidator(_tuple_from_json_array)
    ] = ()
    issuers: Annotated[tuple[str, ...], BeforeValidator(_tuple_from_json_array)] = ()
    languages: Annotated[
        tuple[Literal["en", "ko"], ...], BeforeValidator(_tuple_from_json_array)
    ] = ()
    fiscal_years: Annotated[
        tuple[Annotated[StrictInt, Field(gt=0)], ...],
        BeforeValidator(_tuple_from_json_array),
    ] = ()
    forms: Annotated[tuple[str, ...], BeforeValidator(_tuple_from_json_array)] = ()
    sections: Annotated[tuple[str | None, ...], BeforeValidator(_tuple_from_json_array)] = ()
    retrieval_preset: RetrievalPreset = "balanced"
    custom_retrieval: CustomRetrievalProfile | None = None
    applied_from_evaluation: str | None = None
    snapshot_id: Annotated[StrictInt, Field(gt=0)] | None = None
    prompt_policy: PromptPolicy = Field(default_factory=PromptPolicy)

    @model_validator(mode="after")
    def validate_custom_shape(self) -> Self:
        """Keep Custom configuration present exactly when its preset is selected."""
        if (self.retrieval_preset == "custom") != (self.custom_retrieval is not None):
            raise ValueError("custom_retrieval is required exactly for the custom preset")
        return self

    def explicit_filters(self) -> RetrievalFilters:
        """Project profile selections onto the shared exact-match filter contract."""
        return RetrievalFilters(
            doc_ids=self.doc_ids,
            registries=self.registries,
            kinds=self.kinds,
            languages=self.languages,
            issuers=self.issuers,
            fiscal_years=self.fiscal_years,
            forms=self.forms,
            items=self.sections,
            snapshot_id=self.snapshot_id,
        )


class ResolvedRetrievalProfile(StrictProfileModel):
    """The exact server-owned retrieval settings applied to one request."""

    preset: RetrievalPreset
    strategy: RetrievalStrategy
    k: Annotated[StrictInt, Field(gt=0, le=100)]
    candidate_k: Annotated[StrictInt, Field(gt=0, le=500)]
    rrf_k: Annotated[StrictInt, Field(gt=0, le=10_000)]
    lexical_ranker: LexicalRanker | None
    bm25_k1: Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)]
    bm25_b: Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)]
    bm25_idf: BM25Idf
    route_by_language: StrictBool
    reranker: RerankerName | None


def resolve_retrieval_profile(profile: ReviewSessionProfile) -> ResolvedRetrievalProfile:
    """Expand a named preset or validated Custom settings into one exact plan."""
    from app.api.preset_store import preset_store

    selected = profile.custom_retrieval
    if profile.retrieval_preset != "custom":
        selected = next(
            (
                preset.retrieval
                for preset in preset_store.catalog().presets
                if preset.id == profile.retrieval_preset
            ),
            None,
        )
    if selected is None:
        raise ValueError("retrieval preset settings are missing")
    return ResolvedRetrievalProfile(
        preset=profile.retrieval_preset,
        **selected.model_dump(mode="python"),
    )


def zero_cost() -> Decimal:
    """Return the exact cost identity used by local provider budgets."""
    return Decimal("0")
