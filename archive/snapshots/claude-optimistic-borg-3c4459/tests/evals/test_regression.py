"""Metric regression comparison, config canonicalization, and run persistence."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import MetaData, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Base
from app.evals.regression import (
    HIGHER_IS_BETTER_METRICS,
    RegressionTolerances,
    compare_against_baseline,
    latest_comparable_baseline,
    persist_eval_result,
    serialize_config,
)
from tests.live_postgres import live_postgres_unavailable

SCORING = {"k": 5, "coverage_threshold": 0.5}


def metrics(**changes: float) -> dict[str, float]:
    """Build one complete gated-metric mapping with optional replacements."""
    values: dict[str, float] = {
        "recall_at_k": 0.8,
        "hit_rate_at_k": 0.75,
        "mrr": 0.6,
    }
    values.update(changes)
    return values


def test_comparison_is_typed_ordered_and_higher_is_better():
    """Compare gated metrics in declaration order and flag only the drop."""
    result = compare_against_baseline(
        metrics(),
        metrics(recall_at_k=0.81, hit_rate_at_k=0.74, mrr=0.6),
    )

    assert tuple(item.metric for item in result.metrics) == HIGHER_IS_BETTER_METRICS
    assert result.metrics[0].delta == pytest.approx(0.01)
    assert result.metrics[1].delta == pytest.approx(-0.01)
    assert result.regressed_metrics == ("hit_rate_at_k",)
    assert not result.passed


def test_configurable_tolerance_includes_the_exact_drop_boundary():
    """Accept a drop exactly equal to its tolerance and reject the next step."""
    limits = RegressionTolerances(recall_at_k=0.01, hit_rate_at_k=0.02, mrr=0.0)

    boundary = compare_against_baseline(
        metrics(),
        metrics(recall_at_k=0.79, hit_rate_at_k=0.73),
        tolerances=limits,
    )
    exceeded = compare_against_baseline(
        metrics(),
        metrics(recall_at_k=0.789, hit_rate_at_k=0.73),
        tolerances=limits,
    )

    assert boundary.passed
    assert exceeded.regressed_metrics == ("recall_at_k",)


def test_tolerances_accept_a_partial_metric_mapping():
    """Apply a mapping that names only some gated metrics."""
    result = compare_against_baseline(metrics(), metrics(mrr=0.59), tolerances={"mrr": 0.01})

    assert result.passed


def test_tolerances_reject_metrics_without_an_explicit_direction():
    """Reject a tolerance for a metric with no declared better direction."""
    with pytest.raises(ValueError, match="unsupported metric tolerances: latency_ms"):
        compare_against_baseline(metrics(), metrics(), tolerances={"latency_ms": 10.0})


def test_only_explicit_quality_metrics_are_compared():
    """Ignore extra metrics instead of guessing their better direction."""
    result = compare_against_baseline(metrics(latency_ms=20.0), metrics(latency_ms=200.0))

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
    """Reject a missing, non-finite, out-of-range, or boolean metric value."""
    with pytest.raises(ValueError, match=message):
        compare_against_baseline(baseline, current)


@pytest.mark.parametrize("value", [-0.01, float("inf"), True])
def test_tolerances_must_be_finite_nonnegative_numbers(value):
    """Reject a negative, non-finite, or boolean tolerance."""
    with pytest.raises(ValueError, match="finite nonnegative"):
        RegressionTolerances(mrr=value)


def test_config_serialization_is_canonical_and_does_not_mutate_input():
    """Serialize equal configs identically without touching the caller's mapping."""
    left = {"retriever": {"weights": {"vector": 0.6, "lexical": 0.4}}, "k": 5}
    right = {"k": 5, "retriever": {"weights": {"lexical": 0.4, "vector": 0.6}}}
    original = repr(left)

    serialized = serialize_config(left)

    assert serialized == serialize_config(right)
    assert serialized == '{"k":5,"retriever":{"weights":{"lexical":0.4,"vector":0.6}}}'
    assert repr(left) == original


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({1: "not-a-string-key"}, "config keys must be strings"),
        ({"retriever": {1: "not-a-string-key"}}, "config keys must be strings"),
        ({"threshold": float("nan")}, "only finite JSON values"),
        ({"provider": object()}, "only finite JSON values"),
    ],
)
def test_config_serialization_rejects_ambiguous_or_non_json_values(config, message):
    """Reject configs JSON cannot represent comparably, naming the actual defect."""
    with pytest.raises(ValueError, match=message):
        serialize_config(config)


@pytest.mark.parametrize(
    ("run_metrics", "message"),
    [
        ({"latency_ms": 42.0}, "run metrics are missing recall_at_k"),
        ({}, "run metrics are missing recall_at_k"),
        (metrics(mrr=1.5), "run mrr"),
    ],
)
def test_persisted_runs_must_carry_metrics_the_gate_can_read(run_metrics, message):
    """Reject at write time the metric sets a later comparison could not gate on."""
    with pytest.raises(ValueError, match=message):
        asyncio.run(
            persist_eval_result(
                cast(AsyncSession, object()),
                suite="retrieval-v1",
                config={"k": 5},
                metrics=run_metrics,
                raw_artifact_path="data/eval_runs/rejected.json",
                scoring=SCORING,
            )
        )


def test_a_config_cannot_shadow_the_reserved_scoring_stamp():
    """Reject a config that would overwrite the scoring settings defining comparability."""
    with pytest.raises(ValueError, match="reserved 'scoring' key"):
        asyncio.run(
            persist_eval_result(
                cast(AsyncSession, object()),
                suite="retrieval-v1",
                config={"scoring": {"k": 99}},
                metrics=metrics(),
                raw_artifact_path="data/eval_runs/rejected.json",
                scoring=SCORING,
            )
        )


async def _exercise_live_postgres(database_url: URL) -> tuple[bool, str]:
    """Persist three runs in a model-derived temporary table and read the baseline back.

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
        Base.metadata.tables["eval_results"].to_metadata(temporary_metadata, schema="pg_temp")
        await connection.run_sync(
            lambda sync_connection: temporary_metadata.create_all(
                sync_connection,
                checkfirst=False,
            )
        )

        started = datetime(2026, 8, 12, 12, tzinfo=UTC)
        config: dict[str, Any] = {
            "provider": "deterministic",
            "retriever": {"k": 5, "kind": "hybrid"},
        }

        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            first = await persist_eval_result(
                session,
                suite="retrieval-v1",
                config=config,
                metrics=metrics(),
                raw_artifact_path="data/eval_runs/first.json",
                scoring=SCORING,
                created_at=started,
            )
            await persist_eval_result(
                session,
                suite="retrieval-v1",
                config={"retriever": {"kind": "vector", "k": 5}},
                metrics=metrics(mrr=0.7),
                raw_artifact_path="data/eval_runs/not-comparable.json",
                scoring=SCORING,
                created_at=started + timedelta(minutes=2),
            )
            latest = await persist_eval_result(
                session,
                suite="retrieval-v1",
                config={"retriever": {"kind": "hybrid", "k": 5}, "provider": "deterministic"},
                metrics=metrics(mrr=0.61, latency_ms=12.5),
                raw_artifact_path="data/eval_runs/latest.json",
                scoring=SCORING,
                created_at=started + timedelta(minutes=1),
            )
            first_id, latest_id = first.id, latest.id
            # Without this the query below returns the identity-mapped objects with the
            # attributes this test just assigned, and never reads a stored column.
            session.expire_all()

            baseline = await latest_comparable_baseline(
                session,
                suite="retrieval-v1",
                config=config,
                scoring=SCORING,
            )
            other_cutoff = await latest_comparable_baseline(
                session,
                suite="retrieval-v1",
                config=config,
                scoring={**SCORING, "k": 20},
            )

            assert first_id is not None
            assert baseline is not None
            # Metrics measured at another cutoff are not a baseline for this run.
            assert other_cutoff is None
            # The newer run with a different config is not comparable, so the older
            # run whose canonical config matches wins the baseline.
            assert baseline.id == latest_id
            assert baseline.config == {
                "provider": "deterministic",
                "retriever": {"k": 5, "kind": "hybrid"},
                "scoring": {"k": 5, "coverage_threshold": 0.5},
            }
            assert baseline.metrics["mrr"] == 0.61
            assert baseline.metrics["latency_ms"] == 12.5
            assert baseline.raw_artifact_path == "data/eval_runs/latest.json"
            assert baseline.created_at == started + timedelta(minutes=1)
        return True, ""
    finally:
        if connection is not None:
            await connection.close()
        await engine.dispose()


@pytest.mark.live_postgres
def test_live_postgres_persists_and_retrieves_latest_comparable_baseline():
    """Persist evaluation runs and read back the newest comparable baseline."""
    database_url = make_url(get_settings().database_url)
    reachable, detail = asyncio.run(_exercise_live_postgres(database_url))
    if not reachable:
        live_postgres_unavailable(detail)
