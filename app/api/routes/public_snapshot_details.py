"""Read-only public routes for exact snapshot dataset and evaluation evidence."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.api.deps import Services
from app.api.errors import ApiProblemError, translate_runtime_errors
from app.api.public_snapshot_schemas import PublicSnapshotDataset, PublicSnapshotEvaluation
from app.api.runtime import RuntimeApiServices
from app.evals.public_snapshot_details import PublicSnapshotDetails

router = APIRouter(prefix="/public/snapshots", tags=["snapshots"])
SnapshotId = Annotated[int, Path(gt=0)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
Search = Annotated[str, Query(max_length=200)]


def _details(services: Services) -> PublicSnapshotDetails:
    """Require runtime evidence; canned mode must not fabricate published data."""
    if not isinstance(services, RuntimeApiServices):
        raise ApiProblemError(
            status_code=503,
            code="snapshot_evidence_unavailable",
            message="Published evaluation evidence requires the runtime service.",
        )
    return PublicSnapshotDetails(services.session_factory, services._snapshots)


@router.get("/{snapshot_id}/dataset", response_model=PublicSnapshotDataset)
async def dataset(
    snapshot_id: SnapshotId,
    services: Services,
    offset: Offset = 0,
    limit: Limit = 50,
    query: Search = "",
    sort: Literal["id", "question"] = "id",
) -> PublicSnapshotDataset:
    """Read a filtered page of the exact published dataset."""
    async with translate_runtime_errors():
        return await _details(services).dataset(
            snapshot_id, offset=offset, limit=limit, query=query, sort=sort
        )


@router.get("/{snapshot_id}/evaluation", response_model=PublicSnapshotEvaluation)
async def evaluation(
    snapshot_id: SnapshotId,
    services: Services,
    offset: Offset = 0,
    limit: Limit = 50,
    query: Search = "",
    sort: Literal["id", "question"] = "id",
) -> PublicSnapshotEvaluation:
    """Read recorded settings and case scores without launching any work."""
    async with translate_runtime_errors():
        return await _details(services).evaluation(
            snapshot_id, offset=offset, limit=limit, query=query, sort=sort
        )
