"""Safe local schema inspection and empty-database preparation."""

import asyncio
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.schema import status
from scripts.schema.status import schema_status


@pytest.mark.live_postgres
def test_schema_preparation_preserves_incompatible_database():
    """Create an empty schema but reject drift without modifying existing data."""
    admin_url = os.environ.get("SCHEMA_TEST_ADMIN_URL")
    if not admin_url:
        pytest.skip("SCHEMA_TEST_ADMIN_URL must identify an isolated disposable test server")
    database = "schema_recovery_" + uuid4().hex
    url = admin_url.rsplit("/", 1)[0] + "/" + database

    async def scenario():
        """Own and remove only the unique test database on the isolated server."""
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
        try:
            assert (await schema_status(url))["schema_status"] == "empty"
            assert (await schema_status(url, prepare=True))["created"] is True
            assert (await schema_status(url, prepare=True))["created"] is False
            engine = create_async_engine(url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("CREATE TABLE preserved_data (value text)"))
                    await connection.execute(text("INSERT INTO preserved_data VALUES ('keep')"))
                    await connection.execute(text("ALTER TABLE documents DROP COLUMN issuer_id"))
                result = await schema_status(url, prepare=True)
                assert result["schema_status"] == "drifted"
                assert result["created"] is False
                async with engine.connect() as connection:
                    assert (
                        await connection.execute(text("SELECT value FROM preserved_data"))
                    ).scalar() == "keep"
            finally:
                await engine.dispose()
        finally:
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{database}"'))
            await admin.dispose()

    asyncio.run(scenario())


def test_schema_preparation_uses_shared_startup_contract(monkeypatch):
    """Schema preparation delegates to the same non-destructive implementation as the container."""
    from unittest.mock import Mock

    engine = Mock(dispose=AsyncMock())
    shared = AsyncMock(return_value=False)
    monkeypatch.setattr(status, "create_async_engine", lambda *a, **k: engine)
    monkeypatch.setattr(status, "prepare_empty_schema", shared)
    assert asyncio.run(status.prepare_schema("unused")) is False
    shared.assert_awaited_once_with(engine)
    engine.dispose.assert_awaited_once()
