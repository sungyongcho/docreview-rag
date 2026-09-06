"""Golden-suite evaluation, raw artifacts, and persistence evidence."""

import asyncio
from datetime import UTC, datetime
import json

import pytest

from app.evals.regression import BaselineComparison, MetricComparison
from app.evals.retrieval_eval import (
    PersistedEvaluation,
    evaluate_retriever,
    write_evaluation_artifact,
)
from tests.evals.support import SOURCE_SHA256, absent_case, positive_case, relevant_hit


def _evaluation():
    """Evaluate one absent and one positive case against a fixed clock."""

    async def retriever(_query, _k):
        """Return one relevant hit for the deterministic evaluation."""
        return [relevant_hit()]

    clock_values = iter((0, 1_000_000, 2_000_000, 5_000_000))
    return asyncio.run(
        evaluate_retriever(
            [absent_case(), positive_case()],
            retriever,
            suite="m3-runner-test",
            config={"provider": "deterministic", "k": 5},
            clock=lambda: next(clock_values),
            recorded_at=datetime(2026, 8, 12, 15, tzinfo=UTC),
        )
    )


def test_runner_records_all_cases_but_scores_only_source_bearing_positives():
    """Record every case in id order while scoring only the source-bearing ones."""
    evaluation = _evaluation()

    assert [case.golden.id for case in evaluation.cases] == ["m3c-01", "m3c-02"]
    assert evaluation.score.case_count == 1
    assert evaluation.score.recall_at_k == 1.0
    assert evaluation.score.hit_rate_at_k == 1.0
    assert evaluation.score.mrr == 1.0
    assert evaluation.cases[0].score is not None
    assert evaluation.cases[1].score is None
    assert evaluation.provenance.total_cases == 2
    assert evaluation.provenance.scored_positive_cases == 1
    assert evaluation.provenance.unscored_absent_cases == 1
    assert evaluation.provenance.curation_status == "agent-curated"
    assert evaluation.provenance.approval_status == "pending-author-approval"
    assert evaluation.provenance.human_verified is False
    assert evaluation.latency.total_ms == 4.0
    assert evaluation.latency.mean_ms == 2.0
    assert evaluation.latency.p95_ms == 3.0


def test_runner_reports_each_completed_case_in_canonical_order():
    """Publish absolute case progress without coupling evaluation to a terminal."""

    async def retriever(_query, _k):
        """Return one relevant hit while case progress is recorded."""
        return [relevant_hit()]

    updates = []
    asyncio.run(
        evaluate_retriever(
            [absent_case(), positive_case()],
            retriever,
            suite="m3-runner-test",
            config={"provider": "deterministic", "k": 5},
            on_progress=updates.append,
        )
    )

    assert [(update.current, update.total, update.message) for update in updates] == [
        (1, 2, "m3c-01"),
        (2, 2, "m3c-02"),
    ]


def test_raw_artifact_preserves_hits_spans_latency_and_review_provenance(tmp_path):
    """Preserve hits, source spans, latency, and review provenance in the artifact."""
    path = write_evaluation_artifact(tmp_path / "raw.json", _evaluation())
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["recorded_at"] == "2026-08-12T15:00:00Z"
    assert payload["golden_provenance"]["human_verified"] is False
    assert payload["golden_provenance"]["approval_status"] == "pending-author-approval"
    assert payload["cases"][0]["hits"][0]["source_sha256"] == SOURCE_SHA256
    assert payload["cases"][0]["hits"][0]["start_char"] == 90
    assert payload["cases"][0]["latency_ms"] == 1.0
    assert payload["cases"][1]["score"] is None


@pytest.mark.parametrize(
    "cases",
    [[], [absent_case()]],
)
def test_runner_rejects_empty_or_absent_only_scoring_suites(cases):
    """Reject a suite with nothing to score rather than reporting empty metrics."""

    async def retriever(_query, _k):
        """Return no hits for an invalid scoring suite."""
        return []

    with pytest.raises(ValueError):
        asyncio.run(
            evaluate_retriever(
                cases,
                retriever,
                suite="m3-test",
                config={},
            )
        )


def test_persisted_evaluation_reports_the_regression_verdict_it_justifies():
    """Carry the gating verdict into serialized evidence instead of dropping it."""
    regressed = MetricComparison(
        metric="recall_at_k",
        baseline=0.9,
        current=0.4,
        delta=-0.5,
        tolerance=0.0,
        regressed=True,
    )
    persisted = PersistedEvaluation(
        result_id=7,
        baseline_id=6,
        comparison=BaselineComparison(metrics=(regressed,)),
    )

    payload = persisted.to_dict()

    assert persisted.passed is False
    assert payload["passed"] is False
    assert payload["comparison"]["regressed_metrics"] == ["recall_at_k"]
    assert payload["comparison"]["metrics"][0]["delta"] == -0.5


def test_a_run_without_a_comparable_baseline_passes():
    """Treat a first run as passing: there is no baseline to regress against."""
    persisted = PersistedEvaluation(result_id=1, baseline_id=None, comparison=None)

    assert persisted.passed is True
    assert persisted.to_dict()["comparison"] is None
