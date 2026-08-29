"""PostgreSQL statement and transaction tests without a live database."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.ingestion import seed
from tests.ingestion.seed.support import sample_batch


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_document_upsert_targets_doc_id_and_updates_snapshot_metadata():
    """Update filing identity and source metadata on document conflicts."""
    batch = sample_batch()
    sql = _sql(seed.document_upsert_statement(batch.documents))
    assert "ON CONFLICT (doc_id) DO UPDATE SET" in sql
    assert "source_length = excluded.source_length" in sql
    assert "source_sha256 = excluded.source_sha256" in sql
    assert "report_period = excluded.report_period" in sql
    assert "parse_status = excluded.parse_status" in sql
    assert "item_index = excluded.item_index" in sql


def test_chunk_upsert_targets_doc_ordinal_and_never_writes_embeddings():
    """Upsert chunk content without inserting an embedding payload."""
    batch = sample_batch()
    statement = seed.chunk_upsert_statement(batch.chunks)
    sql = _sql(statement)
    assert "ON CONFLICT (doc_id, ordinal) DO UPDATE SET" in sql
    assert "body = excluded.body" in sql
    assert "context_header = excluded.context_header" in sql
    assert "index_text = excluded.index_text" in sql
    assert "start_char = excluded.start_char" in sql
    assert "end_char = excluded.end_char" in sql
    assert "embedding" not in sql.split("ON CONFLICT", maxsplit=1)[0]
    assert not any("embedding" in name for name in statement.compile().params)


def test_chunk_upsert_invalidates_only_stale_embeddings():
    """Preserve embeddings only when indexed text remains unchanged."""
    sql = _sql(seed.chunk_upsert_statement(sample_batch().chunks))
    normalized = " ".join(sql.split())
    assert "embedding = CASE WHEN (chunks.index_text = excluded.index_text)" in normalized
    assert "THEN chunks.embedding END" in normalized


class _Transaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.begins += 1

    async def __aexit__(self, exc_type, _exc, _traceback):
        if exc_type is None:
            self.session.commits += 1
        else:
            self.session.rollbacks += 1


class _Session:
    def __init__(self, *, active=False, fail_at=None):
        self.active = active
        self.fail_at = fail_at
        self.executed = []
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    def in_transaction(self):
        return self.active

    def begin(self):
        return _Transaction(self)

    async def execute(self, statement):
        self.executed.append(statement)
        if self.fail_at == len(self.executed):
            raise RuntimeError("simulated database failure")


def test_persist_seed_batch_owns_one_transaction_and_batches_chunks():
    """Own one transaction while writing bounded chunk batches."""
    session = _Session()
    result = asyncio.run(seed.persist_seed_batch(session, sample_batch(), chunk_batch_size=1))
    assert result.documents == 1
    assert result.chunks == 2
    assert session.begins == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(session.executed) == 4


def test_persist_seed_batch_rolls_back_the_whole_batch_on_failure():
    """Roll back every seed write when one statement fails."""
    session = _Session(fail_at=2)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        asyncio.run(seed.persist_seed_batch(session, sample_batch(), chunk_batch_size=1))
    assert session.begins == 1
    assert session.commits == 0
    assert session.rollbacks == 1


def test_persist_seed_batch_rejects_ambiguous_nested_transaction():
    """Reject sessions that already own a transaction."""
    session = _Session(active=True)
    with pytest.raises(RuntimeError, match="without an active transaction"):
        asyncio.run(seed.persist_seed_batch(session, sample_batch()))
    assert session.executed == []


def test_persist_seed_batch_rejects_nonpositive_batch_size():
    """Reject nonpositive chunk batch sizes before writing."""
    with pytest.raises(ValueError, match="batch size must be positive"):
        asyncio.run(seed.persist_seed_batch(_Session(), sample_batch(), chunk_batch_size=0))


def test_seed_corpus_offloads_preparation_before_persisting(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run blocking corpus preparation through ``asyncio.to_thread``."""
    batch = sample_batch()
    expected = seed.SeedResult(documents=1, chunks=2)
    to_thread = AsyncMock(return_value=batch)
    persist = AsyncMock(return_value=expected)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    monkeypatch.setattr(seed, "persist_seed_batch", persist)

    session = object()
    result = asyncio.run(seed.seed_corpus(session, expected_documents=1, chunk_batch_size=7))

    assert result == expected
    to_thread.assert_awaited_once_with(
        seed.prepare_seed_batch,
        None,
        expected_documents=1,
    )
    persist.assert_awaited_once_with(session, batch, chunk_batch_size=7)
