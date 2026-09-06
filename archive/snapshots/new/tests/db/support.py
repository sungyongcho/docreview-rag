"""Small deterministic records shared by M1.4 tests."""

from app.ingestion.chunk import Chunk
from app.ingestion.parser import ParsedFiling, Section

SOURCE_SHA256 = "a" * 64


def sample_filing(doc_id: str = "NVDA-FY2024") -> ParsedFiling:
    """Return a complete synthetic filing without parsing corpus HTML."""
    ticker, year = doc_id.split("-FY", maxsplit=1)
    return ParsedFiling(
        doc_id=doc_id,
        ticker=ticker,
        cik="1045810",
        form="10-K",
        filing_date=f"{year}-02-21",
        report_period=f"{year}-01-28",
        fiscal_year=int(year),
        accession=f"0001045810-{year[-2:]}-000001",
        source_url=f"https://www.sec.gov/Archives/{doc_id}.htm",
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


def sample_batch(module):
    """Build a seed batch through the selected implementation module."""
    filing = sample_filing()
    document, chunks = module.filing_records(filing, sample_chunks())
    return module.SeedBatch((document,), chunks)
