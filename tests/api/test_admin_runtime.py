"""Administrator composition preserves current command, document and retrieval contracts."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock

import pytest

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.runtime import RuntimeApiServices
from app.corpus_admin.runtime import RuntimeCorpusAdminService
from app.corpus_admin.types import CorpusStatus
from app.db.session_factory import SessionFactory
from app.evals.admin import EvaluationAdminService
from app.operator.jobs import JobDomain, JobStatus
from app.retrieval.embeddings import DeterministicEmbeddingProvider


@pytest.mark.parametrize("strategy", ["vector", "lexical", "hybrid"])
def test_preview_strategies_use_the_shared_search_contract(monkeypatch, hit, strategy):
    """Run each valid preview plan through retrieval and preserve its actual component ranks."""
    from contextlib import asynccontextmanager

    from app.api import search_consistency
    from app.api.admin_schemas import RetrievalPreviewRequest
    from app.retrieval import service as retrieval

    calls = []

    async def prepare(*args):
        """Skip the database readiness probe, retaining the real retrieval dispatcher."""
        del args

    async def vector_search(*args, **kwargs):
        """Return a recorded vector candidate without querying PostgreSQL."""
        calls.append("vector")
        return [hit]

    async def lexical_search(*args, **kwargs):
        """Return a recorded lexical candidate without querying PostgreSQL."""
        calls.append("lexical")
        return [hit]

    @asynccontextmanager
    async def no_database():
        """Provide the session seam consumed by the isolated search components."""
        yield None

    monkeypatch.setattr(search_consistency, "prepare_search", prepare)
    monkeypatch.setattr(retrieval, "vector_search", vector_search)
    monkeypatch.setattr(retrieval, "lexical_search", lexical_search)
    services = RuntimeAdminApiServices(
        runtime=RuntimeApiServices(
            embedding_provider=DeterministicEmbeddingProvider(),
            session_factory=cast(SessionFactory, no_database),
        )
    )
    request = RetrievalPreviewRequest.model_validate(
        {
            "query": "Revenue?",
            "profile": {
                "strategy": strategy,
                "lexical_ranker": None if strategy == "vector" else "ts_rank_cd",
            },
            "filters": {"languages": ["en"]},
        }
    )

    result = asyncio.run(services.retrieval_preview(request))

    expected = [lane for lane in ("vector", "lexical") if strategy in {lane, "hybrid"}]
    assert calls == expected
    assert [item.chunk_id for item in result.results] == [hit.chunk_id]
    assert result.component_rankings["vector"] == ((hit.chunk_id,) if "vector" in expected else ())
    assert result.component_rankings["lexical_by_language"] == (
        {"en": (hit.chunk_id,)} if "lexical" in expected else {}
    )


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

    from app.api.admin_schemas import EvaluationRunRequest
    from app.corpus_admin.stored_jobs import command_payload
    from app.corpus_admin.types import AdminCommand
    from tests.corpus_admin.support import LedgerStore

    async def scenario():
        """Populate the ledger without workers, then exercise the real board and lookup."""
        from dataclasses import replace

        from app.operator.job_history import ARCHIVE_KEY

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
                job_id=job_id,
                domain=domain,
                kind=kind,
                request_json=request,
                created_at=created,
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
            service = object.__new__(RuntimeAdminApiServices)
            service._corpus = cast(
                RuntimeCorpusAdminService, SimpleNamespace(recover_jobs=AsyncMock())
            )
            service._evaluations = cast(
                EvaluationAdminService, SimpleNamespace(recover_jobs=AsyncMock())
            )
            service._job_store = store
            return service

        board = await api().operator_jobs()
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
        assert await fresh.operator_job("queued-corpus") == board.jobs[0]
        assert await fresh.operator_job("failed-evaluation") == board.jobs[5]
        assert await fresh.operator_job("missing") is None
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
        assert len((await fresh.operator_jobs()).jobs) == 100
        assert await fresh.operator_job("history-success") == historical
        assert await fresh.operator_job("queued-corpus") == board.jobs[0]

        failed = store.rows["failed-evaluation"]
        store.rows[failed.job_id] = replace(failed, result_refs={ARCHIVE_KEY: True})
        assert await fresh.operator_job(failed.job_id) is None
        store.rows[failed.job_id] = failed
        assert await fresh.operator_job(failed.job_id) == board.jobs[5]

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
    services = RuntimeAdminApiServices(
        runtime=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
        corpus=cast(RuntimeCorpusAdminService, corpus),
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
    service._evaluations = cast(
        EvaluationAdminService,
        SimpleNamespace(
            enqueue=AsyncMock(side_effect=EvaluationAlreadyQueuedError("eval-existing"))
        ),
    )
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(service.enqueue_evaluation(EvaluationRunRequest(suite_id="sec-en")))
    assert error.value.status_code == 409
    assert error.value.error.code == "evaluation_already_queued"
    assert "eval-existing" in error.value.error.message


def test_acquisition_api_preserves_absent_deletion_and_document_arguments():
    """New optional deletion fields must not make ordinary corpus commands invalid."""
    from app.corpus_admin.types import AdminCommand, AdminJob

    request = AdminCommand(kind="acquire_edgar", identifiers=("NVDA",), years=(2024,))
    service = object.__new__(RuntimeAdminApiServices)

    async def enqueue(command):
        """Return the accepted command through the actual dataclass serialization boundary."""
        assert command is request
        assert command.document_ids is None and command.confirm_delete is None
        return AdminJob("download", command, "queued", "queued", 0, None, "Queued")

    service._corpus = cast(RuntimeCorpusAdminService, SimpleNamespace(enqueue=enqueue))
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
    assert url.database is not None
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
            service._runtime = cast(RuntimeApiServices, SimpleNamespace(session_factory=factory))
            service._evaluations = cast(
                EvaluationAdminService, SimpleNamespace(jobs=AsyncMock(return_value=board))
            )
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
    assert url.database is not None
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
            service._runtime = cast(RuntimeApiServices, SimpleNamespace(session_factory=factory))
            first = await service.golden_evidence_chunks("NVDA-FY2024", "", 0, 1)
            assert first.next_after is not None
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
    service._corpus = cast(
        RuntimeCorpusAdminService,
        SimpleNamespace(preview_source_deletion=AsyncMock(return_value=plan)),
    )
    resource = asyncio.run(
        service.source_deletion_preview(
            SourceDeletionRequest(document_ids=("dart-20250311001085",))
        )
    )
    assert resource.documents[0].document_id == "dart-20250311001085"
    assert resource.files[0].retained is False
    assert resource.retained_inputs == 2


def test_previews_run_and_present_the_effective_bm25_values(monkeypatch):
    """A preview keeps its stated BM25 value and takes the rest from the server settings."""
    from contextlib import asynccontextmanager

    from app.api import admin_runtime
    from app.api.admin_schemas import RetrievalPreviewRequest, ReviewPreviewRequest
    from app.retrieval.service import ComponentRankings, RetrievalResult

    calls = []

    async def retrieve(session, query, **kwargs):
        """Capture the hybrid retrieval plan without a database."""
        del session, query
        calls.append(kwargs)
        return RetrievalResult(
            hits=(),
            candidates=(),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(), lexical=()),
        )

    @asynccontextmanager
    async def no_database():
        """Open no session; the recording retrieval never uses one."""
        yield None

    monkeypatch.setattr(admin_runtime, "consistent_retrieve", retrieve)
    services = RuntimeAdminApiServices(
        runtime=RuntimeApiServices(
            embedding_provider=DeterministicEmbeddingProvider(),
            session_factory=cast(SessionFactory, no_database),
            bm25_k1=1.6,
            bm25_b=0.5,
            bm25_idf="robertson",
        )
    )
    payload = {"query": "Revenue?", "profile": {"lexical_ranker": "bm25", "bm25_b": 0.3}}

    response = asyncio.run(
        services.retrieval_preview(RetrievalPreviewRequest.model_validate(payload))
    )

    assert [(call["bm25_k1"], call["bm25_b"], call["bm25_idf"]) for call in calls] == [
        (1.6, 0.3, "robertson")
    ]
    assert (response.profile.bm25_k1, response.profile.bm25_b, response.profile.bm25_idf) == (
        1.6,
        0.3,
        "robertson",
    )

    reviewed = []

    async def review_with_retrieval(review, retrieval):
        """Capture the Custom plan the review preview hands to the workflow."""
        del retrieval
        reviewed.append(review)
        raise LookupError("review boundary reached")

    monkeypatch.setattr(services._runtime, "review_with_retrieval", review_with_retrieval)
    with pytest.raises(LookupError, match="review boundary"):
        asyncio.run(services.review_preview(ReviewPreviewRequest.model_validate(payload)))
    custom = reviewed[0].session_profile.custom_retrieval
    assert (custom.bm25_k1, custom.bm25_b, custom.bm25_idf) == (1.6, 0.3, "robertson")
