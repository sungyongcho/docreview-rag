"""Persisted workflow run and trace resource routes."""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import Services
from app.api.errors import not_found
from app.api.schemas import ErrorResponse, RunResponse, TraceListResponse
from app.observability.types import RUN_ID_PATTERN

router = APIRouter(tags=["runs"])
RunPath = Annotated[str, Path(pattern=RUN_ID_PATTERN)]


@router.get(
    "/runs/{run_id}",
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
    response_model=TraceListResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def list_traces(run_id: RunPath, services: Services) -> TraceListResponse:
    """Return ordered raw provider traces for one persisted run."""
    traces = await services.get_traces(run_id)
    if traces is None:
        raise not_found("run", run_id)
    return TraceListResponse(run_id=run_id, traces=tuple(traces))
