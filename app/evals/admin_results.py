"""Stored evaluation results: baseline lookup, comparison, and detail reading.

Every artifact read is confined to the configured evaluation directory, so a stored
row can never point the admin surface at an arbitrary file.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    EvaluationCaseDelta,
    EvaluationCaseSummary,
    EvaluationComparisonResponse,
    EvaluationMetricDelta,
    EvaluationResultDetailResponse,
)
from app.db.models import EvalResult
from app.db.session_factory import SessionFactory
from app.evals.artifacts import EvaluationArtifacts, cases_by_id
from app.evals.regression import SCORING_CONFIG_KEY


async def compatible_baseline(
    session: AsyncSession,
    *,
    suite: str,
    golden_sha256: str,
    corpus_fingerprint: str,
    k: int,
) -> EvalResult | None:
    """Return the newest run sharing suite, source corpus, golden bytes, and cutoff."""
    rows = tuple(
        await session.scalars(
            select(EvalResult)
            .where(EvalResult.suite == suite)
            .order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
            .limit(100)
        )
    )
    for row in rows:
        identity = row.config.get("admin_identity", {})
        scoring = row.config.get(SCORING_CONFIG_KEY, {})
        if (
            isinstance(identity, dict)
            and identity.get("golden_sha256") == golden_sha256
            and identity.get("corpus_fingerprint") == corpus_fingerprint
            and isinstance(scoring, dict)
            and scoring.get("k") == k
        ):
            return row
    return None


async def compare_stored_results(
    session_factory: SessionFactory,
    artifact_dir: Path,
    candidate_id: int,
    baseline_id: int,
) -> EvaluationComparisonResponse:
    """Compare compatible stored artifacts at metric and golden-case level."""
    async with session_factory() as session:
        candidate = await session.get(EvalResult, candidate_id)
        baseline = await session.get(EvalResult, baseline_id)
    if candidate is None or baseline is None:
        raise ValueError("evaluation result was not found")
    if candidate.suite != baseline.suite:
        raise ValueError("evaluation suites are not compatible")
    if candidate.config.get("admin_identity") != baseline.config.get("admin_identity"):
        raise ValueError("evaluation corpus or golden identity is not compatible")
    candidate_scoring = candidate.config.get(SCORING_CONFIG_KEY, {})
    baseline_scoring = baseline.config.get(SCORING_CONFIG_KEY, {})
    if not isinstance(candidate_scoring, dict) or not isinstance(baseline_scoring, dict):
        raise ValueError("evaluation scoring metadata must be an object")
    if candidate_scoring.get("k") != baseline_scoring.get("k"):
        raise ValueError("evaluation cutoffs are not compatible")
    artifacts = EvaluationArtifacts(artifact_dir)
    candidate_payload = artifacts.read(candidate.raw_artifact_path)
    baseline_payload = artifacts.read(baseline.raw_artifact_path)
    metric_names = ("recall_at_k", "hit_rate_at_k", "mrr", "mean_latency_ms")
    candidate_metrics = candidate_payload.get("metrics", {})
    baseline_metrics = baseline_payload.get("metrics", {})
    metrics = tuple(
        EvaluationMetricDelta(
            name=name,
            baseline=float(baseline_metrics[name]),
            candidate=float(candidate_metrics[name]),
            delta=float(candidate_metrics[name]) - float(baseline_metrics[name]),
        )
        for name in metric_names
    )

    baseline_cases = cases_by_id(baseline_payload)
    candidate_cases = cases_by_id(candidate_payload)
    case_deltas: list[EvaluationCaseDelta] = []
    for case_id in sorted(set(baseline_cases) & set(candidate_cases)):
        before = baseline_cases[case_id]
        after = candidate_cases[case_id]
        before_score = before.get("score") or {}
        after_score = after.get("score") or {}
        before_rank = before_score.get("first_relevant_rank")
        after_rank = after_score.get("first_relevant_rank")
        if before_rank is None and after_rank is None:
            transition = "stable_miss"
        elif before_rank is None:
            transition = "miss_to_hit"
        elif after_rank is None:
            transition = "hit_to_miss"
        else:
            transition = "stable_hit"
        rank_delta = (
            int(after_rank) - int(before_rank)
            if before_rank is not None and after_rank is not None
            else None
        )
        case_deltas.append(
            EvaluationCaseDelta(
                case_id=case_id,
                question=str(after["golden"]["question"]),
                baseline_rank=before_rank,
                candidate_rank=after_rank,
                transition=transition,
                rank_delta=rank_delta,
                baseline_citations=tuple(
                    str(hit["citation"]) for hit in before.get("hits", [])[:5]
                ),
                candidate_citations=tuple(
                    str(hit["citation"]) for hit in after.get("hits", [])[:5]
                ),
            )
        )
    return EvaluationComparisonResponse(
        baseline_id=baseline_id,
        candidate_id=candidate_id,
        suite=candidate.suite,
        metrics=metrics,
        cases=tuple(case_deltas),
    )


async def stored_result_detail(
    session_factory: SessionFactory, artifact_dir: Path, result_id: int
) -> EvaluationResultDetailResponse | None:
    """Return absolute metrics and bounded case summaries for one result."""
    async with session_factory() as session:
        result = await session.get(EvalResult, result_id)
    if result is None:
        return None
    payload = EvaluationArtifacts(artifact_dir).read(result.raw_artifact_path)
    raw_metrics = payload.get("metrics")
    if not isinstance(raw_metrics, dict):
        raise ValueError("evaluation artifact metrics must be an object")
    cases: list[EvaluationCaseSummary] = []
    for item in list(cases_by_id(payload).values())[:50]:
        raw_score = item.get("score")
        score = raw_score if isinstance(raw_score, dict) else {}
        cases.append(
            EvaluationCaseSummary(
                case_id=item["golden"]["id"],
                question=str(item["golden"].get("question", "")),
                first_relevant_rank=score.get("first_relevant_rank"),
                citations=tuple(
                    str(hit.get("citation", ""))
                    for hit in item.get("hits", [])[:5]
                    if isinstance(hit, dict)
                ),
            )
        )
    return EvaluationResultDetailResponse(
        result_id=result.id,
        suite=result.suite,
        config=dict(result.config),
        metrics={name: float(value) for name, value in raw_metrics.items()},
        cases=tuple(cases),
        raw_artifact_path=result.raw_artifact_path,
        created_at=result.created_at,
    )
