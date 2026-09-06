"""Small deterministic records shared by seed tests."""

from pathlib import Path

from app.ingestion import seed
from app.ingestion.chunk import Chunk
from app.ingestion.manifest import (
    Acquisition,
    CorpusIdentity,
    DocumentReference,
    FilingSource,
    SecMetadata,
    SourceArtifact,
)
from app.ingestion.parser import ParsedFiling, Section

SOURCE_SHA256 = "a" * 64


def sample_source(doc_id: str) -> FilingSource:
    """Construct a typed source reference for injected-parser tests."""
    issuer, year = doc_id.split("-FY", maxsplit=1)
    cik = str(sum(map(ord, issuer))).zfill(10)
    accession = f"{cik}-{year[-2:]}-000001"
    url = f"https://www.sec.gov/{doc_id}.html"
    document = DocumentReference(
        document_id=doc_id,
        registry="sec",
        language="en",
        issuer=issuer,
        issuer_id=cik,
        filing_id=accession,
        fiscal_year=int(year),
        form="10-K",
        filing_date=f"{year}-02-21",
        report_period=f"{year}-01-28",
        source_url=url,
        sec=SecMetadata(cik=cik, accession=accession, primary_document=f"{doc_id}.html"),
    )
    artifact = SourceArtifact(
        artifact_id=f"{doc_id}-source",
        document_id=doc_id,
        role="primary",
        path=f"{doc_id}.html",
        sha256=SOURCE_SHA256,
        byte_length=200,
        encoding="utf-8",
        acquisition=Acquisition(acquired_at=None, url=url, media_type="text/html"),
    )
    return FilingSource(
        document,
        artifact,
        Path("/synthetic-corpus"),
        CorpusIdentity(corpus_id="test", name="Test corpus"),
    )


def sample_filing(doc_id: str = "NVDA-FY2024") -> ParsedFiling:
    """Return a complete synthetic filing without parsing corpus HTML."""
    return ParsedFiling(
        source=sample_source(doc_id),
        source_length=200,
        source_sha256=SOURCE_SHA256,
        sections=[
            Section(
                part="I",
                item="1B",
                canonical_title="Unresolved Staff Comments",
                reported_title="Unresolved Staff Comments",
                status="empty_disclosure",
            )
        ],
        item_index=[
            {
                "item": "1B",
                "reported_title": "Unresolved Staff Comments",
                "pages": [],
                "status": "empty_disclosure",
                "reference_source": None,
            }
        ],
    )


def sample_chunks(doc_id: str = "NVDA-FY2024") -> list[Chunk]:
    """Return one text chunk and one table chunk with dense ordinals."""
    return [
        Chunk(
            doc_id=doc_id,
            item="1",
            kind="text",
            ordinal=0,
            body="Source-derived narrative.",
            context_header=f"{doc_id} context",
            citation=f"{doc_id} citation",
            start_char=10,
            end_char=40,
            source_sha256=SOURCE_SHA256,
        ),
        Chunk(
            doc_id=doc_id,
            item="8",
            kind="table",
            ordinal=1,
            body="| Metric | Value |\n| --- | --- |\n| Revenue | 10 |",
            context_header=f"{doc_id} table context",
            citation=f"{doc_id} table citation",
            start_char=80,
            end_char=140,
            source_sha256=SOURCE_SHA256,
        ),
    ]


def sample_batch() -> seed.SeedBatch:
    """Build one deterministic seed batch."""
    filing = sample_filing()
    document, chunks = seed.filing_records(filing, sample_chunks())
    return seed.SeedBatch((document,), chunks, (filing,))
