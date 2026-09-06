"""Retrieve resource route."""

from fastapi import APIRouter

from app.api.deps import Services
from app.api.schemas import ErrorResponse, RetrieveRequest, RetrieveResponse

router = APIRouter(tags=["retrieve"])


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def retrieve_evidence(request: RetrieveRequest, services: Services) -> RetrieveResponse:
    """Return source-cited ranked evidence for one validated query."""
    return await services.retrieve(request)
