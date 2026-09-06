"""Corpus invariants for complete embedding inputs and deterministic identities."""

from app.ingestion.tokens import count_tokens


def test_corpus_chunks_fit_complete_input_limits(chunks_by_doc):
    """Bound context and body together for every corpus retrieval unit."""
    for chunks in chunks_by_doc.values():
        assert chunks
        assert all(count_tokens(chunk.content) <= 8192 for chunk in chunks)
        assert all(len(chunk.content) <= 32768 for chunk in chunks)


def test_corpus_chunk_identities_are_deterministic(chunks_by_doc, corpus, chunker):
    """Rebuilding unchanged sources reproduces every stable identity and body."""
    for doc_id, (filing, _raw) in corpus.items():
        actual = chunker(filing)
        expected = chunks_by_doc[doc_id]
        assert [(chunk.stable_key, chunk.body) for chunk in actual] == [
            (chunk.stable_key, chunk.body) for chunk in expected
        ]
        assert len({chunk.stable_key for chunk in actual}) == len(actual)
