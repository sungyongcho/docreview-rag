"""L1 deterministic record-conversion tests."""

from dataclasses import replace

import pytest

from tests.db.support import SOURCE_SHA256, sample_chunks, sample_filing
from tests.support import need


def test_filing_records_keep_body_context_index_text_and_metadata(S):
    need(S, "filing_records")
    document, chunks = S.filing_records(sample_filing(), sample_chunks())

    assert document.values() == {
        "doc_id": "NVDA-FY2024",
        "ticker": "NVDA",
        "cik": 1045810,
        "fiscal_year": 2024,
        "form": "10-K",
        "filing_date": "2024-02-21",
        "report_period": "2024-01-28",
        "accession": "0001045810-24-000001",
        "url": "https://www.sec.gov/Archives/NVDA-FY2024.htm",
        "parse_status": "parsed",
        "item_index": [
            {
                "item": "1B",
                "pages": [],
                "reference_source": None,
                "reported_title": "Unresolved Staff Comments",
                "status": "empty_disclosure",
            }
        ],
        "source_length": 200,
        "source_sha256": SOURCE_SHA256,
    }
    assert [record.ordinal for record in chunks] == [0, 1]
    assert chunks[0].body == "Source-derived narrative."
    assert chunks[0].context_header == "NVDA-FY2024 context"
    assert chunks[0].index_text == "NVDA-FY2024 context\n\nSource-derived narrative."
    assert chunks[1].kind == "table"
    assert chunks[1].start_char == 80
    assert chunks[1].end_char == 140
    assert "embedding" not in chunks[0].values()
    assert "content_tsv" not in chunks[0].values()


def test_document_record_rejects_invalid_parser_and_item_statuses(S):
    need(S, "document_record")
    filing = sample_filing()
    filing.parse_status = "unknown"
    with pytest.raises(ValueError, match="invalid parse status"):
        S.document_record(filing)

    filing = sample_filing()
    filing.item_index[0]["status"] = "unknown"
    with pytest.raises(ValueError, match="invalid status"):
        S.document_record(filing)


def test_record_conversion_is_deterministic(S):
    need(S, "filing_records")
    first = S.filing_records(sample_filing(), sample_chunks())
    second = S.filing_records(sample_filing(), sample_chunks())
    assert first == second


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"doc_id": "AMD-FY2024"}, "document mismatch"),
        ({"ordinal": 3}, "ordinals must be dense"),
        ({"kind": "image"}, "unsupported chunk kind"),
        ({"body": ""}, "empty body"),
        ({"start_char": 190, "end_char": 210}, "invalid source span"),
        ({"source_sha256": "b" * 64}, "different source SHA-256"),
    ],
)
def test_chunk_record_conversion_rejects_broken_provenance(S, changed, message):
    need(S, "chunk_records")
    filing = sample_filing()
    chunks = sample_chunks()
    chunks[0] = replace(chunks[0], **changed)
    with pytest.raises(ValueError, match=message):
        S.chunk_records(filing, chunks)


def test_build_seed_batch_sorts_manifest_and_output(S):
    need(S, "build_seed_batch")
    filings = {
        "AMD": sample_filing("AMD-FY2023"),
        "NVDA": sample_filing("NVDA-FY2024"),
    }

    def parser(entry):
        return filings[entry["ticker"]], {}

    def chunker(filing):
        return sample_chunks(filing.doc_id)

    entries = [
        {"ticker": "NVDA", "report_date": "2024-01-28"},
        {"ticker": "AMD", "report_date": "2023-12-30"},
    ]
    batch = S.build_seed_batch(
        entries,
        expected_documents=2,
        parser=parser,
        chunker=chunker,
    )
    assert [record.doc_id for record in batch.documents] == ["AMD-FY2023", "NVDA-FY2024"]
    assert [(record.doc_id, record.ordinal) for record in batch.chunks] == [
        ("AMD-FY2023", 0),
        ("AMD-FY2023", 1),
        ("NVDA-FY2024", 0),
        ("NVDA-FY2024", 1),
    ]


def test_build_seed_batch_enforces_expected_manifest_size(S):
    need(S, "build_seed_batch")
    with pytest.raises(ValueError, match="expected 20 manifest documents, found 0"):
        S.build_seed_batch([], expected_documents=20)


def test_seed_batch_revalidates_cross_record_provenance(S):
    need(S, "SeedBatch", "filing_records")
    document, chunks = S.filing_records(sample_filing(), sample_chunks())
    mismatched = replace(chunks[0], source_sha256="b" * 64)
    with pytest.raises(ValueError, match="source SHA-256 differs from document"):
        S.SeedBatch((document,), (mismatched, chunks[1]))


def test_chunk_record_rejects_inconsistent_index_text(S):
    need(S, "ChunkRecord", "filing_records")
    _document, chunks = S.filing_records(sample_filing(), sample_chunks())
    with pytest.raises(ValueError, match="inconsistent index text"):
        replace(chunks[0], index_text="stale combined text")
