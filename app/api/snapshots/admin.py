"""Administrator snapshot creation and publication controls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import AdminDependency
from app.api.errors import translate_runtime_errors
from app.evals.contracts import (
    SnapshotComparisonResponse,
    SnapshotCreateRequest,
    SnapshotResource,
    SnapshotVisibilityRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])
ResultId = Annotated[int, Query(gt=0)]


@router.get("/snapshots", response_model=tuple[SnapshotResource, ...])
async def list_admin_snapshots(services: AdminDependency) -> tuple[SnapshotResource, ...]:
    """Return public and private local snapshots."""
    async with translate_runtime_errors():
        return await services.snapshots.list(public_only=False)


@router.post("/snapshots", response_model=SnapshotResource)
async def create_snapshot(
    request: SnapshotCreateRequest, services: AdminDependency
) -> SnapshotResource:
    """Create one immutable snapshot from a persisted eval result."""
    async with translate_runtime_errors():
        return await services.snapshots.create(
            label=request.label, eval_result_id=request.eval_result_id, public=request.public
        )


@router.put("/snapshots/{snapshot_id}/visibility", response_model=SnapshotResource)
async def set_snapshot_visibility(
    snapshot_id: int, request: SnapshotVisibilityRequest, services: AdminDependency
) -> SnapshotResource:
    """Publish or hide one ready snapshot without changing its identity."""
    async with translate_runtime_errors():
        return await services.snapshots.set_public(snapshot_id, public=request.public)


@router.get("/snapshots/compare", response_model=SnapshotComparisonResponse)
async def compare_admin_snapshots(
    services: AdminDependency, baseline_id: ResultId, candidate_id: ResultId
) -> SnapshotComparisonResponse:
    """Compare any two local snapshots without executing evaluation work."""
    async with translate_runtime_errors():
        return await services.snapshots.compare(baseline_id, candidate_id)
