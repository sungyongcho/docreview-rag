"""Shared pure helpers for ingestion API tests."""

import asyncio

import httpx


def client_returning(handler) -> httpx.AsyncClient:
    """Build a mock-transport client for one handler."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coroutine):
    """Run one asynchronous client operation to completion."""
    return asyncio.run(coroutine)


def filing_document(
    *, registry="sec", issuer=None, filing_id=None, fiscal_year=2024, document_id=None, aliases=()
):
    """Construct valid common metadata directly for one synthetic filing."""
    from app.ingestion.manifest import DartMetadata, DocumentReference, SecMetadata

    issuer = issuer or ("NVDA" if registry == "sec" else "005930")
    filing_id = filing_id or ("0001045810-24-000029" if registry == "sec" else "20250311001085")
    return DocumentReference(
        document_id=document_id or f"{issuer}-FY{fiscal_year}",
        registry=registry,
        language="en" if registry == "sec" else "ko",
        issuer=issuer,
        issuer_id="0001045810" if registry == "sec" else "00126380",
        aliases=aliases,
        filing_id=filing_id,
        fiscal_year=fiscal_year,
        form="10-K" if registry == "sec" else "사업보고서",
        filing_date=f"{fiscal_year + (registry == 'dart')}-03-11",
        report_period=f"{fiscal_year}-12-31",
        source_url=f"https://example.test/{filing_id}",
        sec=SecMetadata(cik="0001045810", accession=filing_id, primary_document="report.html")
        if registry == "sec"
        else None,
        dart=DartMetadata(
            corp_code="00126380",
            receipt_number=filing_id,
            report_code="11011",
            report_name=f"사업보고서 ({fiscal_year}.12)",
        )
        if registry == "dart"
        else None,
    )


def filing_source(path, *, document=None, encoding="utf-8"):
    """Bind a synthetic typed document to exact bytes already written by a test."""
    from datetime import UTC, datetime
    import hashlib

    from app.ingestion.manifest import Acquisition, CorpusIdentity, FilingSource, SourceArtifact

    document = document or filing_document()
    payload = path.read_bytes()
    artifact = SourceArtifact(
        artifact_id=f"{document.document_id}:primary",
        document_id=document.document_id,
        role="primary",
        path=path.name,
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
        encoding=encoding,
        acquisition=Acquisition(
            acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
            url=document.source_url,
            media_type="text/html",
        ),
    )
    return FilingSource(
        document, artifact, path.parent, CorpusIdentity(corpus_id="test", name="Test corpus")
    )


def write_selection_catalog(root):
    """Publish four synthetic SEC source files using real catalog identities."""
    import hashlib
    from pathlib import Path

    from app.ingestion.manifest import Manifest

    original = Manifest.read(Path(__file__).resolve().parents[2] / "data/corpus/manifest.json")
    documents = tuple(
        d
        for d in original.documents
        if d.issuer in {"NVDA", "AMD"} and d.fiscal_year in {2023, 2024}
    )
    ids = {d.document_id for d in documents}
    artifacts = []
    root.mkdir(parents=True, exist_ok=True)
    for artifact in original.artifacts:
        if artifact.document_id not in ids or artifact.role != "primary":
            continue
        raw = f"synthetic fixture {artifact.document_id}".encode()
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        artifacts.append(
            artifact.model_copy(
                update={"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
            )
        )
    manifest = Manifest(corpus=original.corpus, documents=documents, artifacts=tuple(artifacts))
    manifest.write(root / "manifest.json")
    return manifest
