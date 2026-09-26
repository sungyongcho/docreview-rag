"""Read-only public routes for exact snapshot dataset and evaluation evidence."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from app.api.errors import translate_runtime_errors, unavailable
from app.evals.contracts import PublicSnapshotDataset, PublicSnapshotEvaluation
from app.evals.snapshots.evidence import PublicSnapshotDetails

router = APIRouter(prefix="/public/snapshots", tags=["snapshots"])
SnapshotId = Annotated[int, Path(gt=0)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
Search = Annotated[str, Query(max_length=200)]


def get_snapshot_details() -> PublicSnapshotDetails | None:
    """Require the publication reader composed with the runtime's stored artifacts."""
    return None


SnapshotDetails = Annotated[PublicSnapshotDetails | None, Depends(get_snapshot_details)]


@router.get("/{snapshot_id}/dataset", response_model=PublicSnapshotDataset)
async def dataset(
    snapshot_id: SnapshotId,
    details: SnapshotDetails,
    offset: Offset = 0,
    limit: Limit = 50,
    query: Search = "",
    sort: Literal["id", "question"] = "id",
) -> PublicSnapshotDataset:
    """Read a filtered page of the exact published dataset."""
    if details is None:
        raise unavailable(
            "snapshot_evidence_unavailable",
            "Published evaluation evidence requires the runtime service.",
        )
    async with translate_runtime_errors():
        return await details.dataset(
            snapshot_id, offset=offset, limit=limit, query=query, sort=sort
        )


@router.get("/{snapshot_id}/evaluation", response_model=PublicSnapshotEvaluation)
async def evaluation(
    snapshot_id: SnapshotId,
    details: SnapshotDetails,
    offset: Offset = 0,
    limit: Limit = 50,
    query: Search = "",
    sort: Literal["id", "question"] = "id",
) -> PublicSnapshotEvaluation:
    """Read recorded settings and case scores without launching any work."""
    if details is None:
        raise unavailable(
            "snapshot_evidence_unavailable",
            "Published evaluation evidence requires the runtime service.",
        )
    async with translate_runtime_errors():
        return await details.evaluation(
            snapshot_id, offset=offset, limit=limit, query=query, sort=sort
        )
