"""Decomposition comparison: category slices, paired artifacts, and deltas."""

import asyncio
from datetime import datetime
import json
from types import SimpleNamespace

import pytest

from app.evals.decomposition import category_metrics, run_decomposition_comparison
from app.evals.scoring import CaseScore
from tests.evals.support import EVALUATION_RECORDED_AT, absent_case, positive_case, relevant_hit


def test_category_metrics_slices_scored_cases_only():
    """Report per-category metrics over scored cases, omitting unscored ones."""

    def case(category, recall, rank, index):
        """Build one evaluated case, scored or left unscored."""
        score = None
        if recall is not None:
            score = CaseScore(
                case_id=f"m3c-{category[:2]}-{index}",
                k=5,
                gold_span_count=2,
                matched_gold_count=int(recall * 2),
                recall_at_k=recall,
                hit_at_k=float(recall > 0),
                reciprocal_rank=1.0 / rank,
                first_relevant_rank=rank,
            )
        return SimpleNamespace(golden=SimpleNamespace(category=category), score=score)

    evaluation = SimpleNamespace(
        cases=(
            case("multi_hop", 0.5, 2, 1),
            case("multi_hop", 1.0, 1, 2),
            case("simple_lookup", 1.0, 1, 1),
            case("absent", None, 1, 1),
        )
    )

    metrics = category_metrics(evaluation)

    assert set(metrics) == {"multi_hop", "simple_lookup"}
    assert metrics["multi_hop"]["scored_case_count"] == 2.0
    assert metrics["multi_hop"]["recall_at_k"] == pytest.approx(0.75)
    assert metrics["multi_hop"]["mrr"] == pytest.approx(0.75)
    assert metrics["simple_lookup"]["recall_at_k"] == pytest.approx(1.0)


def test_comparison_writes_paired_artifacts_and_signed_category_deltas(tmp_path):
    """Run both arms through the real harness and difference their categories."""
    cases = (positive_case(), absent_case())

    async def covering(question, k):
        """Return the hit that covers the positive case's gold span."""
        return (relevant_hit(),)

    async def empty(question, k):
        """Return no hits, so the decomposed arm scores zero."""
        return ()

    result = asyncio.run(
        run_decomposition_comparison(
            cases,
            baseline_retriever=covering,
            decomposed_retriever=empty,
            baseline_config={"strategy": "single_query"},
            decomposed_config={"strategy": "decomposed"},
            suite="m9-decomposition-v1",
            artifact_dir=tmp_path,
            k=5,
            recorded_at=EVALUATION_RECORDED_AT,
        )
    )

    assert result["baseline"]["categories"]["simple_lookup"]["recall_at_k"] == 1.0
    assert result["decomposed"]["categories"]["simple_lookup"]["recall_at_k"] == 0.0
    assert result["category_deltas"]["simple_lookup"]["recall_at_k"] == pytest.approx(-1.0)
    for label in ("baseline", "decomposed"):
        path = tmp_path / f"20260101T000000Z-m9-decomposition-v1-decomposition-{label}.json"
        assert result["artifacts"][label] == str(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["suite"] == "m9-decomposition-v1"


def test_comparison_refuses_to_overwrite_and_rejects_naive_timestamps(tmp_path):
    """Fail loudly on an existing artifact, and on a naive timestamp before any retrieval."""
    cases = (positive_case(), absent_case())
    retrievals = []

    async def counting(question, k):
        """Count every retrieval so a rejected run provably ran none."""
        retrievals.append(question)
        return (relevant_hit(),)

    shared = {
        "baseline_retriever": counting,
        "decomposed_retriever": counting,
        "baseline_config": {"strategy": "single_query"},
        "decomposed_config": {"strategy": "decomposed"},
        "suite": "m9-decomposition-v1",
        "artifact_dir": tmp_path,
    }

    naive = datetime(2026, 1, 1)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(run_decomposition_comparison(cases, recorded_at=naive, **shared))
    assert retrievals == []

    asyncio.run(run_decomposition_comparison(cases, recorded_at=EVALUATION_RECORDED_AT, **shared))
    with pytest.raises(FileExistsError):
        asyncio.run(
            run_decomposition_comparison(cases, recorded_at=EVALUATION_RECORDED_AT, **shared)
        )
