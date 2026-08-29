"""Isolated temporary-corpus evaluation and regression persistence on PostgreSQL."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_IDF,
    DEFAULT_BM25_K1,
    LexicalRanker,
    get_settings,
)
from app.evals.arms import RetrievalStrategy, make_retriever
from app.evals.corpus import temporary_corpus_session
from app.evals.retrieval_eval import evaluate_retriever, persist_evaluation
from app.evals.types import GoldenCase, GoldenSpan
from app.ingestion.seed import ChunkRecord, DocumentRecord, SeedBatch
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.live_postgres import live_postgres_unavailable

SOURCE_SHA256 = "a" * 64


def _batch() -> SeedBatch:
    """Build the one-document corpus indexed into the temporary tables."""
    document = DocumentRecord(
        doc_id="NVDA-FY2024",
        registry="sec",
        issuer="NVDA",
        issuer_id="1045810",
        fiscal_year=2024,
        form="10-K",
        filing_date="2024-02-21",
        report_period="2024-01-28",
        filing_id="0001045810-24-000029",
        source_url="https://example.test/nvda-2024",
        parse_status="parsed",
        item_index=({"item": "7", "status": "parsed"},),
        source_length=1_000,
        source_sha256=SOURCE_SHA256,
    )
    bodies = (
        "research expense increased 2024 research expense increased 2024",
        "inventory and supply obligations decreased during the year",
        "a collaboration agreement discussed unrelated operating terms",
    )
    chunks = tuple(
        ChunkRecord(
            doc_id=document.doc_id,
            item="7",
            kind="text",
            ordinal=index,
            body=body,
            context_header="NVDA FY2024 · Item 7",
            index_text=f"NVDA FY2024 · Item 7\n\n{body}",
            start_char=(index + 1) * 100,
            end_char=(index + 1) * 100 + 90,
            source_sha256=SOURCE_SHA256,
            citation="NVDA FY2024 · Item 7",
        )
        for index, body in enumerate(bodies)
    )
    return SeedBatch(documents=(document,), chunks=chunks)


def _cases() -> list[GoldenCase]:
    """Build one positive and one absent case for the temporary corpus."""
    return [
        GoldenCase(
            id="m3c-01",
            question="research expense increased 2024",
            category="simple_lookup",
            facet="factual",
            tags=("postgres",),
            answers=(
                GoldenSpan(
                    doc_id="NVDA-FY2024",
                    source_sha256=SOURCE_SHA256,
                    start_char=100,
                    end_char=190,
                ),
            ),
            expected_label="SUPPORTED",
            reference_answer="Research expense increased.",
            note="Temporary-table positive case.",
            curation_status="agent-curated",
            approval_status="pending-author-approval",
            human_verified=False,
        ),
        GoldenCase(
            id="m3c-02",
            question="a fact absent from this temporary corpus",
            category="absent",
            facet="risk",
            tags=("postgres",),
            answers=(),
            expected_label="NOT_IN_DOCS",
            reference_answer="NOT_IN_DOCS",
            note="Temporary-table absent case.",
            curation_status="agent-curated",
            approval_status="pending-author-approval",
            human_verified=False,
        ),
    ]


async def _exercise(database_url: URL) -> tuple[bool, str]:
    """Index an isolated corpus, run every arm, and persist two comparable runs.

    Returns ``(False, detail)`` when the database is unavailable.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    try:
        try:
            async with asyncio.timeout(3):
                connection = await engine.connect()
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            return False, str(exc)
        await connection.close()
        connection = None

        provider = DeterministicEmbeddingProvider()
        recorded_at = datetime(2026, 8, 12, 16, tzinfo=UTC)
        evaluations = {}
        async with temporary_corpus_session(
            engine,
            _batch(),
            provider,
            target_text_chars=500,
            embedding_provider="deterministic",
        ) as (session, indexing):
            assert indexing.document_count == 1
            assert indexing.chunk_count == 3
            assert indexing.passed

            # The corpus arm owns its BM25 statistics: indexing built them once,
            # before any experiment ran, and every BM25 arm below reads the same set.
            chunks_with_lengths = await session.scalar(text("SELECT count(*) FROM chunk_lengths"))
            lexemes = await session.scalar(text("SELECT count(*) FROM lexeme_stats"))
            max_df = await session.scalar(text("SELECT max(df) FROM lexeme_stats"))
            assert chunks_with_lengths == 3
            assert lexemes > 0
            assert max_df <= 3

            arms: tuple[tuple[RetrievalStrategy, LexicalRanker | None], ...] = (
                ("lexical", "ts_rank_cd"),
                ("lexical", "bm25"),
                ("vector", None),
                ("hybrid", "ts_rank_cd"),
                ("hybrid", "bm25"),
            )
            for strategy, ranker in arms:
                retriever = make_retriever(
                    session,
                    strategy=strategy,
                    provider=provider,
                    lexical_ranker=ranker,
                    bm25_k1=DEFAULT_BM25_K1 if ranker == "bm25" else None,
                    bm25_b=DEFAULT_BM25_B if ranker == "bm25" else None,
                    bm25_idf=DEFAULT_BM25_IDF if ranker == "bm25" else None,
                    candidate_k=3,
                )
                evaluation = await evaluate_retriever(
                    _cases(),
                    retriever,
                    suite="m3-postgres-test",
                    config={
                        "strategy": strategy,
                        "lexical_ranker": ranker,
                        "chunking": 500,
                        "provider": "deterministic",
                    },
                    k=2,
                    recorded_at=recorded_at,
                )
                assert evaluation.score.recall_at_k == 1.0
                assert evaluation.score.hit_rate_at_k == 1.0
                evaluations[(strategy, ranker)] = evaluation

            with pytest.raises(ValueError, match="requires an explicit lexical ranker"):
                make_retriever(session, strategy="hybrid", provider=provider)
            with pytest.raises(ValueError, match="must not name a lexical ranker"):
                make_retriever(
                    session,
                    strategy="vector",
                    provider=provider,
                    lexical_ranker="bm25",
                )

            # Indexing committed the corpus, so ending this read transaction cannot
            # discard it. Without that commit the rollback below would silently empty
            # every corpus table while leaving the tables themselves in place.
            await session.rollback()
            assert await session.scalar(text("SELECT count(*) FROM chunks")) == 3
            assert await session.scalar(text("SELECT count(*) FROM chunk_lengths")) == 3

            await session.execute(
                text(
                    """
                    CREATE TEMP TABLE eval_results (
                        id bigserial PRIMARY KEY,
                        suite varchar(128) NOT NULL,
                        config jsonb NOT NULL,
                        metrics jsonb NOT NULL,
                        raw_artifact_path text NOT NULL,
                        created_at timestamptz NOT NULL DEFAULT now()
                    ) ON COMMIT PRESERVE ROWS
                    """
                )
            )
            await session.commit()

            first = await persist_evaluation(
                session,
                evaluations[("hybrid", "bm25")],
                raw_artifact_path="data/eval_runs/first.json",
            )
            await session.commit()
            second_evaluation = replace(
                evaluations[("hybrid", "bm25")],
                recorded_at=recorded_at + timedelta(minutes=1),
            )
            second = await persist_evaluation(
                session,
                second_evaluation,
                raw_artifact_path="data/eval_runs/second.json",
            )
            await session.commit()

            assert first.baseline_id is None
            assert second.baseline_id == first.result_id
            assert second.comparison is not None
            assert second.comparison.passed
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


@pytest.mark.live_postgres
def test_live_postgres_runs_isolated_matrix_and_regression_persistence():
    """Score every retrieval arm on an isolated corpus and gate the persisted runs."""
    database_url = make_url(get_settings().database_url)
    reachable, detail = asyncio.run(_exercise(database_url))
    if not reachable:
        live_postgres_unavailable(detail)
