"""Synchronous evidence-review resource route."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import Services
from app.api.errors import not_found
from app.api.review.schemas import (
    ErrorResponse,
    RetrieveRequest,
    RetrieveResponse,
    ReviewRequest,
    RunResponse,
    TraceListResponse,
)
from app.observability.types import RUN_ID_PATTERN

router = APIRouter()


STATUS_CODES = {
    "ok": 200,
    "budget_exceeded": 429,
    "schema_rejected": 502,
    "error": 503,
}


@router.post(
    "/review",
    tags=["review"],
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


@router.post(
    "/retrieve",
    tags=["retrieve"],
    response_model=RetrieveResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def retrieve_evidence(request: RetrieveRequest, services: Services) -> RetrieveResponse:
    """Return source-cited ranked evidence for one validated query."""
    return await services.retrieve(request)


RunPath = Annotated[str, Path(pattern=RUN_ID_PATTERN)]


@router.get(
    "/runs/{run_id}",
    tags=["runs"],
    response_model=RunResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def get_run(run_id: RunPath, services: Services) -> RunResponse:
    """Return one persisted run without executing it again."""
    result = await services.get_run(run_id)
    if result is None:
        raise not_found("run", run_id)
    return RunResponse.from_run_report(result)


@router.get(
    "/runs/{run_id}/traces",
    tags=["runs"],
    response_model=TraceListResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def list_traces(run_id: RunPath, services: Services) -> TraceListResponse:
    """Return ordered raw provider traces for one persisted run."""
    traces = await services.get_traces(run_id)
    if traces is None:
        raise not_found("run", run_id)
    return TraceListResponse(run_id=run_id, traces=tuple(traces))
