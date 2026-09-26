"""Coherent reads and strategy-specific index gates: live PostgreSQL evidence for the
live tables and scripted probes for snapshot filters."""

import asyncio
import os
from typing import cast

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.errors import ApiProblemError
from app.api.search_consistency import prepare_search
from app.db.bootstrap import bootstrap_schema
from app.db.models import Chunk
from app.ingestion.seed import persist_seed_batch
from app.retrieval.bm25 import backfill_term_stats
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.types import RetrievalFilters
from tests.ingestion.seed.support import sample_batch
from tests.live_postgres import live_postgres_unavailable


@pytest.mark.live_postgres
def test_search_snapshot_and_strategy_gates_on_isolated_postgres():
    """A committed writer cannot change a read snapshot; stale indexes reject new searches."""
    dsn = os.getenv("SEARCH_CONSISTENCY_TEST_DSN")
    if not dsn:
        live_postgres_unavailable("SEARCH_CONSISTENCY_TEST_DSN is not configured")
    url = make_url(dsn)
    assert url.database is not None
    assert url.host in {"127.0.0.1", "localhost"} and url.database.startswith("pipeline_test_")

    async def exercise():
        """Use only the explicit disposable database, with independent writer connections."""
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        provider = DeterministicEmbeddingProvider()
        try:
            await bootstrap_schema(engine)
            async with factory() as writer:
                await persist_seed_batch(writer, sample_batch())
            async with factory() as writer:
                await backfill_term_stats(writer)
                await writer.commit()
            async with factory() as reader:
                await prepare_search(reader, provider, "lexical", "bm25", RetrievalFilters())
                assert await reader.scalar(text("SHOW transaction_isolation")) == "repeatable read"
                before = (await reader.execute(select(Chunk.id, Chunk.citation))).all()
                async with factory.begin() as writer:
                    await writer.execute(
                        update(Chunk).values(
                            citation="changed evidence", index_text=Chunk.index_text
                        )
                    )
                after = (await reader.execute(select(Chunk.id, Chunk.citation))).all()
                assert before == after
            async with factory() as reader:
                with pytest.raises(ApiProblemError) as error:
                    await prepare_search(reader, provider, "lexical", "bm25", RetrievalFilters())
                assert error.value.error.code == "bm25_not_ready"
            async with factory() as reader:
                with pytest.raises(ApiProblemError) as error:
                    await prepare_search(reader, provider, "vector", "bm25", RetrievalFilters())
                assert error.value.error.code == "embeddings_not_ready"
            async with factory() as reader:
                await prepare_search(reader, provider, "lexical", "ts_rank_cd", RetrievalFilters())
                assert set(await reader.scalars(select(Chunk.citation))) == {"changed evidence"}
            async with factory() as writer:
                await backfill_term_stats(writer)
                await writer.commit()
            async with factory() as reader:
                await prepare_search(reader, provider, "lexical", "bm25", RetrievalFilters())
        finally:
            await engine.dispose()

    asyncio.run(exercise())


class _ScriptedSession:
    """Answer readiness probes in order and record the SQL each one sent."""

    def __init__(self, *answers: bool) -> None:
        self.answers = list(answers)
        self.statements: list[object] = []

    def in_transaction(self) -> bool:
        """Report an already pinned transaction."""
        return True

    async def scalar(self, statement: object) -> bool:
        """Record the probe and return the next scripted answer."""
        self.statements.append(statement)
        return self.answers.pop(0)


@pytest.mark.parametrize(
    ("strategy", "ranker", "answers", "code"),
    [
        pytest.param("hybrid", "bm25", (True,), "embeddings_not_ready", id="vectors"),
        pytest.param("hybrid", "bm25", (False, False), "bm25_not_ready", id="bm25"),
        pytest.param("lexical", "bm25", (False,), "bm25_not_ready", id="lexical"),
    ],
)
def test_snapshot_readiness_rejects_missing_required_indexes(strategy, ranker, answers, code):
    """A snapshot frozen without the vectors or statistics a preset needs answers a typed 503
    from its own tables instead of reaching the search and failing untyped."""
    session = _ScriptedSession(*answers)

    with pytest.raises(ApiProblemError) as raised:
        asyncio.run(
            prepare_search(
                cast(AsyncSession, session),
                DeterministicEmbeddingProvider(),
                strategy,
                ranker,
                RetrievalFilters(snapshot_id=7),
            )
        )

    assert raised.value.status_code == 503
    assert raised.value.error.code == code
    assert not session.answers


def test_ready_snapshot_passes_and_a_ts_rank_cd_snapshot_needs_no_statistics():
    """Vectors present and statistics present pass; ts_rank_cd never asks for statistics."""
    ready = _ScriptedSession(False, True)
    asyncio.run(
        prepare_search(
            cast(AsyncSession, ready),
            DeterministicEmbeddingProvider(),
            "hybrid",
            "bm25",
            RetrievalFilters(snapshot_id=7),
        )
    )
    assert len(ready.statements) == 2

    lexical = _ScriptedSession()
    asyncio.run(
        prepare_search(
            cast(AsyncSession, lexical),
            DeterministicEmbeddingProvider(),
            "lexical",
            "ts_rank_cd",
            RetrievalFilters(snapshot_id=7),
        )
    )
    assert lexical.statements == []
