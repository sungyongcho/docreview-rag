"""Builders and constants shared by evaluation tests."""

from datetime import UTC, datetime
import json
from pathlib import Path

from app.evals.golden.models import GoldenCase, GoldenSpan
from app.ingestion.parsing.html import source_digest
from app.ingestion.sources.models import CorpusIdentity, Manifest
from app.retrieval.types import ChunkHit
from tests.ingestion.support import acquired_filing, filing_document

SOURCE_SHA256 = "a" * 64
EVALUATION_RECORDED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def positive_case() -> GoldenCase:
    """Build a source-bearing case that :func:`relevant_hit` answers."""
    return GoldenCase(
        id="m3c-01",
        question="What evidence is supported?",
        category="simple_lookup",
        facet="factual",
        tags=("runner",),
        answers=(
            GoldenSpan(
                doc_id="NVDA-FY2024",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="Supported evidence.",
        note="Deterministic runner fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def absent_case() -> GoldenCase:
    """Build an absent case that carries no answer span."""
    return GoldenCase(
        id="m3c-02",
        question="What evidence is absent?",
        category="absent",
        facet="risk",
        tags=("negative",),
        answers=(),
        expected_label="NOT_IN_DOCS",
        reference_answer="NOT_IN_DOCS",
        note="Retrieval-only metrics do not score absence.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def relevant_hit() -> ChunkHit:
    """Build the hit that covers the positive case's gold span."""
    return ChunkHit(
        chunk_id=1,
        doc_id="NVDA-FY2024",
        item="7",
        kind="text",
        citation="NVDA FY2024 · Item 7",
        start_char=90,
        end_char=210,
        source_sha256=SOURCE_SHA256,
        body="Supported evidence.",
        context_header="NVDA FY2024 · Item 7",
        index_text="NVDA FY2024 · Item 7\n\nSupported evidence.",
        score=1.0,
    )


def source_bound_golden(tmp_path: Path):
    """Create one current original and an explicit historical evidence identity."""
    document = filing_document(issuer="NVDA", document_id="sec-current")
    body = b"<p>Verified revenue evidence.</p>"
    acquired = acquired_filing(tmp_path, document=document, payload=body)
    path = tmp_path / acquired.primary.path
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    manifest_path = tmp_path / "manifest.json"
    manifest = Manifest(
        corpus=CorpusIdentity(corpus_id="test", name="test"),
        documents=(document,),
        artifacts=acquired.artifacts,
    )
    manifest_path.write_text(manifest.model_dump_json())
    requirement_path = tmp_path / "requirements.json"
    requirement_path.write_text(
        json.dumps(
            {
                "NVDA-FY2024": {
                    "registry": "sec",
                    "issuer": "NVDA",
                    "fiscal_year": document.fiscal_year,
                    "filing_id": document.filing_id,
                }
            }
        )
    )
    payload = [
        {
            "id": "case-1",
            "question": "What is the evidence?",
            "category": "simple_lookup",
            "facet": "factual",
            "tags": [],
            "answers": [
                {
                    "doc_id": "NVDA-FY2024",
                    "source_sha256": source_digest(body.decode()),
                    "start_char": 3,
                    "end_char": 29,
                }
            ],
            "expected_label": "SUPPORTED",
            "reference_answer": "Verified revenue evidence.",
            "note": "Fixture only.",
            "curation_status": "agent-curated",
            "approval_status": "pending-author-approval",
            "human_verified": False,
        }
    ]
    return payload, manifest_path, requirement_path
