"""Exercise system behavior at service and HTTP boundaries."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.api.app import create_api_app
from app.api.dependencies import create_admin_services
from app.api.review.runtime import RuntimeApiServices
from app.api.system.jobs import _operator_job, _operator_jobs, _readiness_status
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.corpus_admin.types import AdminCommand, CorpusStatus
from app.evals.admin.service import EvaluationAdminService
from app.operator.jobs.store import JobDomain, JobStatus
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from tests.api.support import _admin


@pytest.mark.parametrize(
    "running_domain,running_kind,running_can_cancel",
    [
        ("corpus", "backfill_embeddings", True),
        ("corpus", "ingest_selected", False),
        ("evaluation", "quick", False),
    ],
)
def test_operator_board_reads_persisted_history_and_global_queue_actions(
    running_domain: JobDomain,
    running_kind: Literal["backfill_embeddings", "ingest_selected", "quick"],
    running_can_cancel: bool,
):
    """A fresh API instance shows shared FIFO positions and safe actions from current records."""
    from datetime import timedelta

    from app.corpus_admin.types import command_payload
    from app.evals.contracts import EvaluationRunRequest
    from tests.corpus_admin.support import LedgerStore

    async def scenario():
        """Populate the ledger without workers, then exercise the real board and lookup."""
        from dataclasses import replace

        from app.operator.jobs.history import ARCHIVE_KEY

        store = LedgerStore()
        started = datetime(2026, 9, 1, tzinfo=UTC)
        ingest = command_payload(AdminCommand("ingest_selected", document_ids=("filing-a",)))
        evaluation = EvaluationRunRequest(suite_id="sec-en").model_dump(mode="json")
        running_request = (
            evaluation
            if running_kind == "quick"
            else command_payload(
                AdminCommand(
                    running_kind,
                    document_ids=("filing-a",) if running_kind == "ingest_selected" else None,
                )
            )
        )
        records: tuple[tuple[str, JobDomain, str, dict[str, object], JobStatus], ...] = (
            ("history-success", "corpus", "ingest_selected", ingest, "succeeded"),
            (
                "failed-corpus",
                "corpus",
                "rebuild_bm25",
                command_payload(AdminCommand("rebuild_bm25")),
                "failed",
            ),
            ("failed-evaluation", "evaluation", "quick", evaluation, "failed"),
            (
                "failed-deletion",
                "corpus",
                "delete_sources",
                command_payload(
                    AdminCommand("delete_sources", deletion_token="preview", confirm_delete=True)
                ),
                "failed",
            ),
            ("interrupted-evaluation", "evaluation", "quick", evaluation, "interrupted"),
            ("running", running_domain, running_kind, running_request, "running"),
            ("queued-evaluation", "evaluation", "quick", evaluation, "queued"),
            ("queued-corpus", "corpus", "ingest_selected", ingest, "queued"),
        )
        for index, (job_id, domain, kind, request, status) in enumerate(records):
            created = started + timedelta(minutes=index)
            await store.create(
                job_id=job_id, domain=domain, kind=kind, request_json=request, created_at=created
            )
            if status != "queued":
                await store.put(
                    job_id,
                    status=status,
                    stage="work" if status == "running" else status,
                    current=1,
                    total=2,
                    detail_current=None,
                    detail_total=None,
                    message=f"Recorded {job_id}",
                    started_at=created,
                    finished_at=None if status == "running" else created + timedelta(seconds=10),
                    error_code="operation_failed" if status == "failed" else None,
                    result_refs={"selection_id": "selected"} if job_id == "history-success" else {},
                )

        def api():
            """Start a fresh API projection with only recovery side effects replaced."""
            service = SimpleNamespace()
            service.corpus = cast(
                RuntimeCorpusAdminService, SimpleNamespace(recover_jobs=AsyncMock())
            )
            service.evaluations = cast(
                EvaluationAdminService, SimpleNamespace(recover_jobs=AsyncMock())
            )
            service.jobs = store
            return service

        board = await _operator_jobs(api())
        assert board.active_count == 1
        assert board.queued_count == 2
        assert [
            (job.job_id, job.queue_position, job.can_cancel, job.can_retry) for job in board.jobs
        ] == [
            ("queued-corpus", 2, True, False),
            ("queued-evaluation", 1, True, False),
            ("running", None, running_can_cancel, False),
            ("interrupted-evaluation", None, False, True),
            ("failed-deletion", None, False, False),
            ("failed-evaluation", None, False, True),
            ("failed-corpus", None, False, True),
            ("history-success", None, False, False),
        ]
        historical = board.jobs[-1]
        assert historical.request["document_ids"] == ["filing-a"]
        assert historical.message == "Recorded history-success"
        assert historical.result_refs == {"selection_id": "selected"}
        assert (historical.current, historical.total) == (1, 2)
        fresh = api()
        assert await _operator_job(fresh, "queued-corpus") == board.jobs[0]
        assert await _operator_job(fresh, "failed-evaluation") == board.jobs[5]
        assert await _operator_job(fresh, "missing") is None
        assert store.puts == ["succeeded", "failed", "failed", "failed", "interrupted", "running"]
        for index in range(100):
            row = await store.create(
                job_id=f"recent-{index}",
                domain="corpus",
                kind="ingest_selected",
                request_json=ingest,
                created_at=started + timedelta(days=1, minutes=index),
            )
            store.rows[row.job_id] = replace(row, status="succeeded", stage="succeeded")
        assert len((await _operator_jobs(fresh)).jobs) == 100
        assert await _operator_job(fresh, "history-success") == historical
        assert await _operator_job(fresh, "queued-corpus") == board.jobs[0]
        failed = store.rows["failed-evaluation"]
        store.rows[failed.job_id] = replace(failed, result_refs={ARCHIVE_KEY: True})
        assert await _operator_job(fresh, failed.job_id) is None
        store.rows[failed.job_id] = failed
        assert await _operator_job(fresh, failed.job_id) == board.jobs[5]

    asyncio.run(scenario())


class _RecordingCorpus:
    """Stand-in corpus service that records the reuse window each readiness read allowed."""

    def __init__(self) -> None:
        self.ages: list[float] = []

    async def status(self, *, max_age_s: float = 0.0) -> CorpusStatus:
        """Return one fixed compatible status."""
        self.ages.append(max_age_s)
        return CorpusStatus(
            database_connected=True,
            schema_status="compatible",
            schema_message="ok",
            documents=1,
            chunks=1,
            embedded_chunks=1,
            pending_embeddings=0,
            bm25_ready=True,
            writable=True,
            provider="deterministic",
        )


def test_readiness_status_extends_max_age_while_a_job_is_registered() -> None:
    """Readiness reuses a reading for 2 s normally and 10 s while a job holds or awaits its turn."""
    corpus = _RecordingCorpus()
    services = create_admin_services(
        runtime=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
        corpus=cast(RuntimeCorpusAdminService, corpus),
    )

    async def scenario() -> None:
        """Read readiness idle, with a registered job, and after its cancellation."""
        await _readiness_status(services)
        await services.coordinator.register("job-1", datetime.now(UTC))
        await _readiness_status(services)
        await services.coordinator.cancel("job-1")
        await _readiness_status(services)

    asyncio.run(scenario())
    assert corpus.ages == [2.0, 10.0, 2.0]


def test_history_routes_validate_scope_and_translate_conflicts(tmp_path):
    """History confirmation, conflict and backup failures retain their HTTP semantics."""
    from app.operator.jobs.history import HistoryConflictError, HistoryResult, HistorySummary

    async def apply(action, expected_count, confirmation):
        """Emulate the history transaction's distinct refusal modes."""
        if expected_count != 3:
            raise HistoryConflictError("Job history changed; refresh")
        if action == "delete":
            if confirmation != "DELETE JOB HISTORY":
                raise ValueError("Type DELETE JOB HISTORY to confirm deletion")
            raise OSError("private filesystem details")
        return HistoryResult(action, ("1", "2", "3"), None)

    def backup_path(backup_id):
        """Resolve only the prepared backup identity."""
        if backup_id != "known":
            raise ValueError("Invalid backup identifier")
        return tmp_path / "backup.json"

    (tmp_path / "backup.json").write_text('{"records": []}')
    history = SimpleNamespace(
        summary=AsyncMock(return_value=HistorySummary(2, 1, 3)),
        apply=apply,
        backup_path=backup_path,
    )
    with TestClient(create_api_app(admin_services=_admin(history=history))) as client:
        assert client.get("/admin/jobs/history").json()["active"] == 3
        assert (
            client.post(
                "/admin/jobs/history", json={"action": "restore", "expected_count": 3}
            ).status_code
            == 200
        )
        conflict = client.post(
            "/admin/jobs/history", json={"action": "archive", "expected_count": 1}
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "history_changed"
        assert (
            client.post(
                "/admin/jobs/history", json={"action": "delete", "expected_count": 3}
            ).status_code
            == 400
        )
        failure = client.post(
            "/admin/jobs/history",
            json={"action": "delete", "expected_count": 3, "confirmation": "DELETE JOB HISTORY"},
        )
        assert failure.status_code == 503
        assert "private filesystem details" not in failure.text
        assert client.get("/admin/jobs/history/backups/unknown").status_code == 404
        assert client.get("/admin/jobs/history/backups/known").json() == {"records": []}
    with TestClient(create_api_app()) as client:
        assert client.get("/admin/jobs/history/backups/known").status_code == 404
