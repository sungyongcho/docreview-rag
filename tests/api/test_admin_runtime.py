"""Historical operator jobs stay visible without becoming executable commands."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.live_postgres
def test_evaluation_jobs_expose_each_recorded_result_configuration():
    """Read distinct matrix-arm metadata from real PostgreSQL without reading artifact files."""
    import asyncio
    import os
    from types import SimpleNamespace

    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.admin_schemas import (
        EvaluationJobResource,
        EvaluationJobsResponse,
        EvaluationRunRequest,
    )
    from app.db.bootstrap import bootstrap_schema
    from app.db.models import EvalResult
    from tests.live_postgres import live_postgres_unavailable

    dsn = os.getenv("EVAL_IDENTITY_TEST_DSN")
    if not dsn:
        live_postgres_unavailable("EVAL_IDENTITY_TEST_DSN is not configured")
    url = make_url(dsn)
    assert url.host in {"localhost", "127.0.0.1"} and url.database.startswith("pipeline_test_")

    async def exercise():
        """Compose only the read boundary against an explicitly disposable database."""
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await bootstrap_schema(engine)
            async with factory.begin() as session:
                rows = [
                    EvalResult(
                        suite="dart-en",
                        config={
                            "golden_provenance": {
                                "filename": "recorded.json",
                                "golden_sha256": "a" * 64,
                            },
                            "strategy": strategy,
                            "k": 5,
                        },
                        metrics={},
                        raw_artifact_path="not-read.json",
                    )
                    for strategy in ["lexical", "hybrid"]
                ]
                session.add_all(rows)
            board = EvaluationJobsResponse(
                jobs=(
                    EvaluationJobResource(
                        job_id="matrix-fixture",
                        request=EvaluationRunRequest(suite_id="dart-en", mode="matrix"),
                        status="succeeded",
                        stage="done",
                        message="Done",
                        created_at=rows[0].created_at,
                        result_id=rows[0].id,
                        result_ids=tuple(row.id for row in rows),
                    ),
                )
            )
            service = object.__new__(RuntimeAdminApiServices)
            service._runtime = SimpleNamespace(session_factory=factory)
            service._evaluations = SimpleNamespace(jobs=AsyncMock(return_value=board))
            result = await service.evaluation_jobs()
            assert [item.config["strategy"] for item in result.jobs[0].result_summaries] == [
                "lexical",
                "hybrid",
            ]
            assert all(
                item.config["golden_provenance"]["filename"] == "recorded.json"
                for item in result.jobs[0].result_summaries
            )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_golden_evidence_pages_preserve_exact_source_coordinates():
    """A separate PostgreSQL fixture proves chunk paging, search, and original spans."""
    import os

    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.bootstrap import bootstrap_schema
    from app.ingestion.seed import persist_seed_batch
    from tests.ingestion.seed.support import sample_batch
    from tests.live_postgres import live_postgres_unavailable

    dsn = os.getenv("GOLDEN_EVIDENCE_TEST_DSN")
    if not dsn:
        live_postgres_unavailable("GOLDEN_EVIDENCE_TEST_DSN is not configured")
    url = make_url(dsn)
    assert url.host in {"localhost", "127.0.0.1"} and url.database.startswith("pipeline_test_")

    async def exercise():
        """Use real seeded source identities and leave the user database untouched."""
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await bootstrap_schema(engine)
            batch = sample_batch()
            async with factory() as session:
                await persist_seed_batch(session, batch)
            service = object.__new__(RuntimeAdminApiServices)
            service._runtime = SimpleNamespace(session_factory=factory)
            first = await service.golden_evidence_chunks("NVDA-FY2024", "", 0, 1)
            second = await service.golden_evidence_chunks("NVDA-FY2024", "", first.next_after, 1)
            assert len(first.chunks) == len(second.chunks) == 1
            assert first.chunks[0].chunk_id != second.chunks[0].chunk_id
            assert second.next_after is None
            chunk = first.chunks[0]
            assert chunk.source_sha256 == "a" * 64
            assert (chunk.start_char, chunk.end_char) == (10, 40)
            assert chunk.body == "Source-derived narrative."
            search = await service.golden_evidence_chunks("NVDA-FY2024", "narrative", 0, 20)
            assert [row.chunk_id for row in search.chunks] == [chunk.chunk_id]
            assert not (await service.golden_evidence_chunks("missing", "", 0, 20)).chunks
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_source_deletion_preview_accepts_the_plan_lists_from_the_corpus_service():
    """The fingerprinted plan carries JSON lists; the strict resource still validates."""
    from app.api.admin_schemas import SourceDeletionRequest

    plan = {
        "token": "preview-token",
        "expires_at": 1_800_000_000.5,
        "documents": [
            {
                "document_id": "dart-20250311001085",
                "registry": "dart",
                "issuer": "005930",
                "fiscal_year": 2024,
                "filing_id": "20250311001085",
            }
        ],
        "files": [
            {"path": "dart/005930/20250311001085/primary.xml", "byte_length": 10, "retained": False}
        ],
        "retained_inputs": 2,
        "retained_derived": True,
    }
    service = object.__new__(RuntimeAdminApiServices)
    service._corpus = SimpleNamespace(preview_source_deletion=AsyncMock(return_value=plan))
    resource = asyncio.run(
        service.source_deletion_preview(
            SourceDeletionRequest(document_ids=("dart-20250311001085",))
        )
    )
    assert resource.documents[0].document_id == "dart-20250311001085"
    assert resource.files[0].retained is False
    assert resource.retained_inputs == 2
