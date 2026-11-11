"""Small deterministic records shared by seed tests."""

from datetime import date
from pathlib import Path
import re

from app.ingestion import pipeline as seed
from app.ingestion.chunking import Chunk, chunk_filing
from app.ingestion.parsing.facts import FilingFacts, sec_facts
from app.ingestion.parsing.models import Block, ParsedFiling, Section
from app.ingestion.sources.models import (
    Acquisition,
    CorpusIdentity,
    DocumentReference,
    FilingSource,
    SecMetadata,
    SourceArtifact,
)

SOURCE_SHA256 = "a" * 64


def sample_source(doc_id: str) -> FilingSource:
    """Construct a typed source reference with consistent filing identity."""
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
        filing_date=date(int(year), 2, 21),
        report_period=date(int(year), 1, 28),
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


# A two-year income table whose note states the scale and an explicit currency.
TABLE_HTML = (
    "<table><tr><td>(In millions of U.S. dollars)</td><td>2024</td><td>2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Net income (loss)</td><td>(1,641)</td><td>—</td></tr></table>"
)


def table_batch(
    html: str = TABLE_HTML,
    doc_id: str = "NVDA-FY2024",
    *,
    start: int = 0,
    cell_spans: tuple[tuple[int, int], ...] | None = None,
    facts: FilingFacts | None = None,
) -> seed.SeedBatch:
    """Build one seed batch whose filing is a single table chunked by the real chunker.

    The table block covers ``html[start:]``; ``cell_spans`` are its cells' source
    spans. The filing's facts are ``facts``, or else read from ``html`` as the SEC
    parser reads them.
    """
    filing = sample_filing(doc_id)
    filing.source_length = len(html)
    filing.facts = facts if facts is not None else sec_facts(html, filing.source.document)
    filing.sections = [
        Section(
            "II",
            "7",
            "Management's Discussion",
            "Item 7",
            [
                Block(
                    "table",
                    "",
                    html=html[start:],
                    source_pos=start,
                    end_pos=len(html),
                    cell_spans=cell_spans,
                )
            ],
        )
    ]
    filing.item_index = [{"item": "7", "reported_title": "Item 7", "pages": [], "status": "parsed"}]
    document, chunks = seed.filing_records(filing, chunk_filing(filing))
    return seed.SeedBatch((document,), chunks, (filing,))


def _context(context_id: str, period: str, member: str | None = None) -> str:
    """Render one inline XBRL context, optionally scoped to a segment member."""
    segment = (
        '<xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">'
        f"{member}</xbrldi:explicitMember></xbrli:segment>"
        if member
        else ""
    )
    return (
        f'<xbrli:context id="{context_id}"><xbrli:entity>{segment}</xbrli:entity>'
        f"<xbrli:period>{period}</xbrli:period></xbrli:context>"
    )


def _fact(name: str, context: str, unit: str, scale: int, text: str) -> str:
    """Render one inline XBRL number."""
    return (
        f'<ix:nonFraction name="{name}" contextRef="{context}" unitRef="{unit}" '
        f'scale="{scale}" decimals="-6">{text}</ix:nonFraction>'
    )


# An inline XBRL income table of a fiscal year ending 2024-01-28 (NVDA-FY2024). Its
# note states no currency, the cells' tags do; the EPS row's tag has scale 0 although
# the note says millions, and the segment row is dimensioned.
TAGGED_TABLE_HTML = (
    "<html><ix:header><ix:resources>"
    + _context(
        "fy24",
        "<xbrli:startDate>2023-01-30</xbrli:startDate><xbrli:endDate>2024-01-28</xbrli:endDate>",
    )
    + _context(
        "fy23",
        "<xbrli:startDate>2022-01-31</xbrli:startDate><xbrli:endDate>2023-01-29</xbrli:endDate>",
    )
    + _context(
        "dc24",
        "<xbrli:startDate>2023-01-30</xbrli:startDate><xbrli:endDate>2024-01-28</xbrli:endDate>",
        "nvda:DataCenterMember",
    )
    + '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    '<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>'
    "iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>"
    "xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>"
    "</ix:resources></ix:header>"
    "<table><tr><td>(In millions)</td><td>Jan 28, 2024</td><td>Jan 29, 2023</td></tr>"
    "<tr><td>Revenue</td><td>$ "
    + _fact("us-gaap:Revenues", "fy24", "usd", 6, "60,922")
    + "</td><td>$ "
    + _fact("us-gaap:Revenues", "fy23", "usd", 6, "26,974")
    + "</td></tr><tr><td>Diluted</td><td>$ "
    + _fact("us-gaap:EarningsPerShareDiluted", "fy24", "usdPerShare", 0, "11.93")
    + "</td><td>$ "
    + _fact("us-gaap:EarningsPerShareDiluted", "fy23", "usdPerShare", 0, "1.74")
    + "</td></tr><tr><td>Revenue</td><td>"
    + _fact("us-gaap:Revenues", "dc24", "usd", 6, "47,525")
    + "</td><td>—</td></tr></table></html>"
)


def tagged_table_batch(
    doc_id: str = "NVDA-FY2024", html: str = TAGGED_TABLE_HTML
) -> seed.SeedBatch:
    """Build a tagged table's batch with its cells' source spans, as the parser does."""
    start = html.index("<table>")
    starts = [match.start() for match in re.finditer(r"<td\b", html)]
    spans = tuple(zip(starts, [*starts[1:], len(html)], strict=True))
    return table_batch(html, doc_id, start=start, cell_spans=spans)
