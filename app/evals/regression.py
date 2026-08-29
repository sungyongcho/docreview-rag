"""Metric regression comparisons and PostgreSQL persistence for evaluation runs."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Final, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalResult

type MetricName = Literal["recall_at_k", "hit_rate_at_k", "mrr"]

HIGHER_IS_BETTER_METRICS: Final[tuple[MetricName, ...]] = (
    "recall_at_k",
    "hit_rate_at_k",
    "mrr",
)
SCORING_CONFIG_KEY: Final[str] = "scoring"


def _gated_metric_value(metrics: Mapping[str, float], metric: MetricName, owner: str) -> float:
    """Return one gated metric as a finite float within ``[0, 1]``.

    Persistence and comparison both narrow gated metrics through this function, so a
    run that is accepted at write time is always readable as a baseline later.
    """
    try:
        value = metrics[metric]
    except KeyError as exc:
        raise ValueError(f"{owner} metrics are missing {metric}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{owner} {metric} must be a finite number between 0 and 1")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{owner} {metric} must be a finite number between 0 and 1")
    return numeric


@dataclass(frozen=True, slots=True)
class RegressionTolerances:
    """Maximum accepted absolute drop for each higher-is-better metric."""

    recall_at_k: float = 0.0
    hit_rate_at_k: float = 0.0
    mrr: float = 0.0

    def __post_init__(self) -> None:
        """Reject non-finite or negative tolerance values at construction."""
        for metric in HIGHER_IS_BETTER_METRICS:
            value = getattr(self, metric)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{metric} tolerance must be a finite nonnegative number")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{metric} tolerance must be a finite nonnegative number")

    def for_metric(self, metric: MetricName) -> float:
        """Return the configured tolerance for one supported metric."""
        return float(getattr(self, metric))


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One current metric compared with its higher-is-better baseline."""

    metric: MetricName
    baseline: float
    current: float
    delta: float
    tolerance: float
    regressed: bool


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """Deterministically ordered comparisons for all regression-gated metrics."""

    metrics: tuple[MetricComparison, ...]

    @property
    def regressed_metrics(self) -> tuple[MetricName, ...]:
        """Return metric names whose drop exceeds the configured tolerance."""
        return tuple(result.metric for result in self.metrics if result.regressed)

    @property
    def passed(self) -> bool:
        """Return whether every metric stayed within its allowed drop."""
        return not self.regressed_metrics


def compare_against_baseline(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> BaselineComparison:
    """Compare current values with an explicit higher-is-better metric baseline.

    Parameters
    ----------
    baseline : Mapping[str, float]
        Stored metric values, each finite and within ``[0, 1]``.

    current : Mapping[str, float]
        Fresh metric values compared against the baseline.

    tolerances : RegressionTolerances | Mapping[str, float] | None
        Accepted absolute drop per metric; ``None`` means zero tolerance.

    Returns
    -------
    BaselineComparison
        One comparison per supported metric in declaration order.

    Raises
    ------
    ValueError
        If either side is not a mapping, a supported metric is missing or out
        of range, or a tolerance names an unsupported metric.

    Notes
    -----
    A drop exactly equal to its tolerance passes; the boundary is accepted via
    ``math.isclose`` with ``abs_tol=1e-12`` so float noise cannot flip it.
    Extra metrics are ignored so lower-is-better values such as latency are
    never interpreted implicitly.
    """
    if not isinstance(baseline, Mapping) or not isinstance(current, Mapping):
        raise ValueError("baseline and current metrics must be mappings")
    if tolerances is None:
        limits = RegressionTolerances()
    elif isinstance(tolerances, RegressionTolerances):
        limits = tolerances
    else:
        if not isinstance(tolerances, Mapping) or not all(
            isinstance(metric, str) for metric in tolerances
        ):
            raise ValueError("tolerances must map supported metric names to numbers")
        unknown = set(tolerances) - set(HIGHER_IS_BETTER_METRICS)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported metric tolerances: {names}")
        limits = RegressionTolerances(**tolerances)
    comparisons: list[MetricComparison] = []
    for metric in HIGHER_IS_BETTER_METRICS:
        baseline_value = _gated_metric_value(baseline, metric, "baseline")
        current_value = _gated_metric_value(current, metric, "current")
        tolerance = limits.for_metric(metric)
        delta = current_value - baseline_value
        boundary = -tolerance
        regressed = delta < boundary and not math.isclose(
            delta,
            boundary,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        comparisons.append(
            MetricComparison(
                metric=metric,
                baseline=baseline_value,
                current=current_value,
                delta=delta,
                tolerance=tolerance,
                regressed=regressed,
            )
        )
    return BaselineComparison(metrics=tuple(comparisons))


def serialize_config(config: Mapping[str, Any]) -> str:
    """Serialize a JSON-object config canonically for stable comparability.

    Parameters
    ----------
    config : Mapping[str, Any]
        JSON-compatible object whose nested keys must all be strings.

    Returns
    -------
    str
        Compact JSON with sorted keys, stable across key order and whitespace.

    Raises
    ------
    ValueError
        If the config contains non-string keys, non-finite numbers, or values
        JSON cannot represent.
    """

    def _validate_config_keys(value: object) -> None:
        """Reject non-string keys anywhere in the nested config value."""
        if isinstance(value, Mapping):
            if not all(isinstance(key, str) for key in value):
                raise ValueError("config keys must be strings")
            for child in value.values():
                _validate_config_keys(child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for child in value:
                _validate_config_keys(child)

    if not isinstance(config, Mapping):
        raise ValueError("config must be a JSON object")
    try:
        _validate_config_keys(config)
    except RecursionError as exc:
        raise ValueError("config is nested too deeply to serialize") from exc
    try:
        return json.dumps(
            dict(config),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("config must contain only finite JSON values") from exc


def _canonical_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical dict form produced by a serialization round trip."""
    value = json.loads(serialize_config(config))
    return cast(dict[str, Any], value)


def _comparable_config(config: Mapping[str, Any], scoring: Mapping[str, float]) -> dict[str, Any]:
    """Return the canonical config stamped with the scoring settings behind the metrics.

    Two runs are comparable only when they measured the same thing, and the metric
    values depend on the top-k cutoff and the relevance threshold as much as on the
    retriever. Writing and reading both stamp through here, so a run scored under
    different settings simply stops matching instead of producing a silent false
    regression. ``SuiteScore.parameters`` supplies the mapping.

    The stamp covers scoring only. Everything else that moves a metric — the
    retriever, and above all the chunk configuration, since relevance rises with
    chunk width — has to be in ``config``, or two different experiments will be
    compared as if one were the other's baseline.
    """
    if SCORING_CONFIG_KEY in config:
        raise ValueError(f"config must not define the reserved {SCORING_CONFIG_KEY!r} key")
    return _canonical_config({**config, SCORING_CONFIG_KEY: dict(scoring)})


def _validated_metrics(metrics: Mapping[str, float]) -> dict[str, float]:
    """Return metric values a later regression comparison can actually gate on.

    Every metric in ``HIGHER_IS_BETTER_METRICS`` must be present and within
    ``[0, 1]``: a row without them still wins ``latest_comparable_baseline`` and
    then makes every later comparison fail. Ungated metrics such as ``latency_ms``
    are stored as finite floats and left for the caller to interpret.
    """
    if not isinstance(metrics, Mapping):
        raise ValueError("metrics must be a JSON object")
    validated: dict[str, float] = {
        metric: _gated_metric_value(metrics, metric, "run") for metric in HIGHER_IS_BETTER_METRICS
    }
    for name, value in metrics.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric names must be nonblank strings")
        if name in validated:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric {name} must be a finite number")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"metric {name} must be a finite number")
        validated[name] = numeric
    return validated


def _validated_suite(suite: str) -> str:
    """Return a nonblank suite name within the column length limit."""
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be a nonblank string")
    if len(suite) > 128:
        raise ValueError("suite must be at most 128 characters")
    return suite


def _artifact_path(raw_artifact_path: str | Path) -> str:
    """Return the artifact path as a nonblank string."""
    if not isinstance(raw_artifact_path, (str, Path)):
        raise ValueError("raw_artifact_path must be a string or Path")
    path = str(raw_artifact_path)
    if not path.strip():
        raise ValueError("raw_artifact_path must be nonblank")
    return path


async def persist_eval_result(
    session: AsyncSession,
    *,
    suite: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, float],
    raw_artifact_path: str | Path,
    scoring: Mapping[str, float],
    created_at: datetime | None = None,
) -> EvalResult:
    """Flush one validated result without committing the caller's transaction.

    Parameters
    ----------
    session : AsyncSession
        Open session whose transaction the caller still owns.

    suite : str
        Nonblank suite name grouping comparable runs.

    config : Mapping[str, Any]
        Run configuration stored in canonical JSON form.

    metrics : Mapping[str, float]
        Finite metric values for the run, including every gated metric.

    raw_artifact_path : str | Path
        Nonblank pointer to the run's evidence artifact.

    scoring : Mapping[str, float]
        Scoring settings the metrics depend on, from ``SuiteScore.parameters``.
        They are stamped into the stored config and define comparability.

    created_at : datetime | None
        Optional explicit timestamp; must be timezone-aware when given.

    Returns
    -------
    EvalResult
        Flushed row with its database identity populated.

    Raises
    ------
    ValueError
        If any field fails validation or ``created_at`` is naive.

    Notes
    -----
    The session is flushed but never committed here, so the caller decides
    whether the run becomes durable.
    """
    values: dict[str, Any] = {
        "suite": _validated_suite(suite),
        "config": _comparable_config(config, scoring),
        "metrics": _validated_metrics(metrics),
        "raw_artifact_path": _artifact_path(raw_artifact_path),
    }
    if created_at is not None:
        if not isinstance(created_at, datetime):
            raise ValueError("created_at must be a timezone-aware datetime")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        values["created_at"] = created_at

    result = EvalResult(**values)
    session.add(result)
    await session.flush()
    return result


async def latest_comparable_baseline(
    session: AsyncSession,
    *,
    suite: str,
    config: Mapping[str, Any],
    scoring: Mapping[str, float],
) -> EvalResult | None:
    """Return the newest row with the same suite, config, and scoring settings.

    Parameters
    ----------
    session : AsyncSession
        Open session used for the read.

    suite : str
        Suite name the baseline must match exactly.

    config : Mapping[str, Any]
        Configuration compared in canonical JSON form, so key order and
        whitespace differences never split comparable baselines.

    scoring : Mapping[str, float]
        Scoring settings of the current run, stamped exactly as they were at
        write time so a baseline measured differently cannot match.

    Returns
    -------
    EvalResult | None
        Newest comparable row, or ``None`` when no baseline exists yet.

    Notes
    -----
    Ordering is ``created_at`` descending with ``id`` descending as the tie
    break, so equal timestamps still yield one deterministic baseline.
    """
    statement = (
        select(EvalResult)
        .where(
            EvalResult.suite == _validated_suite(suite),
            EvalResult.config == _comparable_config(config, scoring),
        )
        .order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        .limit(1)
    )
    return await session.scalar(statement)
