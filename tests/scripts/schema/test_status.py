"""Safe local schema inspection and empty-database preparation."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.schema.status import schema_status
from tests.live_postgres import disposable_database_url


@pytest.mark.live_postgres
def test_schema_preparation_preserves_incompatible_database():
    """Create an empty schema but reject drift without modifying existing data."""
    admin_url = disposable_database_url()
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
