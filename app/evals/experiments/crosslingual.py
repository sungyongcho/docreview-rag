"""Cross-lingual retrieval arms: the arm model and the measurement of one arm."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf, LexicalRanker, Settings
from app.evals.execution.evaluator import (
    RetrievalEvaluation,
    evaluate_retriever,
    write_evaluation_artifact,
)
from app.evals.execution.models import EvaluationRetrieval
from app.evals.execution.retrievers import (
    Retriever,
    experiment_search_plan,
    make_retriever,
)
from app.evals.golden.bilingual import BilingualSuite
from app.evals.results.identity import ARM_NAME, RANKER_SLUG, STRATEGY_ORDER, artifact_filename
from app.evals.results.scoring import GroupScore, breakdown_by_category
from app.ingestion.parsing.registry import REGISTRIES, registry_for
from app.ingestion.progress import OperationProgressCallback
from app.ingestion.tokens import TARGET_INPUT_TOKENS
from app.llm.completion import LLMProvider
from app.llm.schemas import ProviderBudget
from app.query.language import QueryLanguage
from app.query.translation import QueryTranslation, translate_query
from app.retrieval.embedding.provider import EmbeddingProvider
from app.retrieval.embedding.sbert import MULTILINGUAL_SBERT_MODEL
from app.retrieval.ranking.fusion import DEFAULT_RRF_K
from app.retrieval.search.plan import RetrievalStrategy
from app.retrieval.types import RetrievalFilters

QueryHandling = Literal["direct", "routed", "translated"]
ProviderChoice = Literal["deterministic", "openai", "sbert", "sbert-multi"]

CROSSLINGUAL_SUITE: Final[str] = "m8-crosslingual-v1"

# The matrix measures embedding space,
# retrieval strategy, query language, and query handling at this fixed target.
CROSSLINGUAL_TARGET_TOKENS: Final[int] = TARGET_INPUT_TOKENS

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
    target_tokens: int = CROSSLINGUAL_TARGET_TOKENS
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        """Reject arm shapes whose measured numbers could not be attributed."""
        if self.embedding_provider not in PROVIDER_CHOICES:
            raise ValueError(f"unsupported embedding provider: {self.embedding_provider}")
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must be nonblank")
        if self.language not in LANGUAGE_CHOICES:
            raise ValueError(f"unsupported query language: {self.language}")
        if self.corpus_registry not in REGISTRIES:
            raise ValueError(f"unsupported corpus registry: {self.corpus_registry}")
        if self.handling not in HANDLING_CHOICES:
            raise ValueError(f"unsupported query handling: {self.handling}")
        # Routing decides whether to ask the lexical component at all, so it only
        # means something where both components run. A "routed" vector arm would be
        # the direct vector arm under a label claiming a route it never took.
        if self.handling != "direct" and self.strategy != "hybrid":
            raise ValueError(f"{self.handling} handling requires the hybrid strategy")
        if (self.handling == "translated") != (self.translator_model is not None):
            raise ValueError("a translator model is required exactly for translated handling")
        if self.dimensions <= 0 or self.target_tokens <= 0:
            raise ValueError("dimensions and target_tokens must be positive")
        experiment_search_plan(
            strategy=self.strategy,
            lexical_ranker=self.lexical_ranker,
            bm25_k1=self.bm25_k1,
            bm25_b=self.bm25_b,
            bm25_idf=self.bm25_idf,
            candidate_k=self.candidate_k,
            rrf_k=self.rrf_k,
            route_by_language=self.handling == "routed",
        ).candidate_limit(self.k)
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
                "target_tokens": self.target_tokens,
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


def category_breakdown(evaluation: RetrievalEvaluation) -> tuple[GroupScore, ...]:
    """Slice one evaluation by golden category through the unmodified breakdown."""
    cases = [case.golden for case in evaluation.cases]
    scores = [case.score for case in evaluation.cases if case.score is not None]
    return breakdown_by_category(cases, scores)


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

    async def translated(query: str, k: int) -> EvaluationRetrieval:
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
    on_progress: OperationProgressCallback | None = None,
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
        on_progress=on_progress,
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
