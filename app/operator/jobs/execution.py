import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
import logging

from sqlalchemy.exc import InterfaceError, OperationalError

logger = logging.getLogger(__name__)


class JobTurnCancelledError(RuntimeError):
    """Signal that a queued ticket was removed before execution."""


class JobPersistenceError(RuntimeError):
    """Keep an uncommitted terminal snapshot distinct from an operation failure."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Terminal state for job {job_id} could not be saved.")


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
        self._active: set[str] = set()
        self._pending: dict[str, Callable[[], Awaitable[None]]] = {}
        self._write_lock = asyncio.Lock()

    def start(self, job_id: str) -> None:
        """Accept progress only while a registered job is active in this process."""
        self._active.add(job_id)

    def schedule(self, job_id: str) -> None:
        """Record that the job's newest state should be written soon."""
        if job_id not in self._active:
            return
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            self._dirty.add(job_id)
            return
        self._tasks[job_id] = asyncio.create_task(self._drain(job_id))

    async def flush(self, job_id: str) -> None:
        """Wait for the job's in-flight write and drop any pending re-write."""
        self._dirty.discard(job_id)
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.shield(task)
            if self._tasks.get(job_id) is task:
                self._tasks.pop(job_id)

    async def write_final(
        self,
        job_id: str,
        write: Callable[[], Awaitable[None]],
    ) -> None:
        """Commit a terminal snapshot or retain it and raise an explicit persistence failure.

        Only transport/database availability errors are retried. Pending snapshots are
        retried before callers read history or admit new work, so a failed terminal write
        cannot silently turn completed work back into a queued/running response.
        """
        self._active.discard(job_id)
        self._pending[job_id] = write
        await self._commit_final(job_id)

    async def write_current(self, job_id: str) -> None:
        """Save required usage before work continues, propagating any storage failure."""
        await self.flush(job_id)
        async with self._write_lock:
            await self._write(job_id)

    async def retry_pending(self) -> None:
        """Reconcile uncommitted terminal snapshots before exposing durable job history."""
        for job_id in tuple(self._pending):
            await self._commit_final(job_id)

    async def _commit_final(self, job_id: str) -> None:
        """Save a retained immutable snapshot, preserving the original failure cause."""
        await self.flush(job_id)
        async with self._write_lock:
            write = self._pending.get(job_id)
            if write is None:
                return
            for attempt in range(1, 4):
                try:
                    await write()
                except (OSError, InterfaceError, OperationalError) as error:
                    if attempt < 3:
                        await asyncio.sleep(0.2 * attempt)
                        continue
                    raise JobPersistenceError(job_id) from error
                except Exception as error:
                    raise JobPersistenceError(job_id) from error
                if self._pending.get(job_id) is write:
                    self._pending.pop(job_id)
                return

    async def _drain(self, job_id: str) -> None:
        """Write the latest snapshot, then once more if a newer one arrived meanwhile."""
        while True:
            self._dirty.discard(job_id)
            try:
                async with self._write_lock:
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
