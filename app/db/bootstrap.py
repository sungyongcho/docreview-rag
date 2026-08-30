"""Minimal idempotent PostgreSQL schema bootstrap."""

from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Base

BM25_INVALIDATION_FUNCTION = "docreview_invalidate_bm25_stats"
BM25_INVALIDATION_TRIGGER = "docreview_chunks_invalidate_bm25_stats"


class SchemaDriftError(RuntimeError):
    """Live tables are missing columns that the ORM models map."""


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
            AFTER INSERT OR DELETE OR UPDATE OF index_text, lexical_text ON {chunks}
            FOR EACH STATEMENT
            EXECUTE FUNCTION {function}()
            """
        )
    )


def _collect_schema_drift(sync_connection: Connection) -> dict[str, list[str]]:
    """Map each existing table to the ORM-mapped columns it is missing."""
    inspector = inspect(sync_connection)
    existing_by_schema: dict[str | None, set[str]] = {}
    drift: dict[str, list[str]] = {}
    for table in Base.metadata.sorted_tables:
        if table.schema not in existing_by_schema:
            existing_by_schema[table.schema] = set(inspector.get_table_names(schema=table.schema))
        if table.name not in existing_by_schema[table.schema]:
            continue
        live_columns = {
            column["name"] for column in inspector.get_columns(table.name, schema=table.schema)
        }
        missing = sorted(column.name for column in table.columns if column.name not in live_columns)
        if missing:
            drift[table.name] = missing
    return drift


async def ensure_schema_compatibility(connection: AsyncConnection) -> None:
    """Fail closed when existing tables lack columns the ORM models map.

    ``create_all`` only creates absent tables and never alters existing ones,
    so a database created before the current models would otherwise fail later
    with obscure ``UndefinedColumn`` errors during trigger creation, seeding,
    or retrieval. The check is read-only and only inspects column names; extra
    live columns are tolerated because they do not break inserts, and tables
    absent from the database are fine because ``create_all`` creates them.

    Raises
    ------
    SchemaDriftError
        If any table that already exists in the database is missing at least
        one ORM-mapped column. The message lists every drifted table with its
        missing columns and the rebuild remedy: drop the listed tables and
        rerun with schema creation, then re-seed.
    """
    drift = await connection.run_sync(_collect_schema_drift)
    if not drift:
        return
    details = "; ".join(
        f"table {table!r} is missing columns: {', '.join(columns)}"
        for table, columns in sorted(drift.items())
    )
    drop_statements = " ".join(f"DROP TABLE {table} CASCADE;" for table in sorted(drift))
    raise SchemaDriftError(
        f"The live database schema is behind the ORM models: {details}. "
        "This project migrates by rebuild, not by ALTER: rerun seeding with "
        "--recreate-schema, or drop the listed tables yourself "
        f"(e.g. {drop_statements}) and rerun with --create-schema; "
        "re-seeding restores all derived state."
    )


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Create schema objects and install BM25 statistic invalidation.

    Raises
    ------
    SchemaDriftError
        If a pre-existing table is missing ORM-mapped columns; nothing is
        created or altered in that case.
    """
    async with engine.begin() as connection:
        await ensure_vector_extension(connection)
        await ensure_schema_compatibility(connection)
        await connection.run_sync(Base.metadata.create_all)
        await ensure_bm25_stats_invalidation(connection)
