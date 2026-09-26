"""Isolated matrix inputs, provider refusal, and selected golden revisions."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
import app.evals.admin.execution as admin_runs_module
from app.evals.admin.preparation import evaluation_cases
from app.evals.admin.service import EvaluationAdminService
from app.evals.contracts import EvaluationRunRequest
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.search.profiles import RetrievalProfile


def _absent_case(question: str) -> dict[str, object]:
    """Build one source-free revision case for focused resolver tests."""
    return {
        "id": "test-01",
        "question": question,
        "category": "absent",
        "facet": "policy",
        "tags": [],
        "answers": [],
        "expected_label": "NOT_IN_DOCS",
        "reference_answer": "NOT_IN_DOCS",
        "note": "Deliberate negative case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }


def test_matrix_forwards_dart_manifest_and_profile_parameters(tmp_path: Path, monkeypatch) -> None:
    """Bind isolated DART runs to their exact selection and explicit BM25 values."""

    async def scenario() -> None:
        """Capture one matrix invocation and verify its explicit parameters."""
        captured = None
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def run_matrix(**kwargs):
            """Capture the matrix parameters without corpus or database work."""
            nonlocal captured
            captured = kwargs
            return {"persisted": [], "artifacts": []}

        from app.ingestion.sources.publication import publish_acquired
        from tests.ingestion.support import acquired_filing, filing_document

        filing = acquired_filing(tmp_path, document=filing_document(registry="dart"))
        publish_acquired(
            tmp_path / "manifest.json",
            [filing],
            selection_id="download",
            selected_document_ids=[filing.document.document_id],
        )

        async def cases(request, **kwargs):
            """Use a source-free question to isolate matrix scope construction."""
            from app.evals.golden.loading import GOLDEN_CASES

            return GOLDEN_CASES.validate_python([_absent_case("Absent?")]), "a" * 64

        monkeypatch.setattr(admin_runs_module, "evaluation_cases", cases)
        monkeypatch.setattr(admin_runs_module, "run_matrix", run_matrix)
        request = EvaluationRunRequest(
            suite_id="dart-ko",
            mode="matrix",
            profile=RetrievalProfile(bm25_k1=1.5, bm25_b=0.6),
        )
        await admin_runs_module.run_matrix_request(
            request,
            settings=service._settings,
            golden_dir=service._golden_dir,
            artifact_dir=service._artifact_dir,
        )

        assert captured is not None
        assert Path(captured["manifest_name"]).name.startswith(".evaluation-scope-")
        assert not Path(captured["manifest_name"]).exists()
        assert captured["selection_id"] == "evaluation-scope"
        assert captured["bm25_k1"] == 1.5
        assert captured["bm25_b"] == 0.6

    asyncio.run(scenario())


def test_matrix_refuses_an_embedding_provider_the_isolated_runner_cannot_use(
    tmp_path: Path, monkeypatch
) -> None:
    """Fail an sbert-configured matrix before the runner starts and leave no scope file."""

    async def scenario() -> None:
        """Bind a real scope, then stop at the provider check."""
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path, embedding_provider="sbert"),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        from app.ingestion.sources.publication import publish_acquired
        from tests.ingestion.support import acquired_filing, filing_document

        filing = acquired_filing(tmp_path, document=filing_document(registry="dart"))
        publish_acquired(
            tmp_path / "manifest.json",
            [filing],
            selection_id="download",
            selected_document_ids=[filing.document.document_id],
        )

        async def cases(request, **kwargs):
            """Use a source-free question to isolate the provider check."""
            from app.evals.golden.loading import GOLDEN_CASES

            return GOLDEN_CASES.validate_python([_absent_case("Absent?")]), "a" * 64

        async def run_matrix(**kwargs):
            """Fail the test if the refused matrix reaches the runner."""
            raise AssertionError("the matrix runner must not start")

        monkeypatch.setattr(admin_runs_module, "evaluation_cases", cases)
        monkeypatch.setattr(admin_runs_module, "run_matrix", run_matrix)
        with pytest.raises(ValueError, match="deterministic and openai"):
            await admin_runs_module.run_matrix_request(
                EvaluationRunRequest(suite_id="dart-ko", mode="matrix"),
                settings=service._settings,
                golden_dir=service._golden_dir,
                artifact_dir=service._artifact_dir,
            )
        assert not list(tmp_path.glob(".evaluation-scope-*"))

    asyncio.run(scenario())


def test_selected_golden_revision_drives_quick_and_matrix_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    """Evaluate the selected DB payload instead of silently falling back to canonical JSON."""

    async def scenario() -> None:
        """Resolve one revision for quick mode and materialize it for matrix mode."""
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        raw = "<p>Source.</p>"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        source_path = corpus_dir / "sec/TEST/0000000001-24-000001/primary.html"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(raw)
        manifest = corpus_dir / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "corpus": {"corpus_id": "test", "name": "Test"},
                    "documents": [
                        {
                            "document_id": "TEST-FY2024",
                            "registry": "sec",
                            "language": "en",
                            "issuer": "TEST",
                            "issuer_id": "0000000001",
                            "filing_id": "0000000001-24-000001",
                            "fiscal_year": 2024,
                            "form": "10-K",
                            "filing_date": "2025-01-01",
                            "report_period": "2024-12-31",
                            "source_url": "https://example.org/source",
                            "sec": {
                                "cik": "0000000001",
                                "accession": "0000000001-24-000001",
                                "primary_document": "source.html",
                            },
                        }
                    ],
                    "artifacts": [
                        {
                            "artifact_id": "source",
                            "document_id": "TEST-FY2024",
                            "role": "primary",
                            "path": "sec/TEST/0000000001-24-000001/primary.html",
                            "sha256": digest,
                            "byte_length": len(raw.encode()),
                            "encoding": "utf-8",
                            "acquisition": {
                                "acquired_at": "2025-01-01T00:00:00Z",
                                "url": "https://example.org/source",
                                "media_type": "text/html",
                            },
                        }
                    ],
                    "selections": [{"selection_id": "sec-evaluation", "artifact_ids": ["source"]}],
                }
            ),
            encoding="utf-8",
        )
        payload = [_absent_case("Revision question?")]
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=corpus_dir),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        from app.evals.golden.store import GoldenAdminService

        golden_dir = tmp_path / "golden"
        golden_dir.mkdir()
        (golden_dir / "retrieval.json").write_text(json.dumps(payload))
        golden = GoldenAdminService(golden_dir=golden_dir, corpus_dir=corpus_dir)
        draft = await golden.create_draft("sec-en", filename="custom.json")
        service._golden_dir = golden_dir

        captured: tuple[dict[str, Any], Any] | None = None

        async def run_matrix(**kwargs):
            """Read the temporary matrix input while it is still present."""
            nonlocal captured
            captured = (kwargs, json.loads(kwargs["golden"].read_text(encoding="utf-8")))
            return {"persisted": [], "artifacts": []}

        monkeypatch.setattr(admin_runs_module, "run_matrix", run_matrix)
        request = EvaluationRunRequest(suite_id="sec-en", golden_revision_id=draft.revision_id)

        cases, sha256 = await evaluation_cases(
            request, golden_dir=service._golden_dir, corpus_dir=service._settings.corpus_dir
        )
        await admin_runs_module.run_matrix_request(
            request.model_copy(update={"mode": "matrix"}),
            settings=service._settings,
            golden_dir=service._golden_dir,
            artifact_dir=service._artifact_dir,
        )

        assert cases[0].question == "Revision question?"
        assert sha256 == draft.sha256
        assert captured is not None
        kwargs, written = captured
        assert written == payload
        assert kwargs["admin_metadata"]["golden_provenance"]["filename"] == "custom.json"
        assert kwargs["admin_metadata"]["golden_provenance"]["golden_sha256"] == draft.sha256
        assert not kwargs["golden"].exists()

    asyncio.run(scenario())
