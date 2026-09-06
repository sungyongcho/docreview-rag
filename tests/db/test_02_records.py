"""L1 deterministic record-conversion tests."""

from copy import deepcopy
from dataclasses import replace
from types import ModuleType
from typing import cast

import pytest

from app.ingestion.chunk import ChunkConfig, chunk_filing
from app.ingestion.parser import Block
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


@pytest.mark.parametrize("item_index", [["bad"], {"item": "1"}])
def test_document_record_rejects_non_object_item_index_entries(
    S: ModuleType, item_index: list[str] | dict[str, str]
) -> None:
    """Reject item indexes whose entries are not JSON objects."""
    need(S, "document_record")
    filing = sample_filing()
    filing.item_index = cast(list[dict], item_index)

    with pytest.raises(ValueError, match=r"item index \d+ is not an object"):
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


def test_chunk_record_conversion_rejects_shared_malformed_source_hash(S: ModuleType) -> None:
    """Retain SHA-256 validation after removing the duplicate helper call."""
    need(S, "chunk_records")
    filing = sample_filing()
    filing.source_sha256 = "bad"
    chunks = [replace(chunk, source_sha256="bad") for chunk in sample_chunks()]

    with pytest.raises(ValueError, match="lowercase hexadecimal SHA-256"):
        S.chunk_records(filing, chunks)


def test_build_seed_batch_sorts_manifest_and_output(S):
    need(S, "build_seed_batch")
    filings = {
        "AMD": sample_filing("AMD-FY2023"),
        "NVDA": sample_filing("NVDA-FY2024"),
    }
    calls = []

    def parser(entry):
        calls.append(("parse", entry["ticker"]))
        return filings[entry["ticker"]], {}

    def chunker(filing):
        calls.append(("chunk", filing.ticker))
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
    assert calls == [
        ("parse", "AMD"),
        ("chunk", "AMD"),
        ("parse", "NVDA"),
        ("chunk", "NVDA"),
    ]


def test_build_seed_batch_enforces_expected_manifest_size(S):
    need(S, "build_seed_batch")
    with pytest.raises(ValueError, match="expected 20 manifest documents, found 0"):
        S.build_seed_batch([], expected_documents=20)


def test_parse_seed_filings_orders_entries_and_calls_parser_once(S):
    need(S, "parse_seed_filings")
    calls = []

    def parser(entry):
        calls.append(entry["doc_id"])
        return sample_filing(entry["doc_id"]), {}

    entries = [
        {"doc_id": "NVDA-FY2024", "ticker": "NVDA", "report_date": "2024-01-28"},
        {"doc_id": "AMD-FY2023", "ticker": "AMD", "report_date": "2023-12-30"},
        {"doc_id": "AMD-FY2022", "ticker": "AMD", "report_date": "2022-12-30"},
    ]
    filings = S.parse_seed_filings(entries, expected_documents=3, parser=parser)

    assert calls == ["AMD-FY2022", "AMD-FY2023", "NVDA-FY2024"]
    assert tuple(filing.doc_id for filing in filings) == tuple(calls)


def test_parse_seed_filings_validates_count_before_parsing(S):
    need(S, "parse_seed_filings")
    calls = []

    def parser(entry):
        calls.append(entry)
        return sample_filing(), {}

    with pytest.raises(ValueError, match="expected 20 manifest documents, found 0"):
        S.parse_seed_filings([], expected_documents=20, parser=parser)

    assert calls == []


def test_parse_once_batch_exactly_matches_build_seed_batch(S):
    need(S, "build_seed_batch", "build_seed_batch_from_filings", "parse_seed_filings")

    def parser(entry):
        return sample_filing(entry["doc_id"]), {}

    def chunker(filing):
        return sample_chunks(filing.doc_id)

    entries = [
        {"doc_id": "NVDA-FY2024", "ticker": "NVDA", "report_date": "2024-01-28"},
        {"doc_id": "AMD-FY2023", "ticker": "AMD", "report_date": "2023-12-30"},
    ]
    legacy = S.build_seed_batch(
        entries,
        expected_documents=2,
        parser=parser,
        chunker=chunker,
    )
    filings = S.parse_seed_filings(entries, expected_documents=2, parser=parser)
    parse_once = S.build_seed_batch_from_filings(filings, chunker=chunker)

    assert parse_once == legacy


def test_reusing_parsed_filing_across_chunk_sizes_does_not_mutate_it(S):
    need(S, "build_seed_batch_from_filings")
    filing = sample_filing()
    filing.source_length = 1_000
    filing.sections[0].blocks = [
        Block("paragraph", "a" * 400, source_pos=10, end_pos=410),
        Block("paragraph", "b" * 400, source_pos=410, end_pos=810),
    ]
    filings = (filing,)
    snapshot = deepcopy(filings)

    batch_500 = S.build_seed_batch_from_filings(
        filings,
        chunker=lambda parsed: chunk_filing(parsed, ChunkConfig(target_text_chars=500)),
    )
    batch_1200 = S.build_seed_batch_from_filings(
        filings,
        chunker=lambda parsed: chunk_filing(parsed, ChunkConfig(target_text_chars=1_200)),
    )

    assert len(batch_500.chunks) == 2
    assert len(batch_1200.chunks) == 1
    assert filings == snapshot


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
