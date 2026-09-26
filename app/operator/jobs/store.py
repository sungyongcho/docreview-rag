import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OperatorJob
from app.db.session_factory import default_session_factory
from app.operator.jobs.history import ARCHIVE_KEY

type JobDomain = Literal["corpus", "evaluation"]


type JobStatus = Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]


@dataclass(frozen=True, slots=True)
class StoredJob:
    """One database job projected without ORM session ownership."""

    job_id: str
    domain: JobDomain
    kind: str
    request_json: dict[str, object]
    status: JobStatus
    stage: str
    current: int
    total: int | None
    detail_current: int | None
    detail_total: int | None
    message: str
    error_code: str | None
    result_refs: dict[str, object]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class JobStore:
    """Persist queue state and fail closed across process restarts."""

    def __init__(
        self, *, session_factory: Callable[[], AsyncSession] = default_session_factory
    ) -> None:
        self._session_factory = session_factory
        self._recovered_domains: set[JobDomain] = set()
        self._recovery_lock = asyncio.Lock()

    async def recover(self, domain: JobDomain) -> None:
        """Interrupt previous-process work once, before any current job is registered."""
        async with self._recovery_lock:
            if domain not in self._recovered_domains:
                await self.interrupt_incomplete(domain)
                self._recovered_domains.add(domain)

    @staticmethod
    def _stored(row: OperatorJob) -> StoredJob:
        """Detach one ORM row into a frozen service value."""
        return StoredJob(
            job_id=row.job_id,
            domain=cast("JobDomain", row.domain),
            kind=row.kind,
            request_json=dict(row.request_json),
            status=cast("JobStatus", row.status),
            stage=row.stage,
            current=row.current,
            total=row.total,
            detail_current=row.detail_current,
            detail_total=row.detail_total,
            message=row.message,
            error_code=row.error_code,
            result_refs=dict(row.result_refs),
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            updated_at=row.updated_at,
        )

    async def create(
        self,
        *,
        job_id: str,
        domain: JobDomain,
        kind: str,
        request_json: dict[str, object],
        message: str = "Queued",
        created_at: datetime | None = None,
        result_refs: dict[str, object] | None = None,
    ) -> StoredJob:
        """Insert one queued job before in-process dispatch."""
        async with self._session_factory() as session:
            row = OperatorJob(
                job_id=job_id,
                domain=domain,
                kind=kind,
                request_json=request_json,
                status="queued",
                stage="queued",
                current=0,
                total=None,
                detail_current=None,
                detail_total=None,
                message=message,
                error_code=None,
                result_refs=result_refs or {},
                created_at=created_at or datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._stored(row)

    async def put(
        self,
        job_id: str,
        *,
        status: JobStatus,
        stage: str,
        current: int,
        total: int | None,
        detail_current: int | None,
        detail_total: int | None,
        message: str,
        started_at: datetime | None,
        finished_at: datetime | None,
        error_code: str | None = None,
        result_refs: dict[str, object] | None = None,
    ) -> StoredJob:
        """Replace mutable progress fields for one existing job."""
        async with self._session_factory() as session:
            row = await session.get(OperatorJob, job_id, with_for_update=True)
            if row is None:
                raise ValueError(f"operator job {job_id} does not exist")
            row.status = status
            row.stage = stage
            row.current = current
            row.total = total
            row.detail_current = detail_current
            row.detail_total = detail_total
            row.message = message
            row.started_at = started_at
            row.finished_at = finished_at
            row.error_code = error_code
            if result_refs is not None:
                row.result_refs = {**row.result_refs, **result_refs}
            await session.commit()
            await session.refresh(row)
        return self._stored(row)

    async def get(self, job_id: str) -> StoredJob | None:
        """Return one persisted job or null."""
        async with self._session_factory() as session:
            row = await session.get(OperatorJob, job_id)
        return self._stored(row) if row is not None else None

    async def queue_positions(self) -> dict[str, int]:
        """Read the whole pending queue in the coordinator's timestamp and ID order."""
        statement = (
            select(OperatorJob.job_id)
            .where(OperatorJob.status == "queued")
            .order_by(OperatorJob.created_at, OperatorJob.job_id)
        )
        async with self._session_factory() as session:
            job_ids = tuple(await session.scalars(statement))
        return {job_id: position for position, job_id in enumerate(job_ids, start=1)}

    async def list(
        self, *, domain: JobDomain | None = None, limit: int = 100, include_archived: bool = False
    ) -> tuple[StoredJob, ...]:
        """Return newest-first persisted jobs with an optional domain filter."""
        statement = select(OperatorJob).order_by(
            OperatorJob.created_at.desc(), OperatorJob.job_id.desc()
        )
        if domain is not None:
            statement = statement.where(OperatorJob.domain == domain)
        if not include_archived:
            statement = statement.where(
                ~OperatorJob.result_refs.contains({ARCHIVE_KEY: True})
                | OperatorJob.status.in_(("queued", "running"))
            )
        async with self._session_factory() as session:
            rows = tuple(await session.scalars(statement.limit(limit)))
        return tuple(self._stored(row) for row in rows)

    async def interrupt_incomplete(self, domain: JobDomain) -> tuple[str, ...]:
        """Mark pre-existing queued/running work interrupted instead of auto-resuming it."""
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            ids = tuple(
                await session.scalars(
                    select(OperatorJob.job_id).where(
                        OperatorJob.domain == domain,
                        OperatorJob.status.in_(("queued", "running")),
                    )
                )
            )
            if ids:
                await session.execute(
                    update(OperatorJob)
                    .where(OperatorJob.job_id.in_(ids))
                    .values(
                        status="interrupted",
                        stage="interrupted",
                        message="Interrupted by application restart; retry explicitly.",
                        error_code="process_restarted",
                        finished_at=now,
                        updated_at=now,
                    )
                )
                await session.commit()
        return ids

    async def cancel(self, job_id: str) -> StoredJob:
        """Persist an explicit cancellation request for queued or running work."""
        row = await self.get(job_id)
        if row is None:
            raise ValueError("operator job does not exist")
        if row.status not in {"queued", "running"}:
            raise ValueError("only queued or running jobs can be cancelled")
        now = datetime.now(UTC)
        return await self.put(
            job_id,
            status="cancelled",
            stage="cancelled",
            current=row.current,
            total=row.total,
            detail_current=row.detail_current,
            detail_total=row.detail_total,
            message="Cancelled by operator.",
            started_at=row.started_at,
            finished_at=now,
            error_code="cancelled",
            result_refs=row.result_refs,
        )
