"""Database bootstrap ordering tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.db.bootstrap import bootstrap_schema, ensure_vector_extension
from app.db.models import Base


class _ConnectionContext:
    def __init__(self, connection: AsyncMock) -> None:
        self.connection = connection

    async def __aenter__(self) -> AsyncMock:
        return self.connection

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        return None


def test_vector_extension_is_created_idempotently() -> None:
    """Issue the idempotent pgvector extension statement."""
    connection = AsyncMock()
    asyncio.run(ensure_vector_extension(connection))

    statement = connection.execute.await_args.args[0]
    assert str(statement) == "CREATE EXTENSION IF NOT EXISTS vector"


def test_bootstrap_enables_vector_before_creating_tables() -> None:
    """Enable pgvector before SQLAlchemy creates tables and indexes."""
    connection = AsyncMock()
    engine = MagicMock()
    engine.begin.return_value = _ConnectionContext(connection)

    asyncio.run(bootstrap_schema(engine))

    assert connection.method_calls[0][0] == "execute"
    connection.run_sync.assert_awaited_once_with(Base.metadata.create_all)
