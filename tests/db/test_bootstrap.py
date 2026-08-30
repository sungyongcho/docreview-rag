"""Database bootstrap ordering and schema-compatibility tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
import app.db.bootstrap as bootstrap
from app.db.bootstrap import (
    SchemaDriftError,
    bootstrap_schema,
    ensure_schema_compatibility,
    ensure_vector_extension,
)
from app.db.models import Base
from tests.live_postgres import live_postgres_unavailable


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


def test_bootstrap_enables_vector_and_checks_drift_before_creating_tables() -> None:
    """Enable pgvector and check schema compatibility before create_all runs."""
    connection = AsyncMock()
    connection.run_sync.return_value = None
    engine = MagicMock()
    engine.begin.return_value = _ConnectionContext(connection)

    asyncio.run(bootstrap_schema(engine))

    assert connection.method_calls[0][0] == "execute"
    run_sync_targets = [call.args[0] for call in connection.run_sync.await_args_list]
    assert run_sync_targets == [bootstrap._collect_schema_drift, Base.metadata.create_all]


def test_schema_drift_error_lists_tables_columns_and_remedy() -> None:
    """Report every drifted table, its missing columns, and the rebuild remedy."""
    connection = AsyncMock()
    connection.run_sync.return_value = {
        "chunks": ["lexical_text"],
        "documents": ["language", "registry"],
    }

    with pytest.raises(SchemaDriftError) as excinfo:
        asyncio.run(ensure_schema_compatibility(connection))

    message = str(excinfo.value)
    assert "'chunks' is missing columns: lexical_text" in message
    assert "'documents' is missing columns: language, registry" in message
    assert "DROP TABLE chunks CASCADE" in message
    assert "DROP TABLE documents CASCADE" in message
    assert "--create-schema" in message


async def _probe_connection(
    engine, *, with_vector: bool = False
) -> tuple[AsyncConnection | None, str]:
    """Open a connection quickly or report why live PostgreSQL is unavailable."""
    try:
        async with asyncio.timeout(3):
            connection = await engine.connect()
            await connection.execute(text("SELECT 1"))
            if with_vector:
                await ensure_vector_extension(connection)
    except Exception as exc:
        return None, str(exc)
    return connection, ""


async def _cleanup_scratch_schema(connection: AsyncConnection | None, quoted: str, engine) -> None:
    """Roll back the scratch transaction and drop the scratch schema."""
    if connection is not None:
        await connection.rollback()
        await connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted} CASCADE"))
        await connection.commit()
        await connection.close()
    await engine.dispose()


async def _exercise_drift_detection(database_url: str) -> tuple[bool, str]:
    """Detect drift on a scratch chunks table that is missing ORM columns."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    schema = f"drift_check_{uuid4().hex}"
    quoted = postgresql.dialect().identifier_preparer.quote_schema(schema)
    try:
        connection, detail = await _probe_connection(engine)
        if connection is None:
            return False, detail

        await connection.execute(text(f"CREATE SCHEMA {quoted}"))
        await connection.execute(text(f"CREATE TABLE {quoted}.chunks (id bigint PRIMARY KEY)"))
        # The scratch schema alone is on the search path, so the inspector sees
        # only the degenerate chunks table regardless of the real public state.
        await connection.execute(text(f"SET search_path TO {quoted}"))

        expected_missing = sorted(
            column.name for column in Base.metadata.tables["chunks"].columns if column.name != "id"
        )
        assert expected_missing

        with pytest.raises(SchemaDriftError) as excinfo:
            await ensure_schema_compatibility(connection)

        message = str(excinfo.value)
        assert "'chunks' is missing columns" in message
        for column_name in expected_missing:
            assert column_name in message
        assert "DROP TABLE chunks CASCADE" in message
        return True, ""
    finally:
        await _cleanup_scratch_schema(connection, quoted, engine)


async def _exercise_clean_schema(database_url: str) -> tuple[bool, str]:
    """Pass the compatibility check on absent and then freshly created tables."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    schema = f"drift_check_{uuid4().hex}"
    quoted = postgresql.dialect().identifier_preparer.quote_schema(schema)
    try:
        connection, detail = await _probe_connection(engine, with_vector=True)
        if connection is None:
            return False, detail

        await connection.execute(text(f"CREATE SCHEMA {quoted}"))
        await connection.execute(text(f"SET search_path TO {quoted}"))
        # No metadata table is visible yet: absent tables must not raise.
        await ensure_schema_compatibility(connection)

        # public must be on the path so the vector extension type resolves, and
        # checkfirst=False forces creation into the scratch schema even when
        # same-named public tables are visible.
        await connection.execute(text(f"SET search_path TO {quoted}, public"))
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=False)
        )
        await ensure_schema_compatibility(connection)
        return True, ""
    finally:
        await _cleanup_scratch_schema(connection, quoted, engine)


@pytest.mark.live_postgres
def test_live_schema_drift_is_reported_with_rebuild_remedy() -> None:
    """Raise SchemaDriftError naming chunks and its missing columns on a live table."""
    reachable, detail = asyncio.run(_exercise_drift_detection(get_settings().database_url))
    if not reachable:
        live_postgres_unavailable(detail)


@pytest.mark.live_postgres
def test_live_schema_check_passes_on_freshly_created_tables() -> None:
    """Accept freshly created metadata tables without raising."""
    reachable, detail = asyncio.run(_exercise_clean_schema(get_settings().database_url))
    if not reachable:
        live_postgres_unavailable(detail)
