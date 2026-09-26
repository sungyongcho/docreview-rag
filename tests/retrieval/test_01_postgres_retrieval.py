"""Real-schema PostgreSQL embedding reuse, stale guards, and retrieval acceptance."""

import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.db.models import Chunk, ChunkEmbedding
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
from tests.live_postgres import isolated_session
from tests.retrieval.support import retrieval_filing


async def _exercise_live_postgres(tmp_path: Path) -> None:
    """Check embedding reuse and stale-input isolation on persisted filing evidence."""
    provider = DeterministicEmbeddingProvider()
    filing = retrieval_filing(tmp_path)
    other = retrieval_filing(tmp_path, other=True)
    batch = build_seed_batch_from_filings([filing, other])
    async with isolated_session() as session:
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
        lexical_hits = await lexical_search(session, '"research expense"', 10)
        scores = {
            chunk_id: score
            for chunk_id, score in (
                await session.execute(
                    select(
                        Chunk.id,
                        func.ts_rank_cd(
                            Chunk.content_tsv,
                            func.websearch_to_tsquery("english", '"research expense"'),
                            4 | 1,
                        ),
                    )
                )
            ).all()
        }
        assert lexical_hits
        assert {hit.chunk_id: hit.score for hit in lexical_hits} == pytest.approx(
            {chunk_id: score for chunk_id, score in scores.items() if score > 0}
        )
        await session.commit()
        row = (
            await session.execute(
                select(Chunk.id, Chunk.index_text, Chunk.index_text_sha256)
                .where(Chunk.doc_id == filing.source.document.document_id)
                .order_by(Chunk.ordinal)
            )
        ).first()
        await session.commit()
        assert row is not None
        pending = PendingEmbedding(row.id, row.index_text, row.index_text_sha256)
        different = replace(provider.identity, tokenizer=provider.identity.tokenizer + ":different")
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
        assert await _store_batch(session, [current], [[1.0] + [0.0] * 383], provider.identity) == 1
        assert await _store_batch(session, [current], [[1.0] + [0.0] * 383], provider.identity) == 0


@pytest.mark.live_postgres
def test_live_postgres_reuses_exact_inputs_and_guards_vector_configurations(tmp_path):
    """Verify normalized persistence and current-input vector lookup against PostgreSQL."""
    asyncio.run(_exercise_live_postgres(tmp_path))
