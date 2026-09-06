"""PostgreSQL statement and transaction tests without a live database."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

import app.ingestion.seed as seed
from tests.ingestion.seed.support import sample_batch


def _sql(statement) -> str:
    """Render one statement as the PostgreSQL SQL it compiles to."""
    return str(statement.compile(dialect=postgresql.dialect()))


def test_document_upsert_targets_doc_id_and_updates_snapshot_metadata():
    """Update filing identity and source metadata on document conflicts."""
    batch = sample_batch()
    sql = _sql(seed.document_upsert_statement(batch.documents))
    assert "ON CONFLICT (doc_id) DO UPDATE SET" in sql
    assert "aliases = excluded.aliases" in sql
    assert "sec = excluded.sec" in sql
    assert "dart = excluded.dart" in sql
    assert "report_period = excluded.report_period" in sql
    assert "parse_status" not in sql
    assert "item_index" not in sql
    assert "source_sha256" not in sql
    assert "source_length" not in sql


def test_chunk_upsert_targets_stable_identity_and_never_writes_embeddings():
    """Upsert chunk content without inserting an embedding payload."""
    batch = sample_batch()
    statement = seed.chunk_upsert_statement(batch.chunks)
    sql = _sql(statement)
    assert "ON CONFLICT (stable_key) DO UPDATE SET" in sql
    assert "body = excluded.body" in sql
    assert "context_header = excluded.context_header" in sql
    assert "index_text = excluded.index_text" in sql
    assert "start_char = excluded.start_char" in sql
    assert "end_char = excluded.end_char" in sql
    assert "embedding" not in sql.split("ON CONFLICT", maxsplit=1)[0]
    assert not any("embedding" in name for name in statement.compile().params)


def test_chunk_upsert_leaves_independent_embedding_versions_untouched():
    """Keep source chunk persistence separate from every embedding configuration."""
    sql = _sql(seed.chunk_upsert_statement(sample_batch().chunks))
    normalized = " ".join(sql.split())
    assert "embedding" not in normalized
    assert "ON CONFLICT (stable_key)" in normalized


class _Transaction:
    """Transaction that counts its own commit and rollback."""

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
    """Session recording every statement, optionally failing at the nth."""

    def __init__(self, *, active=False, fail_at=None):
        self.active = active
        self.fail_at = fail_at
        self.executed = []
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    def in_transaction(self):
        """Report whether this session was opened inside a transaction."""
        return self.active

    def begin(self):
        """Open a counting transaction on this session."""
        return _Transaction(self)

    async def execute(self, statement):
        """Record the statement, raising once the configured failure point is reached."""
        self.executed.append(statement)
        if self.fail_at == len(self.executed):
            raise RuntimeError("simulated database failure")


def test_persist_seed_batch_owns_one_transaction_and_batches_chunks():
    """Own one transaction while writing bounded chunk batches."""
    session = _Session()
    progress = []
    result = asyncio.run(
        seed.persist_seed_batch(
            cast(AsyncSession, session),
            sample_batch(),
            chunk_batch_size=1,
            on_progress=progress.append,
        )
    )
    assert result.documents == 1
    assert result.chunks == 2
    assert session.begins == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    statements = [_sql(statement) for statement in session.executed]
    assert len(statements) == 8
    structure_position = next(
        i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO parsed_structures")
    )
    pointer_position = next(
        i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO document_parses")
    )
    assert structure_position < pointer_position
    assert "ON CONFLICT (doc_id) DO UPDATE SET structure_id" in statements[pointer_position]
    assert [(update.stage, update.current, update.total) for update in progress] == [
        ("documents", 0, 1),
        ("documents", 1, 1),
        ("chunks", 1, 2),
        ("chunks", 2, 2),
        ("cleanup", 1, 1),
    ]


def test_persist_seed_batch_rolls_back_the_whole_batch_on_failure():
    """Roll back every seed write when one statement fails."""
    session = _Session(fail_at=2)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        asyncio.run(
            seed.persist_seed_batch(cast(AsyncSession, session), sample_batch(), chunk_batch_size=1)
        )
    assert session.begins == 1
    assert session.commits == 0
    assert session.rollbacks == 1


def test_persist_seed_batch_rejects_ambiguous_nested_transaction():
    """Reject sessions that already own a transaction."""
    session = _Session(active=True)
    with pytest.raises(RuntimeError, match="without an active transaction"):
        asyncio.run(seed.persist_seed_batch(cast(AsyncSession, session), sample_batch()))
    assert session.executed == []


def test_persist_seed_batch_rejects_nonpositive_batch_size():
    """Reject nonpositive chunk batch sizes before writing."""
    with pytest.raises(ValueError, match="batch size must be positive"):
        asyncio.run(
            seed.persist_seed_batch(
                cast(AsyncSession, _Session()), sample_batch(), chunk_batch_size=0
            )
        )


def test_persistence_rebuilds_statistics_after_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rebuild lexical statistics after successful chunk persistence."""
    batch = sample_batch()
    expected = seed.SeedResult(documents=1, chunks=2)
    persist = AsyncMock(return_value=expected)
    rebuild = AsyncMock()
    monkeypatch.setattr(seed, "persist_seed_batch", persist)
    monkeypatch.setattr("app.retrieval.bm25.backfill_term_stats", rebuild)
    session = cast(AsyncSession, object())

    result = asyncio.run(seed.persist_seed_batch_with_stats(session, batch, chunk_batch_size=7))

    assert result == expected
    persist.assert_awaited_once_with(session, batch, chunk_batch_size=7, on_progress=None)
    rebuild.assert_awaited_once_with(session)
