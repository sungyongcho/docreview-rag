"""Container entrypoint refuses incompatible runtime data before launching the server."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from app.db import startup
from app.db.bootstrap import SchemaDriftError


def test_runtime_prepares_before_exec(monkeypatch, capsys):
    """A runtime target must pass the shared gate before server exec."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("DATABASE_URL", "private-target")
    monkeypatch.setattr(startup.sys, "argv", ["gate", "server", "arg"])
    prepare = AsyncMock(return_value=True)
    launch = Mock()
    monkeypatch.setattr(startup, "prepare", prepare)
    monkeypatch.setattr(startup.os, "execvp", launch)
    assert startup.main() == 0
    prepare.assert_awaited_once_with("private-target")
    launch.assert_called_once_with("server", ["server", "arg"])
    output = capsys.readouterr().out
    assert '"schema_status": "compatible"' in output
    assert "private-target" not in output


def test_drift_blocks_exec_and_reports_recovery(monkeypatch, capsys):
    """A known drift is neither repaired nor hidden by starting the application."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("DATABASE_URL", "private-target")
    monkeypatch.setattr(startup.sys, "argv", ["gate", "server"])
    monkeypatch.setattr(
        startup, "prepare", AsyncMock(side_effect=SchemaDriftError("missing table"))
    )
    launch = Mock()
    monkeypatch.setattr(startup.os, "execvp", launch)
    assert startup.main() == 1
    launch.assert_not_called()
    output = capsys.readouterr().out
    assert "scripts.schema recover" in output and '"created": false' in output
    assert "private-target" not in output


def test_canned_default_does_not_touch_database(monkeypatch):
    """Keep mount-free read-only public images independent of PostgreSQL."""
    monkeypatch.delenv("DOCREVIEW_MODE", raising=False)
    monkeypatch.setattr(startup.sys, "argv", ["gate", "server"])
    prepare = AsyncMock()
    monkeypatch.setattr(startup, "prepare", prepare)
    monkeypatch.setattr(startup.os, "execvp", Mock())
    assert startup.main() == 0
    prepare.assert_not_called()


def test_prepare_uses_the_shared_bootstrap_and_releases_its_engine(monkeypatch):
    """Preparation delegates to the non-destructive bootstrap and always disposes the engine."""
    engine = Mock(dispose=AsyncMock())
    shared = AsyncMock(return_value=False)
    monkeypatch.setattr(startup, "create_async_engine", lambda *a, **k: engine)
    monkeypatch.setattr(startup, "prepare_empty_schema", shared)
    assert asyncio.run(startup.prepare("unused")) is False
    shared.assert_awaited_once_with(engine)
    engine.dispose.assert_awaited_once()


@pytest.mark.live_postgres
def test_live_startup_empty_compatible_and_drifted(monkeypatch):
    """Prepare a fresh database once and preserve rows while rejecting incomplete schema."""
    import asyncio
    from uuid import uuid4

    from sqlalchemy import event, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.documents.catalog import DocumentCatalog
    from app.api.errors import ApiProblemError
    from app.db.bootstrap import prepare_empty_schema
    from app.retrieval.embedding.provider import EmbeddingIdentity
    from tests.live_postgres import disposable_database_url

    admin_url = disposable_database_url()
    name = "startup_" + uuid4().hex

    async def scenario():
        """Own only a uniquely named fixture DB and inspect the real SQL sent to it."""
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_async_engine(admin_url.rsplit("/", 1)[0] + "/" + name)
        try:
            assert await prepare_empty_schema(engine) is True
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE preserved_sentinel (value text)"))
                await connection.execute(text("INSERT INTO preserved_sentinel VALUES ('keep')"))
            statements = []

            def capture(_connection, _cursor, statement, _parameters, _context, _many):
                """Record statements so the compatible path cannot hide schema mutations."""
                statements.append(statement)

            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            assert await prepare_empty_schema(engine) is False
            assert not any(
                row.lstrip()
                .upper()
                .startswith(("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"))
                for row in statements
            )
            async with engine.begin() as connection:
                await connection.execute(text("DROP TABLE chunk_embeddings"))
            with pytest.raises(SchemaDriftError, match="chunk_embeddings"):
                await prepare_empty_schema(engine)
            catalog = DocumentCatalog(
                async_sessionmaker(engine),
                public_only=False,
                embedding_identity=EmbeddingIdentity("deterministic", "test", 384, "test"),
            )
            statements.clear()
            for operation in (
                catalog.document_facets(),
                catalog.document_detail("missing"),
                catalog.documents(
                    query="",
                    registry="",
                    issuer="",
                    fiscal_year=None,
                    language="",
                    form="",
                    parse_status="",
                    embedding_status=None,
                    snapshot_id=None,
                    sort="doc_id",
                    descending=False,
                    cursor=None,
                    limit=10,
                ),
            ):
                with pytest.raises(ApiProblemError) as error:
                    await operation
                assert error.value.error.code == "schema_not_ready"
            assert not any(
                "FROM documents" in row or "FROM chunk_embeddings" in row for row in statements
            )
            async with engine.connect() as connection:
                assert (
                    await connection.execute(text("SELECT value FROM preserved_sentinel"))
                ).scalar_one() == "keep"
        finally:
            await engine.dispose()
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}"'))
            await admin.dispose()

    asyncio.run(scenario())
