"""Live PostgreSQL evidence for coherent reads and strategy-specific index gates."""

import asyncio
import os

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
