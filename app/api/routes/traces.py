"""Persisted provider trace collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ApiServices, get_api_services
from app.api.errors import not_found
from app.api.schemas import ErrorResponse, TraceListResponse

router = APIRouter(tags=["traces"])
Services = Annotated[ApiServices, Depends(get_api_services)]
RunPath = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


@router.get(
    "/runs/{run_id}/traces",
    response_model=TraceListResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def list_traces(run_id: RunPath, services: Services) -> TraceListResponse:
    """Return ordered raw provider traces for one persisted run."""
    traces = await services.get_traces(run_id)
    if traces is None:
        raise not_found("run", run_id)
    return TraceListResponse(run_id=run_id, traces=tuple(traces))
