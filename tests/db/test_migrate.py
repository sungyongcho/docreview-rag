"""Live PostgreSQL tests for the data-preserving usage migration."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.migrate import apply_schema_migrations, plan_schema_migrations
from tests.live_postgres import live_postgres_unavailable


async def _exercise(database_url: URL) -> tuple[bool, str]:
    """Create the previous schema in pg_temp and migrate it twice."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    try:
        try:
            async with asyncio.timeout(3):
                connection = await engine.connect()
                await connection.execute(text("SELECT 1"))
        except Exception as error:
            return False, str(error)
        await connection.execute(
            text(
                "CREATE TEMP TABLE runs ("
                "run_id TEXT PRIMARY KEY, total_requests INTEGER NOT NULL, "
                "total_input_tokens BIGINT NOT NULL, total_output_tokens BIGINT NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "CREATE TEMP TABLE traces ("
                "id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL, retries INTEGER NOT NULL, "
                "input_tokens BIGINT NOT NULL, output_tokens BIGINT NOT NULL, "
                "estimated_cost_usd NUMERIC NOT NULL)"
            )
        )
        await connection.execute(text("INSERT INTO runs VALUES ('old-run', 2, 100, 20)"))
        await connection.execute(
            text(
                "INSERT INTO traces (run_id, retries, input_tokens, output_tokens,"
                " estimated_cost_usd) VALUES ('old-run', 0, 60, 10, 0.01),"
                " ('old-run', 0, 40, 10, 0.02)"
            )
        )

        before = await plan_schema_migrations(connection, schema="pg_temp")
        assert before.needed is True and before.applied is False
        assert "runs.total_estimated_cost_usd" in before.missing_columns

        assert await apply_schema_migrations(connection, schema="pg_temp") == (
            "20260901_usage_accounting",
        )
        after = await plan_schema_migrations(connection, schema="pg_temp")
        assert after.applied is True and after.needed is False
        assert await apply_schema_migrations(connection, schema="pg_temp") == ()

        row = (
            await connection.execute(
                text(
                    "SELECT total_cached_input_tokens, total_cache_write_input_tokens,"
                    " total_reasoning_tokens, total_estimated_cost_usd FROM runs"
                )
            )
        ).one()
        assert tuple(row[:3]) == (0, 0, 0)
        assert row[3] == Decimal("0.03")
        ledger_count = await connection.scalar(
            text("SELECT count(*) FROM docreview_schema_migrations")
        )
        assert ledger_count == 1
        constraints = set(
            (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'pg_temp.runs'::regclass AND contype = 'c'"
                    )
                )
            ).scalars()
        )
        assert "ck_runs_cost_nonnegative" in constraints
        await connection.rollback()
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


async def _exercise_experiment_schema(database_url: URL) -> tuple[bool, str]:
    """Migrate a corpus/eval schema that predates experiment snapshot tables."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    try:
        try:
            async with asyncio.timeout(3):
                connection = await engine.connect()
                await connection.execute(text("SELECT 1"))
        except Exception as error:
            return False, str(error)
        await connection.execute(
            text("CREATE TEMP TABLE documents (doc_id VARCHAR(32) PRIMARY KEY)")
        )
        await connection.execute(text("CREATE TEMP TABLE eval_results (id BIGSERIAL PRIMARY KEY)"))
        await connection.execute(
            text(
                "CREATE TEMP TABLE chunks (id BIGSERIAL PRIMARY KEY, embedding vector(384), "
                "embedding_provider VARCHAR(32), embedding_model VARCHAR(128), "
                "embedding_dimensions INTEGER)"
            )
        )

        before = await plan_schema_migrations(connection, schema="pg_temp")
        assert "evaluation_snapshots" in before.missing_tables
        applied = await apply_schema_migrations(connection, schema="pg_temp")
        assert applied == (
            "20260901_usage_accounting",
            "20260901_job_progress",
            "20260901_snapshot_index_revision",
        )
        after = await plan_schema_migrations(connection, schema="pg_temp")
        assert after.applied is True and after.needed is False
        columns = set(
            (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = (SELECT nspname FROM pg_namespace "
                        "WHERE oid = pg_my_temp_schema()) AND table_name = 'snapshot_chunks'"
                    )
                )
            ).scalars()
        )
        assert {"embedding", "body", "index_text", "content_tsv"} <= columns
        await connection.rollback()
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


@pytest.mark.live_postgres
def test_usage_migration_preserves_old_rows_and_is_idempotent():
    """Migrate the previous usage schema without rebuilding persisted data."""
    reachable, detail = asyncio.run(_exercise(make_url(get_settings().database_url)))
    if not reachable:
        live_postgres_unavailable(detail)


@pytest.mark.live_postgres
def test_experiment_migration_creates_snapshot_tables_idempotently():
    """Create the additive golden and snapshot schema in the requested namespace."""
    reachable, detail = asyncio.run(
        _exercise_experiment_schema(make_url(get_settings().database_url))
    )
    if not reachable:
        live_postgres_unavailable(detail)
