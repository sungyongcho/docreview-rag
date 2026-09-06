"""Persisted evaluation result collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ErrorResponse, EvalListResponse

router = APIRouter(tags=["eval"])
Services = Annotated[ApiServices, Depends(get_api_services)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get(
    "/eval",
    response_model=EvalListResponse,
    responses={503: {"model": ErrorResponse}},
)
async def list_eval_results(
    services: Services,
    limit: Limit = 20,
) -> EvalListResponse:
    """Return the newest persisted retrieval evaluation results."""
    results = tuple(await services.list_eval_results(limit))
    return EvalListResponse(results=results)
