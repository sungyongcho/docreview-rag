"""Cross-lingual command: arguments, corpus profiles, arm expansion, and the paid boundary."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pydantic import SecretStr
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
import app.evals.crosslingual as crosslingual
from app.evals.crosslingual import arguments, build_arms
from app.evals.crosslingual_arms import CROSSLINGUAL_SUITE, CROSSLINGUAL_TARGET_TOKENS, run_arm
from app.evals.crosslingual_diagnostics import gateable_matrix
from app.ingestion.manifest import Manifest
from app.llm.provider import OpenAILLMProvider
from tests.evals.crosslingual_support import arm, hit, scripted, suite
from tests.evals.support import EVALUATION_RECORDED_AT


def test_command_line_defaults_and_flags_match_the_documented_shape():
    """Expose stable defaults and accept explicit cross-lingual matrix flags."""
    defaults = arguments([])

    assert defaults.provider == "deterministic"
    assert defaults.languages == ["en", "ko"]
    assert defaults.strategies == ["lexical", "vector", "hybrid"]
    assert defaults.handling == ["direct"]
    assert defaults.artifact_dir.as_posix() == "data/eval_runs"
    assert defaults.persist_results is False
    assert defaults.gate is False
    assert defaults.min_recall_ratio == pytest.approx(0.85)

    args = arguments(
        [
            "--provider",
            "sbert-multi",
            "--languages",
            "en",
            "ko",
            "--strategies",
            "hybrid",
            "--handling",
            "direct",
            "routed",
            "--artifact-dir",
            "/tmp/runs",
            "--persist-results",
            "--gate",
        ]
    )

    assert (args.provider, args.strategies, args.handling) == (
        "sbert-multi",
        ["hybrid"],
        ["direct", "routed"],
    )
    assert args.persist_results is True
    assert args.gate is True


def test_the_translation_boundary_resolves_its_deferred_sdk_import():
    """Build the paid provider and budget through the import _run_cli defers."""
    # _run_cli needs a corpus and a database and no test executes it, so the deferred
    # import inside it is invisible to both the linter and the suite. Building the
    # boundary here is what makes a moved or renamed SDK symbol fail a test rather
    # than every invocation of the command.
    provider, budget = crosslingual.translation_boundary(
        "gpt-5.6-luna", Settings(openai_api_key_dev=SecretStr("sk-not-a-real-key"))
    )
    try:
        assert provider.model_name == "gpt-5.6-luna"
        assert budget.max_input_tokens == crosslingual.TRANSLATION_MAX_INPUT_TOKENS
        assert budget.max_output_tokens == crosslingual.TRANSLATION_MAX_OUTPUT_TOKENS
    finally:
        asyncio.run(cast(OpenAILLMProvider, provider).aclose())


def test_run_arm_records_the_suite_the_command_was_given(monkeypatch):
    """Stamp the requested suite on the artifact, not the module default."""
    scripted(monkeypatch, {"en": [hit(1, start=100)], "ko": []})

    # Suite identity is half of the baseline key, so a run isolated under its own name
    # must not write into the shipped suite's regression history.
    measured = asyncio.run(
        run_arm(
            cast(AsyncSession, SimpleNamespace()),
            arm(),
            suite(),
            provider=None,
            suite_name="my-isolated-suite",
            recorded_at=EVALUATION_RECORDED_AT,
        )
    )

    assert measured.evaluation.suite == "my-isolated-suite"
    assert arguments([]).suite == CROSSLINGUAL_SUITE


def test_the_gate_is_refused_before_a_corpus_when_the_matrix_cannot_be_gated():
    """Decide gate feasibility from the requested axes alone."""
    # --handling defaults to direct, so plain --gate can never be judged; refusing it
    # only after indexing would spend the whole matrix on a run destined to fail.
    assert gateable_matrix(build_arms(arguments([]), "token-hash-384", target_tokens=2048)) is False
    assert (
        gateable_matrix(
            build_arms(
                arguments(["--handling", "routed", "--languages", "en"]),
                "token-hash-384",
                target_tokens=2048,
            )
        )
        is False
    )
    assert (
        gateable_matrix(
            build_arms(arguments(["--handling", "routed"]), "token-hash-384", target_tokens=2048)
        )
        is True
    )


def test_the_command_rejects_a_candidate_pool_shallower_than_k_during_parsing():
    """Reject an inconsistent depth at parse time, not after the suites are loaded."""
    with pytest.raises(SystemExit) as exit_info:
        arguments(["-k", "10", "--candidate-k", "5"])

    assert exit_info.value.code == 2


def test_the_command_rejects_an_impossible_parity_floor_before_measuring_anything():
    """Reject an out-of-range floor during parsing, not after the matrix has run."""
    with pytest.raises(SystemExit) as exit_info:
        arguments(["--min-recall-ratio", "1.5"])

    assert exit_info.value.code == 2
    assert arguments(["--min-recall-ratio", "1"]).min_recall_ratio == pytest.approx(1.0)


def test_build_arms_gives_a_bm25_matrix_the_parameters_its_binder_demands():
    """Source BM25 values from settings for a BM25 matrix and omit them otherwise."""
    settings = Settings(bm25_k1=1.5, bm25_b=0.5, bm25_idf="robertson")
    args = arguments(["--strategies", "vector", "hybrid", "--lexical-ranker", "bm25"])

    built = build_arms(args, "token-hash-384", target_tokens=2048, settings=settings)
    by_strategy = {arm.strategy: arm for arm in built}

    assert by_strategy["hybrid"].to_config()["retrieval"]["bm25"] == {
        "k1": 1.5,
        "b": 0.5,
        "idf": "robertson",
    }
    # A vector arm runs no lexical query, so it must carry no BM25 provenance at all.
    assert by_strategy["vector"].bm25_k1 is None
    assert "bm25" not in by_strategy["vector"].to_config()["retrieval"]

    default = build_arms(
        arguments(["--strategies", "hybrid"]),
        "token-hash-384",
        target_tokens=2048,
        settings=settings,
    )
    assert "bm25" not in default[0].to_config()["retrieval"]


def test_build_arms_crosses_handling_only_with_the_hybrid_strategy():
    """Cross routed handling only with hybrid arms and deduplicate axes."""
    args = arguments(
        [
            "--strategies",
            "lexical",
            "vector",
            "hybrid",
            "--handling",
            "direct",
            "routed",
            "--languages",
            "ko",
            "en",
            "en",
        ]
    )

    arms = build_arms(args, "token-hash-384", target_tokens=2048)

    assert [built.name for built in arms] == [
        "xling-deterministic-lexical-ts-rank-cd-en",
        "xling-deterministic-lexical-ts-rank-cd-ko",
        "xling-deterministic-vector-en",
        "xling-deterministic-vector-ko",
        "xling-deterministic-hybrid-ts-rank-cd-en",
        "xling-deterministic-hybrid-ts-rank-cd-ko",
        "xling-deterministic-hybrid-ts-rank-cd-routed-en",
        "xling-deterministic-hybrid-ts-rank-cd-routed-ko",
    ]
    assert all(built.target_tokens == CROSSLINGUAL_TARGET_TOKENS for built in arms)
    assert all(built.to_config()["retrieval"]["reranker"] is None for built in arms)


def test_corpus_argument_resolves_suite_goldens_and_chunk_target():
    """--corpus dart binds the DART suite, goldens, manifest, and shared token target."""
    args = crosslingual.arguments(["--corpus", "dart"])

    assert args.suite == crosslingual.DART_CROSSLINGUAL_SUITE
    assert args.golden.name == "dart_retrieval.json"
    assert args.ko_golden.name == "dart_retrieval_ko.json"
    built = crosslingual.build_arms(args, "token-hash-384", target_tokens=2048, settings=Settings())
    assert {arm.corpus_registry for arm in built} == {"dart"}
    assert {arm.target_tokens for arm in built} == {2048}

    edgar_args = crosslingual.arguments([])
    assert edgar_args.suite == CROSSLINGUAL_SUITE
    assert edgar_args.golden.name == "retrieval.json"
    edgar_built = crosslingual.build_arms(
        edgar_args, "token-hash-384", target_tokens=2048, settings=Settings()
    )
    assert {arm.target_tokens for arm in edgar_built} == {2048}


@pytest.mark.parametrize("corpus", ["edgar", "dart"])
def test_each_corpus_profile_selects_only_its_own_registry_from_the_shipped_manifest(corpus):
    """--corpus reads a manifest selection that exists and holds only that registry's filings."""
    profile = crosslingual.CORPUS_PROFILES[corpus]
    corpus_root = Path("data/corpus")

    selected = Manifest.read(corpus_root / profile.manifest_name).selected_sources(
        profile.selection_id, corpus_root
    )

    assert selected
    assert {source.document.registry for source in selected} == {profile.registry}


def test_crosslingual_metadata_records_the_effective_model_target():
    """Report the actual planned size when a model constrains the corpus default."""
    built = build_arms(arguments([]), "small-model", target_tokens=16)
    assert {arm.target_tokens for arm in built} == {16}
