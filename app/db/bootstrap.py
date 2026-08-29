"""Minimal idempotent PostgreSQL schema bootstrap."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Base


async def ensure_vector_extension(connection: AsyncConnection) -> None:
    """Enable pgvector in the current database if it is not already enabled."""
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Enable pgvector before creating missing SQLAlchemy tables and indexes."""
    async with engine.begin() as connection:
        await ensure_vector_extension(connection)
        await connection.run_sync(Base.metadata.create_all)
