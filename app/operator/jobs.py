"""Persistent job ledger shared by corpus and evaluation workers."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Literal, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OperatorJob
from app.operator.job_history import ARCHIVE_KEY

type JobDomain = Literal["corpus", "evaluation"]
type JobStatus = Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]

logger = logging.getLogger(__name__)


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


class ProgressPersister:
    """Write one job's newest state with at most one database write in flight.

    Progress callbacks arrive in bursts. A task per callback holds a pooled connection
    while the writes serialize on the job row lock, and a late progress write can land
    after the terminal write and leave a finished job persisted as running. Here one
    write per job runs at a time, a snapshot that arrives during a write triggers
    exactly one more write, and the terminal write waits for the in-flight one first.
    """

    def __init__(self, write: Callable[[str], Awaitable[None]]) -> None:
        self._write = write
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._dirty: set[str] = set()
        self._closed: set[str] = set()

    def schedule(self, job_id: str) -> None:
        """Record that the job's newest state should be written soon."""
        if job_id in self._closed:
            return
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            self._dirty.add(job_id)
            return
        self._tasks[job_id] = asyncio.create_task(self._drain(job_id))

    async def flush(self, job_id: str) -> None:
        """Wait for the job's in-flight write and drop any pending re-write."""
        self._dirty.discard(job_id)
        task = self._tasks.pop(job_id, None)
        if task is not None and not task.done():
            await task

    async def write_final(
        self,
        job_id: str,
        write: Callable[[], Awaitable[None]] | None = None,
        *,
        attempts: int = 3,
    ) -> bool:
        """Flush progress, then write the terminal state, retrying transient failures.

        Returns whether the terminal write landed. The caller keeps its in-memory
        state either way; ``False`` means the ledger lags until a restart marks the
        job interrupted. Later progress writes for the job are ignored.
        """
        self._closed.add(job_id)
        await self.flush(job_id)
        run = write or (lambda: self._write(job_id))
        for attempt in range(1, attempts + 1):
            try:
                await run()
                return True
            except Exception as error:  # noqa: BLE001 - the ledger must not kill the worker
                logger.warning(
                    "job %s terminal write %d/%d failed: %s",
                    job_id,
                    attempt,
                    attempts,
                    type(error).__name__,
                )
                if attempt < attempts:
                    await asyncio.sleep(0.2 * attempt)
        return False

    async def _drain(self, job_id: str) -> None:
        """Write the latest snapshot, then once more if a newer one arrived meanwhile."""
        while True:
            self._dirty.discard(job_id)
            try:
                await self._write(job_id)
            except Exception as error:  # noqa: BLE001 - progress writes are best effort
                logger.warning("job %s progress write failed: %s", job_id, type(error).__name__)
            if job_id not in self._dirty:
                return


class JobExecutionCoordinator:
    """Serialize corpus and evaluation jobs in deterministic registration order."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._pending: list[tuple[datetime, str]] = []
        self._active: str | None = None
        self._kinds: dict[str, str] = {}
        self._waiting: dict[str, Callable[[str], None]] = {}

    def has_kind(self, kind: str) -> bool:
        """Report a registered active or pending prerequisite without a database poll."""
        return kind in self._kinds.values()

    def _notify_waiters(self) -> None:
        """Refresh queued messages synchronously; callbacks may schedule, never await, writes."""
        preceding = self._active
        for _created, identity in self._pending:
            callback = self._waiting.get(identity)
            if callback is not None:
                callback(
                    f"Waiting for {self._kinds[preceding]} {preceding} to finish."
                    if preceding is not None
                    else "Queued"
                )
            if preceding is None:
                preceding = identity

    @property
    def busy(self) -> bool:
        """True while a job holds the turn or waits for it.

        Both fields change only on the event loop between awaits, so a plain read
        needs no lock; readiness uses it to decide how long a status reading may age.
        """
        return self._active is not None or bool(self._pending)

    async def register(
        self,
        job_id: str,
        created_at: datetime,
        *,
        kind: str = "job",
        on_wait: Callable[[str], None] | None = None,
    ) -> None:
        """Register one job before either domain worker can compete for execution."""
        async with self._condition:
            if any(identity == job_id for _created, identity in self._pending):
                raise ValueError(f"job {job_id} is already registered")
            self._kinds[job_id] = kind
            if on_wait is not None:
                self._waiting[job_id] = on_wait
            self._pending.append((created_at, job_id))
            self._pending.sort(key=lambda item: (item[0], item[1]))
            self._notify_waiters()
            self._condition.notify_all()

    async def cancel(self, job_id: str) -> None:
        """Remove one not-yet-active ticket and wake its waiting worker."""
        async with self._condition:
            self._pending = [item for item in self._pending if item[1] != job_id]
            if self._active != job_id:
                self._kinds.pop(job_id, None)
                self._waiting.pop(job_id, None)
            self._notify_waiters()
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
                    self._waiting.pop(job_id, None)
                    self._notify_waiters()
                    break
                await self._condition.wait()
        try:
            yield
        finally:
            async with self._condition:
                if self._active == job_id:
                    self._active = None
                self._kinds.pop(job_id, None)
                self._waiting.pop(job_id, None)
                self._notify_waiters()
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
