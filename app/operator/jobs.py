"""Persistent job ledger shared by corpus and evaluation workers."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OperatorJob

type JobDomain = Literal["corpus", "evaluation"]
type JobStatus = Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]


def _default_session_factory() -> AsyncSession:
    """Create one caller-owned process session lazily."""
    from app.db.session import Session

    return Session()


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


class JobTurnCancelledError(RuntimeError):
    """Signal that a queued ticket was removed before execution."""


class JobExecutionCoordinator:
    """Serialize corpus and evaluation jobs in deterministic registration order."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._pending: list[tuple[datetime, str]] = []
        self._active: str | None = None

    async def register(self, job_id: str, created_at: datetime) -> None:
        """Register one job before either domain worker can compete for execution."""
        async with self._condition:
            if any(identity == job_id for _created, identity in self._pending):
                raise ValueError(f"job {job_id} is already registered")
            self._pending.append((created_at, job_id))
            self._pending.sort(key=lambda item: (item[0], item[1]))
            self._condition.notify_all()

    async def cancel(self, job_id: str) -> None:
        """Remove one not-yet-active ticket and wake its waiting worker."""
        async with self._condition:
            self._pending = [item for item in self._pending if item[1] != job_id]
            self._condition.notify_all()

    @asynccontextmanager
    async def turn(self, job_id: str) -> AsyncIterator[None]:
        """Yield only when this job is the oldest pending global ticket."""
        async with self._condition:
            while True:
                identities = {identity for _created, identity in self._pending}
                if job_id not in identities:
                    raise JobTurnCancelledError("job ticket was cancelled")
                if self._active is None and self._pending[0][1] == job_id:
                    self._pending.pop(0)
                    self._active = job_id
                    break
                await self._condition.wait()
        try:
            yield
        finally:
            async with self._condition:
                if self._active == job_id:
                    self._active = None
                self._condition.notify_all()


class JobStore:
    """Persist queue state and fail closed across process restarts."""

    def __init__(
        self, *, session_factory: Callable[[], AsyncSession] = _default_session_factory
    ) -> None:
        self._session_factory = session_factory

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

    async def list(
        self, *, domain: JobDomain | None = None, limit: int = 100
    ) -> tuple[StoredJob, ...]:
        """Return newest-first persisted jobs with an optional domain filter."""
        statement = select(OperatorJob).order_by(
            OperatorJob.created_at.desc(), OperatorJob.job_id.desc()
        )
        if domain is not None:
            statement = statement.where(OperatorJob.domain == domain)
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
