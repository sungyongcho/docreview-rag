"""Golden suite catalog metadata and source-readiness listing."""

import asyncio
from pathlib import Path

from app.config import Settings
from app.evals.admin import EvaluationAdminService
import app.evals.suites as suites_module
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_suite_catalog_preserves_unapproved_provenance(tmp_path: Path) -> None:
    """Never present agent-curated pending cases as human-verified goldens."""
    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        artifact_dir=tmp_path / "runs",
    )

    suites = asyncio.run(service.suites())

    assert {suite.suite_id for suite in suites} == {
        "sec-en",
        "sec-ko",
        "dart-en",
        "dart-ko",
        "sec-en_v2_astra",
        "sec-ko_v2_astra",
        "sec-mixed_v2_astra",
    }
    assert {suite.suite_id: suite.title for suite in suites} == {
        "sec-en": "SEC retrieval",
        "sec-ko": "SEC retrieval · Korean",
        "dart-en": "DART retrieval",
        "dart-ko": "DART retrieval · Korean",
        "sec-en_v2_astra": "SEC · English v2",
        "sec-ko_v2_astra": "SEC · Korean v2",
        "sec-mixed_v2_astra": "SEC · Mixed v2",
    }
    assert all(suite.approval_status == "pending-author-approval" for suite in suites)
    assert all(suite.human_verified is False for suite in suites)
    assert all(suite.source_ready is False for suite in suites)


def test_suite_source_failure_is_typed_without_guessing(tmp_path: Path, monkeypatch) -> None:
    """Only actual source absence is classified as an acquisition prerequisite."""
    from app.evals.loader import GoldenDataError

    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        artifact_dir=tmp_path / "runs",
    )

    def missing(*args, **kwargs):
        """Simulate the loader's explicit absent-artifact contract."""
        from app.evals.source_binding import BoundGolden, SourceCheck

        return BoundGolden(
            (),
            (
                SourceCheck(
                    "missing",
                    "sec",
                    "NVDA",
                    2024,
                    "receipt",
                    None,
                    "source_missing",
                    "missing artifact",
                ),
            ),
        )

    monkeypatch.setattr(suites_module, "bind_golden", missing)
    assert all(row.source_error_code == "source_missing" for row in asyncio.run(service.suites()))

    def invalid(*args, **kwargs):
        """Keep invalid hashes or manifests distinct from missing downloads."""
        raise GoldenDataError("invalid source contract")

    monkeypatch.setattr(suites_module, "bind_golden", invalid)
    assert all(row.source_error_code == "source_invalid" for row in asyncio.run(service.suites()))
