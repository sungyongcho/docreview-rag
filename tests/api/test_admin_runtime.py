"""Historical operator jobs stay visible without becoming executable commands."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.runtime import RuntimeApiServices
from app.corpus_admin import CorpusStatus
from app.operator.jobs import StoredJob
from app.retrieval.embeddings import DeterministicEmbeddingProvider


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


def test_document_detail_checks_schema_before_serializing():
    """Do not disguise incompatible document storage as an ordinary missing document."""
    import pytest

    from app.api.errors import ApiProblemError, unavailable

    service = object.__new__(RuntimeAdminApiServices)
    service._documents = SimpleNamespace(
        ensure_ready=AsyncMock(side_effect=unavailable("schema_not_ready", "drifted"))
    )
    service._corpus = SimpleNamespace(document_detail=AsyncMock())
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(service.document_detail("test"))
    assert error.value.error.code == "schema_not_ready"
    service._corpus.document_detail.assert_not_called()


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
    services = RuntimeAdminApiServices(
        runtime=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
        corpus=corpus,  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        """Read readiness idle, with a registered job, and after its cancellation."""
        await services.readiness_status()
        await services._execution_coordinator.register("job-1", datetime.now(UTC))
        await services.readiness_status()
        await services._execution_coordinator.cancel("job-1")
        await services.readiness_status()

    asyncio.run(scenario())
    assert corpus.ages == [2.0, 10.0, 2.0]


def test_duplicate_evaluation_is_a_typed_409():
    """Expose the authoritative duplicate identity through the standard API error contract."""
    import pytest

    from app.api.admin_schemas import EvaluationRunRequest
    from app.api.errors import ApiProblemError
    from app.evals.admin import EvaluationAlreadyQueuedError

    service = object.__new__(RuntimeAdminApiServices)
    service._evaluations = SimpleNamespace(
        enqueue=AsyncMock(side_effect=EvaluationAlreadyQueuedError("eval-existing"))
    )
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(service.enqueue_evaluation(EvaluationRunRequest(suite_id="sec-en")))
    assert error.value.status_code == 409
    assert error.value.error.code == "evaluation_already_queued"
    assert "eval-existing" in error.value.error.message


def test_acquisition_api_preserves_absent_deletion_and_document_arguments():
    """New optional deletion fields must not make ordinary corpus commands invalid."""
    from app.api.admin_schemas import CorpusOperationRequest
    from app.corpus_admin import AdminJob

    request = CorpusOperationRequest(kind="acquire_edgar", identifiers=("NVDA",), years=(2024,))
    service = object.__new__(RuntimeAdminApiServices)

    async def enqueue(command):
        """Return the accepted command through the actual dataclass serialization boundary."""
        assert command.document_ids is None and command.confirm_delete is None
        return AdminJob("download", command, "queued", "queued", 0, None, "Queued")

    service._corpus = SimpleNamespace(enqueue=enqueue)
    result = asyncio.run(service.enqueue_corpus(request))
    assert result["command"]["kind"] == "acquire_edgar"
