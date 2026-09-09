"""Evaluation readiness blocks submission before side effects and distinguishes prerequisites."""

import asyncio
from dataclasses import replace

import pytest

from app.api.admin_schemas import EvaluationRunRequest
from app.config import Settings
from app.corpus_admin import CorpusStatus
from app.evals.admin import EvaluationAdminService, EvaluationNotReadyError
from app.evals.source_binding import BoundGolden, SourceCheck
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_missing_sources_block_job_registration(tmp_path):
    """An empty corpus yields actionable requirements without a failed queued job."""
    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path), provider=DeterministicEmbeddingProvider()
    )

    async def exercise():
        """Use the real bundled suite and absent local corpus."""
        request = EvaluationRunRequest(suite_id="dart-ko")
        preparation = await service.preparation(request)
        assert preparation.state == "source_missing"
        assert {source.issuer for source in preparation.source_checks} == {"000660", "005930"}
        assert preparation.kind == "builtin"
        assert preparation.verification_status == "pending_review"
        with pytest.raises(EvaluationNotReadyError):
            await service.enqueue(request)
        assert service._jobs == {}
        assert service._queue.empty()
        assert service._worker is None

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("unparsed", "parsing_required"),
        ("changed_source", "parsing_required"),
        ("missing_vectors", "index_update_required"),
        ("missing_bm25", "index_update_required"),
        ("ready", "ready"),
    ],
)
def test_preparation_distinguishes_index_and_exact_source_versions(
    tmp_path, monkeypatch, scenario, expected
):
    """Keep author review independent from currently verified source and search readiness."""
    status = CorpusStatus(True, "compatible", "ok", 1, 1, 1, 0, True, True, "deterministic")
    if scenario == "unparsed":
        status = replace(status, chunks=0)
    if scenario == "missing_vectors":
        status = replace(status, pending_embeddings=1)
    if scenario == "missing_bm25":
        status = replace(status, bm25_ready=False)

    async def current_status():
        """Return a controlled independent runtime prerequisite."""
        return status

    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        corpus_status=current_status,
    )

    async def bound(request):
        """Model separately tested successful source binding without source file I/O."""
        return BoundGolden(
            (), (SourceCheck("old", "sec", "NVDA", 2024, "filing", "current", "ready"),)
        ), "a" * 64

    async def missing(cases):
        """Represent the independent exact-source lookup, verified by a live DB test."""
        return {("current", "a" * 64)} if scenario == "changed_source" else set()

    monkeypatch.setattr(service, "_bound_golden", bound)
    monkeypatch.setattr(service, "_missing_parsed_sources", missing)
    result = asyncio.run(
        service.preparation(
            EvaluationRunRequest(
                suite_id="sec-en", golden_revision_id=1, profile={"lexical_ranker": "bm25"}
            )
        )
    )
    assert result.state == expected
    assert result.kind == "user"
    assert result.verification_status == "pending_review"


@pytest.mark.live_postgres
def test_exact_parsed_source_check_on_isolated_postgres():
    """Real PostgreSQL distinguishes the matching source version from stale or absent chunks."""
    import os

    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.evals.loader import GOLDEN_CASES
    from tests.live_postgres import live_postgres_unavailable

    dsn = os.getenv("GOLDEN_PREFLIGHT_TEST_DSN")
    if not dsn:
        live_postgres_unavailable("GOLDEN_PREFLIGHT_TEST_DSN is not configured")
    url = make_url(dsn)
    assert url.host in {"127.0.0.1", "localhost"} and url.database.startswith("pipeline_test_")

    async def exercise():
        """Use a transaction-local schema for the two projected columns without shared data."""
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                await connection.execute(text("CREATE SCHEMA golden_preflight_fixture"))
                await connection.execute(text("SET LOCAL search_path TO golden_preflight_fixture"))
                await connection.execute(
                    text("CREATE TABLE chunks (doc_id varchar(128), source_sha256 varchar(64))")
                )
                await connection.execute(
                    text("INSERT INTO chunks VALUES ('current', :digest), ('stale', :old)"),
                    {"digest": "a" * 64, "old": "b" * 64},
                )
                service = EvaluationAdminService(
                    provider=DeterministicEmbeddingProvider(),
                    session_factory=async_sessionmaker(
                        bind=connection, join_transaction_mode="create_savepoint"
                    ),
                )
                payload = [
                    {
                        "id": "case-1",
                        "question": "Evidence?",
                        "category": "multi_hop",
                        "facet": "factual",
                        "tags": [],
                        "answers": [
                            {
                                "doc_id": doc_id,
                                "source_sha256": "a" * 64,
                                "start_char": 0,
                                "end_char": 1,
                            }
                            for doc_id in ["current", "stale", "missing"]
                        ],
                        "expected_label": "SUPPORTED",
                        "reference_answer": "Evidence.",
                        "note": "Fixture.",
                        "curation_status": "agent-curated",
                        "approval_status": "pending-author-approval",
                        "human_verified": False,
                    }
                ]
                result = await service._missing_parsed_sources(
                    tuple(GOLDEN_CASES.validate_python(payload))
                )
                assert result == {("stale", "a" * 64), ("missing", "a" * 64)}
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())
