"""Synchronous evidence-review resource route."""

from fastapi import APIRouter, Response

from app.api.deps import Services
from app.api.schemas import ReviewRequest, RunResponse

router = APIRouter(tags=["review"])
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
