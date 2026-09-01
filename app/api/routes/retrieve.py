"""Retrieve resource route."""

from fastapi import APIRouter

from app.api.deps import Services
from app.api.review_profile import ReviewSessionProfile, resolve_retrieval_profile
from app.api.schemas import ErrorResponse, EvidenceHit, RetrieveRequest, RetrieveResponse
from app.retrieval.service import RetrievalResult

router = APIRouter(tags=["retrieve"])


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def retrieve_evidence(request: RetrieveRequest, services: Services) -> RetrieveResponse:
    """Return source-cited ranked evidence for one validated query."""
    result = await services.retrieve(request)
    if isinstance(result, RetrieveResponse):
        return result
    if not isinstance(result, RetrievalResult):
        raise TypeError("retrieve services must return RetrieveResponse or RetrievalResult")
    return RetrieveResponse(
        query=request.query,
        results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in result.hits),
        candidates=(),
        candidate_token="legacy-preview",
        candidate_expires_at=0,
        score_stage=result.score_stage,
        component_rankings=result.component_rankings.model_dump(mode="json"),
        resolved_profile=resolve_retrieval_profile(ReviewSessionProfile()),
        resolved_scope=None,
    )
