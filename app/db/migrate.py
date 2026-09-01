"""Explicit idempotent PostgreSQL migrations for data-preserving schema changes."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import re
from typing import Final

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.bootstrap import ensure_schema_compatibility

USAGE_MIGRATION_ID: Final[str] = "20260901_usage_accounting"
LEDGER_TABLE: Final[str] = "docreview_schema_migrations"
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

_COLUMNS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "runs": (
        ("total_cached_input_tokens", "BIGINT NOT NULL DEFAULT 0"),
        ("total_cache_write_input_tokens", "BIGINT NOT NULL DEFAULT 0"),
        ("total_reasoning_tokens", "BIGINT NOT NULL DEFAULT 0"),
        ("total_estimated_cost_usd", "NUMERIC NOT NULL DEFAULT 0"),
    ),
    "traces": (
        ("cached_input_tokens", "BIGINT NOT NULL DEFAULT 0"),
        ("cache_write_input_tokens", "BIGINT NOT NULL DEFAULT 0"),
        ("reasoning_tokens", "BIGINT NOT NULL DEFAULT 0"),
    ),
}
_CONSTRAINTS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "runs": (
        ("ck_runs_cached_input_tokens_nonnegative", "total_cached_input_tokens >= 0"),
        (
            "ck_runs_cache_write_input_tokens_nonnegative",
            "total_cache_write_input_tokens >= 0",
        ),
        ("ck_runs_reasoning_tokens_nonnegative", "total_reasoning_tokens >= 0"),
        ("ck_runs_cost_nonnegative", "total_estimated_cost_usd >= 0"),
    ),
    "traces": (
        ("ck_traces_cached_input_tokens_nonnegative", "cached_input_tokens >= 0"),
        (
            "ck_traces_cache_write_input_tokens_nonnegative",
            "cache_write_input_tokens >= 0",
        ),
        ("ck_traces_reasoning_tokens_nonnegative", "reasoning_tokens >= 0"),
    ),
}


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Read-only evidence describing whether one migration is still needed."""

    migration_id: str
    applied: bool
    needed: bool
    missing_columns: tuple[str, ...]
    missing_constraints: tuple[str, ...]


def _validate_schema(schema: str) -> str:
    """Reject an unsafe dynamic PostgreSQL schema identifier."""
    if not _SCHEMA_NAME.fullmatch(schema):
        raise ValueError("schema must be a lowercase PostgreSQL identifier")
    return schema


async def _resolved_schema(connection: AsyncConnection, schema: str) -> str:
    """Resolve PostgreSQL's pg_temp alias to the connection's actual namespace."""
    _validate_schema(schema)
    if schema != "pg_temp":
        return schema
    value = await connection.scalar(
        text("SELECT nspname FROM pg_namespace WHERE oid = pg_my_temp_schema()")
    )
    if not isinstance(value, str) or not value:
        raise RuntimeError("pg_temp has not been initialized on this connection")
    return value


async def _schema_objects(
    connection: AsyncConnection,
    schema: str,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Read table columns and check constraints from one exact namespace."""
    column_rows = (
        await connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = :schema"
            ),
            {"schema": schema},
        )
    ).all()
    constraint_rows = (
        await connection.execute(
            text(
                "SELECT cls.relname, con.conname FROM pg_constraint AS con "
                "JOIN pg_class AS cls ON cls.oid = con.conrelid "
                "JOIN pg_namespace AS ns ON ns.oid = cls.relnamespace "
                "WHERE ns.nspname = :schema AND con.contype = 'c'"
            ),
            {"schema": schema},
        )
    ).all()
    columns: dict[str, set[str]] = {}
    constraints: dict[str, set[str]] = {}
    for table, column in column_rows:
        columns.setdefault(table, set()).add(column)
    for table, constraint in constraint_rows:
        constraints.setdefault(table, set()).add(constraint)
    return columns, constraints


async def _missing_objects(
    connection: AsyncConnection,
    schema: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Collect missing migration-owned columns and constraints."""
    columns_by_table, constraints_by_table = await _schema_objects(connection, schema)
    missing_columns: list[str] = []
    missing_constraints: list[str] = []
    for table, columns in _COLUMNS.items():
        if table not in columns_by_table:
            continue
        live_columns = columns_by_table[table]
        missing_columns.extend(
            f"{table}.{name}" for name, _ddl in columns if name not in live_columns
        )
        live_constraints = constraints_by_table.get(table, set())
        missing_constraints.extend(
            f"{table}.{name}"
            for name, _expression in _CONSTRAINTS[table]
            if name not in live_constraints
        )
    return tuple(sorted(missing_columns)), tuple(sorted(missing_constraints))


async def plan_schema_migrations(
    connection: AsyncConnection,
    *,
    schema: str = "public",
) -> MigrationPlan:
    """Inspect migration state without creating tables or changing data."""
    actual_schema = await _resolved_schema(connection, schema)
    missing_columns, missing_constraints = await _missing_objects(
        connection,
        actual_schema,
    )
    preparer = postgresql.dialect().identifier_preparer
    ledger = f"{preparer.quote_schema(actual_schema)}.{preparer.quote(LEDGER_TABLE)}"
    ledger_exists = bool(
        await connection.scalar(text("SELECT to_regclass(:ledger) IS NOT NULL"), {"ledger": ledger})
    )
    applied = False
    if ledger_exists:
        applied = bool(
            await connection.scalar(
                text(f"SELECT EXISTS (SELECT 1 FROM {ledger} WHERE migration_id = :id)"),
                {"id": USAGE_MIGRATION_ID},
            )
        )
    return MigrationPlan(
        migration_id=USAGE_MIGRATION_ID,
        applied=applied,
        needed=bool(missing_columns or missing_constraints),
        missing_columns=missing_columns,
        missing_constraints=missing_constraints,
    )


async def apply_schema_migrations(
    connection: AsyncConnection,
    *,
    schema: str = "public",
) -> tuple[str, ...]:
    """Apply pending data-preserving migrations inside the caller transaction."""
    actual_schema = await _resolved_schema(connection, schema)
    preparer = postgresql.dialect().identifier_preparer
    namespace = preparer.quote_schema(actual_schema)
    ledger = f"{namespace}.{preparer.quote(LEDGER_TABLE)}"
    runs = f"{namespace}.{preparer.quote('runs')}"
    traces = f"{namespace}.{preparer.quote('traces')}"
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('docreview_schema_migrations'))")
    )
    await connection.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {ledger} ("
            "migration_id TEXT PRIMARY KEY, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )
    plan = await plan_schema_migrations(connection, schema=schema)
    if plan.applied and not plan.needed:
        return ()

    columns_by_table, _constraints_by_table = await _schema_objects(
        connection,
        actual_schema,
    )
    tables = set(columns_by_table)
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        qualified = f"{namespace}.{preparer.quote(table)}"
        for name, ddl in columns:
            await connection.execute(
                text(
                    f"ALTER TABLE {qualified} ADD COLUMN IF NOT EXISTS {preparer.quote(name)} {ddl}"
                )
            )

    if {"runs", "traces"}.issubset(tables):
        await connection.execute(
            text(
                f"UPDATE {runs} AS run SET "
                "total_cached_input_tokens = usage.cached_input_tokens, "
                "total_cache_write_input_tokens = usage.cache_write_input_tokens, "
                "total_reasoning_tokens = usage.reasoning_tokens, "
                "total_estimated_cost_usd = usage.estimated_cost_usd "
                "FROM (SELECT run_id, "
                "COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens, "
                "COALESCE(SUM(cache_write_input_tokens), 0) AS cache_write_input_tokens, "
                "COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens, "
                "COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd "
                f"FROM {traces} GROUP BY run_id) AS usage "
                "WHERE run.run_id = usage.run_id"
            )
        )

    for table, constraints in _CONSTRAINTS.items():
        if table not in tables:
            continue
        qualified = f"{namespace}.{preparer.quote(table)}"
        for name, expression in constraints:
            await connection.execute(
                text(
                    "DO $migration$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
                    f"WHERE conrelid = '{qualified}'::regclass AND conname = '{name}') THEN "
                    f"ALTER TABLE {qualified} ADD CONSTRAINT {preparer.quote(name)} "
                    f"CHECK ({expression}); "
                    "END IF; END $migration$"
                )
            )
    await connection.execute(
        text(
            f"INSERT INTO {ledger} (migration_id) VALUES (:id) "
            "ON CONFLICT (migration_id) DO NOTHING"
        ),
        {"id": USAGE_MIGRATION_ID},
    )
    if schema == "public":
        await ensure_schema_compatibility(connection)
    return (USAGE_MIGRATION_ID,)


def arguments() -> argparse.Namespace:
    """Parse one explicit migration action."""
    parser = argparse.ArgumentParser(description="Inspect or apply DocReview DB migrations.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true", help="Inspect pending migrations only.")
    action.add_argument("--apply", action="store_true", help="Apply pending migrations.")
    return parser.parse_args()


async def _run(apply: bool) -> dict[str, object]:
    """Run one CLI migration action against the configured database."""
    from app.db.session import engine

    if apply:
        async with engine.begin() as connection:
            applied = await apply_schema_migrations(connection)
            plan = await plan_schema_migrations(connection)
    else:
        async with engine.connect() as connection:
            applied = ()
            plan = await plan_schema_migrations(connection)
    await engine.dispose()
    return {"applied": list(applied), "plan": asdict(plan)}


def main() -> None:
    """Print stable JSON evidence for a plan or apply action."""
    parsed = arguments()
    print(json.dumps(asyncio.run(_run(parsed.apply)), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
