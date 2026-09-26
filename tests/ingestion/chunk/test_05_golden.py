"""Corpus invariants for complete embedding inputs and deterministic identities."""

import app.ingestion.chunking as chunking


def test_corpus_chunk_identities_are_deterministic(chunks_by_doc, corpus):
    """Rebuilding unchanged sources reproduces every stable identity and body."""
    for doc_id, (filing, _raw) in corpus.items():
        actual = chunking.chunk_filing(filing)
        expected = chunks_by_doc[doc_id]
        assert [(chunk.stable_key, chunk.body) for chunk in actual] == [
            (chunk.stable_key, chunk.body) for chunk in expected
        ]
        assert len({chunk.stable_key for chunk in actual}) == len(actual)
