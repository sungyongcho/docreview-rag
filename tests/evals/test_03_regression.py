"""M3 regression comparisons and optional PostgreSQL persistence proof."""

import asyncio
from datetime import UTC, datetime, timedelta
import importlib
import os

import pytest
from sqlalchemy import CheckConstraint, DateTime, Table, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import EvalResult
from tests.support import need

REGRESSION_MODULE_NAME = os.getenv("EVAL_REGRESSION_MODULE", "app.evals.regression")
R = importlib.import_module(REGRESSION_MODULE_NAME)


def metrics(**changes):
    values = {
        "recall_at_k": 0.8,
        "hit_rate_at_k": 0.75,
        "mrr": 0.6,
    }
    values.update(changes)
    return values


def test_eval_result_schema_persists_complete_run_provenance():
    table = EvalResult.__table__
    assert isinstance(table, Table)
    columns = table.columns

    assert set(columns.keys()) == {
        "id",
        "suite",
        "config",
        "metrics",
        "raw_artifact_path",
        "created_at",
    }
    assert columns.id.primary_key
    assert columns.created_at.server_default is not None
    created_at_type = columns.created_at.type
    assert isinstance(created_at_type, DateTime)
    assert created_at_type.timezone is True
    assert all(not columns[name].nullable for name in columns.keys())
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_eval_results_suite_nonempty",
        "ck_eval_results_config_object",
        "ck_eval_results_metrics_object",
        "ck_eval_results_raw_artifact_path_nonempty",
    } <= checks


def test_comparison_is_typed_ordered_and_higher_is_better():
    need(
        R,
        "BaselineComparison",
        "HIGHER_IS_BETTER_METRICS",
        "compare_against_baseline",
    )
    result = R.compare_against_baseline(
        metrics(),
        metrics(recall_at_k=0.81, hit_rate_at_k=0.74, mrr=0.6),
    )

    assert tuple(item.metric for item in result.metrics) == R.HIGHER_IS_BETTER_METRICS
    assert result.metrics[0].delta == pytest.approx(0.01)
    assert result.metrics[1].delta == pytest.approx(-0.01)
    assert result.regressed_metrics == ("hit_rate_at_k",)
    assert not result.passed


def test_configurable_tolerance_includes_the_exact_drop_boundary():
    need(R, "RegressionTolerances", "compare_against_baseline")
    limits = R.RegressionTolerances(recall_at_k=0.01, hit_rate_at_k=0.02, mrr=0.0)

    boundary = R.compare_against_baseline(
        metrics(),
        metrics(recall_at_k=0.79, hit_rate_at_k=0.73),
        tolerances=limits,
    )
    exceeded = R.compare_against_baseline(
        metrics(),
        metrics(recall_at_k=0.789, hit_rate_at_k=0.73),
        tolerances=limits,
    )

    assert boundary.passed
    assert exceeded.regressed_metrics == ("recall_at_k",)


def test_tolerances_accept_a_partial_metric_mapping():
    need(R, "compare_against_baseline")
    result = R.compare_against_baseline(
        metrics(),
        metrics(mrr=0.59),
        tolerances={"mrr": 0.01},
    )

    assert result.passed


def test_tolerances_reject_metrics_without_an_explicit_direction():
    need(R, "compare_against_baseline")
    with pytest.raises(ValueError, match="unsupported metric tolerances: latency_ms"):
        R.compare_against_baseline(metrics(), metrics(), tolerances={"latency_ms": 10.0})


def test_only_explicit_quality_metrics_are_compared():
    need(R, "compare_against_baseline")
    baseline = metrics(latency_ms=20.0)
    current = metrics(latency_ms=200.0)

    result = R.compare_against_baseline(baseline, current)

    assert result.passed
    assert all(item.metric != "latency_ms" for item in result.metrics)


@pytest.mark.parametrize(
    ("baseline", "current", "message"),
    [
        ({"recall_at_k": 0.8}, metrics(), "baseline metrics are missing"),
        (metrics(), metrics(mrr=float("nan")), "current mrr"),
        (metrics(), metrics(recall_at_k=1.1), "current recall_at_k"),
        (metrics(), metrics(hit_rate_at_k=True), "current hit_rate_at_k"),
    ],
)
def test_comparison_rejects_missing_nonfinite_or_unbounded_metrics(baseline, current, message):
    need(R, "compare_against_baseline")
    with pytest.raises(ValueError, match=message):
        R.compare_against_baseline(baseline, current)


@pytest.mark.parametrize("value", [-0.01, float("inf"), True])
def test_tolerances_must_be_finite_nonnegative_numbers(value):
    need(R, "RegressionTolerances")
    with pytest.raises(ValueError, match="finite nonnegative"):
        R.RegressionTolerances(mrr=value)


def test_config_serialization_is_canonical_and_does_not_mutate_input():
    need(R, "serialize_config")
    left = {"retriever": {"weights": {"vector": 0.6, "lexical": 0.4}}, "k": 5}
    right = {"k": 5, "retriever": {"weights": {"lexical": 0.4, "vector": 0.6}}}
    original = repr(left)

    serialized = R.serialize_config(left)

    assert serialized == R.serialize_config(right)
    assert serialized == ('{"k":5,"retriever":{"weights":{"lexical":0.4,"vector":0.6}}}')
    assert repr(left) == original


@pytest.mark.parametrize(
    "config",
    [
        {1: "not-a-string-key"},
        {"retriever": {1: "not-a-string-key"}},
        {"threshold": float("nan")},
        {"provider": object()},
    ],
)
def test_config_serialization_rejects_ambiguous_or_non_json_values(config):
    need(R, "serialize_config")
    with pytest.raises(ValueError, match="config"):
        R.serialize_config(config)


async def _exercise_live_postgres(database_url):
    engine = create_async_engine(database_url, poolclass=NullPool)
    connection = None
    try:
        try:
            async with asyncio.timeout(3):
                connection = await engine.connect()
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            return False, str(exc)

        await connection.execute(
            text(
                """
                CREATE TEMP TABLE eval_results (
                    id bigserial PRIMARY KEY,
                    suite varchar(128) NOT NULL,
                    config jsonb NOT NULL,
                    metrics jsonb NOT NULL,
                    raw_artifact_path text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        started = datetime(2026, 8, 12, 12, tzinfo=UTC)
        config = {"provider": "deterministic", "retriever": {"k": 5, "kind": "hybrid"}}

        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            first = await R.persist_eval_result(
                session,
                suite="retrieval-v1",
                config=config,
                metrics=metrics(),
                raw_artifact_path="data/eval_runs/first.json",
                created_at=started,
            )
            await R.persist_eval_result(
                session,
                suite="retrieval-v1",
                config={"retriever": {"kind": "vector", "k": 5}},
                metrics=metrics(mrr=0.7),
                raw_artifact_path="data/eval_runs/not-comparable.json",
                created_at=started + timedelta(minutes=2),
            )
            latest = await R.persist_eval_result(
                session,
                suite="retrieval-v1",
                config={"retriever": {"kind": "hybrid", "k": 5}, "provider": "deterministic"},
                metrics=metrics(mrr=0.61),
                raw_artifact_path="data/eval_runs/latest.json",
                created_at=started + timedelta(minutes=1),
            )
            baseline = await R.latest_comparable_baseline(
                session,
                suite="retrieval-v1",
                config=config,
            )

        assert first.id is not None
        assert latest.id is not None
        assert baseline is not None
        assert baseline.id == latest.id
        assert baseline.metrics["mrr"] == 0.61
        assert baseline.raw_artifact_path == "data/eval_runs/latest.json"
        assert baseline.created_at == started + timedelta(minutes=1)
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


def test_live_postgres_persists_and_retrieves_latest_comparable_baseline():
    need(R, "latest_comparable_baseline", "persist_eval_result")
    database_url = make_url(get_settings().database_url)
    if database_url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("PostgreSQL integration tests require a loopback database URL")

    reachable, detail = asyncio.run(_exercise_live_postgres(database_url.set(host="127.0.0.1")))
    if not reachable:
        pytest.skip(f"PostgreSQL is unavailable: {detail}")
