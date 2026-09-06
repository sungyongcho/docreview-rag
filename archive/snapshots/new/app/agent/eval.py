"""Category-sliced comparison of single-query and decomposed retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals.retrieval_eval import (
    RetrievalEvaluation,
    Retriever,
    evaluate_retriever,
    write_evaluation_artifact,
)
from app.evals.types import GoldenCase


def category_metrics(evaluation: RetrievalEvaluation) -> dict[str, dict[str, float]]:
    """Return macro retrieval metrics per golden category, scored cases only.

    The suite-level score hides exactly the split this module exists to show:
    a decomposition change should move ``multi_hop`` without touching
    ``simple_lookup``. Absent cases stay excluded, mirroring M3's scoring rule.
    """
    grouped: dict[str, list[Any]] = {}
    for case in evaluation.cases:
        if case.score is None:
            continue
        grouped.setdefault(case.golden.category, []).append(case.score)
    metrics: dict[str, dict[str, float]] = {}
    for category in sorted(grouped):
        scores = grouped[category]
        count = len(scores)
        metrics[category] = {
            "scored_case_count": float(count),
            "recall_at_k": sum(score.recall_at_k for score in scores) / count,
            "hit_rate_at_k": sum(score.hit_at_k for score in scores) / count,
            "mrr": sum(score.reciprocal_rank for score in scores) / count,
        }
    return metrics


def _arm_payload(evaluation: RetrievalEvaluation) -> dict[str, Any]:
    return {
        "metrics": evaluation.metric_values(),
        "categories": category_metrics(evaluation),
    }


def _artifact_name(recorded_at: datetime, label: str) -> str:
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{label}.json"


async def run_decomposition_comparison(
    cases: Sequence[GoldenCase],
    *,
    baseline_retriever: Retriever,
    decomposed_retriever: Retriever,
    baseline_config: Mapping[str, Any],
    decomposed_config: Mapping[str, Any],
    suite: str,
    artifact_dir: str | Path,
    k: int = 5,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate both retrievers on one golden suite and write paired artifacts.

    Both arms run through the unmodified M3 harness, so their artifacts have
    the same schema as every other evaluation and remain comparable with the
    stored baselines. The returned payload adds the per-category split and the
    metric deltas the ablation narrative needs.
    """
    moment = recorded_at or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    baseline = await evaluate_retriever(
        cases,
        baseline_retriever,
        suite=suite,
        config=baseline_config,
        k=k,
        recorded_at=moment,
    )
    decomposed = await evaluate_retriever(
        cases,
        decomposed_retriever,
        suite=suite,
        config=decomposed_config,
        k=k,
        recorded_at=moment,
    )
    directory = Path(artifact_dir)
    baseline_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-baseline"),
        baseline,
    )
    decomposed_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-decomposed"),
        decomposed,
    )
    baseline_categories = category_metrics(baseline)
    decomposed_categories = category_metrics(decomposed)
    deltas = {
        category: {
            "recall_at_k": decomposed_categories[category]["recall_at_k"]
            - baseline_categories[category]["recall_at_k"],
            "mrr": decomposed_categories[category]["mrr"] - baseline_categories[category]["mrr"],
        }
        for category in sorted(set(baseline_categories) & set(decomposed_categories))
    }
    return {
        "suite": suite,
        "k": k,
        "baseline": _arm_payload(baseline),
        "decomposed": _arm_payload(decomposed),
        "category_deltas": deltas,
        "artifacts": {
            "baseline": str(baseline_path),
            "decomposed": str(decomposed_path),
        },
    }
