"""Evaluation readiness blocks submission before side effects and distinguishes prerequisites."""

import asyncio
from dataclasses import replace

import pytest

from app.config import Settings
from app.corpus_admin.types import CorpusStatus
import app.evals.admin.preparation as preparation_module
from app.evals.admin.service import EvaluationAdminService, EvaluationNotReadyError
from app.evals.contracts import EvaluationRunRequest
from app.evals.golden.binding import BoundGolden, SourceCheck
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.search.profiles import RetrievalProfile
from tests.corpus_admin.support import LedgerStore


def test_missing_sources_block_job_registration(tmp_path):
    """An empty corpus yields actionable requirements without a failed queued job."""
    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        job_store=LedgerStore(),
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

    async def bound(request, **kwargs):
        """Model separately tested successful source binding without source file I/O."""
        return BoundGolden(
            (), (SourceCheck("old", "sec", "NVDA", 2024, "filing", "current", "ready"),)
        ), "a" * 64

    async def missing(cases, session_factory):
        """Represent the independent exact-source lookup, verified by a live DB test."""
        return {("current", "a" * 64)} if scenario == "changed_source" else set()

    monkeypatch.setattr(preparation_module, "bound_golden", bound)
    monkeypatch.setattr(preparation_module, "missing_parsed_sources", missing)
    result = asyncio.run(
        service.preparation(
            EvaluationRunRequest(
                suite_id="sec-en",
                golden_revision_id=1,
                profile=RetrievalProfile(lexical_ranker="bm25"),
            )
        )
    )
    assert result.state == expected
    assert result.kind == "user"
    assert result.verification_status == "pending_review"


@pytest.mark.live_postgres
def test_exact_parsed_source_check_on_isolated_postgres():
    """Real PostgreSQL distinguishes the matching source version from stale or absent chunks."""

    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.evals.golden.loading import GOLDEN_CASES
    from tests.live_postgres import disposable_database_url

    url = make_url(disposable_database_url())

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
                result = await preparation_module.missing_parsed_sources(
                    tuple(GOLDEN_CASES.validate_python(payload)), service._session_factory
                )
                assert result == {("stale", "a" * 64), ("missing", "a" * 64)}
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["quick", "matrix"])
@pytest.mark.parametrize("failure", [ValueError("invalid corpus"), OSError("missing corpus")])
def test_preparation_preserves_source_and_runtime_failure_categories(
    tmp_path, monkeypatch, mode, failure
):
    """Keep matrix source failures distinct from live-index readiness outages."""

    async def bound(request, **kwargs):
        """Provide already verified golden input before the failing corpus boundary."""
        return BoundGolden(
            (), (SourceCheck("old", "sec", "NVDA", 2024, "filing", "current", "ready"),)
        ), "a" * 64

    async def unavailable_status():
        """Fail the independently changing corpus readiness check."""
        raise failure

    monkeypatch.setattr(preparation_module, "bound_golden", bound)
    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        corpus_status=unavailable_status,
    )
    result = asyncio.run(service.preparation(EvaluationRunRequest(suite_id="sec-en", mode=mode)))
    assert result.state == ("source_invalid" if mode == "matrix" else "unavailable")
    assert result.next_step == ("filings" if mode == "matrix" else "setup")
