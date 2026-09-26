"""Chunk fixtures that reuse the shared parsed corpus."""

import pytest

import app.ingestion.chunk as chunk_module


@pytest.fixture(scope="session")
def chunks_by_doc(corpus) -> dict[str, list]:
    """Chunk every parsed corpus filing once for package-wide checks."""
    return {doc_id: chunk_module.chunk_filing(filing) for doc_id, (filing, _raw) in corpus.items()}
