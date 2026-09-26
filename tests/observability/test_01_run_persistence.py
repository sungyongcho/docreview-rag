"""Live PostgreSQL storage of a workflow run: DDL, flush order, and constraints."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.api.system.usage import usage_summary
from app.db.models import Run, Trace
from app.observability.redaction import REDACTED
from tests.live_postgres import isolated_session_factory
from tests.observability.support import persist_run_report, run_report, step_trace

SECRET = "sk-live-test-secret-123456"


async def _exercise_live_postgres() -> None:
    """Commit one report, read it through new sessions, and reject invalid stored rows."""
    async with isolated_session_factory() as factory:
        report = run_report(
            system_prompt=f"Ground every claim. API_KEY={SECRET}",
            node_path=["retrieve", "grade"],
            request_context={
                "model_calls": [
                    {
                        "step": step,
                        "node": node,
                        "model": "gpt-4.1-mini",
                        "provider": "openai_responses",
                        "local": False,
                        "credential_slot": "OPENAI_API_KEY_LOCAL",
                        "attempts": attempts,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cached_input_tokens": 0,
                        "cache_write_input_tokens": 0,
                        "reasoning_tokens": 0,
                        "estimated_cost_usd": cost,
                        "elapsed_ms": 12.5,
                        "local_timings": [],
                        "projected_input_tokens": None,
                    }
                    for step, node, attempts, input_tokens, output_tokens, cost in (
                        (1, "grade", 1, 100, 20, "0.000072"),
                        (2, "check", 2, 40, 8, "0.0000288"),
                    )
                ]
            },
            steps=[
                step_trace(),
                step_trace(
                    step=2,
                    node="check",
                    input_tokens=40,
                    output_tokens=8,
                    estimated_cost_usd=Decimal("0.0000288"),
                    retries=1,
                    requests=2,
                ),
            ],
        )

        async with factory() as session:
            await persist_run_report(session, report, secret_values=[SECRET])
            await session.commit()

        async with factory() as session:
            stored_run = (await session.execute(select(Run.__table__))).mappings().one()
            stored_traces = (
                (await session.execute(select(Trace.__table__).order_by(Trace.step)))
                .mappings()
                .all()
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

            # Reuse accepted rows and invalidate one field, so unrelated constraints
            # cannot make a missing check appear to work.
            for invalid_values in (
                {"status": "unknown"},
                {"system_prompt": "   "},
                {"node_path": "retrieve"},
            ):
                with pytest.raises(IntegrityError) as failure:
                    async with session.begin_nested():
                        await session.execute(
                            insert(Run).values(
                                {**stored_run, "run_id": "run-rejected", **invalid_values}
                            ),
                        )
                assert getattr(failure.value.orig, "sqlstate", None) == "23514"

            trace_values = {key: value for key, value in stored_traces[0].items() if key != "id"}
            for invalid_values, sqlstate in (
                ({"node": "unknown"}, "23514"),
                ({"estimated_cost_usd": Decimal("-0.000001")}, "23514"),
                ({"step": 0}, "23514"),
                ({"step": 1}, "23505"),
            ):
                with pytest.raises(IntegrityError) as failure:
                    async with session.begin_nested():
                        await session.execute(
                            insert(Trace).values({**trace_values, "step": 3, **invalid_values}),
                        )
                assert getattr(failure.value.orig, "sqlstate", None) == sqlstate

        usage = await usage_summary(factory)
        assert usage.runs == 1
        assert usage.requests == 3
        assert usage.input_tokens == 140
        assert usage.estimated_cost_usd == Decimal("0.0001008")
        assert {model.model_name for model in usage.models} == {"gpt-4.1-mini"}
        assert {model.role for model in usage.models} == {"grade", "check"}
        assert sum(group.requests for group in usage.providers) == usage.requests


@pytest.mark.live_postgres
def test_live_postgres_stores_one_run_with_its_traces_and_rejects_invalid_rows():
    """Persist a run and its traces in one flush and enforce the table constraints."""
    asyncio.run(_exercise_live_postgres())
