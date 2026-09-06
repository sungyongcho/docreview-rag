"""Corpus-level seed preparation and provenance tests."""

from collections import Counter

import pytest

from app.ingestion import seed
from app.ingestion.chunk import compose_index_text
from tests.ingestion.chunk.golden import CHUNK_COUNTS

EXPECTED_DOCUMENT_IDS = tuple(sorted(CHUNK_COUNTS))
EXPECTED_DOCUMENTS = len(EXPECTED_DOCUMENT_IDS)
EXPECTED_CHUNKS = sum(total for total, _text, _table in CHUNK_COUNTS.values())
EXPECTED_TEXT_CHUNKS = sum(text for _total, text, _table in CHUNK_COUNTS.values())
EXPECTED_TABLE_CHUNKS = sum(table for _total, _text, table in CHUNK_COUNTS.values())


@pytest.fixture(scope="module")
def corpus_batch(corpus):
    """Build seed records from the already parsed shared corpus."""
    filings = (filing for filing, _raw in corpus.values())
    return seed.build_seed_batch_from_filings(filings)


def test_batch_contains_every_document_and_chunk(corpus_batch):
    """Preserve measured per-document text and table chunk counts."""
    assert tuple(record.doc_id for record in corpus_batch.documents) == EXPECTED_DOCUMENT_IDS
    assert len(corpus_batch.documents) == EXPECTED_DOCUMENTS
    assert len(corpus_batch.chunks) == EXPECTED_CHUNKS

    counts = Counter((record.doc_id, record.kind) for record in corpus_batch.chunks)
    for doc_id, (total, text, table) in CHUNK_COUNTS.items():
        assert counts[doc_id, "text"] == text
        assert counts[doc_id, "table"] == table
        assert counts[doc_id, "text"] + counts[doc_id, "table"] == total

    assert counts.total() == EXPECTED_CHUNKS
    assert sum(count for (doc_id, kind), count in counts.items() if kind == "text") == (
        EXPECTED_TEXT_CHUNKS
    )
    assert sum(count for (doc_id, kind), count in counts.items() if kind == "table") == (
        EXPECTED_TABLE_CHUNKS
    )


def test_corpus_records_preserve_metadata_and_provenance(corpus_batch):
    """Keep registry identity and chunk provenance in every seed record."""
    documents = {record.doc_id: record for record in corpus_batch.documents}
    assert all(record.registry == "sec" for record in documents.values())
    assert all(
        record.source_url.startswith("https://www.sec.gov/") for record in documents.values()
    )
    assert all(record.source_length > 0 for record in documents.values())
    assert all(len(record.source_sha256) == 64 for record in documents.values())
    assert all(record.parse_status == "parsed" for record in documents.values())

    xref_documents = [record for record in documents.values() if record.item_index]
    assert xref_documents
    assert any(
        entry["status"] in {"empty_disclosure", "incorporated_by_reference"}
        for record in xref_documents
        for entry in record.item_index
    )

    for record in corpus_batch.chunks:
        document = documents[record.doc_id]
        assert record.source_sha256 == document.source_sha256
        assert 0 <= record.start_char < record.end_char <= document.source_length
        assert record.index_text == compose_index_text(record.context_header, record.body)
        assert "embedding" not in record.values()
