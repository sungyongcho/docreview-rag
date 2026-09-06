"""Corpus-level seed preparation and provenance tests."""

from collections import Counter

import pytest

from app.ingestion.chunk import compose_index_text
import app.ingestion.seed as seed
from app.ingestion.tokens import MAX_INPUT_CHARACTERS, MAX_INPUT_TOKENS, count_tokens
from tests.ingestion.golden import BLOCKS

EXPECTED_DOCUMENT_IDS = tuple(sorted(BLOCKS))


@pytest.fixture(scope="module")
def corpus_batch(corpus):
    """Build seed records from the already parsed shared corpus."""
    filings = (filing for filing, _raw in corpus.values())
    return seed.build_seed_batch_from_filings(filings)


def test_batch_preserves_every_selected_document_and_bounded_chunk(corpus_batch, corpus):
    """Preserve every parsed document with unique, bounded, source-ordered retrieval units."""
    documents = {record.doc_id for record in corpus_batch.documents}
    assert documents == set(corpus)
    assert len(documents) == len(corpus_batch.documents)
    keys = [record.stable_key for record in corpus_batch.chunks]
    assert len(keys) == len(set(keys))
    counts = Counter((record.doc_id, record.kind) for record in corpus_batch.chunks)
    for doc_id in documents:
        assert counts[doc_id, "text"] > 0
        assert counts[doc_id, "table"] > 0
        ordinals = [record.ordinal for record in corpus_batch.chunks if record.doc_id == doc_id]
        assert ordinals == list(range(len(ordinals)))
    for record in corpus_batch.chunks:
        assert len(record.index_text) <= MAX_INPUT_CHARACTERS
        assert count_tokens(record.index_text) <= MAX_INPUT_TOKENS


def test_corpus_records_preserve_metadata_and_provenance(corpus_batch):
    """Keep registry identity and chunk provenance in every seed record."""
    documents = {record.doc_id: record for record in corpus_batch.documents}
    assert all(record.registry == "sec" for record in documents.values())
    assert all(
        record.source_url.startswith("https://www.sec.gov/") for record in documents.values()
    )
    filings = {filing.source.document.document_id: filing for filing in corpus_batch.filings}
    assert all(filing.source_length > 0 for filing in filings.values())
    assert all(len(filing.source_sha256) == 64 for filing in filings.values())
    # Only the measured corpus is held to a clean parse; see the widened-corpus note
    # in tests/ingestion/golden.py.
    assert all(
        filings[doc_id].parse_status == "parsed"
        for doc_id in EXPECTED_DOCUMENT_IDS
        if doc_id in documents
    )

    xref_documents = [filing for filing in filings.values() if filing.item_index]
    assert xref_documents
    assert any(
        entry["status"] in {"empty_disclosure", "incorporated_by_reference"}
        for record in xref_documents
        for entry in record.item_index
    )

    for record in corpus_batch.chunks:
        filing = filings[record.doc_id]
        assert record.source_sha256 == filing.source_sha256
        assert 0 <= record.start_char < record.end_char <= filing.source_length
        assert record.index_text == compose_index_text(record.context_header, record.body)
        assert "embedding" not in record.values()
