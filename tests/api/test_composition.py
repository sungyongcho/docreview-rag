"""Application composition keeps every domain on the selected runtime resources."""

import asyncio

from app.api import composition
from app.api.review.runtime import RuntimeApiServices
from app.config import Settings
from app.evals.contracts import EvaluationRunRequest
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider


def test_evaluation_preparation_reads_the_runtime_corpus(tmp_path, monkeypatch):
    """An invalid selected manifest must not be replaced by another corpus's readiness."""
    runtime_root = tmp_path / "selected"
    runtime_root.mkdir()
    (runtime_root / "manifest.json").write_text("invalid JSON")
    ambient = Settings(corpus_dir=tmp_path / "ambient")
    monkeypatch.setattr(composition, "get_settings", lambda: ambient)
    monkeypatch.setattr("app.corpus_admin.service.get_settings", lambda: ambient)
    monkeypatch.setattr("app.evals.admin.service.get_settings", lambda: ambient)
    runtime = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), corpus_root=runtime_root
    )
    services = composition.create_admin_services(runtime=runtime)

    result = asyncio.run(services.evaluations.preparation(EvaluationRunRequest(suite_id="dart-ko")))

    assert result.state == "source_invalid"
    assert result.next_step == "filings"
