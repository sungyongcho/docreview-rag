"""Fakes and builders shared by corpus administrator tests."""

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

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


def write_manifest(root: Path) -> None:
    """Write a small common catalog with one exact acquired selection."""
    import hashlib

    raw = b"report"
    (root / "report.html").write_bytes(raw)
    payload = {
        "corpus": {"corpus_id": "test", "name": "Test"},
        "documents": [
            {
                "document_id": "nvda-2024",
                "registry": "sec",
                "language": "en",
                "issuer": "NVDA",
                "issuer_id": "0001045810",
                "filing_id": "0001045810-24-000001",
                "fiscal_year": 2024,
                "form": "10-K",
                "filing_date": "2024-02-01",
                "report_period": "2024-01-01",
                "source_url": "https://example.org/report",
                "sec": {
                    "cik": "0001045810",
                    "accession": "0001045810-24-000001",
                    "primary_document": "report.html",
                },
            }
        ],
        "artifacts": [
            {
                "artifact_id": "nvda-source",
                "document_id": "nvda-2024",
                "role": "primary",
                "path": "report.html",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_length": len(raw),
                "encoding": "utf-8",
                "acquisition": {
                    "acquired_at": "2024-02-01T00:00:00Z",
                    "url": "https://example.org/report",
                    "media_type": "text/html",
                },
            }
        ],
        "selections": [{"selection_id": "selected", "artifact_ids": ["nvda-source"]}],
    }
    (root / "manifest.json").write_text(json.dumps(payload))
