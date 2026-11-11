"""Safe local schema inspection and empty-database preparation."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ParsedTable
from app.ingestion.persistence import persist_seed_batch
from app.ingestion.table_records import resolver_identity
from scripts.schema.status import schema_status
from tests.ingestion.seed.support import table_batch, tagged_table_batch
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


@pytest.mark.live_postgres
def test_schema_check_counts_tables_read_by_other_interpreter_code():
    """Report every stored table, and as stale only those read by other interpreter code."""
    admin_url = disposable_database_url()
    database = "schema_stale_" + uuid4().hex
    url = admin_url.rsplit("/", 1)[0] + "/" + database

    async def scenario():
        """Store two documents' tables, then mark one as read by an older interpreter."""
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
        try:
            assert (await schema_status(url, prepare=True))["stored_tables"] == {
                "total": 0,
                "stale": 0,
                "resolver_identity": resolver_identity(),
            }
            engine = create_async_engine(url)
            try:
                factory = async_sessionmaker(engine)
                for batch in (table_batch(), tagged_table_batch("AMD-FY2023")):
                    async with factory() as session:
                        await persist_seed_batch(session, batch)
                current = await schema_status(url)
                assert current["schema_status"] == "compatible"
                assert current["stored_tables"] == {
                    "total": 2,
                    "stale": 0,
                    "resolver_identity": resolver_identity(),
                }
                async with engine.begin() as connection:
                    await connection.execute(
                        update(ParsedTable)
                        .where(ParsedTable.doc_id == "AMD-FY2023")
                        .values(resolver_identity="0" * 64)
                    )
                stale = (await schema_status(url))["stored_tables"]
                assert isinstance(stale, dict)
                assert (stale["total"], stale["stale"]) == (2, 1)
            finally:
                await engine.dispose()
        finally:
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{database}"'))
            await admin.dispose()

    asyncio.run(scenario())
