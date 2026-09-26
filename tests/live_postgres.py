"""Shared availability policy for optional live PostgreSQL tests."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from typing import NoReturn
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.bootstrap import ensure_vector_extension
from app.db.models import Base

EXPECT_LIVE_POSTGRES_ENV = "DOCREVIEW_EXPECT_LIVE_POSTGRES"


def live_postgres_unavailable(detail: str) -> NoReturn:
    """Fail when live PostgreSQL was required, otherwise skip explicitly."""
    if os.getenv(EXPECT_LIVE_POSTGRES_ENV) == "1":
        pytest.fail(f"Expected live PostgreSQL, but it is unavailable: {detail}")
    pytest.skip(f"PostgreSQL is unavailable: {detail}")


@asynccontextmanager
async def isolated_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Give committing or concurrent sessions one disposable schema on the test database."""
    url = os.environ.get("DOCREVIEW_TEST_DATABASE_URL")
    if not url:
        live_postgres_unavailable(
            "DOCREVIEW_TEST_DATABASE_URL must identify an isolated disposable test database"
        )
    schema = f"behavior_test_{uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f'"{schema}", public'}},
    )
    try:
        try:
            async with asyncio.timeout(5):
                connection = await admin.connect()
        except (OSError, TimeoutError) as error:
            live_postgres_unavailable(str(error))
        try:
            await ensure_vector_extension(connection)
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.commit()
        finally:
            await connection.close()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync: Base.metadata.create_all(sync, checkfirst=False)
                )
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()
        await admin.dispose()


@asynccontextmanager
async def isolated_session() -> AsyncIterator[AsyncSession]:
    """Run ORM queries in a session whose schema and rows are removed after the test."""
    async with isolated_session_factory() as factory, factory() as session:
        yield session
