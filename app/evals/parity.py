"""Cross-language parity metrics and the gate that keeps them honest."""

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any, Final

from app.evals.regression import (
    HIGHER_IS_BETTER_METRICS,
    MetricName,
    RegressionTolerances,
)
from app.evals.retrieval_eval import RetrievalEvaluation

DEFAULT_MIN_RECALL_RATIO: Final[float] = 0.85

# One positive case out of 24 moves a macro metric by about 0.042. A tolerance below
# that would let a single flipped case fail the gate, so the standing per-language
# regression allowance sits deliberately above single-case granularity.
PARITY_REGRESSION_TOLERANCE: Final[float] = 0.05

# Parity is a ratio between two arms measured together; this is the other half of the
# gate, and each language slice is compared with its own stored baseline through
# ``persist_evaluation``. Raising the Korean slice while quietly dropping the English
# one would improve the ratio, so the English slice keeps its own standing check.
LANGUAGE_REGRESSION_TOLERANCES: Final[RegressionTolerances] = RegressionTolerances(
    recall_at_k=PARITY_REGRESSION_TOLERANCE,
    hit_rate_at_k=PARITY_REGRESSION_TOLERANCE,
    mrr=PARITY_REGRESSION_TOLERANCE,
)

GATED_METRIC: Final[MetricName] = "recall_at_k"


@dataclass(frozen=True, slots=True)
class ParityMetric:
    """One metric measured on both language slices of the same arm."""

    metric: MetricName
    en: float
    ko: float
    delta: float
    ratio: float | None


@dataclass(frozen=True, slots=True)
class ParityAssessment:
    """The complete cross-language verdict for one arm pair."""

    suite: str
    k: int
    case_count: int
    min_recall_ratio: float
    metrics: tuple[ParityMetric, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the gated ratio cleared its floor."""
        return not self.failures

    def metric(self, name: MetricName) -> ParityMetric:
        """Return one measured metric pair by name."""
        for result in self.metrics:
            if result.metric == name:
                return result
        raise KeyError(name)

    @property
    def recall_ratio(self) -> float | None:
        """Return the gated ko/en recall ratio, or None when the English slice is 0."""
        return self.metric(GATED_METRIC).ratio


def _config_identity(config: Mapping[str, Any], expected_language: str) -> dict[str, Any]:
    """Strip the arm name and the query language, leaving what both arms must share."""
    query = config.get("query")
    if not isinstance(query, Mapping) or "language" not in query:
        raise ValueError("parity requires an evaluation config carrying query.language")
    if query["language"] != expected_language:
        raise ValueError(f"expected a {expected_language} evaluation, got {query['language']!r}")
    identity = {key: value for key, value in config.items() if key != "name"}
    identity["query"] = {key: value for key, value in query.items() if key != "language"}
    return identity


def _case_ids(evaluation: RetrievalEvaluation) -> tuple[frozenset[str], frozenset[str]]:
    """Return the evaluated case ids and the subset that carried a score."""
    all_ids = frozenset(case.golden.id for case in evaluation.cases)
    scored_ids = frozenset(case.golden.id for case in evaluation.cases if case.score is not None)
    return all_ids, scored_ids


def assess_parity(
    en_eval: RetrievalEvaluation,
    ko_eval: RetrievalEvaluation,
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> ParityAssessment:
    """Compare evaluations whose only configured difference is query language.

    The assessment records ``delta = en - ko`` and ``ratio = ko / en`` for each gated
    metric. A zero English score leaves the ratio undefined and fails closed.
    """
    if not isinstance(en_eval, RetrievalEvaluation) or not isinstance(ko_eval, RetrievalEvaluation):
        raise TypeError("parity requires two RetrievalEvaluation values")
    if not math.isfinite(min_recall_ratio) or not 0.0 < min_recall_ratio <= 1.0:
        raise ValueError("min_recall_ratio must be in (0, 1]")
    if en_eval.suite != ko_eval.suite:
        raise ValueError("parity requires both evaluations to share one suite")
    if en_eval.score.k != ko_eval.score.k:
        raise ValueError("parity requires both evaluations to use the same k")

    en_ids, en_scored = _case_ids(en_eval)
    ko_ids, ko_scored = _case_ids(ko_eval)
    if en_ids != ko_ids or en_scored != ko_scored:
        raise ValueError("parity requires both evaluations to cover the same golden cases")
    if _config_identity(en_eval.config, "en") != _config_identity(ko_eval.config, "ko"):
        raise ValueError("parity arms must differ only in query language")

    en_values = en_eval.metric_values()
    ko_values = ko_eval.metric_values()
    metrics: list[ParityMetric] = []
    failures: list[str] = []
    for name in HIGHER_IS_BETTER_METRICS:
        english = en_values[name]
        korean = ko_values[name]
        ratio = None if english == 0.0 else korean / english
        metrics.append(
            ParityMetric(
                metric=name,
                en=english,
                ko=korean,
                delta=english - korean,
                ratio=ratio,
            )
        )
        if name != GATED_METRIC:
            continue
        if ratio is None:
            failures.append(f"{name}: English slice scored 0, so parity is undefined")
        elif ratio < min_recall_ratio and not math.isclose(
            ratio,
            min_recall_ratio,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            failures.append(f"{name}: ratio {ratio:.6f} is below the floor {min_recall_ratio:.6f}")

    return ParityAssessment(
        suite=en_eval.suite,
        k=en_eval.score.k,
        case_count=en_eval.score.case_count,
        min_recall_ratio=min_recall_ratio,
        metrics=tuple(metrics),
        failures=tuple(failures),
    )


def parity_markdown(assessment: ParityAssessment) -> str:
    """Render one parity assessment as a compact verdict table."""
    verdict = "PASS" if assessment.passed else "FAIL"
    lines = [
        "| Metric | EN | KO | Delta (EN-KO) | Ratio (KO/EN) |",
        "|---|---:|---:|---:|---:|",
    ]
    for result in assessment.metrics:
        ratio = "undefined" if result.ratio is None else f"{result.ratio:.6f}"
        lines.append(
            f"| {result.metric} | {result.en:.6f} | {result.ko:.6f} | "
            f"{result.delta:.6f} | {ratio} |"
        )
    lines.append("")
    lines.append(
        f"{verdict} — {assessment.suite}, k={assessment.k}, "
        f"{assessment.case_count} scored cases, "
        f"{GATED_METRIC} floor {assessment.min_recall_ratio:.2f}."
    )
    for failure in assessment.failures:
        lines.append(f"- {failure}")
    return "\n".join(lines)
