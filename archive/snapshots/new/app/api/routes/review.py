"""Synchronous evidence-review resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ReviewRequest, RunResponse

router = APIRouter(tags=["review"])
Services = Annotated[ApiServices, Depends(get_api_services)]
STATUS_CODES = {
    "ok": 200,
    "budget_exceeded": 429,
    "schema_rejected": 502,
    "error": 503,
}


@router.post("/review", response_model=RunResponse)
async def review_query(
    request: ReviewRequest,
    response: Response,
    services: Services,
) -> RunResponse:
    """Complete one guarded workflow and return its terminal run resource."""
    result = RunResponse.from_run_report(await services.review(request))
    response.status_code = STATUS_CODES[result.status]
    return result
