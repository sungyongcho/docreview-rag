"""Explicit retrieval profiles served through the standard search and review paths."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field

from app.api.admin_deps import AdminServices
from app.api.dependencies import AdminDependencies
from app.api.errors import translate_runtime_errors
from app.api.review.profiles import ReviewSessionProfile
from app.api.review.runtime import _routed_query_variants
from app.api.review.schemas import EvidenceHit, ReviewRequest, RunResponse
from app.contracts.validation import PositiveInt, StrictSchema
from app.retrieval.search.profiles import RetrievalProfile, with_server_bm25
from app.retrieval.types import RetrievalFilters


class RetrievalPreviewRequest(StrictSchema):
    """One query evaluated through an explicit session-scoped retrieval profile."""

    query: Annotated[str, Field(min_length=1, max_length=10_000)]
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class RetrievalPreviewResponse(StrictSchema):
    """Ranked evidence plus component provenance for API inspection."""

    query: str
    profile: RetrievalProfile
    score_stage: Literal["rrf", "reranker"]
    # `vector`/`lexical` hold one rank list each; the `*_by_language` entries nest one
    # list per routed query language, mirroring `ComponentRankings`.
    component_rankings: dict[str, tuple[PositiveInt, ...] | dict[str, tuple[PositiveInt, ...]]]
    results: tuple[EvidenceHit, ...]


class ReviewPreviewRequest(StrictSchema):
    """One evidence-checked review using a session-scoped retrieval profile."""

    query: Annotated[str, Field(min_length=1, max_length=10_000)]
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class ReviewPreviewResponse(StrictSchema):
    """Review output paired with the retrieval profile that produced its evidence."""

    profile: RetrievalProfile
    run: RunResponse


router = APIRouter(prefix="/admin", tags=["admin"])


async def _retrieval_preview(
    dependencies: AdminDependencies, request: RetrievalPreviewRequest
) -> RetrievalPreviewResponse:
    """Return evidence and component ranks for one session-scoped profile."""
    profile = with_server_bm25(request.profile, dependencies.runtime.bm25_parameters)
    runtime = dependencies.runtime
    async with runtime.search_access():
        query_variants = None
        if profile.route_by_language:
            query_variants = await _routed_query_variants(
                request.query,
                request.filters.languages,
                lambda: runtime._engines.resolve_engine(ReviewRequest(query=request.query)),
            )
        async with runtime.session_factory() as session:
            result = await runtime._retrieve_with_session(
                session, request.query, profile.k, request.filters, profile, query_variants
            )
    return RetrievalPreviewResponse(
        query=request.query,
        profile=profile,
        score_stage=result.score_stage,
        component_rankings=result.component_rankings.model_dump(mode="python"),
        results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in result.hits),
    )


async def _review_preview(
    dependencies: AdminDependencies, request: ReviewPreviewRequest
) -> ReviewPreviewResponse:
    """Run an evidence-checked review through one explicit retrieval profile."""
    profile = with_server_bm25(request.profile, dependencies.runtime.bm25_parameters)

    report = await dependencies.runtime.review(
        ReviewRequest(
            query=request.query,
            session_profile=ReviewSessionProfile.model_validate(
                {
                    "retrieval_preset": "custom",
                    "custom_retrieval": profile.model_dump(),
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
        )
    )
    return ReviewPreviewResponse(profile=profile, run=RunResponse.from_run_report(report))


@router.post("/retrieval/preview", response_model=RetrievalPreviewResponse)
async def retrieval_preview(
    request: RetrievalPreviewRequest, services: AdminServices
) -> RetrievalPreviewResponse:
    """Execute one query through an explicit session-scoped retrieval profile."""
    async with translate_runtime_errors():
        return await _retrieval_preview(services, request)


@router.post("/review/preview", response_model=ReviewPreviewResponse)
async def review_preview(
    request: ReviewPreviewRequest, services: AdminServices
) -> ReviewPreviewResponse:
    """Run one evidence-checked review through an explicit retrieval profile."""
    async with translate_runtime_errors():
        return await _review_preview(services, request)
