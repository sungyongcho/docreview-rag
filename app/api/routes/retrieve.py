"""Retrieve resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ErrorResponse, EvidenceHit, RetrieveRequest, RetrieveResponse
from app.retrieval.service import RetrievalResult

router = APIRouter(tags=["retrieve"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    responses={503: {"model": ErrorResponse}},
)
async def retrieve_evidence(request: RetrieveRequest, services: Services) -> RetrieveResponse:
    """Return source-cited ranked evidence for one validated query."""
    result = await services.retrieve(request)
    hits = result.hits if isinstance(result, RetrievalResult) else tuple(result)
    return RetrieveResponse(
        query=request.query,
        results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in hits),
    )
