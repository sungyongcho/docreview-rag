"""Historical operator jobs stay visible without becoming executable commands."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.admin_runtime import RuntimeAdminApiServices
from app.operator.jobs import StoredJob


def test_job_board_reads_history_without_revalidating_ingestion_arguments():
    """Retain a completed old request while refusing an incomplete request's retry."""
    now = datetime.now(UTC)
    job = StoredJob(
        job_id="old-ingest",
        domain="corpus",
        kind="ingest_manifest",
        request_json={"manifest": "manifest.json"},
        status="failed",
        stage="failed",
        current=0,
        total=None,
        detail_current=None,
        detail_total=None,
        message="Earlier ingestion failed",
        error_code=None,
        result_refs={},
        created_at=now,
        started_at=now,
        finished_at=now,
        updated_at=now,
    )
    service = object.__new__(RuntimeAdminApiServices)
    service._corpus = SimpleNamespace(recover_jobs=AsyncMock())
    service._evaluations = SimpleNamespace(recover_jobs=AsyncMock())
    service._job_store = SimpleNamespace(list=AsyncMock(return_value=[job]))
    board = asyncio.run(service.operator_jobs())
    assert board.jobs[0].request == {"manifest": "manifest.json"}
    assert board.jobs[0].message == job.message
    assert board.jobs[0].can_retry is False
