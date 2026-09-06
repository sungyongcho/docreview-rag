"""Configurable M3 retrieval ablations with stable raw artifact paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Literal

from app.config import LexicalRanker
from app.evals.retrieval_eval import RetrievalEvaluation, write_evaluation_artifact

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type ExperimentEvaluator = Callable[["ExperimentConfig"], Awaitable[RetrievalEvaluation]]

STRATEGY_ORDER = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
DEFAULT_LEXICAL_RANKERS: tuple[LexicalRanker, ...] = ("ts_rank_cd", "bm25")
EXPERIMENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def experiment_name(
    target_text_chars: int,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker | None,
) -> str:
    """Return the arm name, which must survive being used as a filename."""
    stem = f"structure-{target_text_chars}-{strategy}"
    return stem if lexical_ranker is None else f"{stem}-{RANKER_SLUG[lexical_ranker]}"


def sort_key(config: ExperimentConfig) -> tuple[int, int, int, str]:
    """Order arms by corpus, then retrieval path, then lexical ranker."""
    return (
        config.target_text_chars,
        STRATEGY_ORDER[config.strategy],
        -1 if config.lexical_ranker is None else RANKER_ORDER[config.lexical_ranker],
        config.name,
    )


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """One explicit chunking and retrieval experiment arm."""

    name: str
    target_text_chars: int
    strategy: RetrievalStrategy
    embedding_provider: str
    dimensions: int
    lexical_ranker: LexicalRanker | None = None
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = 60

    def __post_init__(self) -> None:
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

    def to_dict(self) -> dict[str, object]:
        """Return stable nested config provenance for artifacts and baselines."""
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": {
                "strategy": self.strategy,
                "lexical_ranker": self.lexical_ranker,
                "k": self.k,
                "candidate_k": self.candidate_k,
                "rrf_k": self.rrf_k,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "dimensions": self.dimensions,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
        }


@dataclass(frozen=True, slots=True)
class AblationOutcome:
    """One evaluated arm and its committed raw artifact path."""

    config: ExperimentConfig
    evaluation: RetrievalEvaluation
    artifact_path: Path


@dataclass(frozen=True, slots=True)
class AblationReport:
    """Deterministically ordered experiment outcomes."""

    outcomes: tuple[AblationOutcome, ...]

    def comparison_markdown(self) -> str:
        """Render a compact comparison table backed by raw artifacts."""
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
    embedding_provider: str = "deterministic",
    dimensions: int = 384,
    k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60,
) -> tuple[ExperimentConfig, ...]:
    """Build the sorted M3 chunking-by-retrieval-by-ranker comparison matrix.

    The ranker axis crosses only the strategies that actually run a lexical query.
    Crossing it with ``vector`` as well would evaluate the same retrieval path once
    per ranker and write two artifacts that differ only in a label they did not
    use, so ``vector`` contributes exactly one arm per chunk target.
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

    configs = []
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
                        k=k,
                        candidate_k=candidate_k,
                        rrf_k=rrf_k,
                    )
                )
    return tuple(sorted(configs, key=sort_key))


def artifact_filename(recorded_at: datetime, config: ExperimentConfig) -> str:
    """Return a UTC timestamped stable artifact filename."""
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
    """Evaluate sorted unique arms and write one raw artifact per arm."""
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
