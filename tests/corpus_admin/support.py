"""Fakes and builders shared by corpus administrator tests."""

from dataclasses import replace
from datetime import UTC, datetime

from app.operator.jobs import JobDomain, JobStatus, JobStore, StoredJob


class LedgerStore(JobStore):
    """In-memory job ledger whose writes can be made to fail a set number of times."""

    def __init__(self, failures: int = 0) -> None:
        super().__init__()
        self.rows: dict[str, StoredJob] = {}
        self.failures = failures
        self.puts: list[str] = []

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
        """Insert one queued row."""
        now = created_at or datetime.now(UTC)
        row = StoredJob(
            job_id=job_id,
            domain=domain,
            kind=kind,
            request_json=dict(request_json),
            status="queued",
            stage="queued",
            current=0,
            total=None,
            detail_current=None,
            detail_total=None,
            message=message,
            error_code=None,
            result_refs=dict(result_refs or {}),
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
        self.rows[job_id] = row
        return row

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
        """Replace one row, raising while failures remain."""
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("ledger unavailable")
        row = self.rows[job_id]
        updated = replace(
            row,
            status=status,
            stage=stage,
            current=current,
            total=total,
            detail_current=detail_current,
            detail_total=detail_total,
            message=message,
            started_at=started_at,
            finished_at=finished_at,
            error_code=error_code,
            result_refs={**row.result_refs, **(result_refs or {})},
            updated_at=datetime.now(UTC),
        )
        self.rows[job_id] = updated
        self.puts.append(status)
        return updated

    async def get(self, job_id: str) -> StoredJob | None:
        """Return one row."""
        return self.rows.get(job_id)

    async def list(
        self, *, domain: JobDomain | None = None, limit: int = 100
    ) -> tuple[StoredJob, ...]:
        """Return newest-first rows."""
        rows = sorted(
            self.rows.values(), key=lambda row: (row.created_at, row.job_id), reverse=True
        )
        return tuple(row for row in rows if domain is None or row.domain == domain)[:limit]

    async def interrupt_incomplete(self, domain: JobDomain) -> tuple[str, ...]:
        """Nothing is stale in a fresh in-memory ledger."""
        del domain
        return ()
