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


@router.post(
    "/review",
    response_model=RunResponse,
    responses={
        429: {"model": RunResponse, "description": "Workflow budget exhausted."},
        502: {"model": RunResponse, "description": "Structured output rejected."},
        503: {
            "description": "Workflow error or unavailable runtime dependency.",
            "content": {
                "application/json": {
                    "schema": {
                        "anyOf": [
                            {"$ref": "#/components/schemas/RunResponse"},
                            {"$ref": "#/components/schemas/ErrorResponse"},
                        ]
                    }
                }
            },
        },
    },
)
async def review_query(
    request: ReviewRequest,
    response: Response,
    services: Services,
) -> RunResponse:
    """Complete one guarded workflow and return its terminal run resource."""
    result = RunResponse.from_run_report(await services.review(request))
    response.status_code = STATUS_CODES[result.status]
    return result
