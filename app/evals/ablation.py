"""Define deterministic M3 ablation arms, ordering, and artifact orchestration."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import math
from pathlib import Path
import re
from typing import Literal, get_args

from app.config import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_IDF,
    DEFAULT_BM25_K1,
    BM25Idf,
    LexicalRanker,
)
from app.evals.retrieval_eval import RetrievalEvaluation, write_evaluation_artifact

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type ExperimentEvaluator = Callable[["ExperimentConfig"], Awaitable[RetrievalEvaluation]]

STRATEGY_ORDER = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
DEFAULT_LEXICAL_RANKERS: tuple[LexicalRanker, ...] = ("ts_rank_cd", "bm25")
BM25_IDF_VARIANTS: tuple[BM25Idf, ...] = get_args(BM25Idf)
EXPERIMENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def experiment_name(
    target_text_chars: int,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker | None,
) -> str:
    """Compose the artifact-name stem for one experiment arm.

    Parameters
    ----------
    target_text_chars : int
        Chunk-size target embedded in the name.
    strategy : RetrievalStrategy
        Retrieval path represented by the arm.
    lexical_ranker : LexicalRanker | None
        Lexical ranker to encode, or ``None`` for an arm without lexical retrieval.

    Returns
    -------
    str
        Kebab-style experiment name built from the supplied dimensions.

    Raises
    ------
    KeyError
        If ``lexical_ranker`` has no registered filename slug.

    Notes
    -----
    This helper composes a name but does not validate the chunk target or strategy.
    ``ExperimentConfig`` performs the complete name and cross-field validation.
    """
    stem = f"structure-{target_text_chars}-{strategy}"
    return stem if lexical_ranker is None else f"{stem}-{RANKER_SLUG[lexical_ranker]}"


def sort_key(config: ExperimentConfig) -> tuple[int, int, int, str]:
    """Return the deterministic ordering key for an experiment arm.

    Parameters
    ----------
    config : ExperimentConfig
        Validated arm to position in the comparison matrix.

    Returns
    -------
    tuple[int, int, int, str]
        Key ordered by chunk target, retrieval path, lexical ranker, and arm name.

    Notes
    -----
    The fixed strategy order is lexical, vector, then hybrid. Within lexical and
    hybrid strategies, ``ts_rank_cd`` precedes BM25; the arm name breaks final ties.
    """
    return (
        config.target_text_chars,
        STRATEGY_ORDER[config.strategy],
        -1 if config.lexical_ranker is None else RANKER_ORDER[config.lexical_ranker],
        config.name,
    )


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Represent one validated chunking and retrieval experiment arm.

    Raises
    ------
    ValueError
        If the name is malformed, the chunk target or dimensions are nonpositive, the
        provider is blank, retrieval limits conflict, or strategy, ranker, and BM25
        values form an invalid combination.

    Notes
    -----
    Vector arms cannot declare a lexical ranker, while lexical and hybrid arms must
    declare one. BM25 arms must carry a complete valid parameter set, and other arms
    cannot carry BM25 parameters.
    """

    name: str
    target_text_chars: int
    strategy: RetrievalStrategy
    embedding_provider: str
    dimensions: int
    lexical_ranker: LexicalRanker | None = None
    bm25_k1: float | None = None
    bm25_b: float | None = None
    bm25_idf: BM25Idf | None = None
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = 60

    def __post_init__(self) -> None:
        """Reject contradictory or incomplete experiment provenance."""
        if EXPERIMENT_NAME.fullmatch(self.name) is None:
            raise ValueError("experiment name must be lowercase kebab-case")
        if self.target_text_chars <= 0 or self.dimensions <= 0:
            raise ValueError("chunk target and embedding dimensions must be positive")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if not self.embedding_provider.strip():
            raise ValueError("embedding_provider must be nonblank")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in RANKER_ORDER:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")

        bm25_parameters = (self.bm25_k1, self.bm25_b, self.bm25_idf)
        if self.lexical_ranker != "bm25":
            if any(value is not None for value in bm25_parameters):
                raise ValueError("BM25 parameters are valid only for bm25 arms")
            return
        if any(value is None for value in bm25_parameters):
            raise ValueError("bm25 arms require explicit k1, b, and idf values")
        if (
            isinstance(self.bm25_k1, bool)
            or not isinstance(self.bm25_k1, (int, float))
            or not math.isfinite(self.bm25_k1)
            or self.bm25_k1 <= 0
        ):
            raise ValueError("bm25_k1 must be a finite positive number")
        if (
            isinstance(self.bm25_b, bool)
            or not isinstance(self.bm25_b, (int, float))
            or not math.isfinite(self.bm25_b)
            or not 0 <= self.bm25_b <= 1
        ):
            raise ValueError("bm25_b must be a finite number between 0 and 1")
        if self.bm25_idf not in BM25_IDF_VARIANTS:
            raise ValueError("bm25_idf must be 'lucene' or 'robertson'")

    def to_dict(self) -> dict[str, object]:
        """Build nested experiment provenance for artifacts and baselines.

        Returns
        -------
        dict[str, object]
            JSON-compatible chunking, retrieval, embedding, and measurement metadata.

        Notes
        -----
        Each call creates a new nested mapping. BM25 parameters appear only for an arm
        that actually uses the BM25 lexical ranker, and the paid-API flag is derived
        from ``embedding_provider``.
        """
        retrieval: dict[str, object] = {
            "strategy": self.strategy,
            "lexical_ranker": self.lexical_ranker,
            "k": self.k,
            "candidate_k": self.candidate_k,
            "rrf_k": self.rrf_k,
        }
        if self.lexical_ranker == "bm25":
            retrieval["bm25"] = {
                "k1": self.bm25_k1,
                "b": self.bm25_b,
                "idf": self.bm25_idf,
            }
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": retrieval,
            "embedding": {
                "provider": self.embedding_provider,
                "dimensions": self.dimensions,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "corpus_preparation": "parse-once-per-run",
                "paid_api_calls": self.embedding_provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
        }


@dataclass(frozen=True, slots=True)
class AblationOutcome:
    """Associate one experiment arm with its evaluation and artifact path.

    Notes
    -----
    This record does not validate cross-field consistency or path existence.
    ``run_ablation`` verifies the evaluation provenance and writes the artifact before
    constructing an outcome.
    """

    config: ExperimentConfig
    evaluation: RetrievalEvaluation
    artifact_path: Path


@dataclass(frozen=True, slots=True)
class AblationReport:
    """Preserve experiment outcomes for deterministic comparison rendering.

    Notes
    -----
    Direct construction preserves the supplied tuple order. ``run_ablation`` is the
    boundary that sorts outcomes before creating a report.
    """

    outcomes: tuple[AblationOutcome, ...]

    def comparison_markdown(self) -> str:
        """Render in-memory metrics with links to their raw artifacts.

        Returns
        -------
        str
            Markdown table containing quality metrics, latency, and artifact links.

        Notes
        -----
        Rows retain ``outcomes`` order and artifact paths are rendered as stored; this
        method does not sort outcomes or verify that their paths exist.
        """
        lines = [
            "| Config | Chunk target | Retrieval | Lexical ranker | Recall@k | Hit rate@k "
            "| MRR | P95 ms | Raw |",
            "|---|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for outcome in self.outcomes:
            score = outcome.evaluation.score
            lines.append(
                "| "
                f"{outcome.config.name} | {outcome.config.target_text_chars} | "
                f"{outcome.config.strategy} | {outcome.config.lexical_ranker or '-'} | "
                f"{score.recall_at_k:.6f} | "
                f"{score.hit_rate_at_k:.6f} | {score.mrr:.6f} | "
                f"{outcome.evaluation.latency.p95_ms:.3f} | "
                f"[{outcome.artifact_path.name}]({outcome.artifact_path.as_posix()}) |"
            )
        return "\n".join(lines)


def experiment_matrix(
    *,
    target_text_chars: Sequence[int] = (500, 1200),
    strategies: Sequence[RetrievalStrategy] = ("lexical", "vector", "hybrid"),
    lexical_rankers: Sequence[LexicalRanker] = DEFAULT_LEXICAL_RANKERS,
    bm25_k1: float = DEFAULT_BM25_K1,
    bm25_b: float = DEFAULT_BM25_B,
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
    embedding_provider: str = "deterministic",
    dimensions: int = 384,
    k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60,
) -> tuple[ExperimentConfig, ...]:
    """Build the sorted M3 chunking-by-retrieval-by-ranker matrix.

    Parameters
    ----------
    target_text_chars : Sequence[int]
        Unique chunk-size targets to evaluate.
    strategies : Sequence[RetrievalStrategy]
        Unique retrieval paths to cross with each chunk target.
    lexical_rankers : Sequence[LexicalRanker]
        Unique rankers crossed only with strategies that perform lexical retrieval.
    bm25_k1 : float
        Term-frequency saturation parameter recorded on BM25 arms.
    bm25_b : float
        Document-length normalization parameter recorded on BM25 arms.
    bm25_idf : BM25Idf
        Inverse-document-frequency formula recorded on BM25 arms.
    embedding_provider : str
        Nonblank provider identifier recorded for every arm.
    dimensions : int
        Positive embedding dimensionality recorded for every arm.
    k : int
        Positive final hit count requested from retrieval.
    candidate_k : int
        Candidate count, which must be at least ``k``.
    rrf_k : int
        Positive reciprocal-rank-fusion constant.

    Returns
    -------
    tuple[ExperimentConfig, ...]
        Validated arms in the canonical comparison order.

    Raises
    ------
    ValueError
        If an axis is empty or duplicated, a lexical strategy has no ranker, or any
        generated arm violates ``ExperimentConfig`` invariants.
    KeyError
        If a supplied lexical ranker has no registered filename slug.

    Notes
    -----
    The ranker axis crosses only strategies that execute a lexical query. Vector
    retrieval therefore contributes one arm per chunk target regardless of the
    number of lexical rankers.
    """
    if not target_text_chars or not strategies:
        raise ValueError("experiment matrix axes must not be empty")
    if len(set(target_text_chars)) != len(target_text_chars):
        raise ValueError("chunk targets must be unique")
    if len(set(strategies)) != len(strategies):
        raise ValueError("retrieval strategies must be unique")
    lexical_strategies = [strategy for strategy in strategies if strategy != "vector"]
    if lexical_strategies:
        if not lexical_rankers:
            raise ValueError(f"{lexical_strategies[0]} retrieval requires a lexical ranker")
        if len(set(lexical_rankers)) != len(lexical_rankers):
            raise ValueError("lexical rankers must be unique")

    configs: list[ExperimentConfig] = []
    for target in target_text_chars:
        for strategy in strategies:
            rankers: tuple[LexicalRanker | None, ...] = (
                (None,) if strategy == "vector" else tuple(lexical_rankers)
            )

            for ranker in rankers:
                configs.append(
                    ExperimentConfig(
                        name=experiment_name(target, strategy, ranker),
                        target_text_chars=target,
                        strategy=strategy,
                        embedding_provider=embedding_provider,
                        dimensions=dimensions,
                        lexical_ranker=ranker,
                        bm25_k1=bm25_k1 if ranker == "bm25" else None,
                        bm25_b=bm25_b if ranker == "bm25" else None,
                        bm25_idf=bm25_idf if ranker == "bm25" else None,
                        k=k,
                        candidate_k=candidate_k,
                        rrf_k=rrf_k,
                    )
                )
    return tuple(sorted(configs, key=sort_key))


def artifact_filename(recorded_at: datetime, config: ExperimentConfig) -> str:
    """Build the UTC-timestamped filename for one raw artifact.

    Parameters
    ----------
    recorded_at : datetime
        Timezone-aware recording time encoded in this filename.
    config : ExperimentConfig
        Arm whose validated name identifies the artifact.

    Returns
    -------
    str
        Filename containing a second-resolution UTC timestamp and arm name.

    Raises
    ------
    ValueError
        If ``recorded_at`` is naive or has no UTC offset.

    Notes
    -----
    Equivalent instants in different time zones produce the same timestamp prefix.
    The function creates no file, and second-resolution names are not globally unique.
    """
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{config.name}.json"


async def run_ablation(
    configs: Sequence[ExperimentConfig],
    evaluator: ExperimentEvaluator,
    *,
    artifact_dir: str | Path,
    recorded_at: datetime,
) -> AblationReport:
    """Evaluate unique arms sequentially and persist their raw artifacts.

    Parameters
    ----------
    configs : Sequence[ExperimentConfig]
        Nonempty collection of arms with unique names.
    evaluator : ExperimentEvaluator
        Asynchronous evaluator that returns one result with matching config provenance.
    artifact_dir : str | Path
        Directory in which raw JSON artifacts are written.
    recorded_at : datetime
        Timezone-aware recording time used in every artifact filename.

    Returns
    -------
    AblationReport
        Outcomes ordered by the canonical experiment sort key.

    Raises
    ------
    ValueError
        If configs are empty or names repeat, ``recorded_at`` is naive, or an
        evaluation's config differs from its arm provenance.
    OSError
        If an artifact directory or file cannot be created or written.

    Notes
    -----
    Arms are awaited one at a time in canonical order and each artifact is written
    immediately. Evaluator and serialization failures propagate without rollback, so
    artifacts completed before a later failure remain on disk. Timestamp validation
    occurs after the corresponding evaluator returns, when its filename is built.
    """
    if not configs:
        raise ValueError("ablation configs must not be empty")
    names = [config.name for config in configs]
    if len(names) != len(set(names)):
        raise ValueError("ablation config names must be unique")
    ordered = sorted(configs, key=sort_key)
    directory = Path(artifact_dir)
    outcomes: list[AblationOutcome] = []
    for config in ordered:
        evaluation = await evaluator(config)
        if evaluation.config != config.to_dict():
            raise ValueError(f"evaluation config does not match arm {config.name}")

        path = directory / artifact_filename(recorded_at, config)
        write_evaluation_artifact(path, evaluation)
        outcomes.append(
            AblationOutcome(
                config=config,
                evaluation=evaluation,
                artifact_path=path,
            )
        )
    return AblationReport(outcomes=tuple(outcomes))
