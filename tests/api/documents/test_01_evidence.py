"""Exercise documents behavior at service and HTTP boundaries."""

import asyncio

import pytest

from app.api.documents.catalog import DocumentCatalog
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from tests.ingestion.seed.support import sample_batch
from tests.live_postgres import isolated_session_factory


@pytest.mark.live_postgres
def test_golden_evidence_pages_preserve_exact_source_coordinates():
    """A separate PostgreSQL fixture proves chunk paging, search, and original spans."""

    async def exercise():
        """Use real seeded source identities and leave the user database untouched."""
        async with isolated_session_factory() as factory:
            batch = sample_batch()
            async with factory() as session:
                await persist_seed_batch(session, batch)
            documents = DocumentCatalog(
                factory,
                public_only=False,
                embedding_identity=DeterministicEmbeddingProvider().identity,
            )
            first = await documents.golden_evidence_chunks("NVDA-FY2024", "", 0, 1)
            assert first.next_after is not None
            second = await documents.golden_evidence_chunks("NVDA-FY2024", "", first.next_after, 1)
            assert len(first.chunks) == len(second.chunks) == 1
            assert first.chunks[0].chunk_id != second.chunks[0].chunk_id
            assert second.next_after is None
            chunk = first.chunks[0]
            assert chunk.source_sha256 == "a" * 64
            assert (chunk.start_char, chunk.end_char) == (10, 40)
            assert chunk.body == "Source-derived narrative."
            search = await documents.golden_evidence_chunks("NVDA-FY2024", "narrative", 0, 20)
            assert [row.chunk_id for row in search.chunks] == [chunk.chunk_id]
            assert not (await documents.golden_evidence_chunks("missing", "", 0, 20)).chunks

    asyncio.run(exercise())
