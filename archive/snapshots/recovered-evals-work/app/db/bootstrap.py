"""Minimal idempotent PostgreSQL schema bootstrap."""

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Base

BM25_INVALIDATION_FUNCTION = "docreview_invalidate_bm25_stats"
BM25_INVALIDATION_TRIGGER = "docreview_chunks_invalidate_bm25_stats"


async def ensure_vector_extension(connection: AsyncConnection) -> None:
    """Enable pgvector in the current database if it is not already enabled."""
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def ensure_bm25_stats_invalidation(
    connection: AsyncConnection, *, schema: str = "public"
) -> None:
    """Install the statement trigger that marks derived BM25 statistics stale."""
    preparer = postgresql.dialect().identifier_preparer
    namespace = preparer.quote_schema(schema)
    chunks = f"{namespace}.{preparer.quote('chunks')}"
    corpus_stats = f"{namespace}.{preparer.quote('bm25_corpus_stats')}"
    function = f"{namespace}.{preparer.quote(BM25_INVALIDATION_FUNCTION)}"
    trigger = preparer.quote(BM25_INVALIDATION_TRIGGER)

    await connection.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION {function}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                DELETE FROM {corpus_stats};
                RETURN NULL;
            END;
            $function$
            """
        )
    )
    await connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON {chunks}"))
    await connection.execute(
        text(
            f"""
            CREATE TRIGGER {trigger}
            AFTER INSERT OR DELETE OR UPDATE OF index_text ON {chunks}
            FOR EACH STATEMENT
            EXECUTE FUNCTION {function}()
            """
        )
    )


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Create schema objects and install BM25 statistic invalidation."""
    async with engine.begin() as connection:
        await ensure_vector_extension(connection)
        await connection.run_sync(Base.metadata.create_all)
        await ensure_bm25_stats_invalidation(connection)
