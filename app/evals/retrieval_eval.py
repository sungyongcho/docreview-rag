"""Score one bound retriever against a golden suite and persist comparable evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.arms import Retriever
from app.evals.artifacts import utc_text, write_json_artifact
from app.evals.measurement import Clock, LatencySummary, latency_summary
from app.evals.regression import (
    BaselineComparison,
    RegressionTolerances,
    canonical_config,
    compare_against_baseline,
    latest_comparable_baseline,
    persist_eval_result,
)
from app.evals.scoring import CaseScore, SuiteScore, score_case, score_suite
from app.evals.types import GoldenCase
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.retrieval.types import ChunkHit

RAW_ARTIFACT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GoldenProvenance:
    """Suite-wide review provenance accepted by the strict evaluator.

    Instances distinguish scored positive cases from unscored absent cases while
    preserving one uniform curation and approval state.
    """

    total_cases: int
    scored_positive_cases: int
    unscored_absent_cases: int
    curation_status: str
    approval_status: str
    human_verified: bool


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    """Measured retrieval evidence for one golden case.

    The evaluator preserves raw hit order and leaves ``score`` unset for an absent case
    that intentionally has no source-bearing answer.
    """

    golden: GoldenCase
    latency_ms: float
    hits: tuple[ChunkHit, ...]
    score: CaseScore | None


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    """Complete evidence for one reproducible retrieval experiment.

    Instances contain a canonical configuration, deterministic case order,
    positive-only quality scores, and the raw hits needed for artifact review.
    """

    suite: str
    recorded_at: datetime
    config: dict[str, Any]
    provenance: GoldenProvenance
    score: SuiteScore
    latency: LatencySummary
    cases: tuple[CaseEvaluation, ...]

    def metric_values(self) -> dict[str, float]:
        """Provide quality and latency values accepted by evaluation persistence.

        ``query_count`` is represented as a float so the mapping has the homogeneous
        value type required by the persistence and regression interfaces.
        """
        return {
            "recall_at_k": self.score.recall_at_k,
            "hit_rate_at_k": self.score.hit_rate_at_k,
            "mrr": self.score.mrr,
            "query_count": float(self.latency.query_count),
            "total_latency_ms": self.latency.total_ms,
            "mean_latency_ms": self.latency.mean_ms,
            "p95_latency_ms": self.latency.p95_ms,
        }

    def artifact_payload(self) -> dict[str, Any]:
        """Provide the stable raw-artifact payload for this measured run.

        Returns
        -------
        dict[str, Any]
            JSON-compatible evidence containing configuration, provenance, metrics,
            latency, and every case in evaluation order, with raw hit order retained.
        """
        return {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "suite": self.suite,
            "recorded_at": utc_text(self.recorded_at),
            "config": self.config,
            "golden_provenance": asdict(self.provenance),
            "metrics": {
                "k": self.score.k,
                "scored_case_count": self.score.case_count,
                **self.metric_values(),
            },
            "latency": asdict(self.latency),
            "cases": [
                {
                    "golden": case.golden.model_dump(mode="json"),
                    "latency_ms": case.latency_ms,
                    "hits": [hit.model_dump(mode="json") for hit in case.hits],
                    "score": asdict(case.score) if case.score is not None else None,
                }
                for case in self.cases
            ],
        }


@dataclass(frozen=True, slots=True)
class PersistedEvaluation:
    """Database identity and optional comparison for a persisted evaluation.

    ``baseline_id`` and ``comparison`` remain unset together when no prior run is
    comparable, meaning none shares this run's suite, canonical configuration, and
    scoring settings.
    """

    result_id: int
    baseline_id: int | None
    comparison: BaselineComparison | None

    @property
    def passed(self) -> bool:
        """Report whether this run stayed within tolerance of its baseline.

        A run with no comparable baseline passes: there is nothing to regress against.
        """
        return self.comparison is None or self.comparison.passed

    def to_dict(self) -> dict[str, Any]:
        """Build JSON-compatible persistence evidence including the gating verdict.

        ``asdict`` alone would drop ``passed`` and ``regressed_metrics``, which are
        properties rather than fields, leaving the reported evidence without the
        decision it exists to justify.
        """
        comparison = (
            None
            if self.comparison is None
            else {
                "passed": self.comparison.passed,
                "regressed_metrics": list(self.comparison.regressed_metrics),
                "metrics": [asdict(metric) for metric in self.comparison.metrics],
            }
        )
        return {
            "result_id": self.result_id,
            "baseline_id": self.baseline_id,
            "passed": self.passed,
            "comparison": comparison,
        }


def _golden_provenance(cases: Sequence[GoldenCase]) -> GoldenProvenance:
    """Validate and summarize the review state of one golden suite.

    Returns
    -------
    GoldenProvenance
        Uniform review metadata and separate counts for scored and absent cases.

    Raises
    ------
    ValueError
        If there is no positive case, review statuses differ within the suite, or any
        case claims human verification.
    """
    positive_count = sum(bool(case.answers) for case in cases)
    if positive_count == 0:
        raise ValueError("evaluation requires at least one positive golden case")
    curation_statuses = {case.curation_status for case in cases}
    approval_statuses = {case.approval_status for case in cases}
    verification_states = {case.human_verified for case in cases}
    if len(curation_statuses) != 1 or len(approval_statuses) != 1:
        raise ValueError("golden review provenance must be uniform within a suite")
    if verification_states != {False}:
        raise ValueError("golden cases must not claim human verification")
    return GoldenProvenance(
        total_cases=len(cases),
        scored_positive_cases=positive_count,
        unscored_absent_cases=len(cases) - positive_count,
        curation_status=next(iter(curation_statuses)),
        approval_status=next(iter(approval_statuses)),
        human_verified=False,
    )


async def evaluate_retriever(
    cases: Sequence[GoldenCase],
    retriever: Retriever,
    *,
    suite: str,
    config: Mapping[str, Any],
    k: int = 5,
    clock: Clock = time.perf_counter_ns,
    recorded_at: datetime | None = None,
    on_progress: OperationProgressCallback | None = None,
) -> RetrievalEvaluation:
    """Evaluate every case once while scoring only source-bearing positives.

    Parameters
    ----------
    cases : Sequence[GoldenCase]
        Golden questions to evaluate, each identified by a unique case ID.
    retriever : Retriever
        Awaitable retrieval callable invoked with a question and requested hit count.
    suite : str
        Nonblank suite identity stored with metrics and artifacts.
    config : Mapping[str, Any]
        JSON-compatible experiment configuration used for baseline comparability.
    k : int, optional
        Positive hit count requested from the retriever and used for scoring.
    clock : Clock, optional
        Monotonic nanosecond clock called immediately around each retrieval.
    recorded_at : datetime | None, optional
        Artifact timestamp, or the current UTC time when omitted.

    Returns
    -------
    RetrievalEvaluation
        Canonical configuration, suite provenance, quality scores, latency, and raw hits.

    Raises
    ------
    ValueError
        If suite metadata, ``k``, case identity, golden provenance, configuration, or
        measured clock order is invalid.

    Notes
    -----
    Cases are sorted by ID before sequential retrieval. Absent cases retain hits and
    latency evidence but do not contribute to suite quality metrics. Exceptions from the
    bound retriever are propagated without producing a partial evaluation.
    """
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be nonblank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    ordered = tuple(sorted(cases, key=lambda case: case.id))
    if not ordered:
        raise ValueError("golden cases must not be empty")
    if len({case.id for case in ordered}) != len(ordered):
        raise ValueError("golden case ids must be unique")
    provenance = _golden_provenance(ordered)

    results: list[CaseEvaluation] = []
    scores: list[CaseScore] = []
    latencies: list[float] = []
    for position, case in enumerate(ordered, start=1):
        started = clock()
        hits = tuple(await retriever(case.question, k))
        elapsed_ms = (clock() - started) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        case_score = score_case(case.id, case.answers, hits, k) if case.answers else None
        if case_score is not None:
            scores.append(case_score)
        results.append(
            CaseEvaluation(
                golden=case,
                latency_ms=elapsed_ms,
                hits=hits,
                score=case_score,
            )
        )
        if on_progress is not None:
            on_progress(OperationProgress("evaluate", position, len(ordered), case.id))

    return RetrievalEvaluation(
        suite=suite,
        recorded_at=recorded_at or datetime.now(UTC),
        config=canonical_config(config),
        provenance=provenance,
        score=score_suite(scores),
        latency=latency_summary(latencies),
        cases=tuple(results),
    )


def write_evaluation_artifact(path: str | Path, evaluation: RetrievalEvaluation) -> Path:
    """Write one stable raw evaluation artifact.

    Raises
    ------
    ValueError
        If the destination does not end in ``.json`` or the payload contains a
        non-finite number.
    OSError
        If the parent directory cannot be created or the artifact cannot be written.
    """
    return write_json_artifact(path, evaluation.artifact_payload())


async def persist_evaluation(
    session: AsyncSession,
    evaluation: RetrievalEvaluation,
    *,
    raw_artifact_path: str | Path,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> PersistedEvaluation:
    """Persist one run and compare it with the latest matching baseline.

    Parameters
    ----------
    session : AsyncSession
        Database session used for baseline lookup and result insertion.
    evaluation : RetrievalEvaluation
        Completed run whose canonical suite, configuration, and metrics are persisted.
    raw_artifact_path : str | Path
        Path recorded as the reviewable raw evidence for the new row.
    tolerances : RegressionTolerances | Mapping[str, float] | None, optional
        Accepted absolute drops for quality metrics, or zero tolerance when omitted.

    Returns
    -------
    PersistedEvaluation
        New row identity and an optional comparison with the preceding comparable row.

    Raises
    ------
    ValueError
        If persisted metadata, metrics, or regression tolerances violate their contracts.
    RuntimeError
        If the inserted result is not assigned a database identity.

    Notes
    -----
    Baseline lookup precedes insertion, and comparability requires the suite, the
    canonical configuration, and the scoring settings behind the metrics to match. The
    scoring stamp comes from the evaluated suite itself, so a run can never be compared
    with one measured at another cutoff or relevance threshold. This function does not
    commit the caller's transaction.
    """
    scoring = evaluation.score.parameters
    baseline = await latest_comparable_baseline(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
        scoring=scoring,
    )
    comparison = (
        compare_against_baseline(
            baseline.metrics,
            evaluation.metric_values(),
            tolerances=tolerances,
        )
        if baseline is not None
        else None
    )
    result = await persist_eval_result(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
        metrics=evaluation.metric_values(),
        raw_artifact_path=raw_artifact_path,
        scoring=scoring,
        created_at=evaluation.recorded_at,
    )
    if result.id is None:
        raise RuntimeError("persisted evaluation did not receive an id")
    return PersistedEvaluation(
        result_id=result.id,
        baseline_id=baseline.id if baseline is not None else None,
        comparison=comparison,
    )
