"""Optional live PostgreSQL retrieval acceptance tests."""

import asyncio

import pytest
from sqlalchemy import MetaData, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.bootstrap import ensure_vector_extension
from app.db.models import Base
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.lexical import lexical_search
from app.retrieval.service import retrieve
from tests.live_postgres import live_postgres_unavailable


async def _exercise_live_postgres(database_url: URL) -> tuple[bool, str]:
    """Exercise vector, lexical, and fused retrieval against PostgreSQL.

    Returns ``(False, detail)`` when the database or vector extension is unavailable.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    provider = DeterministicEmbeddingProvider()
    bodies = [
        "Research expense research expense increased in fiscal 2024.",
        "Inventory and supply obligations decreased during the year.",
        "Research expense appeared in one collaboration agreement.",
    ]
    headers = ["NVDA FY2024 Item 7", "NVDA FY2024 Item 7", "NVDA FY2024 Item 8"]
    vectors = await provider.embed_documents(
        [f"{header}\n\n{body}" for header, body in zip(headers, bodies, strict=True)]
    )

    try:
        try:
            async with asyncio.timeout(3):
                connection = await engine.connect()
                await connection.execute(text("SELECT 1"))
                await ensure_vector_extension(connection)
        except Exception as exc:
            return False, str(exc)

        extension_version = await connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        assert extension_version
        temporary_metadata = MetaData()
        for table_name in ("documents", "chunks"):
            Base.metadata.tables[table_name].to_metadata(temporary_metadata, schema="pg_temp")
        await connection.run_sync(
            lambda sync_connection: temporary_metadata.create_all(
                sync_connection,
                checkfirst=False,
            )
        )

        documents = temporary_metadata.tables["pg_temp.documents"]
        chunks = temporary_metadata.tables["pg_temp.chunks"]
        source_sha256 = "a" * 64
        await connection.execute(
            documents.insert(),
            {
                "doc_id": "NVDA-FY2024",
                "registry": "sec",
                "issuer": "NVDA",
                "issuer_id": "1045810",
                "fiscal_year": 2024,
                "form": "10-K",
                "filing_date": "2024-02-21",
                "report_period": "2024-01-28",
                "filing_id": "0001045810-24-000001",
                "source_url": "https://www.sec.gov/Archives/NVDA-FY2024.htm",
                "parse_status": "parsed",
                "item_index": [],
                "source_length": 1_000,
                "source_sha256": source_sha256,
            },
        )
        chunk_rows = []
        for index, (body, header, vector) in enumerate(
            zip(bodies, headers, vectors, strict=True), start=1
        ):
            start_char = index * 100
            chunk_rows.append(
                {
                    "id": index,
                    "doc_id": "NVDA-FY2024",
                    "item": "7" if index < 3 else "8",
                    "kind": "text",
                    "ordinal": index - 1,
                    "body": body,
                    "context_header": header,
                    "index_text": f"{header}\n\n{body}",
                    "start_char": start_char,
                    "end_char": start_char + len(body),
                    "source_sha256": source_sha256,
                    "citation": header,
                    "embedding": vector,
                },
            )
        await connection.execute(chunks.insert(), chunk_rows)
        await connection.commit()

        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            result = await retrieve(
                session,
                "research expense",
                provider=provider,
                k=2,
                candidate_k=3,
            )

        assert result.component_rankings.vector[0] == 1
        # The relaxed parse is a disjunction, so cover density rewards the chunk that
        # carries the pair twice; chunk 2 matches neither term and is not ranked at all.
        assert result.component_rankings.lexical == (1, 3)
        assert result.hits[0].chunk_id == 1
        assert result.hits[0].citation == "NVDA FY2024 Item 7"
        assert result.hits[0].source_sha256 == "a" * 64

        # A partial match must still retrieve. No chunk contains "unobtainium", so
        # the unrelaxed AND parse would have matched nothing at all; the relaxed
        # disjunction ranks every chunk that covers any part of the query.
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            partial = await lexical_search(
                session,
                "research expense unobtainium inventory obligations",
                3,
            )
        assert [hit.chunk_id for hit in partial] == [1, 3, 2]
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


@pytest.mark.live_postgres
def test_live_postgres_runs_vector_lexical_and_rrf_end_to_end():
    """Run exact vector, lexical, and fused retrieval against PostgreSQL."""
    database_url = make_url(get_settings().database_url)
    reachable, detail = asyncio.run(_exercise_live_postgres(database_url))
    if not reachable:
        live_postgres_unavailable(f"retrieval prerequisites are unavailable: {detail}")
