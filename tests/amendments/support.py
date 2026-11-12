"""Small synthetic filings that share a report period, for amendment tests."""

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.amendments.policy import eligible_chunk
from app.db.models import Chunk as ChunkRow
from app.ingestion import pipeline as seed
from app.ingestion.chunking import Chunk
from app.ingestion.parsing.models import ParsedFiling
from app.ingestion.sources.models import (
    Acquisition,
    CorpusIdentity,
    DartMetadata,
    DocumentReference,
    FilingSource,
    SecMetadata,
    SourceArtifact,
)

CIK = "0000002488"
CORP_CODE = "00164779"
PERIOD = date(2025, 12, 27)


def sec_document(
    sequence: int,
    *,
    form: str = "10-K",
    filed: date = date(2026, 2, 4),
    accepted: datetime | None = None,
    period: date = PERIOD,
) -> DocumentReference:
    """Describe one SEC filing of the shared issuer; ``sequence`` makes its accession."""
    accession = f"{CIK}-26-{sequence:06d}"
    return DocumentReference(
        document_id=f"sec-{accession}",
        registry="sec",
        language="en",
        issuer="AMD",
        issuer_id=CIK,
        filing_id=accession,
        fiscal_year=period.year,
        form=form,
        filing_date=filed,
        report_period=period,
        source_url=f"https://www.sec.gov/Archives/{accession}.htm",
        sec=SecMetadata(
            cik=CIK, accession=accession, primary_document="report.htm", accepted_at=accepted
        ),
    )


def amendment_document(sequence: int, *, hour: int = 20) -> DocumentReference:
    """Describe a 10-K/A of the shared report period, accepted at ``hour`` on the filing day."""
    return sec_document(
        sequence, form="10-K/A", accepted=datetime(2026, 2, 4, hour, 6, 57, tzinfo=UTC)
    )


def dart_document(receipt: str, *, fiscal_year: int = 2020) -> DocumentReference:
    """Describe one DART annual report of the shared issuer by its receipt number."""
    return DocumentReference(
        document_id=f"dart-{receipt}",
        registry="dart",
        language="ko",
        issuer="000660",
        issuer_id=CORP_CODE,
        filing_id=receipt,
        fiscal_year=fiscal_year,
        form="사업보고서",
        filing_date=date(int(receipt[:4]), int(receipt[4:6]), int(receipt[6:8])),
        report_period=date(fiscal_year, 12, 31),
        source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
        dart=DartMetadata(
            corp_code=CORP_CODE,
            receipt_number=receipt,
            report_code="11011",
            report_name=f"사업보고서 ({fiscal_year}.12)",
        ),
    )


def parsed(
    document: DocumentReference, items: tuple[str | None, ...], *, digest: str = "a"
) -> tuple[ParsedFiling, list[Chunk]]:
    """Return a parsed filing with one text chunk per given Item, ``None`` for no Item."""
    source_sha256 = digest * 64
    artifact = SourceArtifact(
        artifact_id=f"{document.document_id}-source-{digest}",
        document_id=document.document_id,
        role="primary",
        path=f"{document.document_id}-{digest}.txt",
        sha256=source_sha256,
        byte_length=1000,
        encoding="utf-8",
        acquisition=Acquisition(acquired_at=None, url=document.source_url, media_type="text/html"),
    )
    source = FilingSource(
        document,
        artifact,
        Path("/synthetic-corpus"),
        CorpusIdentity(corpus_id="test", name="Test corpus"),
    )
    filing = ParsedFiling(source=source, source_length=1000, source_sha256=source_sha256)
    chunks = [
        Chunk(
            doc_id=document.document_id,
            item=item,
            kind="text",
            ordinal=ordinal,
            body=f"{document.document_id} text of Item {item}.",
            context_header=f"{document.issuer} FY{document.fiscal_year} · Item {item}",
            citation=f"{document.issuer} FY{document.fiscal_year} · Item {item}",
            start_char=ordinal * 100,
            end_char=ordinal * 100 + 50,
            source_sha256=source_sha256,
        )
        for ordinal, item in enumerate(items)
    ]
    return filing, chunks


def batch(*filings: tuple[ParsedFiling, list[Chunk]]) -> seed.SeedBatch:
    """Build one seed batch from parsed filings, in the order persistence requires."""
    records = [seed.filing_records(filing, chunks) for filing, chunks in filings]
    documents = sorted((document for document, _ in records), key=lambda d: d.document_id)
    chunks = sorted(
        (chunk for _, filing_chunks in records for chunk in filing_chunks),
        key=lambda chunk: (chunk.doc_id, chunk.ordinal),
    )
    return seed.SeedBatch(tuple(documents), tuple(chunks), tuple(f for f, _ in filings))


async def eligible(session: AsyncSession) -> set[tuple[str, str | None]]:
    """Return the (document, Item) of every chunk the policy admits as current evidence."""
    rows = await session.execute(select(ChunkRow.doc_id, ChunkRow.item).where(eligible_chunk()))
    return {(doc_id, item) for doc_id, item in rows}
