"""Live PostgreSQL storage of a workflow run: DDL, flush order, and constraints."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import MetaData, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.runtime import RuntimeApiServices
from app.config import get_settings
from app.db.models import Base
from app.observability.persistence import REDACTED, persist_run_report
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.live_postgres import live_postgres_unavailable
from tests.observability.support import run_report, step_trace

SECRET = "sk-live-test-secret-123456"

REJECTED_ROWS = (
    # A blank prompt would leave the run without the provenance the trace contract promises.
    ("ck_runs_system_prompt_nonempty", "'   '", "'[\"retrieve\"]'::jsonb"),
    # node_path is read back as an ordered list, so a JSON scalar is not a usable path.
    ("ck_runs_node_path_array", "'Ground every claim.'", "'\"retrieve\"'::jsonb"),
)


async def _exercise_live_postgres(database_url: URL) -> tuple[bool, str]:
    """Create the run tables, persist one report, and read the stored rows back.

    Returns ``(False, detail)`` when the database is unavailable.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    try:
        try:
            async with asyncio.timeout(3):
                connection = await engine.connect()
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            return False, str(exc)

        temporary_metadata = MetaData()
        for table_name in ("runs", "traces", "operator_jobs"):
            Base.metadata.tables[table_name].to_metadata(temporary_metadata, schema="pg_temp")
        await connection.run_sync(
            lambda sync_connection: temporary_metadata.create_all(
                sync_connection,
                checkfirst=False,
            )
        )
        runs = temporary_metadata.tables["pg_temp.runs"]
        traces = temporary_metadata.tables["pg_temp.traces"]

        report = run_report(
            system_prompt=f"Ground every claim. API_KEY={SECRET}",
            node_path=["retrieve", "grade"],
            steps=[
                step_trace(),
                step_trace(
                    step=2,
                    node="check",
                    input_tokens=40,
                    output_tokens=8,
                    estimated_cost_usd=Decimal("0.0000288"),
                    retries=1,
                ),
            ],
        )

        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            await persist_run_report(session, report, secret_values=[SECRET])
            # Without this the queries below return identity-mapped objects carrying the
            # attributes just assigned, and never read a stored column.
            session.expire_all()

            stored_run = (await session.execute(select(runs))).mappings().one()
            stored_traces = (
                (await session.execute(select(traces).order_by(traces.c.step))).mappings().all()
            )

            assert stored_run["run_id"] == report.run_id
            assert stored_run["node_path"] == ["retrieve", "grade"]
            assert stored_run["report"] == {"label": "SUPPORTED"}
            assert stored_run["total_input_tokens"] == 140
            assert stored_run["total_requests"] == 3
            assert SECRET not in stored_run["system_prompt"]
            assert REDACTED in stored_run["system_prompt"]

            assert [row["step"] for row in stored_traces] == [1, 2]
            assert all(row["run_id"] == report.run_id for row in stored_traces)
            # NUMERIC keeps the provider's estimate exact instead of rounding it to a float.
            assert stored_traces[0]["estimated_cost_usd"] == Decimal("0.000072")
            assert stored_traces[1]["estimated_cost_usd"] == Decimal("0.0000288")

            for constraint, prompt, node_path in REJECTED_ROWS:
                with pytest.raises(IntegrityError, match=constraint):
                    async with session.begin_nested():
                        await session.execute(
                            text(
                                "INSERT INTO runs (run_id, status, iterations, total_requests,"
                                " total_input_tokens, total_output_tokens,"
                                " total_cached_input_tokens, total_cache_write_input_tokens,"
                                " total_reasoning_tokens, total_estimated_cost_usd,"
                                " total_time_seconds,"
                                " system_prompt, node_path, report) VALUES"
                                f" ('run-rejected', 'ok', 1, 1, 0, 0, 0, 0, 0, 0.0, 0.0, {prompt},"
                                f" {node_path}, NULL)"
                            )
                        )

            with pytest.raises(IntegrityError, match="ck_traces_step_positive"):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "INSERT INTO traces (run_id, step, node, model_name, api_url,"
                            " input_tokens, output_tokens, cached_input_tokens,"
                            " cache_write_input_tokens, reasoning_tokens, estimated_cost_usd,"
                            " request_time_ms,"
                            " llm_output, retries) VALUES"
                            f" ('{report.run_id}', 0, 'grade', 'gpt-5.6-terra',"
                            " 'https://api.test', 1, 1, 0, 0, 0, 0.0, 1.0, '{}', 0)"
                        )
                    )
        factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        usage = await RuntimeAdminApiServices(
            runtime=RuntimeApiServices(
                session_factory=factory, embedding_provider=DeterministicEmbeddingProvider()
            )
        ).usage()
        assert usage.runs == 1
        assert usage.requests == 3
        assert usage.input_tokens == 140
        assert usage.estimated_cost_usd == Decimal("0.0001008")
        assert {model.model_name for model in usage.models} == {"gpt-4.1-mini"}
        assert {model.role for model in usage.models} == {"grade", "check"}
        assert sum(group.requests for group in usage.providers) == usage.requests
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


@pytest.mark.live_postgres
def test_live_postgres_stores_one_run_with_its_traces_and_rejects_invalid_rows():
    """Persist a run and its traces in one flush and enforce the table constraints."""
    database_url = make_url(get_settings().database_url)
    reachable, detail = asyncio.run(_exercise_live_postgres(database_url))
    if not reachable:
        live_postgres_unavailable(detail)
