"""PostgreSQL statement and transaction tests without a live database."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.ingestion.seed as seed
from tests.ingestion.seed.support import sample_batch


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


def test_persist_seed_batch_reports_committed_progress():
    """Report the committed document and chunk progress in one transaction."""
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
    assert [(update.stage, update.current, update.total) for update in progress] == [
        ("documents", 0, 1),
        ("documents", 1, 1),
        ("chunks", 0, 2),
        ("chunks", 1, 2),
        ("chunks", 2, 2),
        ("cleanup", 0, 1),
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
