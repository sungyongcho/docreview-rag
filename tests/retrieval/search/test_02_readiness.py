"""Coherent reads and strategy-specific index gates: live PostgreSQL evidence for the
live tables and scripted probes for snapshot filters."""

import asyncio
from typing import cast

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.indexing.bm25 import backfill_term_stats
from app.retrieval.search.plan import SearchPlan
from app.retrieval.search.service import SearchNotReadyError, prepare_search
from app.retrieval.types import RetrievalFilters
from tests.ingestion.seed.support import sample_batch
from tests.live_postgres import isolated_session_factory


@pytest.mark.live_postgres
def test_search_snapshot_and_strategy_gates_on_isolated_postgres():
    """A committed writer cannot change a read snapshot; stale indexes reject new searches."""

    async def exercise():
        """Use a disposable schema with independent writer connections."""
        provider = DeterministicEmbeddingProvider()
        async with isolated_session_factory() as factory:
            async with factory() as writer:
                await persist_seed_batch(writer, sample_batch())
            async with factory() as writer:
                await backfill_term_stats(writer)
                await writer.commit()
            async with factory() as reader:
                await prepare_search(
                    reader,
                    provider,
                    SearchPlan(strategy="lexical", lexical_ranker="bm25"),
                    RetrievalFilters(),
                )
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
                with pytest.raises(SearchNotReadyError) as error:
                    await prepare_search(
                        reader,
                        provider,
                        SearchPlan(strategy="lexical", lexical_ranker="bm25"),
                        RetrievalFilters(),
                    )
                assert error.value.code == "bm25_not_ready"
            async with factory() as reader:
                with pytest.raises(SearchNotReadyError) as error:
                    await prepare_search(
                        reader, provider, SearchPlan(strategy="vector"), RetrievalFilters()
                    )
                assert error.value.code == "embeddings_not_ready"
            async with factory() as reader:
                await prepare_search(
                    reader, provider, SearchPlan(strategy="lexical"), RetrievalFilters()
                )
                assert set(await reader.scalars(select(Chunk.citation))) == {"changed evidence"}
            async with factory() as writer:
                await backfill_term_stats(writer)
                await writer.commit()
            async with factory() as reader:
                await prepare_search(
                    reader,
                    provider,
                    SearchPlan(strategy="lexical", lexical_ranker="bm25"),
                    RetrievalFilters(),
                )

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
    """A snapshot frozen without the vectors or statistics a preset needs raises its domain error
    before model calls or search execution."""
    session = _ScriptedSession(*answers)

    with pytest.raises(SearchNotReadyError) as raised:
        asyncio.run(
            prepare_search(
                cast(AsyncSession, session),
                DeterministicEmbeddingProvider(),
                SearchPlan(strategy=strategy, lexical_ranker=ranker),
                RetrievalFilters(snapshot_id=7),
            )
        )

    assert raised.value.code == code
    assert not session.answers


def test_ready_snapshot_passes_and_a_ts_rank_cd_snapshot_needs_no_statistics():
    """Vectors present and statistics present pass; ts_rank_cd never asks for statistics."""
    ready = _ScriptedSession(False, True)
    asyncio.run(
        prepare_search(
            cast(AsyncSession, ready),
            DeterministicEmbeddingProvider(),
            SearchPlan(strategy="hybrid", lexical_ranker="bm25"),
            RetrievalFilters(snapshot_id=7),
        )
    )
    assert len(ready.statements) == 2

    lexical = _ScriptedSession()
    asyncio.run(
        prepare_search(
            cast(AsyncSession, lexical),
            DeterministicEmbeddingProvider(),
            SearchPlan(strategy="lexical"),
            RetrievalFilters(snapshot_id=7),
        )
    )
    assert lexical.statements == []
