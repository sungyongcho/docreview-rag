"""Explicit database recreation uses confirmation and atomic, non-cascading deletion."""

import asyncio
import os
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from scripts import schema_recreate as command


@pytest.mark.parametrize("answer", ["", "yes", "RECREATE another-checkout"])
def test_wrong_confirmation_never_stops_or_deletes(tmp_path, monkeypatch, answer):
    """Only the exact irreversible phrase can progress beyond the read-only preview."""
    target = {"port": "12345", "apps": ["app"], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "local_target", lambda root: (target, {}))
    operation = AsyncMock(return_value={"documents": 1})
    stop = Mock()
    monkeypatch.setattr(command, "recreate", operation)
    monkeypatch.setattr(command.subprocess, "run", stop)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert command.run(tmp_path) == 0
    assert operation.await_count == 1
    assert operation.await_args.args == (
        "postgresql+asyncpg://filing:filing@127.0.0.1:12345/filing",
    )
    stop.assert_not_called()


def test_noninteractive_recreate_does_not_inspect_or_mutate(tmp_path, monkeypatch):
    """Piped confirmation is never accepted."""
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: False)
    target = Mock()
    monkeypatch.setattr(command, "local_target", target)
    with pytest.raises(ValueError, match="interactive"):
        command.run(tmp_path)
    target.assert_not_called()


def test_remote_docker_is_rejected_before_contact(tmp_path, monkeypatch):
    """An external Docker daemon cannot redirect the local destructive operation."""
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example:2375")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    contact = Mock()
    monkeypatch.setattr(command.subprocess, "check_output", contact)
    with pytest.raises(ValueError, match="local Docker"):
        command.local_target(tmp_path)
    contact.assert_not_called()


@pytest.mark.live_postgres
def test_recreate_rolls_back_foreign_dependencies_and_preserves_unrelated_data():
    """Use a disposable legacy DB to verify actual rollback and then successful ORM creation."""
    url = os.environ.get("SCHEMA_TEST_ADMIN_URL")
    if not url:
        pytest.skip("SCHEMA_TEST_ADMIN_URL must identify an isolated test server")
    name = "recreate_" + uuid4().hex

    async def scenario():
        """Own one fixture DB; never connect to the user's database for destructive checks."""
        admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        target = url.rsplit("/", 1)[0] + "/" + name
        engine = create_async_engine(target)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE documents (id integer PRIMARY KEY)"))
                await connection.execute(text("INSERT INTO documents VALUES (1)"))
                await connection.execute(
                    text(
                        "CREATE TABLE user_sentinel (id integer REFERENCES documents(id), "
                        "value text)"
                    )
                )
                await connection.execute(text("INSERT INTO user_sentinel VALUES (1, 'keep')"))
            await engine.dispose()
            preview = await command.recreate(target)
            assert preview == {"documents": 1}
            with pytest.raises(SQLAlchemyError):
                await command.recreate(target, preview)
            async with engine.begin() as connection:
                assert (
                    await connection.execute(text("SELECT count(*) FROM documents"))
                ).scalar_one() == 1
                assert (
                    await connection.execute(text("SELECT value FROM user_sentinel"))
                ).scalar_one() == "keep"
                await connection.execute(
                    text("ALTER TABLE user_sentinel DROP CONSTRAINT user_sentinel_id_fkey")
                )
            await engine.dispose()
            result = await command.recreate(target, preview)
            assert "chunk_embeddings" in result and not any(result.values())
            async with engine.connect() as connection:
                assert (
                    await connection.execute(text("SELECT value FROM user_sentinel"))
                ).scalar_one() == "keep"
        finally:
            await engine.dispose()
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}"'))
            await admin.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["expired", "changed"])
def test_stale_preview_never_stops_or_deletes(tmp_path, monkeypatch, boundary):
    """Confirmation cannot authorize a stale preview or another database target."""
    target = {"port": "12345", "apps": ["app"], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    replies = [(target, {}), ({**target, "port": "12346"}, {})]
    monkeypatch.setattr(command, "local_target", Mock(side_effect=replies))
    operation = AsyncMock(return_value={"documents": 1})
    stop = Mock()
    monkeypatch.setattr(command, "recreate", operation)
    monkeypatch.setattr(command.subprocess, "run", stop)
    monkeypatch.setattr("builtins.input", lambda prompt: f"RECREATE {tmp_path.name} AND SOURCES")
    from types import SimpleNamespace

    monkeypatch.setattr(
        command,
        "time",
        SimpleNamespace(monotonic=iter([0, 301 if boundary == "expired" else 1]).__next__),
    )
    with pytest.raises(ValueError, match="expired" if boundary == "expired" else "changed"):
        command.run(tmp_path)
    assert operation.await_count == 1
    stop.assert_not_called()
