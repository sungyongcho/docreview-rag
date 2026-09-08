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
    from app.ingestion.source_publication import fixed_path

    original = Manifest.read(Path(__file__).resolve().parents[2] / "data/corpus/manifest.json")
    documents = tuple(
        d
        for d in original.documents
        if d.issuer in {"NVDA", "AMD"} and d.fiscal_year in {2023, 2024}
    )
    ids = {d.document_id: d for d in documents}
    artifacts = []
    root.mkdir(parents=True, exist_ok=True)
    for artifact in original.artifacts:
        if artifact.document_id not in ids or artifact.role != "primary":
            continue
        raw = f"synthetic fixture {artifact.document_id}".encode()
        document = ids[artifact.document_id]
        relative = fixed_path(document.registry, document.filing_id, "primary")
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        artifacts.append(
            artifact.model_copy(
                update={
                    "path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "byte_length": len(raw),
                }
            )
        )
    manifest = Manifest(corpus=original.corpus, documents=documents, artifacts=tuple(artifacts))
    manifest.write(root / "manifest.json")
    return manifest


def acquired_filing(root, *, document=None, payload=b"synthetic source"):
    """Build a current filing with explicit bytes, preserving the opaque document ID."""
    from datetime import UTC, datetime
    import hashlib
    import io
    import zipfile

    from app.ingestion.acquisition import AcquiredFiling
    from app.ingestion.dart_api import AnnualReport, CorpCode, DocumentArchive, archive_document
    from app.ingestion.manifest import Acquisition, SourceArtifact
    from app.ingestion.source_publication import fixed_path

    document = document or filing_document()
    if document.registry == "dart":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(f"{document.filing_id}.xml", payload)
        raw = buffer.getvalue()
        return archive_document(
            DocumentArchive(document.filing_id, raw, hashlib.sha256(raw).hexdigest()),
            AnnualReport(
                document.filing_id,
                document.issuer_id,
                document.issuer,
                document.dart.report_name,
                document.filing_date.isoformat(),
            ),
            CorpCode(document.issuer_id, document.issuer, document.issuer),
            fiscal_year=document.fiscal_year,
            corpus_dir=root,
            document_reference=document,
        )
    digest = hashlib.sha256(payload).hexdigest()
    artifact = SourceArtifact(
        artifact_id=f"{document.document_id}:primary:{digest}",
        document_id=document.document_id,
        role="primary",
        path=fixed_path(document.registry, document.filing_id, "primary"),
        sha256=digest,
        byte_length=len(payload),
        encoding="utf-8",
        acquisition=Acquisition(
            acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
            url=document.source_url,
            media_type="text/html",
        ),
    )
    return AcquiredFiling(document, (artifact,), (payload,))


def selected_document_ids(root, identifiers, years):
    """Extract explicit IDs from the synthetic catalog when constructing a test request."""
    from app.ingestion.manifest import Manifest

    return tuple(
        d.document_id
        for d in Manifest.read(root / "manifest.json").documents
        if d.issuer in identifiers and d.fiscal_year in years
    )
