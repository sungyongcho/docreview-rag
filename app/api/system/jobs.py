"""Persisted job history, shared queue actions, and readiness projection."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import StrictBool

from app.api.admin_deps import AdminServices
from app.api.dependencies import AdminDependencies
from app.api.errors import ApiProblemError, not_found, translate_runtime_errors
from app.api.review.schemas import ErrorResponse
from app.contracts.validation import NonNegativeInt, PositiveInt, StrictSchema
from app.corpus_admin.types import CorpusStatus
from app.operator.jobs.history import ARCHIVE_KEY, HistoryConflictError
from app.operator.jobs.progress import progress_fields
from app.operator.jobs.store import StoredJob


class OperatorJobResource(StrictSchema):
    """One persisted corpus or evaluation job with queue and progress state."""

    job_id: str
    domain: Literal["corpus", "evaluation"]
    kind: str
    request: dict[str, object]
    status: Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]
    stage: str
    current: NonNegativeInt
    total: NonNegativeInt | None
    detail_current: NonNegativeInt | None
    detail_total: NonNegativeInt | None
    overall_current: NonNegativeInt | None = None
    overall_total: NonNegativeInt | None = None
    stage_index: PositiveInt | None = None
    stage_count: PositiveInt | None = None
    stage_started_at: datetime | None = None
    progress_stage: str | None = None
    message: str
    error_code: str | None
    result_refs: dict[str, object]
    queue_position: PositiveInt | None
    can_cancel: StrictBool
    can_retry: StrictBool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class OperatorJobsResponse(StrictSchema):
    """Newest persisted jobs plus active and queued summary counts."""

    jobs: tuple[OperatorJobResource, ...]
    active_count: NonNegativeInt
    queued_count: NonNegativeInt


class JobHistorySummaryResource(StrictSchema):
    """Terminal history counts and protected active jobs."""

    visible: NonNegativeInt
    archived: NonNegativeInt
    active: NonNegativeInt


class JobHistoryRequest(StrictSchema):
    """An explicit history operation against a reviewed eligible count."""

    action: Literal["archive", "restore", "delete"]
    expected_count: NonNegativeInt
    confirmation: str = ""


class JobHistoryResultResource(StrictSchema):
    """Confirmed history changes and a private backup reference."""

    action: Literal["archive", "restore", "delete"]
    changed_count: NonNegativeInt
    backup_id: str | None
    summary: JobHistorySummaryResource


router = APIRouter(prefix="/admin", tags=["admin"])

READINESS_STATUS_MAX_AGE_S = 2.0
READINESS_STATUS_MAX_AGE_BUSY_S = 10.0


async def _readiness_status(dependencies: AdminDependencies) -> CorpusStatus:
    """Return corpus status for ``/ready``, reusing a recent reading longer while a job runs.

    A queued or running corpus or evaluation job already loads the database and the
    invalidation trigger keeps ``bm25_ready`` false until it finishes, so re-measuring
    every poll would only add catalog sweeps to the contention it reports.
    """
    max_age = (
        READINESS_STATUS_MAX_AGE_BUSY_S
        if dependencies.coordinator.busy
        else READINESS_STATUS_MAX_AGE_S
    )
    return await dependencies.corpus.status(max_age_s=max_age)


def _operator_resource(job: StoredJob, queue_positions: dict[str, int]) -> OperatorJobResource:
    """Project one stored job with derived queue actions and position."""
    return OperatorJobResource(
        job_id=job.job_id,
        domain=job.domain,
        kind=job.kind,
        request=job.request_json,
        status=job.status,
        stage=job.stage,
        current=job.current,
        total=job.total,
        detail_current=job.detail_current,
        detail_total=job.detail_total,
        message=job.message,
        error_code=job.error_code,
        result_refs=job.result_refs,
        **progress_fields(job.result_refs),
        queue_position=queue_positions.get(job.job_id),
        can_cancel=job.status == "queued"
        or (
            job.status == "running"
            and job.domain == "corpus"
            and (job.kind == "backfill_embeddings")
        ),
        can_retry=job.kind != "delete_sources"
        and job.status in {"failed", "interrupted"}
        and (job.kind != "embedding_usage"),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


async def _job_history_summary(dependencies: AdminDependencies) -> JobHistorySummaryResource:
    """Read history counts without changing records or running jobs."""
    return JobHistorySummaryResource(**asdict(await dependencies.history.summary()))


async def _manage_job_history(
    dependencies: AdminDependencies, request: JobHistoryRequest
) -> JobHistoryResultResource:
    """Archive, restore or back up and delete only reviewed terminal history."""
    result = await dependencies.history.apply(
        request.action, request.expected_count, request.confirmation
    )
    return JobHistoryResultResource(
        action=result.action,
        changed_count=len(result.changed_ids),
        backup_id=result.backup_id,
        summary=await _job_history_summary(dependencies),
    )


def _job_history_backup(dependencies: AdminDependencies, backup_id: str) -> Path:
    """Resolve only an owned private backup for an authenticated download."""
    return dependencies.history.backup_path(backup_id)


async def _operator_jobs(dependencies: AdminDependencies) -> OperatorJobsResponse:
    """Return the persistent unified corpus and evaluation job board."""
    await dependencies.corpus.recover_jobs()
    await dependencies.evaluations.recover_jobs()
    rows = await dependencies.jobs.list(limit=100)
    positions = await dependencies.jobs.queue_positions()
    resources = tuple(_operator_resource(job, positions) for job in rows)
    return OperatorJobsResponse(
        jobs=resources,
        active_count=sum(job.status == "running" for job in rows),
        queued_count=sum(job.status == "queued" for job in rows),
    )


async def _operator_job(dependencies: AdminDependencies, job_id: str) -> OperatorJobResource | None:
    """Return one persisted job with its current queue position."""
    await dependencies.corpus.recover_jobs()
    await dependencies.evaluations.recover_jobs()
    job = await dependencies.jobs.get(job_id)
    if job is None or (
        job.result_refs.get(ARCHIVE_KEY) is True and job.status not in {"queued", "running"}
    ):
        return None
    positions = await dependencies.jobs.queue_positions() if job.status == "queued" else {}
    return _operator_resource(job, positions)


async def _retry_operator_job(dependencies: AdminDependencies, job_id: str) -> OperatorJobResource:
    """Dispatch an explicit retry to the job's owning domain."""
    stored = await dependencies.jobs.get(job_id)
    if stored is None:
        raise ValueError("operator job does not exist")
    if stored.domain == "corpus":
        created = await dependencies.corpus.retry(job_id)
        new_id = created.job_id
    else:
        created = await dependencies.evaluations.retry(job_id)
        new_id = created.job_id
    resource = await _operator_job(dependencies, new_id)
    if resource is None:
        raise RuntimeError("retried job was not persisted")
    return resource


async def _cancel_operator_job(dependencies: AdminDependencies, job_id: str) -> OperatorJobResource:
    """Dispatch a safe cancellation to the job's owning domain."""
    stored = await dependencies.jobs.get(job_id)
    if stored is None:
        raise ValueError("operator job does not exist")
    if stored.domain == "corpus":
        await dependencies.corpus.cancel(job_id)
    else:
        await dependencies.evaluations.cancel(job_id)
    resource = await _operator_job(dependencies, job_id)
    if resource is None:
        raise RuntimeError("cancelled job disappeared from persistence")
    return resource


@router.get("/jobs/history", response_model=JobHistorySummaryResource)
async def job_history_summary(services: AdminServices) -> JobHistorySummaryResource:
    """Read protected active and terminal history counts."""
    async with translate_runtime_errors():
        return await _job_history_summary(services)


@router.post("/jobs/history", response_model=JobHistoryResultResource)
async def manage_job_history(
    request: JobHistoryRequest, services: AdminServices
) -> JobHistoryResultResource:
    """Apply one explicitly confirmed terminal-history operation."""
    try:
        async with translate_runtime_errors():
            return await _manage_job_history(services, request)
    except HistoryConflictError as error:
        raise ApiProblemError(
            status_code=409, code="history_changed", message=str(error)
        ) from error
    except OSError as error:
        raise ApiProblemError(
            status_code=503,
            code="history_backup_failed",
            message="The history backup could not be written; deletion was not completed.",
        ) from error


@router.get("/jobs/history/backups/{backup_id}", response_class=FileResponse)
async def job_history_backup(backup_id: str, services: AdminServices) -> FileResponse:
    """Download an owned backup without exposing arbitrary filesystem paths."""
    try:
        path = _job_history_backup(services, backup_id)
    except (ValueError, OSError) as error:
        raise not_found("job_history_backup", backup_id) from error
    return FileResponse(
        path, media_type="application/json", filename=f"job-history-{backup_id}.json"
    )


@router.get("/jobs", response_model=OperatorJobsResponse)
async def operator_jobs(services: AdminServices) -> OperatorJobsResponse:
    """Return the persistent unified corpus and evaluation job board."""
    async with translate_runtime_errors():
        return await _operator_jobs(services)


@router.get(
    "/jobs/{job_id}", response_model=OperatorJobResource, responses={404: {"model": ErrorResponse}}
)
async def operator_job(job_id: str, services: AdminServices) -> OperatorJobResource:
    """Return one persisted operator job by identity."""
    job = await _operator_job(services, job_id)
    if job is None:
        raise not_found("operator_job", job_id)
    return job


@router.post("/jobs/{job_id}/retry", response_model=OperatorJobResource)
async def retry_operator_job(job_id: str, services: AdminServices) -> OperatorJobResource:
    """Create a new queued job from failed or interrupted request provenance."""
    async with translate_runtime_errors():
        return await _retry_operator_job(services, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=OperatorJobResource)
async def cancel_operator_job(job_id: str, services: AdminServices) -> OperatorJobResource:
    """Cancel queued work or cooperatively cancel a supported running corpus job."""
    async with translate_runtime_errors():
        return await _cancel_operator_job(services, job_id)
