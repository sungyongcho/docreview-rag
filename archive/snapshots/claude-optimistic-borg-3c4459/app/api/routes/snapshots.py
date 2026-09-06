"""Public read-only evaluation snapshot resources."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import Services
from app.api.errors import translate_runtime_errors
from app.api.schemas import SnapshotComparisonResponse, SnapshotListResponse

router = APIRouter(prefix="/snapshots", tags=["snapshots"])
SnapshotId = Annotated[int, Query(gt=0)]


@router.get("", response_model=SnapshotListResponse)
async def list_snapshots(services: Services) -> SnapshotListResponse:
    """Return only ready snapshots explicitly published by an operator."""
    async with translate_runtime_errors():
        snapshots = await services.list_snapshots(public_only=True)
    return SnapshotListResponse(snapshots=tuple(snapshots))


@router.get("/compare", response_model=SnapshotComparisonResponse)
async def compare_snapshots(
    services: Services,
    baseline_id: SnapshotId,
    candidate_id: SnapshotId,
) -> SnapshotComparisonResponse:
    """Compare two public stored artifacts without executing an evaluation."""
    async with translate_runtime_errors():
        return await services.compare_snapshots(baseline_id, candidate_id)
