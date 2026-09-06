"""Real-schema PostgreSQL embedding reuse, stale guards, and retrieval acceptance."""

import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.bootstrap import ensure_vector_extension
from app.db.models import Base, Chunk, ChunkEmbedding
from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.seed import build_seed_batch_from_filings, persist_seed_batch_with_stats
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    PendingEmbedding,
    _store_batch,
    embed_missing_chunks,
)
from app.retrieval.lexical import lexical_search
from app.retrieval.service import retrieve
from app.retrieval.vector import vector_search
from tests.ingestion.support import filing_document, filing_source
from tests.live_postgres import live_postgres_unavailable


def _filing(tmp_path: Path, *, other: bool = False) -> ParsedFiling:
    """Build parsed source blocks tied to exact real fixture bytes and metadata."""
    bodies = (
        ["Other issuer source evidence."]
        if other
        else [
            "Research expense research expense increased in fiscal 2024.",
            "Inventory and supply obligations decreased during the year.",
            "Research expense appeared in one collaboration agreement.",
        ]
    )
    document = filing_document(
        issuer="AMD" if other else "NVDA",
        filing_id="0001045810-24-000002" if other else "0001045810-24-000001",
    )
    path = tmp_path / f"{document.document_id}.html"
    raw = "\n".join(bodies)
    path.write_text(raw)
    source = filing_source(path, document=document)
    sections = []
    offset = 0
    for index, body in enumerate(bodies):
        sections.append(
            Section(
                "II",
                "7" if index < 2 else "8",
                "",
                "",
                [
                    Block(
                        "paragraph",
                        body,
                        source_pos=offset,
                        end_pos=offset + len(body),
                        source_group=index,
                    )
                ],
            )
        )
        offset += len(body) + 1
    return ParsedFiling(
        source=source,
        source_length=len(raw),
        source_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        sections=sections,
    )


async def _exercise_live_postgres(database_url: URL, tmp_path: Path) -> tuple[bool, str]:
    """Use the actual normalized schema in a disposable, connection-local namespace."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    schema = "embedding_acceptance_" + uuid4().hex
    created = False
    provider = DeterministicEmbeddingProvider()
    try:
        try:
            async with asyncio.timeout(5):
                connection = await engine.connect()
                await ensure_vector_extension(connection)
        except (OSError, TimeoutError) as error:
            return False, str(error)
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        created = True
        await connection.execute(text(f"SET search_path TO {schema}, public"))
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, checkfirst=False))
        await connection.commit()
        filing = _filing(tmp_path)
        other = _filing(tmp_path, other=True)
        batch = build_seed_batch_from_filings([filing, other])
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            await persist_seed_batch_with_stats(session, batch)
            result = await embed_missing_chunks(
                session, provider, document_ids=(filing.source.document.document_id,)
            )
            assert result.selected == result.embedded == 3
            assert (
                await embed_missing_chunks(
                    session, provider, document_ids=(filing.source.document.document_id,)
                )
            ).selected == 0
            assert (await embed_missing_chunks(session, provider, document_ids=())).selected == 0
            assert await session.scalar(select(func.count()).select_from(ChunkEmbedding)) == 3
            await session.commit()
            retrieved = await retrieve(
                session, "research expense", provider=provider, k=2, candidate_k=3
            )
            assert retrieved.hits[0].doc_id == filing.source.document.document_id
            assert "Research expense research expense" in retrieved.hits[0].body
            assert len(retrieved.component_rankings.lexical) == 2
            partial = await lexical_search(
                session, "research expense unobtainium inventory obligations", 3
            )
            assert len(partial) == 3
            await session.commit()
            row = (
                await session.execute(
                    select(Chunk.id, Chunk.index_text, Chunk.index_text_sha256)
                    .where(Chunk.doc_id == filing.source.document.document_id)
                    .order_by(Chunk.ordinal)
                )
            ).first()
            await session.commit()
            pending = PendingEmbedding(row.id, row.index_text, row.index_text_sha256)
            different = replace(
                provider.identity, tokenizer=provider.identity.tokenizer + ":different"
            )
            assert await _store_batch(session, [pending], [[1.0] + [0.0] * 383], different) == 1
            assert await session.scalar(select(func.count()).select_from(ChunkEmbedding)) == 4
            await session.commit()
            query = await provider.embed_query("research expense")
            matched = await vector_search(session, query, k=10, identity=different)
            assert [hit.chunk_id for hit in matched] == [row.id]
            unmatched = await vector_search(
                session, query, k=10, identity=replace(different, model="other")
            )
            assert unmatched == []
            await session.commit()
            changed = "Changed source text."
            changed_hash = hashlib.sha256(changed.encode()).hexdigest()
            async with session.begin():
                await session.execute(
                    update(Chunk)
                    .where(Chunk.id == row.id)
                    .values(
                        body=changed,
                        context_header="",
                        index_text=changed,
                        index_text_sha256=changed_hash,
                    )
                )
            assert (
                await _store_batch(
                    session, [pending], [[1.0] + [0.0] * 383], replace(different, model="stale")
                )
                == 0
            )
            current = PendingEmbedding(row.id, changed, changed_hash)
            assert (
                await _store_batch(session, [current], [[1.0] + [0.0] * 383], provider.identity)
                == 1
            )
            assert (
                await _store_batch(session, [current], [[1.0] + [0.0] * 383], provider.identity)
                == 0
            )
        return True, ""
    finally:
        if connection is not None:
            await connection.rollback()
            if created:
                await connection.execute(text("SET search_path TO public"))
                await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
                await connection.commit()
            await connection.close()
        await engine.dispose()


@pytest.mark.live_postgres
def test_live_postgres_reuses_exact_inputs_and_guards_vector_configurations(tmp_path):
    """Verify normalized persistence and current-input vector lookup against PostgreSQL."""
    reachable, detail = asyncio.run(
        _exercise_live_postgres(make_url(get_settings().database_url), tmp_path)
    )
    if not reachable:
        live_postgres_unavailable(f"retrieval prerequisites unavailable: {detail}")
