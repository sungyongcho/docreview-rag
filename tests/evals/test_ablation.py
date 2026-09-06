"""Configurable experiment matrix, arm provenance, and artifact orchestration."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1
from app.evals.ablation import ExperimentConfig, experiment_matrix, run_ablation
from app.evals.identity import ARM_NAME
from app.evals.retrieval_eval import evaluate_retriever
from app.evals.types import GoldenCase, GoldenSpan
from app.retrieval.types import ChunkHit

SOURCE_SHA256 = "a" * 64


def golden_case() -> GoldenCase:
    """Build the deterministic positive case shared by these arms."""
    return GoldenCase(
        id="m3c-01",
        question="Where is the source-grounded evidence?",
        category="simple_lookup",
        facet="factual",
        tags=("demo-hero",),
        answers=(
            GoldenSpan(
                doc_id="NVDA-FY2024",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="In the cited span.",
        note="Deterministic ablation fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def hit() -> ChunkHit:
    """Build the single hit that covers the fixture gold span."""
    return ChunkHit(
        chunk_id=1,
        doc_id="NVDA-FY2024",
        item="7",
        kind="text",
        citation="NVDA FY2024 · Item 7",
        start_char=90,
        end_char=210,
        source_sha256=SOURCE_SHA256,
        body="Source-grounded evidence.",
        context_header="NVDA FY2024 · Item 7",
        index_text="NVDA FY2024 · Item 7\n\nSource-grounded evidence.",
        score=1.0,
    )


def test_experiment_matrix_crosses_chunking_retrieval_and_lexical_ranker():
    """Cross every chunk target, retrieval path, and lexical ranker in canonical order."""
    configs = experiment_matrix(
        target_tokens=(2048, 1024),
        strategies=("hybrid", "lexical", "vector"),
        lexical_rankers=("bm25", "ts_rank_cd"),
        embedding_provider="deterministic",
        dimensions=384,
    )

    assert [
        (config.target_tokens, config.strategy, config.lexical_ranker) for config in configs
    ] == [
        (1024, "lexical", "ts_rank_cd"),
        (1024, "lexical", "bm25"),
        (1024, "vector", None),
        (1024, "hybrid", "ts_rank_cd"),
        (1024, "hybrid", "bm25"),
        (2048, "lexical", "ts_rank_cd"),
        (2048, "lexical", "bm25"),
        (2048, "vector", None),
        (2048, "hybrid", "ts_rank_cd"),
        (2048, "hybrid", "bm25"),
    ]


def test_experiment_matrix_names_are_unique_and_filename_safe():
    """Name every arm uniquely with a filename-safe kebab-case slug."""
    configs = experiment_matrix(target_tokens=(1024, 2048))
    names = [config.name for config in configs]

    assert len(set(names)) == len(names) == 10
    assert "structure-1024-lexical-ts-rank-cd" in names
    assert "structure-2048-hybrid-bm25" in names
    for name in names:
        assert ARM_NAME.fullmatch(name)


def test_vector_arm_is_not_duplicated_across_rankers():
    """The vector path never runs a lexical query, so a ranker label would lie."""
    configs = experiment_matrix(
        target_tokens=(1024,),
        strategies=("vector",),
        lexical_rankers=("ts_rank_cd", "bm25"),
    )

    assert len(configs) == 1
    assert configs[0].name == "structure-1024-vector"
    assert configs[0].lexical_ranker is None


def test_matrix_is_sorted_the_same_way_however_the_axes_are_given():
    """Order arms by the matrix contract rather than by axis input order."""
    forward = experiment_matrix(
        target_tokens=(1024, 2048),
        strategies=("lexical", "vector", "hybrid"),
        lexical_rankers=("ts_rank_cd", "bm25"),
    )
    reversed_axes = experiment_matrix(
        target_tokens=(2048, 1024),
        strategies=("hybrid", "vector", "lexical"),
        lexical_rankers=("bm25", "ts_rank_cd"),
    )

    assert [config.name for config in forward] == [config.name for config in reversed_axes]


def test_config_provenance_records_the_ranker_that_produced_the_numbers():
    """Record chunking, retrieval, embedding, and measurement provenance per arm."""
    lexical, _bm25, vector = experiment_matrix(
        target_tokens=(1024,),
        strategies=("lexical", "vector"),
    )

    assert lexical.to_dict() == {
        "name": "structure-1024-lexical-ts-rank-cd",
        "chunking": {
            "strategy": "structure-aware",
            "target_tokens": 1024,
            "golden_identity": "source-sha256-and-half-open-span",
        },
        "retrieval": {
            "strategy": "lexical",
            "lexical_ranker": "ts_rank_cd",
            "k": 5,
            "candidate_k": 20,
            "rrf_k": 60,
        },
        "embedding": {"provider": "deterministic", "dimensions": 384},
        "measurement": {
            "environment": "isolated-temporary-postgresql",
            "corpus_preparation": "parse-once-per-run",
            "paid_api_calls": False,
            "populated_corpus_embeddings_modified": False,
        },
    }
    assert vector.to_dict()["retrieval"]["lexical_ranker"] is None
    assert "bm25" not in lexical.to_dict()["retrieval"]
    assert "bm25" not in vector.to_dict()["retrieval"]


def test_bm25_arms_record_explicit_project_defaults_only_when_used():
    """Carry the project BM25 defaults on BM25 arms and nowhere else."""
    ts_rank, bm25, vector = experiment_matrix(
        target_tokens=(1024,),
        strategies=("lexical", "vector"),
    )

    assert (bm25.bm25_k1, bm25.bm25_b, bm25.bm25_idf) == (
        DEFAULT_BM25_K1,
        DEFAULT_BM25_B,
        DEFAULT_BM25_IDF,
    )
    assert bm25.to_dict()["retrieval"]["bm25"] == {
        "k1": DEFAULT_BM25_K1,
        "b": DEFAULT_BM25_B,
        "idf": DEFAULT_BM25_IDF,
    }
    assert (ts_rank.bm25_k1, ts_rank.bm25_b, ts_rank.bm25_idf) == (None, None, None)
    assert (vector.bm25_k1, vector.bm25_b, vector.bm25_idf) == (None, None, None)


def test_experiment_matrix_propagates_explicit_bm25_parameters():
    """Propagate caller-supplied BM25 parameters into arm provenance."""
    (config,) = experiment_matrix(
        target_tokens=(1024,),
        strategies=("hybrid",),
        lexical_rankers=("bm25",),
        bm25_k1=1.5,
        bm25_b=0.4,
        bm25_idf="robertson",
    )

    assert config.to_dict()["retrieval"]["bm25"] == {
        "k1": 1.5,
        "b": 0.4,
        "idf": "robertson",
    }


def test_matrix_rejects_a_lexical_axis_without_a_ranker():
    """Reject a lexical axis with no ranker or with a repeated ranker."""
    with pytest.raises(ValueError, match="requires a lexical ranker"):
        experiment_matrix(target_tokens=(1024,), strategies=("lexical",), lexical_rankers=())
    with pytest.raises(ValueError, match="must be unique"):
        experiment_matrix(
            target_tokens=(1024,),
            strategies=("lexical",),
            lexical_rankers=("bm25", "bm25"),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Not Stable"},
        {"target_tokens": 0},
        {"strategy": "unknown"},
        {"candidate_k": 4},
        {"lexical_ranker": None},
        {"lexical_ranker": "okapi"},
        {"strategy": "vector"},
    ],
)
def test_experiment_config_rejects_ambiguous_or_inconsistent_values(changes):
    """Reject arm provenance that is malformed or internally contradictory."""
    values = {
        "name": "structure-1024-hybrid",
        "target_tokens": 1024,
        "strategy": "hybrid",
        "embedding_provider": "deterministic",
        "dimensions": 384,
        "lexical_ranker": "bm25",
        "bm25_k1": DEFAULT_BM25_K1,
        "bm25_b": DEFAULT_BM25_B,
        "bm25_idf": DEFAULT_BM25_IDF,
        "k": 5,
        "candidate_k": 20,
        "rrf_k": 60,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        ExperimentConfig(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"bm25_k1": None},
        {"bm25_k1": 0},
        {"bm25_k1": float("inf")},
        {"bm25_b": None},
        {"bm25_b": -0.1},
        {"bm25_b": float("nan")},
        {"bm25_idf": None},
        {"bm25_idf": "unknown"},
    ],
)
def test_bm25_config_rejects_missing_or_invalid_parameters(changes):
    """Reject a BM25 arm whose parameters are missing or out of range."""
    values = {
        "name": "structure-1024-hybrid-bm25",
        "target_tokens": 1024,
        "strategy": "hybrid",
        "embedding_provider": "deterministic",
        "dimensions": 384,
        "lexical_ranker": "bm25",
        "bm25_k1": DEFAULT_BM25_K1,
        "bm25_b": DEFAULT_BM25_B,
        "bm25_idf": DEFAULT_BM25_IDF,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        ExperimentConfig(**values)


@pytest.mark.parametrize("lexical_ranker", [None, "ts_rank_cd"])
def test_non_bm25_config_rejects_bm25_parameters(lexical_ranker):
    """Reject BM25 parameters on an arm that runs no BM25 query."""
    strategy = "vector" if lexical_ranker is None else "lexical"

    with pytest.raises(ValueError, match="only for bm25 arms"):
        ExperimentConfig(
            name=f"structure-1024-{strategy}",
            target_tokens=1024,
            strategy=strategy,
            embedding_provider="deterministic",
            dimensions=384,
            lexical_ranker=lexical_ranker,
            bm25_k1=DEFAULT_BM25_K1,
        )


def test_run_ablation_writes_stable_raw_artifacts_and_comparison_table(tmp_path):
    """Evaluate arms in canonical order, writing one artifact and one table row each."""
    recorded_at = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)
    configs = experiment_matrix(
        target_tokens=(1024, 2048),
        strategies=("lexical",),
        lexical_rankers=("bm25",),
    )

    async def evaluator(config):
        """Evaluate one arm against a fixed hit and a fixed clock."""

        async def retriever(_query, _k):
            """Return the one relevant hit for every query."""
            return [hit()]

        clock_values = iter((0, 1_000_000))
        return await evaluate_retriever(
            [golden_case()],
            retriever,
            suite="m3-test",
            config=config.to_dict(),
            clock=lambda: next(clock_values),
            recorded_at=recorded_at,
        )

    report = asyncio.run(
        run_ablation(
            tuple(reversed(configs)),
            evaluator,
            artifact_dir=tmp_path,
            recorded_at=recorded_at,
        )
    )

    assert [outcome.config.target_tokens for outcome in report.outcomes] == [1024, 2048]
    assert [outcome.artifact_path.name for outcome in report.outcomes] == [
        "20260812T143000Z-structure-1024-lexical-bm25.json",
        "20260812T143000Z-structure-2048-lexical-bm25.json",
    ]
    assert all(outcome.artifact_path.is_file() for outcome in report.outcomes)
    table = report.comparison_markdown()
    assert "| Config | Chunk target (tokens) | Retrieval | Lexical ranker |" in table
    assert "| structure-1024-lexical-bm25 | 1024 | lexical | bm25 | 1.000000 |" in table
    assert "20260812T143000Z-structure-2048-lexical-bm25.json" in table


def test_run_ablation_rejects_duplicate_config_names(tmp_path):
    """Reject repeated arm names before any evaluator runs."""
    config = ExperimentConfig(
        name="same-name",
        target_tokens=1024,
        strategy="lexical",
        embedding_provider="deterministic",
        dimensions=384,
        lexical_ranker="ts_rank_cd",
    )

    async def evaluator(_config):
        """Fail if reached, because name validation must run first."""
        raise AssertionError("duplicate validation must run first")

    with pytest.raises(ValueError, match="names must be unique"):
        asyncio.run(
            run_ablation(
                [config, config],
                evaluator,
                artifact_dir=tmp_path,
                recorded_at=datetime.now(UTC),
            )
        )
