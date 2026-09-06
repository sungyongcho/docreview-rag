"""Corpus-level proof that M1.4 prepares every M1.3 chunk."""

from collections import Counter

import pytest

from app.ingestion import parser as parser_module
from tests.chunk.golden import CHUNK_COUNTS
from tests.db.golden import (
    EXPECTED_CHUNKS,
    EXPECTED_DOCUMENT_IDS,
    EXPECTED_DOCUMENTS,
    EXPECTED_TABLE_CHUNKS,
    EXPECTED_TEXT_CHUNKS,
)
from tests.support import need


@pytest.fixture(scope="module")
def corpus_batch(S, tmp_path_factory):
    need(S, "prepare_seed_batch")
    original_profiles = parser_module.PROFILES
    parser_module.PROFILES = tmp_path_factory.mktemp("db_profiles")
    try:
        return S.prepare_seed_batch(expected_documents=EXPECTED_DOCUMENTS)
    finally:
        parser_module.PROFILES = original_profiles


def test_batch_contains_all_20_documents_and_m13_chunks(corpus_batch):
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
    documents = {record.doc_id: record for record in corpus_batch.documents}
    assert all(record.url.startswith("https://www.sec.gov/") for record in documents.values())
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
        expected = (
            f"{record.context_header}\n\n{record.body}" if record.context_header else record.body
        )
        assert record.index_text == expected
        assert "embedding" not in record.values()
