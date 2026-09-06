"""Latency aggregation and budget assessment for one isolated evaluation run."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
import math
import time
from typing import Any

from app.config import BM25Idf, LexicalRanker
from app.evals.arms import BM25Parameters, RetrievalStrategy, Retriever
from app.evals.artifacts import utc_text

type Clock = Callable[[], int]

INDEXING_BUDGET_SECONDS = 300.0
QUERY_BUDGET_COUNT = 200
QUERY_BUDGET_SECONDS = 90.0
BUDGET_ARTIFACT_SCHEMA_VERSION = 2


def query_budget_seconds(query_count: int) -> float:
    """Scale the declared repeated-query allowance to a requested query count.

    The published budget is ``QUERY_BUDGET_SECONDS`` for ``QUERY_BUDGET_COUNT``
    queries. Deriving every other count from that same per-query allowance keeps
    a shortened or lengthened run from asserting a limit it never exercised.

    Raises
    ------
    ValueError
        If ``query_count`` is not a positive integer.
    """
    if isinstance(query_count, bool) or not isinstance(query_count, int) or query_count <= 0:
        raise ValueError("query_count must be a positive integer")
    return QUERY_BUDGET_SECONDS * query_count / QUERY_BUDGET_COUNT


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Aggregate evidence for nonnegative sequential retrieval latencies.

    Summaries use nearest-rank percentiles and retain both the total wall-clock
    measurement and its per-query distribution in milliseconds.
    """

    query_count: int
    total_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class QueryBudgetMeasurement:
    """Wall-clock evidence for a sequential repeated-query budget.

    ``passed`` follows the inclusive total-time boundary, and the latency
    distribution behind that decision is preserved alongside it.
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

    Raises
    ------
    ValueError
        If the operation is blank, no document was prepared, or the duration is
        negative or non-finite.
    """

    operation: str
    document_count: int
    total_seconds: float

    def __post_init__(self) -> None:
        """Reject preparation evidence that cannot be charged to an indexing arm."""
        if not self.operation.strip():
            raise ValueError("operation must be nonblank")
        if self.document_count <= 0:
            raise ValueError("document_count must be positive")
        if not math.isfinite(self.total_seconds) or self.total_seconds < 0:
            raise ValueError("total_seconds must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class IndexingBudgetMeasurement:
    """Per-target indexing evidence with a derived standalone duration.

    Instances add shared corpus preparation to target-specific work and assess
    the resulting total against one inclusive budget boundary.
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
class QueryBudgetArm:
    """The single experiment arm a repeated-query budget was measured on.

    The budget runs on one corpus and one retrieval lane, so the artifact records
    that identity explicitly; without it a p95 cannot be attributed to any of the
    indexed arms it sits beside.
    """

    target_text_chars: int
    strategy: RetrievalStrategy
    lexical_ranker: LexicalRanker | None
    bm25: BM25Parameters | None
    k: int
    candidate_k: int
    rrf_k: int

    def to_dict(self) -> dict[str, Any]:
        """Build JSON-compatible arm provenance for the budget artifact."""
        bm25: dict[str, float | BM25Idf] | None = None
        if self.bm25 is not None:
            k1, b, idf = self.bm25
            bm25 = {"k1": k1, "b": b, "idf": idf}
        return {
            "target_text_chars": self.target_text_chars,
            "strategy": self.strategy,
            "lexical_ranker": self.lexical_ranker,
            "bm25": bm25,
            "k": self.k,
            "candidate_k": self.candidate_k,
            "rrf_k": self.rrf_k,
        }


def latency_summary(values: Sequence[float]) -> LatencySummary:
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


async def measure_query_budget(
    queries: Sequence[str],
    retriever: Retriever,
    *,
    k: int = 5,
    query_count: int = QUERY_BUDGET_COUNT,
    budget_seconds: float | None = None,
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
    budget_seconds : float | None, optional
        Explicit finite positive upper bound for total elapsed time. When omitted
        the bound is derived from ``query_count`` by :func:`query_budget_seconds`,
        so the assessed limit always matches the workload actually measured.
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
    The measured total spans from just before the first retrieval to just after
    the last, so it includes the loop's own sequencing cost. No warm-up or
    concurrency is introduced, and retriever exceptions are propagated.
    """
    if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("queries must contain nonblank strings")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    resolved_budget = (
        query_budget_seconds(query_count) if budget_seconds is None else budget_seconds
    )
    if not math.isfinite(resolved_budget) or resolved_budget <= 0:
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

    summary = latency_summary(latencies)
    total_seconds = summary.total_ms / 1_000
    return QueryBudgetMeasurement(
        query_count=query_count,
        total_seconds=total_seconds,
        budget_seconds=resolved_budget,
        passed=total_seconds <= resolved_budget,
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
    The standalone duration is the sum of shared preparation and the target phase, so
    the shared phase is charged to every arm without being re-executed.
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


def indexing_budget_payload(
    shared_preparation: SharedPreparationMeasurement,
    measurements: Sequence[IndexingBudgetMeasurement],
) -> dict[str, Any]:
    """Build explicit shared and per-target indexing evidence.

    ``measured_multi_target_work_seconds`` counts shared preparation once and adds
    each measured target phase; it does not sum derived standalone durations.

    Raises
    ------
    ValueError
        If no target measurement is supplied.
    """
    if not measurements:
        raise ValueError("indexing measurements must not be empty")
    return {
        "shared_preparation": asdict(shared_preparation),
        "arms": [asdict(measurement) for measurement in measurements],
        "measured_multi_target_work_seconds": shared_preparation.total_seconds
        + sum(measurement.target_phase_seconds for measurement in measurements),
    }


def budget_artifact_payload(
    *,
    recorded_at: datetime,
    embedding_provider: str,
    shared_preparation: SharedPreparationMeasurement,
    indexing: Sequence[IndexingBudgetMeasurement],
    query_budget: QueryBudgetMeasurement,
    query_budget_arm: QueryBudgetArm,
) -> dict[str, Any]:
    """Build the complete budget artifact for one multi-target run.

    Parameters
    ----------
    recorded_at : datetime
        Timezone-aware recording time shared with the run's raw artifacts.
    embedding_provider : str
        Provider identity used for every indexed arm.
    shared_preparation : SharedPreparationMeasurement
        Parse-once work charged to each arm's derived standalone duration.
    indexing : Sequence[IndexingBudgetMeasurement]
        Nonempty per-target indexing evidence in execution order.
    query_budget : QueryBudgetMeasurement
        Repeated-query measurement and its inclusive budget decision.
    query_budget_arm : QueryBudgetArm
        The one corpus and retrieval lane ``query_budget`` was measured on.

    Returns
    -------
    dict[str, Any]
        JSON-compatible evidence pairing every budget decision with the exact
        configuration that produced it.

    Raises
    ------
    ValueError
        If ``recorded_at`` is naive or no indexing measurement is supplied.
    """
    return {
        "schema_version": BUDGET_ARTIFACT_SCHEMA_VERSION,
        "recorded_at": utc_text(recorded_at),
        "measurement_provenance": {
            "embedding_provider": embedding_provider,
            "corpus_preparation": "parse-once-per-run",
            "environment": "isolated-temporary-postgresql",
            "paid_api_calls": embedding_provider != "deterministic",
            "populated_corpus_embeddings_modified": False,
        },
        "indexing": indexing_budget_payload(shared_preparation, indexing),
        "query_budget": {**asdict(query_budget), "arm": query_budget_arm.to_dict()},
    }


def budgets_passed(
    indexing: Sequence[IndexingBudgetMeasurement],
    query_budget: QueryBudgetMeasurement,
) -> bool:
    """Report whether every indexing arm and the repeated-query run stayed in budget."""
    return all(measurement.passed for measurement in indexing) and query_budget.passed
