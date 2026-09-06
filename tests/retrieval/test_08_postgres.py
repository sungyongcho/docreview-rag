"""L8: optional live PostgreSQL proof for the complete retrieval path."""

import asyncio
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.bootstrap import bootstrap_schema, ensure_vector_extension
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.lexical import lexical_search
from app.retrieval.service import retrieve


class _Connection:
    def __init__(self, events):
        self.events = events

    async def execute(self, statement):
        self.events.append(("execute", str(statement)))

    async def run_sync(self, operation):
        self.events.append(("run_sync", operation.__name__))


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _Engine:
    def __init__(self, events):
        self.connection = _Connection(events)

    def begin(self):
        return _Transaction(self.connection)


def test_bootstrap_enables_vector_before_create_all():
    events = []

    asyncio.run(bootstrap_schema(cast(AsyncEngine, _Engine(events))))

    assert events == [
        ("execute", "CREATE EXTENSION IF NOT EXISTS vector"),
        ("run_sync", "create_all"),
    ]


def _vector_literal(vector: list[float]) -> str:
    """Serialize a finite test vector for an explicit PostgreSQL cast."""
    return "[" + ",".join(str(component) for component in vector) + "]"


async def _exercise_live_postgres(database_url: URL) -> tuple[bool, str]:
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
        except Exception as exc:
            return False, str(exc)

        await ensure_vector_extension(connection)
        await ensure_vector_extension(connection)
        extension_version = await connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        assert extension_version
        await connection.execute(
            text(
                """
                CREATE TEMP TABLE documents (
                    doc_id text PRIMARY KEY,
                    ticker text NOT NULL,
                    fiscal_year integer NOT NULL,
                    form text NOT NULL
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TEMP TABLE chunks (
                    id bigint PRIMARY KEY,
                    doc_id text NOT NULL REFERENCES documents(doc_id),
                    item text,
                    kind text NOT NULL,
                    ordinal integer NOT NULL,
                    body text NOT NULL,
                    context_header text NOT NULL,
                    index_text text NOT NULL,
                    start_char bigint NOT NULL,
                    end_char bigint NOT NULL,
                    source_sha256 text NOT NULL,
                    citation text NOT NULL,
                    embedding vector(384),
                    content_tsv tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', index_text)
                    ) STORED,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO documents (doc_id, ticker, fiscal_year, form)
                VALUES ('NVDA-FY2024', 'NVDA', 2024, '10-K')
                """
            )
        )
        insert_chunk = text(
            """
            INSERT INTO chunks (
                id, doc_id, item, kind, ordinal, body, context_header, index_text,
                start_char, end_char, source_sha256, citation, embedding
            )
            VALUES (
                :id, 'NVDA-FY2024', :item, 'text', :ordinal, :body, :header,
                :index_text, :start_char, :end_char, :source_sha256, :citation,
                CAST(:embedding AS vector)
            )
            """
        )
        for index, (body, header, vector) in enumerate(
            zip(bodies, headers, vectors, strict=True), start=1
        ):
            start_char = index * 100
            await connection.execute(
                insert_chunk,
                {
                    "id": index,
                    "item": "7" if index < 3 else "8",
                    "ordinal": index - 1,
                    "body": body,
                    "header": header,
                    "index_text": f"{header}\n\n{body}",
                    "start_char": start_char,
                    "end_char": start_char + len(body),
                    "source_sha256": "a" * 64,
                    "citation": header,
                    "embedding": _vector_literal(vector),
                },
            )
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
        # The extent-distance normalization penalizes repeating one pair, so the
        # lexical leg prefers the single tight mention over the double one. Fusion
        # still puts chunk 1 first because the vector leg agrees with it.
        assert result.component_rankings.lexical[0] == 3
        assert result.hits[0].chunk_id == 1
        assert result.hits[0].citation == "NVDA FY2024 Item 7"
        assert result.hits[0].source_sha256 == "a" * 64

        # A partial match must still retrieve. No chunk contains "unobtainium", so
        # the unrelaxed AND parse would have matched nothing at all; the relaxed
        # disjunction ranks by how much of the query each chunk covers instead.
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            partial = await lexical_search(
                session,
                "research expense unobtainium inventory obligations",
                3,
            )
        assert [hit.chunk_id for hit in partial] == [3, 1, 2]
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


def test_live_postgres_runs_vector_lexical_and_rrf_end_to_end(postgres_test_database_url):
    reachable, detail = asyncio.run(_exercise_live_postgres(postgres_test_database_url))
    if not reachable:
        pytest.skip(f"PostgreSQL is unavailable: {detail}")
