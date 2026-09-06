"""Exact evaluated-index identity without database or provider calls."""

import asyncio
from dataclasses import replace

import pytest

from app.evals.index_identity import index_fingerprint
from app.retrieval.embeddings import EmbeddingIdentity


class _Result:
    """Expose recorded rows through the SQLAlchemy result boundary."""

    def __init__(self, rows):
        """Retain one deterministic result batch."""
        self.rows = rows

    def all(self):
        """Return the recorded batch."""
        return self.rows


class _Session:
    """Return stable source identities followed by caller-supplied chunk rows."""

    def __init__(self, chunk):
        """Prepare both queries without executing SQL."""
        self.rows = iter(([("document", "a" * 64)], [chunk]))

    async def execute(self, statement):
        """Return the next index projection."""
        return _Result(next(self.rows))


@pytest.mark.parametrize("field,value", [(1, "new-key"), (2, "c" * 64), (9, [0.0, 1.0])])
def test_index_fingerprint_rejects_changed_chunks_with_unchanged_document_sources(field, value):
    """Rechunking, changed input, and changed vectors each invalidate evaluation identity."""
    identity = EmbeddingIdentity("test", "model", 2, "cl100k_base")
    chunk = ["document", "key", "b" * 64, 0, "en", "text", "1", None, None, [1.0, 0.0]]
    baseline = asyncio.run(index_fingerprint(_Session(chunk), identity))
    changed = list(chunk)
    changed[field] = value
    assert asyncio.run(index_fingerprint(_Session(changed), identity)) != baseline
    assert asyncio.run(index_fingerprint(_Session(chunk), identity)) == baseline
    assert (
        asyncio.run(index_fingerprint(_Session(chunk), replace(identity, tokenizer="different")))
        != baseline
    )
