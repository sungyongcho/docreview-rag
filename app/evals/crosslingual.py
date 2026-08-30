"""Cross-lingual retrieval arms, query-path diagnostics, and the parity command."""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
import json
import math
from pathlib import Path
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import BM25Idf, LexicalRanker, Settings, get_settings
from app.evals.arms import (
    LEXICAL_RANKERS,
    RETRIEVAL_STRATEGIES,
    RetrievalStrategy,
    Retriever,
    make_retriever,
    resolve_bm25_parameters,
)
from app.evals.bilingual import KO_GOLDEN_PATH, BilingualSuite, load_bilingual_suites
from app.evals.breakdown import GroupScore, breakdown_by_category
from app.evals.cli import positive_int, unit_ratio
from app.evals.corpus import build_chunking_batch, temporary_corpus_session
from app.evals.identity import ARM_NAME, RANKER_SLUG, STRATEGY_ORDER, artifact_filename
from app.evals.loader import DEFAULT_GOLDEN_PATH
from app.evals.parity import (
    DEFAULT_MIN_RECALL_RATIO,
    LANGUAGE_REGRESSION_TOLERANCES,
    ParityAssessment,
    assess_parity,
    parity_markdown,
)
from app.evals.reporting import markdown_table
from app.evals.retrieval_eval import (
    PersistedEvaluation,
    RetrievalEvaluation,
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.types import GoldenCase
from app.ingestion.registry import REGISTRIES, registry_for
from app.ingestion.seed import DEFAULT_MANIFEST_NAME, EXPECTED_DOCUMENTS
from app.llm.provider import LLMProvider
from app.llm.schemas import ProviderBudget
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.language import QueryLanguage
from app.retrieval.sbert import MULTILINGUAL_SBERT_MODEL
from app.retrieval.translate import QueryTranslation, translate_query
from app.retrieval.types import ChunkHit, RetrievalFilters

QueryHandling = Literal["direct", "routed", "translated"]
ProviderChoice = Literal["deterministic", "openai", "sbert", "sbert-multi"]

CROSSLINGUAL_SUITE: Final[str] = "m8-crosslingual-v1"
DART_CROSSLINGUAL_SUITE: Final[str] = "m10-dart-crosslingual-v1"

# Kept for the committed EDGAR artifacts: the matrix measures only embedding space,
# retrieval strategy, query language, and query handling at this fixed target.
CROSSLINGUAL_TARGET_TEXT_CHARS: Final[int] = 1200

DART_GOLDEN_PATH: Final[Path] = DEFAULT_GOLDEN_PATH.parent / "dart_retrieval.json"
DART_KO_GOLDEN_PATH: Final[Path] = DEFAULT_GOLDEN_PATH.parent / "dart_retrieval_ko.json"


@dataclass(frozen=True, slots=True)
class CorpusProfile:
    """One measured corpus per command run.

    A profile binds everything that changes with the corpus — suite, golden twins,
    manifest, and document count — while the corpus language and chunk target are
    read from the registry adapter, so retuning ``Registry.chunk_target`` cannot
    leave this matrix measuring a corpus the seeding path no longer produces.
    """

    registry: str
    suite: str
    golden: Path
    ko_golden: Path
    manifest_name: str
    expected_documents: int

    @property
    def language(self) -> str:
        """Return the corpus language the registry publishes in."""
        return registry_for(self.registry).language

    @property
    def target_text_chars(self) -> int:
        """Return the registry's measured chunk target."""
        return registry_for(self.registry).chunk_target


CORPUS_PROFILES: Final[dict[str, CorpusProfile]] = {
    "edgar": CorpusProfile(
        registry="sec",
        suite=CROSSLINGUAL_SUITE,
        golden=DEFAULT_GOLDEN_PATH,
        ko_golden=KO_GOLDEN_PATH,
        manifest_name=DEFAULT_MANIFEST_NAME,
        expected_documents=EXPECTED_DOCUMENTS,
    ),
    "dart": CorpusProfile(
        registry="dart",
        suite=DART_CROSSLINGUAL_SUITE,
        golden=DART_GOLDEN_PATH,
        ko_golden=DART_KO_GOLDEN_PATH,
        manifest_name="dart-manifest.json",
        expected_documents=2,
    ),
}
DETERMINISTIC_EMBEDDING_MODEL: Final[str] = "token-hash-384"
PROVIDER_CHOICES: Final[tuple[ProviderChoice, ...]] = (
    "deterministic",
    "openai",
    "sbert",
    "sbert-multi",
)
LANGUAGE_CHOICES: Final[tuple[QueryLanguage, ...]] = ("en", "ko")
HANDLING_CHOICES: Final[tuple[QueryHandling, ...]] = ("direct", "routed", "translated")
# Report order for the two axes this module adds. Membership is decided against the
# choice tuples above and against the shared retrieval vocabulary, never against these
# tables: an ordering entry that is forgotten should change how a matrix reads, not
# make an otherwise valid arm unconstructible.
HANDLING_ORDER: Final[dict[str, int]] = {"direct": 0, "routed": 1, "translated": 2}
LANGUAGE_ORDER: Final[dict[str, int]] = {"en": 0, "ko": 1}


def embedding_identity(provider: ProviderChoice, settings: Settings) -> tuple[str, str]:
    """Map one CLI provider choice onto the Settings provider and the model name.

    ``sbert-multi`` is not a new provider literal. It is the existing ``sbert``
    provider pointed at the multilingual checkpoint, which is natively 384
    dimensions, so the arm changes the vector space without changing the schema.
    """
    if provider == "deterministic":
        return "deterministic", DETERMINISTIC_EMBEDDING_MODEL
    if provider == "openai":
        return "openai", settings.embedding_model
    if provider == "sbert":
        return "sbert", settings.sbert_model
    if provider == "sbert-multi":
        return "sbert", MULTILINGUAL_SBERT_MODEL
    raise ValueError(f"unsupported embedding provider choice: {provider}")


@dataclass(frozen=True, slots=True)
class CrosslingualArm:
    """One measured cross-lingual retrieval arm and its canonical provenance."""

    embedding_provider: ProviderChoice
    embedding_model: str
    strategy: RetrievalStrategy
    language: QueryLanguage
    corpus_registry: str = "sec"
    handling: QueryHandling = "direct"
    lexical_ranker: LexicalRanker | None = None
    bm25_k1: float | None = None
    bm25_b: float | None = None
    bm25_idf: BM25Idf | None = None
    translator_model: str | None = None
    dimensions: int = 384
    target_text_chars: int = CROSSLINGUAL_TARGET_TEXT_CHARS
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        """Reject arm shapes whose measured numbers could not be attributed."""
        if self.embedding_provider not in PROVIDER_CHOICES:
            raise ValueError(f"unsupported embedding provider: {self.embedding_provider}")
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must be nonblank")
        if self.strategy not in RETRIEVAL_STRATEGIES:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if self.language not in LANGUAGE_CHOICES:
            raise ValueError(f"unsupported query language: {self.language}")
        if self.corpus_registry not in REGISTRIES:
            raise ValueError(f"unsupported corpus registry: {self.corpus_registry}")
        if self.handling not in HANDLING_CHOICES:
            raise ValueError(f"unsupported query handling: {self.handling}")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in LEXICAL_RANKERS:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")
        # Routing decides whether to ask the lexical component at all, so it only
        # means something where both components run. A "routed" vector arm would be
        # the direct vector arm under a label claiming a route it never took.
        if self.handling != "direct" and self.strategy != "hybrid":
            raise ValueError(f"{self.handling} handling requires the hybrid strategy")
        if (self.handling == "translated") != (self.translator_model is not None):
            raise ValueError("a translator model is required exactly for translated handling")
        # The same narrowing the ablation matrix and the retriever binder use, so an
        # arm can never be labelled with BM25 parameters its queries did not run under.
        # Checked last so it reports on a shape that is otherwise already coherent.
        resolve_bm25_parameters(self.lexical_ranker, self.bm25_k1, self.bm25_b, self.bm25_idf)
        if self.dimensions <= 0 or self.target_text_chars <= 0:
            raise ValueError("dimensions and target_text_chars must be positive")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if ARM_NAME.fullmatch(self.name) is None:
            raise ValueError("arm name must be lowercase kebab-case")

    @property
    def name(self) -> str:
        """Return the kebab arm name, which must survive being used as a filename."""
        # The EDGAR corpus keeps its historical names; any other corpus is named so
        # the two cells sharing a question language cannot share an artifact file.
        parts = ["xling"]
        if self.corpus_registry != "sec":
            parts.append(self.corpus_registry)
        parts += [self.embedding_provider, self.strategy]
        if self.lexical_ranker is not None:
            parts.append(RANKER_SLUG[self.lexical_ranker])
        if self.handling != "direct":
            parts.append(self.handling)
        parts.append(self.language)
        return "-".join(parts)

    @property
    def corpus_language(self) -> str:
        """Return the corpus language, owned by the registry the arm measures."""
        return registry_for(self.corpus_registry).language

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Order arms by retrieval path, then handling, then language."""
        return (
            STRATEGY_ORDER[self.strategy],
            HANDLING_ORDER[self.handling],
            LANGUAGE_ORDER[self.language],
            self.name,
        )

    def to_config(self) -> dict[str, Any]:
        """Return the canonical config dict consumed by artifacts and baselines.

        The config records the embedding model, query language and handling, disabled
        reranker, and any BM25 parameters so incompatible runs never share a baseline.
        """
        translator = (
            None
            if self.translator_model is None
            else {"provider": "openai", "model": self.translator_model}
        )
        retrieval: dict[str, Any] = {
            "strategy": self.strategy,
            "lexical_ranker": self.lexical_ranker,
            "reranker": None,
            "k": self.k,
            "candidate_k": self.candidate_k,
            "rrf_k": self.rrf_k,
        }
        if self.lexical_ranker == "bm25":
            retrieval["bm25"] = {"k1": self.bm25_k1, "b": self.bm25_b, "idf": self.bm25_idf}
        return {
            "name": self.name,
            "corpus": {
                "registry": self.corpus_registry,
                "language": self.corpus_language,
            },
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": retrieval,
            "embedding": {
                "provider": self.embedding_provider,
                "model": self.embedding_model,
                "dimensions": self.dimensions,
            },
            "query": {
                "language": self.language,
                "handling": self.handling,
                "translator": translator,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider == "openai"
                or self.handling == "translated",
                "populated_corpus_embeddings_modified": False,
            },
        }


@dataclass(frozen=True, slots=True)
class TwinCosine:
    """One twin pair's query-vector cosine under a single embedding provider."""

    case_id: str
    cosine: float


@dataclass(frozen=True, slots=True)
class TwinAlignment:
    """How closely one embedding space places Korean queries beside their twins."""

    provider: str
    pair_count: int
    mean_cosine: float
    min_cosine: float
    max_cosine: float
    pairs: tuple[TwinCosine, ...]


@dataclass(frozen=True, slots=True)
class LexicalCoverage:
    """How often the English lexical index returns nothing for one language."""

    language: QueryLanguage
    case_count: int
    zero_candidate_cases: int
    zero_candidate_rate: float
    mean_candidate_count: float
    zero_candidate_case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LanguageRun:
    """One evaluated arm together with its per-category slice."""

    arm: CrosslingualArm
    evaluation: RetrievalEvaluation
    categories: tuple[GroupScore, ...]
    artifact_path: Path | None = None


@dataclass(slots=True)
class TranslationLog:
    """Record each translated query under the measured arm that produced it."""

    entries: list[tuple[str, str, QueryTranslation]] = field(default_factory=list)

    def record(self, arm_name: str, original: str, translation: QueryTranslation) -> None:
        """Append one translated query in call order, under the arm that ran it."""
        self.entries.append((arm_name, original, translation))

    def payload(self) -> list[dict[str, str]]:
        """Return a JSON-ready record for the run artifact."""
        return [
            {
                "arm": arm_name,
                "original": original,
                "translated": translation.translated_query,
                "source_language": translation.source_language,
            }
            for arm_name, original, translation in self.entries
        ]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Return the cosine of two equal-length nonzero vectors."""
    if len(left) != len(right):
        raise ValueError("cosine requires vectors of equal length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("cosine is undefined for a zero vector")
    return dot / (left_norm * right_norm)


async def twin_query_alignment(
    provider: EmbeddingProvider,
    suite: BilingualSuite,
    *,
    provider_name: str = "unknown",
) -> TwinAlignment:
    """Measure each Korean query's cosine alignment with its English twin.

    This diagnostic exercises the embedding space without a corpus or database.
    """
    pairs = suite.pairs()
    if not pairs:
        raise ValueError("twin alignment requires at least one pair")
    en_vectors = await provider.embed_documents([english.question for english, _ in pairs])
    ko_vectors = await provider.embed_documents([korean.question for _, korean in pairs])
    measured = tuple(
        TwinCosine(case_id=english.id, cosine=_cosine(en_vector, ko_vector))
        for (english, _), en_vector, ko_vector in zip(pairs, en_vectors, ko_vectors, strict=True)
    )
    cosines = [item.cosine for item in measured]
    return TwinAlignment(
        provider=provider_name,
        pair_count=len(measured),
        mean_cosine=sum(cosines) / len(cosines),
        min_cosine=min(cosines),
        max_cosine=max(cosines),
        pairs=measured,
    )


async def lexical_candidate_coverage(
    retriever: Retriever,
    cases: Sequence[GoldenCase],
    *,
    language: QueryLanguage,
    candidate_k: int = 20,
) -> LexicalCoverage:
    """Measure how often one language produces no lexical candidates.

    The injected retriever keeps the diagnostic usable both offline and in a measured
    corpus run.
    """
    if not cases:
        raise ValueError("lexical coverage requires at least one case")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    empty: list[str] = []
    total = 0
    for case in sorted(cases, key=lambda item: item.id):
        hits = await retriever(case.question, candidate_k)
        total += len(hits)
        if not hits:
            empty.append(case.id)
    return LexicalCoverage(
        language=language,
        case_count=len(cases),
        zero_candidate_cases=len(empty),
        zero_candidate_rate=len(empty) / len(cases),
        mean_candidate_count=total / len(cases),
        zero_candidate_case_ids=tuple(empty),
    )


def category_breakdown(evaluation: RetrievalEvaluation) -> tuple[GroupScore, ...]:
    """Slice one evaluation by golden category through the unmodified breakdown."""
    cases = [case.golden for case in evaluation.cases]
    scores = [case.score for case in evaluation.cases if case.score is not None]
    return breakdown_by_category(cases, scores)


def arm_comparison_markdown(runs: Sequence[LanguageRun]) -> str:
    """Render one row per measured arm in deterministic arm order."""
    if not runs:
        raise ValueError("comparison requires at least one run")
    return markdown_table(
        [
            "Arm",
            "Strategy",
            "Handling",
            "Language",
            "Cases",
            "Recall@k",
            "Hit rate@k",
            "MRR",
            "P95 ms",
        ],
        ["left", "left", "left", "left", "right", "right", "right", "right", "right"],
        [
            [
                run.arm.name,
                run.arm.strategy,
                run.arm.handling,
                run.arm.language,
                str(run.evaluation.score.case_count),
                f"{run.evaluation.score.recall_at_k:.6f}",
                f"{run.evaluation.score.hit_rate_at_k:.6f}",
                f"{run.evaluation.score.mrr:.6f}",
                f"{run.evaluation.latency.p95_ms:.3f}",
            ]
            for run in sorted(runs, key=lambda item: item.arm.sort_key)
        ],
    )


def language_category_markdown(runs: Sequence[LanguageRun]) -> str:
    """Join each language run's category slices into one comparison table."""
    if not runs:
        raise ValueError("category table requires at least one run")
    return markdown_table(
        ["Arm", "Language", "Category", "Cases", "Recall@k", "Hit rate@k", "MRR"],
        ["left", "left", "left", "right", "right", "right", "right"],
        [
            [
                run.arm.name,
                run.arm.language,
                group.group,
                str(group.suite.case_count),
                f"{group.suite.recall_at_k:.6f}",
                f"{group.suite.hit_rate_at_k:.6f}",
                f"{group.suite.mrr:.6f}",
            ]
            for run in sorted(runs, key=lambda item: item.arm.sort_key)
            for group in run.categories
        ],
    )


def make_crosslingual_retriever(
    session: AsyncSession,
    arm: CrosslingualArm,
    *,
    provider: EmbeddingProvider | None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind direct, routed, or translated handling to the shared retriever factory."""
    if filters is None or not filters.languages:
        # Every arm pins its corpus language: the filter is what selects the lexical
        # tokenization the rows were indexed with, and it keeps an arm from silently
        # retrieving the other corpus should one database ever hold both.
        base = filters.model_dump() if filters is not None else {}
        filters = RetrievalFilters.model_validate({**base, "languages": (arm.corpus_language,)})
    bound = make_retriever(
        session,
        strategy=arm.strategy,
        provider=provider,
        lexical_ranker=arm.lexical_ranker,
        bm25_k1=arm.bm25_k1,
        bm25_b=arm.bm25_b,
        bm25_idf=arm.bm25_idf,
        candidate_k=arm.candidate_k,
        rrf_k=arm.rrf_k,
        # A translated arm sends the corpus language downstream, so routing it would
        # skip the lexical component the translation exists to make usable.
        route_by_language=arm.handling == "routed",
        filters=filters,
    )
    if arm.handling != "translated":
        return bound
    if llm_provider is None or provider_budget is None:
        raise ValueError("translated handling requires an LLM provider and a budget")
    bound_llm_provider = llm_provider
    bound_provider_budget = provider_budget

    async def translated(query: str, k: int) -> Sequence[ChunkHit]:
        """Translate into the corpus language first, recording what was sent."""
        translation = await translate_query(
            query,
            llm_provider=bound_llm_provider,
            provider_budget=bound_provider_budget,
            target_language=arm.corpus_language,
        )
        if translation_log is not None:
            translation_log.record(arm.name, query, translation)
        return await bound(translation.translated_query, k)

    return translated


async def run_arm(
    session: AsyncSession,
    arm: CrosslingualArm,
    suite: BilingualSuite,
    *,
    provider: EmbeddingProvider | None,
    suite_name: str = CROSSLINGUAL_SUITE,
    artifact_dir: str | Path | None = None,
    recorded_at: datetime | None = None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
) -> LanguageRun:
    """Evaluate one language arm and optionally persist its raw artifact."""
    moment = recorded_at or datetime.now(UTC)
    retriever = make_crosslingual_retriever(
        session,
        arm,
        provider=provider,
        llm_provider=llm_provider,
        provider_budget=provider_budget,
        translation_log=translation_log,
    )
    evaluation = await evaluate_retriever(
        suite.cases(arm.language),
        retriever,
        suite=suite_name,
        config=arm.to_config(),
        k=arm.k,
        recorded_at=moment,
    )
    artifact_path = None
    if artifact_dir is not None:
        artifact_path = write_evaluation_artifact(
            Path(artifact_dir) / artifact_filename(moment, arm.name),
            evaluation,
        )
    return LanguageRun(
        arm=arm,
        evaluation=evaluation,
        categories=category_breakdown(evaluation),
        artifact_path=artifact_path,
    )


def _parity_identity(arm: CrosslingualArm) -> tuple[str, str, str, str | None]:
    """Return the key the two language slices of one measured arm must share.

    The corpus registry is part of the key: without it, the four cells of a
    question-language x corpus matrix would collapse onto two slots and half the
    measured runs would be silently overwritten before assessment.
    """
    return (arm.corpus_registry, arm.strategy, arm.handling, arm.lexical_ranker)


def gateable_matrix(arms: Sequence[CrosslingualArm]) -> bool:
    """Report whether the requested matrix can produce a pair the gate may judge.

    Decidable from the arms alone, so ``--gate`` on a matrix that could never be gated
    is refused before a corpus is parsed rather than after every arm has been measured
    and, with a paid provider, paid for.
    """
    languages: dict[tuple[str, str, str, str | None], set[str]] = {}
    for arm in arms:
        if arm.strategy == "hybrid" and arm.handling != "direct":
            languages.setdefault(_parity_identity(arm), set()).add(arm.language)
    return any(covered == set(LANGUAGE_CHOICES) for covered in languages.values())


def parity_pairs(
    runs: Sequence[LanguageRun],
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Assess parity for every arm that was measured in both languages."""
    by_identity: dict[tuple[str, str, str, str | None], dict[str, LanguageRun]] = {}
    for run in runs:
        by_identity.setdefault(_parity_identity(run.arm), {})[run.arm.language] = run
    assessments: list[tuple[CrosslingualArm, ParityAssessment]] = []
    ordered = sorted(
        by_identity,
        key=lambda key: (key[0], STRATEGY_ORDER[key[1]], HANDLING_ORDER[key[2]], key[3] or ""),
    )
    for identity in ordered:
        slices = by_identity[identity]
        if set(slices) != {"en", "ko"}:
            continue
        assessments.append(
            (
                slices["ko"].arm,
                assess_parity(
                    slices["en"].evaluation,
                    slices["ko"].evaluation,
                    min_recall_ratio=min_recall_ratio,
                    native_language=slices["ko"].arm.corpus_language,
                ),
            )
        )
    return tuple(assessments)


def gated_assessments(
    assessments: Sequence[tuple[CrosslingualArm, ParityAssessment]],
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Select language-aware hybrid arms whose parity can gate shipping."""
    return tuple(
        (arm, assessment)
        for arm, assessment in assessments
        if arm.strategy == "hybrid" and arm.handling != "direct"
    )


def gate_verdict(
    gated: Sequence[tuple[CrosslingualArm, ParityAssessment]],
    persisted: Sequence[tuple[CrosslingualArm, PersistedEvaluation]],
    *,
    enabled: bool,
    require_baseline: bool = False,
) -> dict[str, Any]:
    """Combine parity and per-language regression into one gate verdict.

    Parameters
    ----------
    gated : Sequence[tuple[CrosslingualArm, ParityAssessment]]
        Shipping arms whose ko/en ratio the gate may judge.
    persisted : Sequence[tuple[CrosslingualArm, PersistedEvaluation]]
        Runs compared against their own stored baseline, empty when the command did
        not persist results.
    enabled : bool
        Whether ``--gate`` was requested, recorded so a reported verdict says whether
        anything depended on it.

    Returns
    -------
    dict[str, Any]
        Component results, their arm names, and the combined decision. Regression is
        ``None`` when no persisted baseline comparison ran.
    """
    parity_passed = all(assessment.passed for _, assessment in gated)
    regression_passed = all(result.passed for _, result in persisted) if persisted else None
    # A missing baseline passes by default (there is nothing to regress against),
    # but it is reported by name so a silently reset history is visible in every
    # verdict, and --require-baseline turns it into a failure.
    first_runs = [arm.name for arm, result in persisted if result.comparison is None]
    baseline_ok = not (require_baseline and first_runs)
    return {
        "enabled": enabled,
        "parity_arms": [arm.name for arm, _ in gated],
        "regression_arms": [arm.name for arm, _ in persisted],
        "regression_first_runs": first_runs,
        "parity_passed": parity_passed,
        "regression_passed": regression_passed,
        "passed": parity_passed and regression_passed is not False and baseline_ok,
    }


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the cross-lingual measurement command."""
    parser = argparse.ArgumentParser(
        description="Measure retrieval on Korean and English twin queries and gate parity."
    )
    parser.add_argument(
        "--corpus",
        choices=tuple(CORPUS_PROFILES),
        default="edgar",
        help="Corpus cell to measure; suite, goldens, manifest, and chunk target follow it.",
    )
    parser.add_argument("--suite", default=None)
    parser.add_argument("--golden", type=Path, default=None)
    parser.add_argument("--ko-golden", type=Path, default=None)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=PROVIDER_CHOICES, default="deterministic")
    parser.add_argument(
        "--languages",
        choices=LANGUAGE_CHOICES,
        nargs="+",
        default=list(LANGUAGE_CHOICES),
    )
    parser.add_argument(
        "--strategies",
        choices=RETRIEVAL_STRATEGIES,
        nargs="+",
        default=list(RETRIEVAL_STRATEGIES),
    )
    parser.add_argument(
        "--handling",
        choices=HANDLING_CHOICES,
        nargs="+",
        default=["direct"],
        help="Query-path variants to cross with every hybrid arm.",
    )
    parser.add_argument("--lexical-ranker", choices=LEXICAL_RANKERS, default="ts_rank_cd")
    parser.add_argument("--translator-model", default="gpt-4.1-mini")
    parser.add_argument("-k", type=positive_int, default=5)
    parser.add_argument("--candidate-k", type=positive_int, default=20)
    parser.add_argument("--rrf-k", type=positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--min-recall-ratio", type=unit_ratio, default=DEFAULT_MIN_RECALL_RATIO)
    parser.add_argument("--persist-results", action="store_true")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Exit nonzero when a shipping arm fails the ko/en recall parity floor.",
    )
    parser.add_argument(
        "--require-baseline",
        action="store_true",
        help="Fail the gate when a persisted arm has no comparable stored baseline.",
    )
    parsed = parser.parse_args(argv)
    # Rejected here rather than inside CrosslingualArm, so an inconsistent depth cannot
    # fail after the provider is built and both golden suites are loaded.
    if parsed.candidate_k < parsed.k:
        parser.error("--candidate-k must be at least -k")
    profile = CORPUS_PROFILES[parsed.corpus]
    if parsed.suite is None:
        parsed.suite = profile.suite
    if parsed.golden is None:
        parsed.golden = profile.golden
    if parsed.ko_golden is None:
        parsed.ko_golden = profile.ko_golden
    return parsed


def build_arms(
    args: argparse.Namespace,
    embedding_model: str,
    *,
    settings: Settings | None = None,
) -> tuple[CrosslingualArm, ...]:
    """Expand parsed axes into sorted arms with explicit BM25 provenance."""
    resolved = settings if settings is not None else get_settings()
    profile = CORPUS_PROFILES[args.corpus]
    languages = list(dict.fromkeys(args.languages))
    strategies = list(dict.fromkeys(args.strategies))
    handlings = list(dict.fromkeys(args.handling))
    arms: list[CrosslingualArm] = []
    for strategy in strategies:
        ranker = None if strategy == "vector" else args.lexical_ranker
        bm25 = (
            (resolved.bm25_k1, resolved.bm25_b, resolved.bm25_idf)
            if ranker == "bm25"
            else (None, None, None)
        )
        for handling in handlings:
            if handling != "direct" and strategy != "hybrid":
                continue
            for language in languages:
                arms.append(
                    CrosslingualArm(
                        embedding_provider=args.provider,
                        embedding_model=embedding_model,
                        strategy=strategy,
                        language=language,
                        corpus_registry=profile.registry,
                        handling=handling,
                        lexical_ranker=ranker,
                        bm25_k1=bm25[0],
                        bm25_b=bm25[1],
                        bm25_idf=bm25[2],
                        translator_model=(
                            args.translator_model if handling == "translated" else None
                        ),
                        target_text_chars=profile.target_text_chars,
                        k=args.k,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                )
    if not arms:
        raise ValueError("the requested matrix contains no arms")
    return tuple(sorted(arms, key=lambda arm: arm.sort_key))


TRANSLATION_MAX_INPUT_TOKENS: Final[int] = 2_000
TRANSLATION_MAX_OUTPUT_TOKENS: Final[int] = 400


def translation_boundary(model_name: str, settings: Settings) -> tuple[LLMProvider, ProviderBudget]:
    """Build the paid translation provider and the budget one query may spend.

    The SDK is imported here rather than at module scope so a matrix with no translated
    arm never loads it. The key travels through ``Settings`` exactly as it does for the
    embedding provider, which keeps a configured-but-unexported ``.env`` key working and
    keeps every paid boundary in this command sourced the same way.
    """
    from app.llm.provider import OpenAILLMProvider
    from app.llm.schemas import TokenPricing

    provider = OpenAILLMProvider(
        model_name=model_name,
        api_key=(settings.openai_api_key.get_secret_value() if settings.openai_api_key else None),
    )
    budget = ProviderBudget(
        max_input_tokens=TRANSLATION_MAX_INPUT_TOKENS,
        max_output_tokens=TRANSLATION_MAX_OUTPUT_TOKENS,
        max_cost_usd=Decimal("0.05"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0.4"),
            output_per_million_usd=Decimal("1.6"),
        ),
    )
    return provider, budget


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    """Measure the requested matrix in one isolated corpus and assess parity.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command carrying the provider, matrix axes, artifact directory, and
        gate selection.

    Returns
    -------
    dict[str, Any]
        Rendered tables plus the JSON-ready diagnostics, artifacts, persistence rows,
        and gate verdict printed by ``main``.

    Raises
    ------
    RuntimeError
        If ``--gate`` is requested for a matrix that measured no hybrid arm with
        routed or translated handling in both languages.
    """
    from app.db.bootstrap import bootstrap_schema

    settings_provider, embedding_model = embedding_identity(args.provider, get_settings())
    settings = get_settings().model_copy(
        update={"embedding_provider": settings_provider, "sbert_model": embedding_model}
        if settings_provider == "sbert"
        else {"embedding_provider": settings_provider}
    )
    provider = get_embedding_provider(settings)
    profile = CORPUS_PROFILES[args.corpus]
    manifest_path = settings.corpus_dir / profile.manifest_name
    suite = load_bilingual_suites(args.golden, args.ko_golden, manifest_path=manifest_path)
    arms = build_arms(args, embedding_model, settings=settings)
    # Refused here, not after the matrix has been measured: the answer depends only on
    # the requested axes, and --handling defaults to direct, so plain --gate always
    # takes this path.
    if args.gate and not gateable_matrix(arms):
        raise ValueError(
            "--gate requires a hybrid arm with routed or translated handling in both languages"
        )
    recorded_at = datetime.now(UTC)

    llm_provider = None
    provider_budget = None
    if any(arm.handling == "translated" for arm in arms):
        llm_provider, provider_budget = translation_boundary(args.translator_model, settings)

    alignment = await twin_query_alignment(provider, suite, provider_name=args.provider)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    runs: list[LanguageRun] = []
    coverage: list[LexicalCoverage] = []
    translations = TranslationLog()
    try:
        target_text_chars = profile.target_text_chars
        batch = build_chunking_batch(
            target_text_chars,
            settings=settings,
            manifest_name=profile.manifest_name,
            expected_documents=profile.expected_documents,
        )
        async with temporary_corpus_session(
            engine,
            batch,
            provider,
            target_text_chars=target_text_chars,
            embedding_provider=args.provider,
        ) as (session, indexing):
            probe_bm25 = args.lexical_ranker == "bm25"
            lexical_probe = make_retriever(
                session,
                strategy="lexical",
                provider=None,
                lexical_ranker=args.lexical_ranker,
                bm25_k1=settings.bm25_k1 if probe_bm25 else None,
                bm25_b=settings.bm25_b if probe_bm25 else None,
                bm25_idf=settings.bm25_idf if probe_bm25 else None,
                candidate_k=args.candidate_k,
                # The probe pins the corpus language exactly as the measured arms
                # do: the filter selects the lexical tokenization the rows were
                # indexed with.
                filters=RetrievalFilters(languages=(profile.language,)),
            )
            for language in dict.fromkeys(args.languages):
                coverage.append(
                    await lexical_candidate_coverage(
                        lexical_probe,
                        suite.cases(language),
                        language=language,
                        candidate_k=args.candidate_k,
                    )
                )
            for arm in arms:
                runs.append(
                    await run_arm(
                        session,
                        arm,
                        suite,
                        provider=provider,
                        suite_name=args.suite,
                        artifact_dir=args.artifact_dir,
                        recorded_at=recorded_at,
                        llm_provider=llm_provider,
                        provider_budget=provider_budget,
                        translation_log=translations,
                    )
                )

        assessments = parity_pairs(runs, min_recall_ratio=args.min_recall_ratio)
        gated = gated_assessments(assessments)

        persisted: list[tuple[CrosslingualArm, PersistedEvaluation]] = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as db_session:
                for run in runs:
                    if run.artifact_path is None:
                        continue
                    result = await persist_evaluation(
                        db_session,
                        run.evaluation,
                        raw_artifact_path=run.artifact_path,
                        tolerances=LANGUAGE_REGRESSION_TOLERANCES,
                    )
                    persisted.append((run.arm, result))
                await db_session.commit()

        return {
            "comparison_table": arm_comparison_markdown(runs),
            "category_table": language_category_markdown(runs),
            "parity_tables": [parity_markdown(assessment) for _, assessment in assessments],
            "twin_alignment": {
                "provider": alignment.provider,
                "pair_count": alignment.pair_count,
                "mean_cosine": alignment.mean_cosine,
                "min_cosine": alignment.min_cosine,
                "max_cosine": alignment.max_cosine,
            },
            "lexical_coverage": [asdict(item) for item in coverage],
            "indexing": asdict(indexing),
            "translations": translations.payload(),
            "artifacts": [str(run.artifact_path) for run in runs if run.artifact_path],
            # ``to_dict`` rather than ``asdict``: the regression verdict lives on
            # properties, so ``asdict`` would report a comparison with no decision.
            # The arm name is carried alongside it, so a failing verdict names the
            # slice that failed instead of leaving a positional join to the reader.
            "persisted": [{"arm": arm.name} | result.to_dict() for arm, result in persisted],
            "gate": gate_verdict(
                gated,
                persisted,
                enabled=bool(args.gate),
                require_baseline=bool(args.require_baseline),
            ),
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the cross-lingual measurement command and honour the parity gate."""
    args = arguments()
    result = asyncio.run(_run_cli(args))
    print(result["comparison_table"])
    print()
    print(result["category_table"])
    for table in result["parity_tables"]:
        print()
        print(table)
    print()
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"comparison_table", "category_table", "parity_tables"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.gate and not result["gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
