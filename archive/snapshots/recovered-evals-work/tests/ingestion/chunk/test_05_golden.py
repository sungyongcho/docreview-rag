"""Measured corpus regression tests for chunk counts."""

from tests.ingestion.chunk.golden import (
    CHUNK_COUNTS,
    TOTAL_CHUNKS,
    TOTAL_TABLE_CHUNKS,
    TOTAL_TEXT_CHUNKS,
)


def test_chunk_counts_match_golden(chunks_by_doc):
    """Keep per-document text and table chunk counts at the measured baseline."""
    actual = {
        doc_id: (
            len(chunks),
            sum(chunk.kind == "text" for chunk in chunks),
            sum(chunk.kind == "table" for chunk in chunks),
        )
        for doc_id, chunks in chunks_by_doc.items()
    }
    assert actual == CHUNK_COUNTS


def test_total_chunk_counts(chunks_by_doc):
    """Keep aggregate chunk counts equal to the measured corpus totals."""
    chunks = [chunk for document in chunks_by_doc.values() for chunk in document]
    assert len(chunks) == TOTAL_CHUNKS
    assert sum(chunk.kind == "text" for chunk in chunks) == TOTAL_TEXT_CHUNKS
    assert sum(chunk.kind == "table" for chunk in chunks) == TOTAL_TABLE_CHUNKS
