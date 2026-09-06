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

from app.db.bootstrap import ensure_schema_compatibility, remove_snapshot_chunk_protection
from app.db.models import Base

USAGE_MIGRATION_ID: Final[str] = "20260901_usage_accounting"
EXPERIMENT_MIGRATION_ID: Final[str] = "20260901_job_progress"
SNAPSHOT_REVISION_MIGRATION_ID: Final[str] = "20260901_snapshot_index_revision"
LEDGER_TABLE: Final[str] = "docreview_schema_migrations"
EXPERIMENT_TABLES: Final[tuple[str, ...]] = (
    "golden_revisions",
    "evaluation_snapshots",
    "snapshot_documents",
    "snapshot_chunks",
    "snapshot_chunk_terms",
    "snapshot_chunk_lengths",
    "snapshot_bm25_corpus_stats",
    "snapshot_lexeme_stats",
    "operator_jobs",
)
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

_COLUMNS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "chunks": (
        ("embedding_provider", "VARCHAR(32)"),
        ("embedding_model", "VARCHAR(128)"),
        ("embedding_dimensions", "INTEGER"),
    ),
    "runs": (
        ("request_context", "JSONB"),
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
    "snapshot_chunks": (
        ("embedding", "vector(384)"),
        ("doc_id", "VARCHAR(32)"),
        ("registry", "VARCHAR(16)"),
        ("language", "VARCHAR(8)"),
        ("issuer", "VARCHAR(32)"),
        ("fiscal_year", "INTEGER"),
        ("form", "VARCHAR(32)"),
        ("item", "VARCHAR(8)"),
        ("kind", "VARCHAR(16)"),
        ("ordinal", "INTEGER"),
        ("body", "TEXT"),
        ("context_header", "TEXT"),
        ("index_text", "TEXT"),
        ("lexical_text", "TEXT"),
        ("start_char", "BIGINT"),
        ("end_char", "BIGINT"),
        ("citation", "TEXT"),
        (
            "content_tsv",
            "TSVECTOR GENERATED ALWAYS AS ("
            "CASE WHEN language = 'ko' "
            "THEN to_tsvector('simple', coalesce(lexical_text, index_text)) "
            "ELSE to_tsvector('english', index_text) END) STORED",
        ),
    ),
}
_CONSTRAINTS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "chunks": (
        (
            "ck_chunks_embedding_identity_complete",
            "(embedding IS NULL AND embedding_provider IS NULL AND embedding_model IS NULL "
            "AND embedding_dimensions IS NULL) OR (embedding IS NOT NULL AND "
            "btrim(embedding_provider) <> '' AND btrim(embedding_model) <> '' AND "
            "embedding_dimensions > 0)",
        ),
    ),
    "runs": (
        (
            "ck_runs_request_context_object",
            "request_context IS NULL OR jsonb_typeof(request_context) = 'object'",
        ),
        ("ck_runs_cached_input_tokens_nonnegative", "total_cached_input_tokens >= 0"),
        (
            "ck_runs_cache_write_input_tokens_nonnegative",
            "total_cache_write_input_tokens >= 0",
        ),
        ("ck_runs_reasoning_tokens_nonnegative", "total_reasoning_tokens >= 0"),
        ("ck_runs_cost_nonnegative", "total_estimated_cost_usd >= 0"),
    ),
    "traces": (
        (
            "ck_traces_node_v2",
            "node IN ('gate', 'route', 'retrieve', 'chat', 'grade', 'check', 'report')",
        ),
        ("ck_traces_cached_input_tokens_nonnegative", "cached_input_tokens >= 0"),
        (
            "ck_traces_cache_write_input_tokens_nonnegative",
            "cache_write_input_tokens >= 0",
        ),
        ("ck_traces_reasoning_tokens_nonnegative", "reasoning_tokens >= 0"),
    ),
    "snapshot_chunks": (
        ("ck_snapshot_chunks_ordinal_nonnegative", "ordinal >= 0"),
        ("ck_snapshot_chunks_kind", "kind IN ('text', 'table')"),
        ("ck_snapshot_chunks_language_format", "language ~ '^[a-z]{2}$'"),
        (
            "ck_snapshot_chunks_lexical_text_language",
            "(language = 'ko') = (lexical_text IS NOT NULL)",
        ),
        ("ck_snapshot_chunks_start_nonnegative", "start_char >= 0"),
        ("ck_snapshot_chunks_span_order", "end_char > start_char"),
        (
            "ck_snapshot_chunks_embedding_identity_complete",
            "(embedding IS NULL AND embedding_provider IS NULL AND embedding_model IS NULL "
            "AND embedding_dimensions IS NULL) OR (embedding IS NOT NULL AND "
            "btrim(embedding_provider) <> '' AND btrim(embedding_model) <> '' AND "
            "embedding_dimensions > 0)",
        ),
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
    missing_tables: tuple[str, ...] = ()


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
            for name, _expression in _CONSTRAINTS.get(table, ())
            if name not in live_constraints
            and not (
                table == "traces" and name == "ck_traces_node_v2" and "node" not in live_columns
            )
        )
    return tuple(sorted(missing_columns)), tuple(sorted(missing_constraints))


async def plan_schema_migrations(
    connection: AsyncConnection,
    *,
    schema: str = "public",
) -> MigrationPlan:
    """Inspect migration state without creating tables or changing data."""
    actual_schema = await _resolved_schema(connection, schema)
    columns_by_table, _constraints_by_table = await _schema_objects(connection, actual_schema)
    missing_columns, missing_constraints = await _missing_objects(
        connection,
        actual_schema,
    )
    experiment_applicable = {"documents", "eval_results"}.issubset(columns_by_table)
    missing_tables = (
        tuple(name for name in EXPERIMENT_TABLES if name not in columns_by_table)
        if experiment_applicable
        else ()
    )
    preparer = postgresql.dialect().identifier_preparer
    ledger = f"{preparer.quote_schema(actual_schema)}.{preparer.quote(LEDGER_TABLE)}"
    ledger_exists = bool(
        await connection.scalar(text("SELECT to_regclass(:ledger) IS NOT NULL"), {"ledger": ledger})
    )
    applied = False
    required_ids = [USAGE_MIGRATION_ID]
    if experiment_applicable:
        required_ids.extend((EXPERIMENT_MIGRATION_ID, SNAPSHOT_REVISION_MIGRATION_ID))
    if ledger_exists:
        applied_count = int(
            await connection.scalar(
                text(f"SELECT count(*) FROM {ledger} WHERE migration_id = ANY(:ids)"),
                {"ids": required_ids},
            )
            or 0
        )
        applied = applied_count == len(required_ids)
    return MigrationPlan(
        migration_id=required_ids[-1],
        applied=applied,
        needed=bool(missing_columns or missing_constraints or missing_tables),
        missing_columns=missing_columns,
        missing_constraints=missing_constraints,
        missing_tables=missing_tables,
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

    applied_ids = set(
        (await connection.execute(text(f"SELECT migration_id FROM {ledger}"))).scalars()
    )
    columns_by_table, _constraints_by_table = await _schema_objects(
        connection,
        actual_schema,
    )
    tables = set(columns_by_table)
    reset_embeddings = any(name.startswith("chunks.embedding_") for name in plan.missing_columns)
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

    if "chunks" in tables and reset_embeddings:
        chunks = f"{namespace}.{preparer.quote('chunks')}"
        await connection.execute(
            text(
                f"UPDATE {chunks} SET embedding = NULL, embedding_provider = NULL, "
                "embedding_model = NULL, embedding_dimensions = NULL"
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
        if table == "traces" and "node" in columns_by_table[table]:
            await connection.execute(
                text(f"ALTER TABLE {qualified} DROP CONSTRAINT IF EXISTS ck_traces_node")
            )
        for name, expression in constraints:
            missing_trace_node = (
                table == "traces"
                and name == "ck_traces_node_v2"
                and "node" not in columns_by_table[table]
            )
            if missing_trace_node:
                continue
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
    if plan.missing_tables:
        experiment_tables = [Base.metadata.tables[name] for name in EXPERIMENT_TABLES]
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection.execution_options(schema_translate_map={None: actual_schema}),
                tables=experiment_tables,
                checkfirst=True,
            )
        )
    available_tables = tables | set(plan.missing_tables)
    if {"documents", "chunks", "snapshot_documents", "snapshot_chunks"}.issubset(available_tables):
        documents = f"{namespace}.{preparer.quote('documents')}"
        chunks = f"{namespace}.{preparer.quote('chunks')}"
        snapshot_documents = f"{namespace}.{preparer.quote('snapshot_documents')}"
        snapshot_chunks = f"{namespace}.{preparer.quote('snapshot_chunks')}"
        snapshot_terms = f"{namespace}.{preparer.quote('snapshot_chunk_terms')}"
        snapshot_lengths = f"{namespace}.{preparer.quote('snapshot_chunk_lengths')}"
        chunk_terms = f"{namespace}.{preparer.quote('chunk_terms')}"
        chunk_lengths = f"{namespace}.{preparer.quote('chunk_lengths')}"
        source_chunk_columns = {
            "id",
            "doc_id",
            "language",
            "item",
            "kind",
            "ordinal",
            "body",
            "context_header",
            "index_text",
            "lexical_text",
            "start_char",
            "end_char",
            "citation",
        }
        source_document_columns = {"doc_id", "registry", "issuer", "fiscal_year", "form"}
        can_backfill_chunks = source_chunk_columns.issubset(
            columns_by_table.get("chunks", set())
        ) and source_document_columns.issubset(columns_by_table.get("documents", set()))
        snapshot_row_count = int(
            await connection.scalar(text(f"SELECT count(*) FROM {snapshot_chunks}")) or 0
        )
        if snapshot_row_count and not can_backfill_chunks:
            raise RuntimeError("existing snapshot rows require complete live chunk metadata")
        if can_backfill_chunks:
            await connection.execute(
                text(
                    f"UPDATE {snapshot_chunks} AS sc SET "
                    "doc_id = c.doc_id, registry = d.registry, language = c.language, "
                    "issuer = d.issuer, fiscal_year = d.fiscal_year, form = d.form, "
                    "item = c.item, kind = c.kind, ordinal = c.ordinal, body = c.body, "
                    "context_header = c.context_header, index_text = c.index_text, "
                    "lexical_text = c.lexical_text, start_char = c.start_char, "
                    "end_char = c.end_char, citation = c.citation "
                    f"FROM {chunks} AS c JOIN {documents} AS d ON d.doc_id = c.doc_id "
                    "WHERE sc.chunk_id = c.id"
                )
            )
        if "chunk_terms" in available_tables:
            await connection.execute(
                text(
                    f"INSERT INTO {snapshot_terms} (snapshot_id, chunk_id, lexeme, tf) "
                    f"SELECT sc.snapshot_id, ct.chunk_id, ct.lexeme, ct.tf "
                    f"FROM {snapshot_chunks} sc "
                    f"JOIN {chunk_terms} ct ON ct.chunk_id = sc.chunk_id "
                    "ON CONFLICT (snapshot_id, chunk_id, lexeme) DO NOTHING"
                )
            )
        if "chunk_lengths" in available_tables:
            await connection.execute(
                text(
                    f"INSERT INTO {snapshot_lengths} (snapshot_id, chunk_id, dl) "
                    f"SELECT sc.snapshot_id, cl.chunk_id, cl.dl FROM {snapshot_chunks} sc "
                    f"JOIN {chunk_lengths} cl ON cl.chunk_id = sc.chunk_id "
                    "ON CONFLICT (snapshot_id, chunk_id) DO NOTHING"
                )
            )
        required_snapshot_columns = (
            "doc_id",
            "registry",
            "language",
            "issuer",
            "fiscal_year",
            "form",
            "kind",
            "ordinal",
            "body",
            "context_header",
            "index_text",
            "start_char",
            "end_char",
            "citation",
        )
        for column in required_snapshot_columns:
            await connection.execute(
                text(
                    f"ALTER TABLE {snapshot_chunks} ALTER COLUMN "
                    f"{preparer.quote(column)} SET NOT NULL"
                )
            )
        await connection.execute(
            text(
                f"ALTER TABLE {snapshot_chunks} DROP CONSTRAINT IF EXISTS "
                "snapshot_chunks_chunk_id_fkey"
            )
        )
        await connection.execute(
            text(
                f"ALTER TABLE {snapshot_documents} DROP CONSTRAINT IF EXISTS "
                "snapshot_documents_doc_id_fkey"
            )
        )
        await connection.execute(
            text(
                "DO $migration$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
                f"WHERE conrelid = '{snapshot_chunks}'::regclass "
                "AND conname = 'uq_snapshot_doc_ordinal') THEN "
                f"ALTER TABLE {snapshot_chunks} ADD CONSTRAINT uq_snapshot_doc_ordinal "
                "UNIQUE (snapshot_id, doc_id, ordinal); "
                "END IF; END $migration$"
            )
        )
        await connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_snapshot_chunks_tsv ON {snapshot_chunks} "
                "USING gin (content_tsv)"
            )
        )
        await remove_snapshot_chunk_protection(connection, schema=actual_schema)
    await connection.execute(
        text(
            f"INSERT INTO {ledger} (migration_id) VALUES (:id) "
            "ON CONFLICT (migration_id) DO NOTHING"
        ),
        {"id": USAGE_MIGRATION_ID},
    )
    if {"documents", "eval_results"}.issubset(columns_by_table):
        await connection.execute(
            text(
                f"INSERT INTO {ledger} (migration_id) VALUES (:id) "
                "ON CONFLICT (migration_id) DO NOTHING"
            ),
            {"id": EXPERIMENT_MIGRATION_ID},
        )
        await connection.execute(
            text(
                f"INSERT INTO {ledger} (migration_id) VALUES (:id) "
                "ON CONFLICT (migration_id) DO NOTHING"
            ),
            {"id": SNAPSHOT_REVISION_MIGRATION_ID},
        )
    if schema == "public":
        await ensure_schema_compatibility(connection)
    applied_now = [
        migration_id
        for migration_id in (
            USAGE_MIGRATION_ID,
            EXPERIMENT_MIGRATION_ID,
            SNAPSHOT_REVISION_MIGRATION_ID,
        )
        if migration_id not in applied_ids
        and (
            migration_id == USAGE_MIGRATION_ID
            or {"documents", "eval_results"}.issubset(columns_by_table)
        )
    ]
    return tuple(applied_now)


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
