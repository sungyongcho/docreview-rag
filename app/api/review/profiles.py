"""Strict conversation-level review settings and server-owned retrieval presets."""

from collections.abc import Mapping
from typing import Annotated, Final, Literal, Self

from pydantic import BeforeValidator, Field, StrictBool, StrictFloat, StrictInt
from pydantic.functional_validators import model_validator

from app.config import BM25Idf, LexicalRanker
from app.contracts.validation import StrictSchema, tuple_from_json_array
from app.observability.types import Budget
from app.query.scope import CorpusScope
from app.retrieval.search.plan import RetrievalStrategy, SearchPlan
from app.retrieval.search.profiles import (
    RerankerName,
    RetrievalProfile,
    ServerBM25,
    with_server_bm25,
    with_server_bm25_for_builtin,
)
from app.retrieval.types import RetrievalFilters
from app.workflow.types import DEFAULT_SYSTEM_PROMPT

type ReviewEngine = Literal["openai", "local"]
type RetrievalPreset = Literal["balanced", "korean", "accuracy", "custom"]


# Public surfaces may run the Custom preset only inside the cost envelope the
# built-in presets already spend: k stays within twice the preset default (5) and
# candidate_k within the Accuracy preset's 50.
PUBLIC_CUSTOM_RETRIEVAL_MAXIMA: Final[Mapping[str, int]] = {"k": 10, "candidate_k": 50}


def public_custom_retrieval_violation(retrieval: Mapping[str, object]) -> str | None:
    """Name the first Custom retrieval field above its public ceiling, or None."""
    for field, ceiling in PUBLIC_CUSTOM_RETRIEVAL_MAXIMA.items():
        value = retrieval.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value > ceiling:
            return f"custom_retrieval.{field} must be at most {ceiling} on the public surface"
    return None


class PromptPolicy(StrictSchema):
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


class ReviewSessionProfile(StrictSchema):
    """Conversation settings persisted by the browser and revalidated by the server."""

    engine: ReviewEngine = "openai"
    local_model: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    corpus_scope: CorpusScope = "auto"
    doc_ids: Annotated[tuple[str, ...], BeforeValidator(tuple_from_json_array)] = ()
    registries: Annotated[tuple[str, ...], BeforeValidator(tuple_from_json_array)] = ()
    kinds: Annotated[
        tuple[Literal["text", "table"], ...], BeforeValidator(tuple_from_json_array)
    ] = ()
    issuers: Annotated[tuple[str, ...], BeforeValidator(tuple_from_json_array)] = ()
    languages: Annotated[
        tuple[Literal["en", "ko"], ...], BeforeValidator(tuple_from_json_array)
    ] = ()
    fiscal_years: Annotated[
        tuple[Annotated[StrictInt, Field(gt=0)], ...],
        BeforeValidator(tuple_from_json_array),
    ] = ()
    forms: Annotated[tuple[str, ...], BeforeValidator(tuple_from_json_array)] = ()
    sections: Annotated[tuple[str | None, ...], BeforeValidator(tuple_from_json_array)] = ()
    retrieval_preset: RetrievalPreset = "balanced"
    custom_retrieval: RetrievalProfile | None = None
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


class ResolvedRetrievalProfile(StrictSchema):
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


def resolve_retrieval_profile(
    profile: ReviewSessionProfile, server: ServerBM25 | None = None
) -> ResolvedRetrievalProfile:
    """Expand a named preset or validated Custom settings into one exact plan.

    BM25 values the plan does not state come from ``server`` (the built-in defaults
    when ``None``), so the resolved plan always carries the values actually applied.
    """
    from app.api.review.presets import preset_store

    selected = profile.custom_retrieval
    builtin = profile.retrieval_preset != "custom"
    if builtin:
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
    if builtin:
        selected = with_server_bm25_for_builtin(selected, server)
    else:
        selected = with_server_bm25(selected, server)
    return ResolvedRetrievalProfile(
        preset=profile.retrieval_preset,
        **selected.model_dump(mode="python"),
    )


def search_plan(profile: ResolvedRetrievalProfile | RetrievalProfile) -> SearchPlan:
    """Carry one resolved request plan into the shared search implementation."""
    return SearchPlan(
        strategy=profile.strategy,
        candidate_k=profile.candidate_k,
        rrf_k=profile.rrf_k,
        lexical_ranker=profile.lexical_ranker,
        bm25_k1=profile.bm25_k1,
        bm25_b=profile.bm25_b,
        bm25_idf=profile.bm25_idf,
        route_by_language=profile.route_by_language,
    )
