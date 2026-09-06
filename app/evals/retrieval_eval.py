"""Source-grounded M3 retrieval experiments and latency-budget measurement.

The runner builds isolated PostgreSQL corpora, binds explicit retrieval strategies,
and emits comparable JSON evidence without modifying the populated application corpus.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import BM25Idf, LexicalRanker, Settings, get_settings
from app.evals.loader import DEFAULT_GOLDEN_PATH, load_golden_cases
from app.evals.regression import (
    BaselineComparison,
    RegressionTolerances,
    compare_against_baseline,
    latest_comparable_baseline,
    persist_eval_result,
    serialize_config,
)
from app.evals.scoring import CaseScore, SuiteScore, score_case, score_suite
from app.evals.types import GoldenCase
from app.ingestion.chunk import Chunk, ChunkConfig, chunk_filing
from app.ingestion.parser import ParsedFiling
from app.ingestion.seed import (
    SeedBatch,
    build_seed_batch,
    build_seed_batch_from_filings,
    load_manifest,
    parse_seed_filings,
    persist_seed_batch,
)
from app.retrieval.bm25 import backfill_term_stats, bm25_search
from app.retrieval.embeddings import (
    EmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.lexical import lexical_search
from app.retrieval.service import normalize_query, retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]
type Clock = Callable[[], int]

if TYPE_CHECKING:
    from app.evals.ablation import ExperimentConfig

INDEXING_BUDGET_SECONDS = 300.0
QUERY_BUDGET_COUNT = 200
QUERY_BUDGET_SECONDS = 90.0
RAW_ARTIFACT_SCHEMA_VERSION = 1
BUDGET_ARTIFACT_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class GoldenProvenance:
    """Suite-wide review provenance accepted by the strict M3 evaluator.

    Instances produced by the runner distinguish scored positive cases from unscored
    absent cases while preserving one uniform curation and approval state.
    """

    total_cases: int
    scored_positive_cases: int
    unscored_absent_cases: int
    curation_status: str
    approval_status: str
    human_verified: bool


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Aggregate evidence for nonnegative sequential retrieval latencies.

    Runner-produced summaries use nearest-rank percentiles and retain both the total
    wall-clock measurement and its per-query distribution in milliseconds.
    """

    query_count: int
    total_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


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

    Evaluator-produced instances contain a canonical configuration, deterministic case
    order, positive-only quality scores, and the raw hits needed for artifact review.
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

        Returns
        -------
        dict[str, float]
            Stable metric names mapped to suite quality values and aggregate latency
            measurements.

        Notes
        -----
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
            JSON-compatible schema-v1 evidence containing configuration, provenance,
            metrics, latency, and every case in evaluation order.

        Notes
        -----
        This payload retains raw hit order and optional per-case scores; serialization
        details such as key ordering and the terminal newline belong to
        :func:`write_evaluation_artifact`.
        """
        return {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "suite": self.suite,
            "recorded_at": _utc_text(self.recorded_at),
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
class QueryBudgetMeasurement:
    """Wall-clock evidence for a sequential repeated-query budget.

    Runner-produced instances derive ``passed`` from the inclusive total-time boundary
    and preserve the latency distribution used to assess that decision.
    """

    query_count: int
    total_seconds: float
    budget_seconds: float
    passed: bool
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class SharedPreparationMeasurement:
    """One manifest-load and parse measurement shared by all chunking arms.

    The evidence prevents parse-once work from being hidden when each target's
    standalone indexing duration is derived.
    """

    operation: str
    document_count: int
    total_seconds: float


@dataclass(frozen=True, slots=True)
class IndexingBudgetMeasurement:
    """Per-target indexing evidence with a derived standalone duration.

    Runner-produced instances add shared corpus preparation to target-specific work and
    assess the resulting total against one inclusive budget boundary.
    """

    target_text_chars: int
    document_count: int
    chunk_count: int
    embedding_provider: str
    target_phase_seconds: float
    derived_standalone_seconds: float
    budget_seconds: float
    passed: bool


@dataclass(frozen=True, slots=True)
class PersistedEvaluation:
    """Database identity and optional comparison for a persisted evaluation.

    ``baseline_id`` and ``comparison`` remain unset together when no prior run has the
    same suite and canonical configuration.
    """

    result_id: int
    baseline_id: int | None
    comparison: BaselineComparison | None


def _utc_text(value: datetime) -> str:
    """Format a timezone-aware datetime as a UTC ``Z`` timestamp.

    Parameters
    ----------
    value : datetime
        Timestamp whose absolute instant must be preserved.

    Returns
    -------
    str
        ISO 8601 text normalized to UTC with the ``Z`` suffix.

    Raises
    ------
    ValueError
        If ``value`` is naive or otherwise lacks a UTC offset.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an experiment configuration through canonical JSON.

    Parameters
    ----------
    config : Mapping[str, Any]
        JSON-object configuration used to identify comparable runs.

    Returns
    -------
    dict[str, Any]
        Detached configuration with canonical JSON value types and key handling.

    Raises
    ------
    ValueError
        If the mapping has non-string keys, non-finite numbers, or non-JSON values.
    """
    return json.loads(serialize_config(config))


def _latency_summary(values: Sequence[float]) -> LatencySummary:
    """Aggregate validated latency measurements without changing their units.

    Parameters
    ----------
    values : Sequence[float]
        Nonempty finite, nonnegative measurements in caller-defined units.

    Returns
    -------
    LatencySummary
        Total, mean, nearest-rank percentiles, and maximum in the input units.

    Raises
    ------
    ValueError
        If no values are supplied or any measurement is negative or non-finite.
    """
    if not values:
        raise ValueError("latency measurements must not be empty")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("latency measurements must be finite and nonnegative")
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        """Select one nearest-rank percentile from the ordered measurements."""
        position = max(0, math.ceil(fraction * len(ordered)) - 1)
        return ordered[position]

    total = sum(values)
    return LatencySummary(
        query_count=len(values),
        total_ms=total,
        mean_ms=total / len(values),
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        max_ms=ordered[-1],
    )


def _golden_provenance(cases: Sequence[GoldenCase]) -> GoldenProvenance:
    """Validate and summarize the review state of one golden suite.

    Parameters
    ----------
    cases : Sequence[GoldenCase]
        Golden cases whose answer presence and review metadata define suite provenance.

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
        raise ValueError("M3 golden cases must not claim human verification")
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
    for case in ordered:
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

    return RetrievalEvaluation(
        suite=suite,
        recorded_at=recorded_at or datetime.now(UTC),
        config=_canonical_config(config),
        provenance=provenance,
        score=score_suite(scores),
        latency=_latency_summary(latencies),
        cases=tuple(results),
    )


def write_evaluation_artifact(path: str | Path, evaluation: RetrievalEvaluation) -> Path:
    """Write one stable UTF-8 raw evaluation artifact.

    Parameters
    ----------
    path : str | Path
        Destination whose filename must use the ``.json`` suffix.
    evaluation : RetrievalEvaluation
        Complete run evidence to serialize.

    Returns
    -------
    Path
        Normalized destination path after a successful write.

    Raises
    ------
    ValueError
        If the destination does not end in ``.json`` or the payload contains a
        non-finite number.
    TypeError
        If the payload contains a value JSON cannot encode.
    OSError
        If the parent directory cannot be created or the artifact cannot be written.

    Notes
    -----
    Serialization uses sorted keys, two-space indentation, non-ASCII text preservation,
    and exactly one terminal newline.
    """
    artifact_path = Path(path)
    if artifact_path.suffix != ".json":
        raise ValueError("evaluation artifact path must end in .json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        evaluation.artifact_payload(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    artifact_path.write_text(payload + "\n", encoding="utf-8")
    return artifact_path


async def measure_query_budget(
    queries: Sequence[str],
    retriever: Retriever,
    *,
    k: int = 5,
    query_count: int = QUERY_BUDGET_COUNT,
    budget_seconds: float = QUERY_BUDGET_SECONDS,
    clock: Clock = time.perf_counter_ns,
) -> QueryBudgetMeasurement:
    """Repeat nonempty queries sequentially and assess a wall-clock budget.

    Parameters
    ----------
    queries : Sequence[str]
        Nonempty query pool cycled in its supplied order.
    retriever : Retriever
        Awaitable retrieval callable measured once per repeated query.
    k : int, optional
        Positive hit count requested for every retrieval.
    query_count : int, optional
        Positive number of sequential retrievals to measure.
    budget_seconds : float, optional
        Finite positive upper bound for total elapsed retrieval time.
    clock : Clock, optional
        Monotonic nanosecond clock sampled before and after each retrieval.

    Returns
    -------
    QueryBudgetMeasurement
        Total and distribution evidence plus the inclusive budget decision.

    Raises
    ------
    ValueError
        If query input, counts, budget, or measured clock order is invalid.

    Notes
    -----
    The first query follows the same timing boundary as later queries. No warm-up or
    concurrency is introduced, and retriever exceptions are propagated.
    """
    if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("queries must contain nonblank strings")
    if isinstance(query_count, bool) or not isinstance(query_count, int) or query_count <= 0:
        raise ValueError("query_count must be a positive integer")
    if k <= 0:
        raise ValueError("k must be positive")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")

    previous = clock()
    latencies: list[float] = []
    for index in range(query_count):
        await retriever(queries[index % len(queries)], k)
        current = clock()
        elapsed_ms = (current - previous) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        previous = current

    summary = _latency_summary(latencies)
    total_seconds = summary.total_ms / 1_000
    return QueryBudgetMeasurement(
        query_count=query_count,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
        mean_ms=summary.mean_ms,
        p50_ms=summary.p50_ms,
        p95_ms=summary.p95_ms,
        max_ms=summary.max_ms,
    )


def assess_indexing_budget(
    *,
    target_text_chars: int,
    document_count: int,
    chunk_count: int,
    embedding_provider: str,
    target_phase_seconds: float,
    shared_preparation_seconds: float = 0.0,
    budget_seconds: float = INDEXING_BUDGET_SECONDS,
) -> IndexingBudgetMeasurement:
    """Assess one indexing arm from shared and target-specific durations.

    Parameters
    ----------
    target_text_chars : int
        Positive chunk-size target identifying the corpus arm.
    document_count : int
        Positive number of documents indexed for the arm.
    chunk_count : int
        Positive number of chunks indexed for the arm.
    embedding_provider : str
        Nonblank provider identity attached to the measurement.
    target_phase_seconds : float
        Finite nonnegative duration for target-specific preparation and indexing.
    shared_preparation_seconds : float, optional
        Finite nonnegative manifest-load and parse duration shared across arms.
    budget_seconds : float, optional
        Finite positive standalone indexing limit.

    Returns
    -------
    IndexingBudgetMeasurement
        Supplied evidence, derived standalone duration, and inclusive budget decision.

    Raises
    ------
    ValueError
        If counts, provider identity, durations, or budget are outside their contracts.

    Notes
    -----
    The standalone duration is the sum of shared preparation and the target phase. The
    shared phase is therefore charged to every arm without being re-executed.
    """
    if target_text_chars <= 0 or document_count <= 0 or chunk_count <= 0:
        raise ValueError("indexing counts and target_text_chars must be positive")
    if not embedding_provider.strip():
        raise ValueError("embedding_provider must be nonblank")
    if not math.isfinite(target_phase_seconds) or target_phase_seconds < 0:
        raise ValueError("target_phase_seconds must be finite and nonnegative")
    if not math.isfinite(shared_preparation_seconds) or shared_preparation_seconds < 0:
        raise ValueError("shared_preparation_seconds must be finite and nonnegative")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")
    derived_standalone_seconds = shared_preparation_seconds + target_phase_seconds
    return IndexingBudgetMeasurement(
        target_text_chars=target_text_chars,
        document_count=document_count,
        chunk_count=chunk_count,
        embedding_provider=embedding_provider,
        target_phase_seconds=target_phase_seconds,
        derived_standalone_seconds=derived_standalone_seconds,
        budget_seconds=budget_seconds,
        passed=derived_standalone_seconds <= budget_seconds,
    )


def _indexing_budget_payload(
    shared_preparation: SharedPreparationMeasurement,
    measurements: Sequence[IndexingBudgetMeasurement],
) -> dict[str, object]:
    """Build explicit shared and per-target schema-v2 indexing evidence.

    Parameters
    ----------
    shared_preparation : SharedPreparationMeasurement
        Manifest-load and parse work executed once for the multi-target run.
    measurements : Sequence[IndexingBudgetMeasurement]
        Nonempty target-specific measurements in execution order.

    Returns
    -------
    dict[str, object]
        Shared evidence, serialized arm evidence, and measured multi-target work total.

    Raises
    ------
    ValueError
        If no target measurement is supplied.

    Notes
    -----
    ``measured_multi_target_work_seconds`` counts shared preparation once and adds each
    measured target phase; it does not sum derived standalone durations.
    """
    if not measurements:
        raise ValueError("indexing measurements must not be empty")
    return {
        "shared_preparation": asdict(shared_preparation),
        "arms": [asdict(measurement) for measurement in measurements],
        "measured_multi_target_work_seconds": shared_preparation.total_seconds
        + sum(measurement.target_phase_seconds for measurement in measurements),
    }


def make_retriever(
    session: AsyncSession,
    *,
    strategy: RetrievalStrategy,
    provider: EmbeddingProvider | None,
    lexical_ranker: LexicalRanker | None = None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one explicit retrieval strategy and ranker configuration to a session.

    Parameters
    ----------
    session : AsyncSession
        SQLAlchemy session used by every invocation of the returned callable.
    strategy : RetrievalStrategy
        Retrieval lane to execute: lexical, vector, or hybrid.
    provider : EmbeddingProvider | None
        Query embedding provider required by vector-bearing strategies.
    lexical_ranker : LexicalRanker | None, optional
        Explicit lexical algorithm required by lexical-bearing strategies and forbidden
        for a vector-only strategy.
    bm25_k1 : float | None, optional
        Positive term-frequency saturation value required for BM25 arms.
    bm25_b : float | None, optional
        Length normalization in ``[0, 1]`` required for BM25 arms.
    bm25_idf : BM25Idf | None, optional
        Inverse-document-frequency variant required for BM25 arms.
    candidate_k : int, optional
        Positive hybrid candidate depth, which must also cover each requested ``k``.
    rrf_k : int, optional
        Positive reciprocal-rank-fusion constant used by hybrid retrieval.
    filters : RetrievalFilters | None, optional
        Canonical evidence restrictions passed to every active retrieval component.

    Returns
    -------
    Retriever
        Awaitable callable bound to the supplied session and explicit experiment arm.

    Raises
    ------
    ValueError
        If the strategy, provider, ranker, BM25 values, or retrieval limits form an
        invalid or mislabeled experiment arm.

    Notes
    -----
    All strategies receive the same public query normalization. The returned callable
    rejects a per-call ``k`` greater than ``candidate_k`` before accessing the provider
    or database. The bound session's concurrency constraints remain the caller's
    responsibility. The hybrid arm pins ``route_by_language=False`` so an environment
    flag cannot silently reroute a bound arm; language routing enters an experiment
    only through an explicit ``retrieve`` call.
    """
    if strategy not in {"lexical", "vector", "hybrid"}:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    if strategy == "vector":
        if lexical_ranker is not None:
            raise ValueError("vector retrieval must not name a lexical ranker")
    elif lexical_ranker not in {"ts_rank_cd", "bm25"}:
        raise ValueError(f"{strategy} retrieval requires an explicit lexical ranker")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if strategy in {"vector", "hybrid"} and provider is None:
        raise ValueError(f"{strategy} retrieval requires an embedding provider")
    bm25_values = (bm25_k1, bm25_b, bm25_idf)
    if lexical_ranker == "bm25":
        if any(value is None for value in bm25_values):
            raise ValueError("BM25 retrieval requires explicit k1, b, and idf values")
        assert bm25_k1 is not None and bm25_b is not None and bm25_idf is not None
        if bm25_k1 <= 0:
            raise ValueError("bm25_k1 must be positive")
        if not 0 <= bm25_b <= 1:
            raise ValueError("bm25_b must be between 0 and 1")
    elif any(value is not None for value in bm25_values):
        raise ValueError("BM25 parameters are valid only for BM25 retrieval")

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        """Retrieve normalized hits through the bound experiment arm."""
        if candidate_k < k:
            raise ValueError("candidate_k must be at least k")
        normalized_query = normalize_query(query)
        if strategy == "lexical":
            if lexical_ranker == "bm25":
                assert bm25_k1 is not None and bm25_b is not None and bm25_idf is not None
                return await bm25_search(
                    session,
                    normalized_query,
                    k,
                    filters,
                    k1=bm25_k1,
                    b=bm25_b,
                    idf=bm25_idf,
                )
            return await lexical_search(session, normalized_query, k, filters)
        assert provider is not None
        if strategy == "vector":
            query_vector = await provider.embed_query(normalized_query)
            return await vector_search(session, query_vector, k=k, filters=filters)
        result = await retrieve(
            session,
            normalized_query,
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
            lexical_ranker=lexical_ranker,
            bm25_k1=bm25_k1,
            bm25_b=bm25_b,
            bm25_idf=bm25_idf,
            route_by_language=False,
        )
        return result.hits

    return run


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
    Baseline lookup precedes insertion, and comparability requires both the suite and
    canonical configuration to match. This function does not commit the caller's
    transaction.
    """
    baseline = await latest_comparable_baseline(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
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
        created_at=evaluation.recorded_at,
    )
    if result.id is None:
        raise RuntimeError("persisted evaluation did not receive an id")
    return PersistedEvaluation(
        result_id=result.id,
        baseline_id=baseline.id if baseline is not None else None,
        comparison=comparison,
    )


def load_chunking_filings(*, settings: Settings | None = None) -> tuple[ParsedFiling, ...]:
    """Parse the fixed M3 corpus once for reuse by every chunking arm.

    Parameters
    ----------
    settings : Settings | None, optional
        Explicit corpus settings, or the process settings when omitted.

    Returns
    -------
    tuple[ParsedFiling, ...]
        Deterministically ordered parsed filings shared by the current evaluation run.

    Raises
    ------
    OSError
        If the configured manifest or a filing source cannot be read.
    json.JSONDecodeError
        If the manifest does not contain valid JSON.
    ValueError
        If the manifest is invalid, does not contain exactly 20 entries, or a filing
        cannot satisfy parser contracts.

    Notes
    -----
    Returned parser models are mutable. The evaluation runner shares them read-only
    across chunk targets and builds a fresh immutable ``SeedBatch`` for each target.
    """
    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / "manifest.json")
    return parse_seed_filings(entries, expected_documents=20)


def build_chunking_batch(
    target_text_chars: int,
    *,
    parsed_filings: Sequence[ParsedFiling] | None = None,
    settings: Settings | None = None,
) -> SeedBatch:
    """Build one source-stable corpus arm from new or already parsed filings.

    Parameters
    ----------
    target_text_chars : int
        Soft text-length target for the structure-aware chunker.
    parsed_filings : Sequence[ParsedFiling] | None, optional
        Parsed corpus snapshot to reuse. When omitted, this function preserves the
        independent legacy path and parses the configured manifest itself.
    settings : Settings | None, optional
        Explicit corpus settings used only by the independent path.

    Returns
    -------
    SeedBatch
        Validated records with canonical source spans unchanged.

    Raises
    ------
    OSError
        If independent construction cannot read the manifest or a filing source.
    json.JSONDecodeError
        If the independently loaded manifest does not contain valid JSON.
    ValueError
        If the target, manifest, parser output, chunks, or persistence records violate
        their source and ordering contracts.

    Notes
    -----
    Supplying ``parsed_filings`` bypasses settings and manifest parsing. The shared
    parser models are treated as read-only, and a new batch is returned for each call.
    """
    chunk_config = ChunkConfig(target_text_chars=target_text_chars)

    def chunker(filing: ParsedFiling) -> list[Chunk]:
        """Chunk one parsed filing with the selected target."""
        return chunk_filing(filing, chunk_config)

    if parsed_filings is not None:
        return build_seed_batch_from_filings(parsed_filings, chunker=chunker)

    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / "manifest.json")
    return build_seed_batch(
        entries,
        expected_documents=20,
        chunker=chunker,
    )


async def _create_temporary_corpus_tables(connection: AsyncConnection, dimensions: int) -> None:
    """Create the isolated PostgreSQL schema for one corpus arm.

    Parameters
    ----------
    connection : AsyncConnection
        Dedicated connection whose session-local temporary tables hold the corpus.
    dimensions : int
        Embedding width used by the temporary pgvector column.

    Raises
    ------
    RuntimeError
        If the connected database does not expose the pgvector extension.

    Notes
    -----
    Tables preserve rows across commits but remain scoped to ``connection``. The helper
    commits the temporary DDL before callers bind a session and seed data.
    """
    extension = await connection.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    if extension is None:
        raise RuntimeError("the configured PostgreSQL database does not have pgvector")
    await connection.execute(
        text(
            """
            CREATE TEMP TABLE documents (
                doc_id varchar(32) PRIMARY KEY,
                ticker varchar(16) NOT NULL,
                cik bigint NOT NULL,
                fiscal_year integer NOT NULL,
                form varchar(16) NOT NULL,
                filing_date varchar(10) NOT NULL,
                report_period varchar(10) NOT NULL,
                accession varchar(32) NOT NULL,
                url text NOT NULL,
                parse_status varchar(32) NOT NULL,
                item_index jsonb NOT NULL,
                source_length bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(
        text(
            f"""
            CREATE TEMP TABLE chunks (
                id bigserial PRIMARY KEY,
                doc_id varchar(32) NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                item varchar(8),
                kind varchar(16) NOT NULL,
                ordinal integer NOT NULL,
                body text NOT NULL,
                context_header text NOT NULL,
                index_text text NOT NULL,
                start_char bigint NOT NULL,
                end_char bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL,
                citation text NOT NULL,
                embedding vector({dimensions}),
                content_tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', index_text)
                ) STORED,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (doc_id, ordinal)
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(text("CREATE INDEX ON chunks USING gin (content_tsv)"))
    for statement in (
        """
        CREATE TEMP TABLE chunk_terms (
            chunk_id bigint NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            lexeme text NOT NULL,
            tf integer NOT NULL,
            PRIMARY KEY (chunk_id, lexeme)
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE chunk_lengths (
            chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            dl integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE lexeme_stats (
            lexeme text PRIMARY KEY,
            df integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        "CREATE INDEX ON chunk_terms (lexeme)",
    ):
        await connection.execute(text(statement))
    await connection.commit()


@asynccontextmanager
async def temporary_corpus_session(
    engine: AsyncEngine,
    batch: SeedBatch,
    provider: EmbeddingProvider,
    *,
    target_text_chars: int,
    embedding_provider: str,
    shared_preparation_seconds: float = 0.0,
    clock: Clock = time.perf_counter_ns,
    started_at_ns: int | None = None,
) -> AsyncIterator[tuple[AsyncSession, IndexingBudgetMeasurement]]:
    """Index one isolated corpus arm within a connection-scoped session.

    Parameters
    ----------
    engine : AsyncEngine
        Engine used to acquire the dedicated temporary-corpus connection.
    batch : SeedBatch
        Complete source-stable records for one chunking target.
    provider : EmbeddingProvider
        Provider used to populate every missing temporary embedding.
    target_text_chars : int
        Chunk-size target attached to indexing evidence.
    embedding_provider : str
        Provider identity recorded with the measurement.
    shared_preparation_seconds : float, optional
        Parse-once duration charged to the arm's derived standalone total.
    clock : Clock, optional
        Monotonic nanosecond clock used for target-phase timing.
    started_at_ns : int | None, optional
        Earlier target-phase start, allowing caller-side batch construction to be included;
        otherwise timing begins when this context manager is entered.

    Yields
    ------
    tuple[AsyncSession, IndexingBudgetMeasurement]
        Session containing the indexed temporary corpus and its completed budget evidence.

    Raises
    ------
    RuntimeError
        If pgvector is unavailable or embedding backfill does not cover the full batch.
    ValueError
        If timing or indexing evidence violates the budget measurement contract.

    Notes
    -----
    Term statistics are rebuilt once per chunking arm before embeddings. Context exit
    always closes the session and its connection, which discards all temporary corpus
    state; the caller retains ownership of the engine.
    """
    started = clock() if started_at_ns is None else started_at_ns
    connection = await engine.connect()
    session: AsyncSession | None = None
    try:
        await _create_temporary_corpus_tables(connection, provider.dimensions)
        session = AsyncSession(bind=connection, expire_on_commit=False)
        await persist_seed_batch(session, batch)
        # One rebuild per corpus arm. Every BM25 experiment on this chunking shares
        # it, and the next chunk target gets its own corpus and its own statistics,
        # because df, avgdl, and dl are all properties of a particular chunking.
        await backfill_term_stats(session)
        backfill = await embed_missing_chunks(session, provider)
        if backfill.embedded != len(batch.chunks) or backfill.skipped_stale:
            raise RuntimeError("temporary corpus embedding backfill was incomplete")
        target_phase_seconds = (clock() - started) / 1_000_000_000
        measurement = assess_indexing_budget(
            target_text_chars=target_text_chars,
            document_count=len(batch.documents),
            chunk_count=len(batch.chunks),
            embedding_provider=embedding_provider,
            target_phase_seconds=target_phase_seconds,
            shared_preparation_seconds=shared_preparation_seconds,
        )
        yield session, measurement
    finally:
        if session is not None:
            await session.close()
        await connection.close()


def _positive_int(value: str) -> int:
    """Parse one command-line token as a strictly positive integer.

    Parameters
    ----------
    value : str
        Command-line token supplied by ``argparse``.

    Returns
    -------
    int
        Parsed value when it is greater than zero.

    Raises
    ------
    ValueError
        If ``value`` is not an integer literal.
    argparse.ArgumentTypeError
        If the parsed integer is zero or negative.
    """
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the isolated M3 ablation runner.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Explicit argument tokens, or process arguments when omitted.

    Returns
    -------
    argparse.Namespace
        Parsed experiment matrix, artifact, provider, budget, and persistence options.

    Raises
    ------
    SystemExit
        If help is requested or supplied arguments fail parser validation.
    """
    parser = argparse.ArgumentParser(
        description="Run isolated source-span retrieval ablations and latency budgets."
    )
    parser.add_argument("--suite", default="m3-retrieval-v1")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=("deterministic", "openai"), default="deterministic")
    parser.add_argument("--target-text-chars", type=_positive_int, nargs="+", default=[500, 1200])
    parser.add_argument(
        "--strategies",
        choices=("lexical", "vector", "hybrid"),
        nargs="+",
        default=["lexical", "vector", "hybrid"],
    )
    parser.add_argument(
        "--lexical-rankers",
        choices=("ts_rank_cd", "bm25"),
        nargs="+",
        default=["ts_rank_cd", "bm25"],
        help="Lexical rankers to cross with every lexical and hybrid arm.",
    )
    parser.add_argument("-k", type=_positive_int, default=5)
    parser.add_argument("--candidate-k", type=_positive_int, default=20)
    parser.add_argument("--rrf-k", type=_positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--budget-queries", type=_positive_int, default=QUERY_BUDGET_COUNT)
    parser.add_argument("--persist-results", action="store_true")
    return parser.parse_args(argv)


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the complete parse-once M3 experiment command.

    Parameters
    ----------
    args : argparse.Namespace
        Namespace produced by :func:`arguments`.

    Returns
    -------
    dict[str, Any]
        Comparison table, raw artifact paths, schema-v2 budget evidence, and optional
        persisted-result identities.

    Raises
    ------
    ValueError
        If the requested matrix or retrieval limits are invalid.
    RuntimeError
        If indexing, query-budget measurement, or result persistence is incomplete.
    OSError
        If corpus or artifact files cannot be read or written.

    Notes
    -----
    The manifest is parsed once, while each chunk target receives a fresh ``SeedBatch``
    and temporary PostgreSQL corpus. Raw evaluation artifacts retain schema v1; only the
    budget artifact uses schema v2. The engine is disposed on every exit path.
    """
    from app.db.bootstrap import bootstrap_schema
    from app.evals.ablation import experiment_matrix, run_ablation

    if args.candidate_k < args.k:
        raise ValueError("candidate_k must be at least k")
    targets = sorted(set(args.target_text_chars))
    if not targets:
        raise ValueError("target_text_chars must not be empty")
    settings = get_settings().model_copy(update={"embedding_provider": args.provider})
    provider = get_embedding_provider(settings)
    cases = load_golden_cases(args.golden)
    recorded_at = datetime.now(UTC)
    preparation_started_at_ns = time.perf_counter_ns()
    parsed_filings = load_chunking_filings(settings=settings)
    shared_preparation_seconds = (
        time.perf_counter_ns() - preparation_started_at_ns
    ) / 1_000_000_000
    shared_preparation = SharedPreparationMeasurement(
        operation="manifest-load-and-parse",
        document_count=len(parsed_filings),
        total_seconds=shared_preparation_seconds,
    )
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    all_outcomes = []
    indexing_measurements: list[IndexingBudgetMeasurement] = []
    query_budget: QueryBudgetMeasurement | None = None
    budget_ranker: LexicalRanker | None = None
    try:
        for target_text_chars in targets:
            indexing_started_at_ns = time.perf_counter_ns()
            batch = build_chunking_batch(
                target_text_chars,
                parsed_filings=parsed_filings,
                settings=settings,
            )
            configs = experiment_matrix(
                target_text_chars=(target_text_chars,),
                strategies=tuple(args.strategies),
                lexical_rankers=tuple(dict.fromkeys(args.lexical_rankers)),
                embedding_provider=args.provider,
                dimensions=provider.dimensions,
                k=args.k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
                bm25_k1=settings.bm25_k1,
                bm25_b=settings.bm25_b,
                bm25_idf=settings.bm25_idf,
            )
            async with temporary_corpus_session(
                engine,
                batch,
                provider,
                target_text_chars=target_text_chars,
                embedding_provider=args.provider,
                shared_preparation_seconds=shared_preparation_seconds,
                started_at_ns=indexing_started_at_ns,
            ) as (session, indexing):
                indexing_measurements.append(indexing)

                async def evaluator(config: ExperimentConfig) -> RetrievalEvaluation:
                    """Evaluate one matrix configuration against the active corpus."""
                    retriever = make_retriever(
                        session,
                        strategy=config.strategy,
                        provider=provider,
                        lexical_ranker=config.lexical_ranker,
                        bm25_k1=config.bm25_k1,
                        bm25_b=config.bm25_b,
                        bm25_idf=config.bm25_idf,
                        candidate_k=config.candidate_k,
                        rrf_k=config.rrf_k,
                    )
                    return await evaluate_retriever(
                        cases,
                        retriever,
                        suite=args.suite,
                        config=config.to_dict(),
                        k=config.k,
                        recorded_at=recorded_at,
                    )

                report = await run_ablation(
                    configs,
                    evaluator,
                    artifact_dir=args.artifact_dir,
                    recorded_at=recorded_at,
                )
                all_outcomes.extend(report.outcomes)

                if target_text_chars == targets[-1]:
                    budget_strategy = (
                        "hybrid" if "hybrid" in args.strategies else args.strategies[-1]
                    )
                    budget_ranker = None if budget_strategy == "vector" else args.lexical_rankers[0]
                    budget_retriever = make_retriever(
                        session,
                        strategy=budget_strategy,
                        provider=provider,
                        lexical_ranker=budget_ranker,
                        bm25_k1=settings.bm25_k1 if budget_ranker == "bm25" else None,
                        bm25_b=settings.bm25_b if budget_ranker == "bm25" else None,
                        bm25_idf=settings.bm25_idf if budget_ranker == "bm25" else None,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                    query_budget = await measure_query_budget(
                        [case.question for case in cases],
                        budget_retriever,
                        k=args.k,
                        query_count=args.budget_queries,
                    )

        if query_budget is None:
            raise RuntimeError("query budget was not measured")

        timestamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
        budget_path = args.artifact_dir / f"{timestamp}-budgets.json"
        indexing_payload = _indexing_budget_payload(shared_preparation, indexing_measurements)
        budget_payload = {
            "schema_version": BUDGET_ARTIFACT_SCHEMA_VERSION,
            "recorded_at": _utc_text(recorded_at),
            "measurement_provenance": {
                "embedding_provider": args.provider,
                "budget_lexical_ranker": budget_ranker,
                "budget_bm25": (
                    {
                        "k1": settings.bm25_k1,
                        "b": settings.bm25_b,
                        "idf": settings.bm25_idf,
                    }
                    if budget_ranker == "bm25"
                    else None
                ),
                "corpus_preparation": "parse-once-per-run",
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": args.provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
            "indexing": indexing_payload,
            "query_budget": asdict(query_budget),
        }
        budget_path.parent.mkdir(parents=True, exist_ok=True)
        budget_path.write_text(
            json.dumps(budget_payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        persisted = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                for outcome in all_outcomes:
                    persisted.append(
                        await persist_evaluation(
                            session,
                            outcome.evaluation,
                            raw_artifact_path=outcome.artifact_path,
                        )
                    )
                await session.commit()

        from app.evals.ablation import AblationReport

        combined = AblationReport(outcomes=tuple(all_outcomes))
        return {
            "comparison_table": combined.comparison_markdown(),
            "artifacts": [str(outcome.artifact_path) for outcome in all_outcomes],
            "budget_artifact": str(budget_path),
            "indexing": indexing_payload,
            "query_budget": asdict(query_budget),
            "persisted": [asdict(result) for result in persisted],
        }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    # Run the complete isolated M3 evaluation command directly from this module.
    result = asyncio.run(_run_cli(arguments()))
    print(result["comparison_table"])
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "comparison_table"}, indent=2
        )
    )
