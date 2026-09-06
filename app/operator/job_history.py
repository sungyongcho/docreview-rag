"""Archive terminal job records and back them up before explicit deletion."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import stat
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OperatorJob

ARCHIVE_KEY = "__history_archived"
TERMINAL_STATUSES = ("succeeded", "failed", "interrupted", "cancelled")
type HistoryAction = Literal["archive", "restore", "delete"]


class HistoryConflictError(RuntimeError):
    """The eligible history changed after the operator reviewed its count."""


@dataclass(frozen=True, slots=True)
class HistorySummary:
    """Counts of terminal visible/archived records and excluded active jobs."""

    visible: int
    archived: int
    active: int


@dataclass(frozen=True, slots=True)
class HistoryResult:
    """Changed ledger identities and an optional private backup identifier."""

    action: HistoryAction
    changed_ids: tuple[str, ...]
    backup_id: str | None


class JobHistoryService:
    """Maintain history without replaying work or touching result artifacts."""

    def __init__(self, session_factory: Callable[[], AsyncSession], backup_dir: Path) -> None:
        """Keep the caller's session factory and dedicated private backup directory."""
        self._session_factory = session_factory
        self._backup_dir = Path(backup_dir).absolute()

    async def summary(self) -> HistorySummary:
        """Count history from persisted records rather than worker caches."""
        async with self._session_factory() as session:
            rows = await session.execute(select(OperatorJob.status, OperatorJob.result_refs))
            visible = archived = active = 0
            for status, refs in rows:
                if status in TERMINAL_STATUSES:
                    if refs.get(ARCHIVE_KEY) is True:
                        archived += 1
                    else:
                        visible += 1
                elif status in ("queued", "running"):
                    active += 1
        return HistorySummary(visible=visible, archived=archived, active=active)

    async def apply(
        self, action: HistoryAction, expected_count: int, confirmation: str = ""
    ) -> HistoryResult:
        """Lock eligible terminal records, validate the count and apply one action."""
        if action not in ("archive", "restore", "delete"):
            raise ValueError("Unsupported job history action")
        if expected_count < 0:
            raise ValueError("Expected count must be nonnegative")
        if action == "delete" and confirmation != "DELETE JOB HISTORY":
            raise ValueError("Type DELETE JOB HISTORY to confirm deletion")
        backup_id = None
        async with self._session_factory() as session, session.begin():
            rows = tuple(
                await session.scalars(
                    select(OperatorJob)
                    .where(OperatorJob.status.in_(TERMINAL_STATUSES))
                    .order_by(OperatorJob.job_id)
                    .with_for_update()
                )
            )
            eligible = tuple(
                row
                for row in rows
                if action == "delete"
                or (row.result_refs.get(ARCHIVE_KEY) is True) == (action == "restore")
            )
            if len(eligible) != expected_count:
                raise HistoryConflictError(
                    "Job history changed; refresh the counts and review again"
                )
            if action == "delete" and eligible:
                # No DELETE is issued until the complete backup is durable on disk.
                backup_id = self._write_backup(eligible)
                for row in eligible:
                    await session.delete(row)
            else:
                for row in eligible:
                    refs = dict(row.result_refs)
                    if action == "archive":
                        refs[ARCHIVE_KEY] = True
                    else:
                        refs.pop(ARCHIVE_KEY, None)
                    row.result_refs = refs
            changed_ids = tuple(row.job_id for row in eligible)
        return HistoryResult(action=action, changed_ids=changed_ids, backup_id=backup_id)

    def _check_directory(self, *, create: bool = False) -> None:
        """Reject symlink paths and require a private, process-owned directory."""
        for part in (*reversed(self._backup_dir.parents), self._backup_dir):
            if part.is_symlink():
                raise ValueError("Backup directory must not contain symlinks")
        if create:
            self._backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self._backup_dir.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise ValueError("Backup directory must be private and owned by the application")

    def _write_backup(self, rows: tuple[OperatorJob, ...]) -> str:
        """Atomically publish and fsync a complete JSON backup before database deletion."""
        self._check_directory(create=True)
        backup_id = str(uuid4())
        target = self._backup_dir / f"{backup_id}.json"
        temporary = self._backup_dir / f".{backup_id}.tmp"
        records = []
        for row in rows:
            record = {}
            for column in OperatorJob.__table__.columns:
                value = getattr(row, column.key)
                record[column.key] = value.isoformat() if isinstance(value, datetime) else value
            records.append(record)
        payload = {
            "format": "docreview-job-history-v1",
            "backup_id": backup_id,
            "created_at": datetime.now(UTC).isoformat(),
            "records": records,
        }
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory = os.open(self._backup_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return backup_id

    def backup_path(self, backup_id: str) -> Path:
        """Resolve only an owned private UUID backup for an authenticated download."""
        if str(UUID(backup_id)) != backup_id:
            raise ValueError("Invalid backup identifier")
        self._check_directory()
        path = self._backup_dir / f"{backup_id}.json"
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("Backup must be a private application-owned regular file")
        return path
