"""Category-sliced comparison of single-query and decomposed retrieval."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.evals.retrieval_eval import RetrievalEvaluation, Retriever
    from app.evals.scoring import CaseScore
    from app.evals.types import GoldenCase
else:
    RetrievalEvaluation = object
    Retriever = Callable[..., Awaitable[Sequence[object]]]
    CaseScore = object
    GoldenCase = object


def category_metrics(evaluation: RetrievalEvaluation) -> dict[str, dict[str, float]]:
    """Return macro retrieval metrics per golden category, scored cases only.

    Parameters
    ----------
    evaluation : RetrievalEvaluation
        Completed M3-compatible evaluation with optional per-case scores.

    Returns
    -------
    dict[str, dict[str, float]]
        Macro retrieval metrics keyed by golden category.

    Notes
    -----
    Absent cases remain unscored, matching M3. The category split shows whether
    decomposition moves ``multi_hop`` without regressing ``simple_lookup``.
    """
    grouped: dict[str, list[CaseScore]] = {}
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
    """Pair one arm's suite metrics with its per-category split."""
    return {
        "metrics": evaluation.metric_values(),
        "categories": category_metrics(evaluation),
    }


def _artifact_name(recorded_at: datetime, label: str) -> str:
    """Name one artifact from the shared UTC timestamp so both arms sort together."""
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

    Parameters
    ----------
    cases : Sequence[GoldenCase]
        Shared golden cases evaluated by both arms.
    baseline_retriever : Retriever
        Single-query retrieval callable.
    decomposed_retriever : Retriever
        Query-decomposing retrieval callable.
    baseline_config : Mapping[str, Any]
        Complete provenance for the baseline arm.
    decomposed_config : Mapping[str, Any]
        Complete provenance for the decomposed arm.
    suite : str
        Stable evaluation suite name.
    artifact_dir : str | Path
        Destination directory for paired JSON artifacts.
    k : int
        Retrieval cutoff shared by both arms.
    recorded_at : datetime | None
        Optional timezone-aware timestamp shared by both artifacts.

    Returns
    -------
    dict[str, Any]
        Arm metrics, category deltas, and written artifact paths.

    Raises
    ------
    ValueError
        If the supplied timestamp is timezone-naive.

    Notes
    -----
    Both arms run through the unchanged M3 harness and share one timestamp, so their
    artifact schemas and category deltas remain directly comparable.
    """
    from app.evals.retrieval_eval import evaluate_retriever, write_evaluation_artifact

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
