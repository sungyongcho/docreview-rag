"""L2/L3 PostgreSQL statement and transaction tests without a live database."""

import asyncio

import pytest
from sqlalchemy.dialects import postgresql

from tests.db.support import sample_batch
from tests.support import need


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_document_upsert_targets_doc_id_and_updates_snapshot_metadata(S):
    need(S, "DocumentRecord", "ChunkRecord", "SeedBatch", "filing_records")
    need(S, "document_upsert_statement")
    batch = sample_batch(S)
    sql = _sql(S.document_upsert_statement(batch.documents))
    assert "ON CONFLICT (doc_id) DO UPDATE SET" in sql
    assert "source_length = excluded.source_length" in sql
    assert "source_sha256 = excluded.source_sha256" in sql
    assert "report_period = excluded.report_period" in sql
    assert "parse_status = excluded.parse_status" in sql
    assert "item_index = excluded.item_index" in sql


def test_chunk_upsert_targets_doc_ordinal_and_never_writes_embeddings(S):
    need(S, "DocumentRecord", "ChunkRecord", "SeedBatch", "filing_records")
    need(S, "chunk_upsert_statement")
    batch = sample_batch(S)
    statement = S.chunk_upsert_statement(batch.chunks)
    sql = _sql(statement)
    assert "ON CONFLICT (doc_id, ordinal) DO UPDATE SET" in sql
    assert "body = excluded.body" in sql
    assert "context_header = excluded.context_header" in sql
    assert "index_text = excluded.index_text" in sql
    assert "start_char = excluded.start_char" in sql
    assert "end_char = excluded.end_char" in sql
    assert "embedding" not in sql.split("ON CONFLICT", maxsplit=1)[0]
    assert not any("embedding" in name for name in statement.compile().params)


def test_chunk_upsert_invalidates_only_stale_embeddings(S):
    need(S, "DocumentRecord", "ChunkRecord", "SeedBatch", "filing_records")
    need(S, "chunk_upsert_statement")
    sql = _sql(S.chunk_upsert_statement(sample_batch(S).chunks))
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


def test_persist_seed_batch_owns_one_transaction_and_batches_chunks(S):
    need(S, "DocumentRecord", "ChunkRecord", "SeedBatch", "filing_records")
    need(S, "persist_seed_batch")
    session = _Session()
    result = asyncio.run(S.persist_seed_batch(session, sample_batch(S), chunk_batch_size=1))
    assert result.documents == 1
    assert result.chunks == 2
    assert session.begins == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(session.executed) == 4


def test_persist_seed_batch_rolls_back_the_whole_batch_on_failure(S):
    need(S, "DocumentRecord", "ChunkRecord", "SeedBatch", "filing_records")
    need(S, "persist_seed_batch")
    session = _Session(fail_at=2)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        asyncio.run(S.persist_seed_batch(session, sample_batch(S), chunk_batch_size=1))
    assert session.begins == 1
    assert session.commits == 0
    assert session.rollbacks == 1


def test_persist_seed_batch_rejects_ambiguous_nested_transaction(S):
    need(S, "DocumentRecord", "ChunkRecord", "SeedBatch", "filing_records")
    need(S, "persist_seed_batch")
    session = _Session(active=True)
    with pytest.raises(RuntimeError, match="without an active transaction"):
        asyncio.run(S.persist_seed_batch(session, sample_batch(S)))
    assert session.executed == []


def test_persist_seed_batch_rejects_nonpositive_batch_size(S):
    need(S, "DocumentRecord", "ChunkRecord", "SeedBatch", "filing_records")
    need(S, "persist_seed_batch")
    with pytest.raises(ValueError, match="batch size must be positive"):
        asyncio.run(S.persist_seed_batch(_Session(), sample_batch(S), chunk_batch_size=0))
