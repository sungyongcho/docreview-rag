"""Latency aggregation, budget derivation, and budget artifact evidence."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.evals.execution.measurement import (
    BUDGET_ARTIFACT_SCHEMA_VERSION,
    QUERY_BUDGET_COUNT,
    QueryBudgetArm,
    SharedPreparationMeasurement,
    assess_indexing_budget,
    budget_artifact_payload,
    budgets_passed,
    indexing_budget_payload,
    measure_query_budget,
)
from app.evals.execution.models import EvaluationRetrieval


def _stepping_clock(step_ns):
    """Build a monotonic clock that advances by a fixed step on every sample."""
    tick = -step_ns

    def clock():
        nonlocal tick
        tick += step_ns
        return tick

    return clock


def test_200_query_budget_measures_exact_boundary_without_storing_fake_results():
    """Measure every repeated query, including the first, against the exact boundary."""
    calls = []

    async def retriever(query, k):
        calls.append((query, k))
        return EvaluationRetrieval(hits=())

    result = asyncio.run(
        measure_query_budget(
            ["q1", "q2"],
            retriever,
            k=5,
            query_count=QUERY_BUDGET_COUNT,
            clock=_stepping_clock(450_000_000),
        )
    )

    assert len(calls) == 200
    assert calls[:3] == [("q1", 5), ("q2", 5), ("q1", 5)]
    assert result.total_seconds == 90.0
    assert result.passed
    assert result.latency.p95_ms == 450.0


def test_query_budget_fails_only_after_the_explicit_limit():
    """Fail the budget only once total time passes the declared limit."""

    async def retriever(_query, _k):
        return EvaluationRetrieval(hits=())

    result = asyncio.run(
        measure_query_budget(
            ["q"],
            retriever,
            query_count=200,
            clock=_stepping_clock(450_000_001),
        )
    )

    assert result.total_seconds > 90.0
    assert not result.passed


@pytest.mark.parametrize("k", [0, True])
def test_query_budget_rejects_a_hit_count_that_is_not_a_positive_integer(k):
    """Reject a boolean or nonpositive ``k`` before measuring anything."""

    async def retriever(_query, _k):
        return EvaluationRetrieval(hits=())

    with pytest.raises(ValueError, match="k must be a positive integer"):
        asyncio.run(measure_query_budget(["q"], retriever, k=k, query_count=1))


@pytest.mark.parametrize(
    "changes",
    [
        {"operation": "  "},
        {"document_count": 0},
        {"total_seconds": -0.1},
        {"total_seconds": float("inf")},
    ],
)
def test_shared_preparation_rejects_evidence_it_cannot_charge_to_an_arm(changes):
    """Validate shared preparation as strictly as the arm evidence it feeds."""
    values = {
        "operation": "manifest-load-and-parse",
        "document_count": 20,
        "total_seconds": 15.0,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        SharedPreparationMeasurement(**values)


def _shared():
    """Build the parse-once measurement shared by the multi-target arms."""
    return SharedPreparationMeasurement(
        operation="manifest-load-and-parse",
        document_count=20,
        total_seconds=15.0,
    )


def _arms():
    """Build two indexed arms that share one preparation phase."""
    return (
        assess_indexing_budget(
            target_tokens=500,
            document_count=20,
            chunk_count=12_984,
            embedding_provider="deterministic",
            target_phase_seconds=25.0,
            shared_preparation_seconds=15.0,
        ),
        assess_indexing_budget(
            target_tokens=1_200,
            document_count=20,
            chunk_count=9_172,
            embedding_provider="deterministic",
            target_phase_seconds=20.0,
            shared_preparation_seconds=15.0,
        ),
    )


def test_indexing_payload_separates_shared_and_target_work():
    """Charge shared preparation to every arm while counting it once overall."""
    payload = indexing_budget_payload(_shared(), _arms())

    assert payload["shared_preparation"] == {
        "operation": "manifest-load-and-parse",
        "document_count": 20,
        "total_seconds": 15.0,
    }
    assert [arm["target_phase_seconds"] for arm in payload["arms"]] == [25.0, 20.0]
    assert [arm["derived_standalone_seconds"] for arm in payload["arms"]] == [40.0, 35.0]
    assert payload["measured_multi_target_work_seconds"] == 60.0


def test_budget_artifact_records_the_arm_the_query_budget_ran_on():
    """Attribute the repeated-query p95 to one corpus and one retrieval lane."""

    async def retriever(_query, _k):
        return EvaluationRetrieval(hits=())

    query_budget = asyncio.run(
        measure_query_budget(["q"], retriever, query_count=4, clock=_stepping_clock(1_000_000))
    )
    payload = budget_artifact_payload(
        recorded_at=datetime(2026, 8, 12, 15, tzinfo=UTC),
        embedding_provider="deterministic",
        shared_preparation=_shared(),
        indexing=_arms(),
        query_budget=query_budget,
        query_budget_arm=QueryBudgetArm(
            target_tokens=1_200,
            strategy="hybrid",
            lexical_ranker="bm25",
            bm25=(1.2, 0.75, "lucene"),
            k=5,
            candidate_k=20,
            rrf_k=60,
        ),
    )

    assert payload["schema_version"] == BUDGET_ARTIFACT_SCHEMA_VERSION
    assert payload["recorded_at"] == "2026-08-12T15:00:00Z"
    assert payload["query_budget"]["arm"] == {
        "target_tokens": 1_200,
        "strategy": "hybrid",
        "lexical_ranker": "bm25",
        "bm25": {"k1": 1.2, "b": 0.75, "idf": "lucene"},
        "k": 5,
        "candidate_k": 20,
        "rrf_k": 60,
    }
    assert payload["query_budget"]["passed"] is True
    assert payload["query_budget"]["latency"]["query_count"] == 4
    assert payload["indexing"]["measured_multi_target_work_seconds"] == 60.0


def test_budgets_pass_only_when_every_measured_limit_holds():
    """Fail the run when any indexing arm or the repeated-query budget is exceeded."""

    async def retriever(_query, _k):
        return EvaluationRetrieval(hits=())

    fast = asyncio.run(
        measure_query_budget(["q"], retriever, query_count=4, clock=_stepping_clock(1_000_000))
    )
    slow = asyncio.run(
        measure_query_budget(["q"], retriever, query_count=4, clock=_stepping_clock(1_000_000_000))
    )
    over_budget = assess_indexing_budget(
        target_tokens=500,
        document_count=20,
        chunk_count=10,
        embedding_provider="deterministic",
        target_phase_seconds=301.0,
    )

    assert budgets_passed(_arms(), fast) is True
    assert budgets_passed(_arms(), slow) is False
    assert budgets_passed((*_arms(), over_budget), fast) is False
