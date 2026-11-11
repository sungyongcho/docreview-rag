"""A seeded, disposable PostgreSQL database for the live MCP script tests.

The scripts open their own engines from ``get_settings().database_url``, which cannot
carry a test schema's search path, so each test gets a whole database of its own on
the disposable server named by ``DOCREVIEW_TEST_DATABASE_URL`` and drops it afterwards.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import Chunk, ChunkEmbedding
from app.ingestion.persistence import persist_seed_batch
from scripts.schema.status import schema_status
from tests.ingestion.seed.support import table_batch
from tests.live_postgres import disposable_database_url, live_postgres_unavailable

EMBEDDING_MODEL = "text-embedding-3-large"


@asynccontextmanager
async def seeded_database(
    filings: Sequence[str], embedded: Sequence[str] = (), local: Sequence[str] = ()
) -> AsyncIterator[str]:
    """Create a database holding one table filing per document id; yield its URL.

    Each id is ``ISSUER-FYyear``; the chunks of the ids in ``embedded`` get an OpenAI
    embedding row of the model the scripts check for, those in ``local`` a row of the
    same model under a local provider, which the scripts must not count.
    """
    admin_url = disposable_database_url()
    database = "mcp_live_" + uuid4().hex
    url = admin_url.rsplit("/", 1)[0] + "/" + database
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
    except OSError as error:
        await admin.dispose()
        live_postgres_unavailable(str(error))
    try:
        await schema_status(url, prepare=True)
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            for doc_id in filings:
                async with factory() as session:
                    await persist_seed_batch(session, table_batch(doc_id=doc_id))
            async with factory() as session, session.begin():
                chunks = await session.scalars(
                    select(Chunk).where(Chunk.doc_id.in_([*embedded, *local]))
                )
                for chunk in chunks:
                    session.add(
                        ChunkEmbedding(
                            chunk_id=chunk.id,
                            input_sha256=chunk.index_text_sha256,
                            provider="openai" if chunk.doc_id in embedded else "sbert",
                            model=EMBEDDING_MODEL,
                            dimensions=384,
                            tokenizer="test",
                            embedding=[1.0] + [0.0] * 383,
                        )
                    )
        finally:
            await engine.dispose()
        yield url
    finally:
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        await admin.dispose()
