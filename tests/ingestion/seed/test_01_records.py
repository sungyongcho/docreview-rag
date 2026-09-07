"""Deterministic seed record-conversion tests."""

from copy import deepcopy
from dataclasses import fields, replace
import hashlib
from typing import cast

import pytest

from app.ingestion.chunk import ChunkConfig, chunk_filing
from app.ingestion.parser import Block, Section
import app.ingestion.seed as seed
from tests.ingestion.seed.support import sample_chunks, sample_filing, sample_source
from tests.ingestion.support import filing_document, filing_source


def test_filing_records_keep_body_context_index_text_and_metadata():
    """Convert filing and chunk values without losing identity or provenance."""
    document, chunks = seed.filing_records(sample_filing(), sample_chunks())

    expected = sample_filing().source.document.model_dump(mode="json")
    expected["doc_id"] = expected.pop("document_id")
    assert document.values() == expected
    assert (
        not {"parse_status", "item_index", "source_length", "source_sha256"}
        & document.values().keys()
    )
    assert {field.name for field in fields(sample_filing())}.isdisjoint(
        {
            "doc_id",
            "registry",
            "issuer",
            "issuer_id",
            "filing_id",
            "form",
            "filing_date",
            "report_period",
            "fiscal_year",
            "source_url",
        }
    )
    assert [record.ordinal for record in chunks] == [0, 1]
    assert chunks[0].body == "Source-derived narrative."
    assert chunks[0].context_header == "NVDA-FY2024 context"
    assert chunks[0].index_text == "NVDA-FY2024 context\n\nSource-derived narrative."
    assert chunks[1].kind == "table"
    assert chunks[1].start_char == 80
    assert chunks[1].end_char == 140
    assert "embedding" not in chunks[0].values()
    assert "content_tsv" not in chunks[0].values()


def test_structure_record_rejects_invalid_parser_and_item_statuses():
    """Reject unsupported parser and item-index statuses."""
    filing = sample_filing()
    filing.parse_status = "unknown"
    with pytest.raises(ValueError, match="invalid parse status"):
        seed.structure_values(filing)

    filing = sample_filing()
    filing.item_index[0]["status"] = "unknown"
    with pytest.raises(ValueError, match="invalid status"):
        seed.structure_values(filing)


@pytest.mark.parametrize("item_index", [["bad"], {"item": "1"}])
def test_structure_record_rejects_non_object_item_index_entries(
    item_index: list[str] | dict[str, str],
) -> None:
    """Reject item indexes whose entries are not JSON objects."""
    filing = sample_filing()
    filing.item_index = cast(list[dict], item_index)

    with pytest.raises(ValueError, match=r"item index"):
        seed.structure_values(filing)


def test_record_conversion_is_deterministic():
    """Return equal immutable records for equal filing inputs."""
    first = seed.filing_records(sample_filing(), sample_chunks())
    second = seed.filing_records(sample_filing(), sample_chunks())
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
def test_chunk_record_conversion_rejects_broken_provenance(changed, message):
    """Reject chunk ownership, ordering, content, and source inconsistencies."""
    filing = sample_filing()
    chunks = sample_chunks()
    chunks[0] = replace(chunks[0], **changed)
    with pytest.raises(ValueError, match=message):
        seed.chunk_records(filing, chunks)


def test_chunk_record_conversion_rejects_shared_malformed_source_hash() -> None:
    """Retain SHA-256 validation after removing the duplicate helper call."""
    filing = sample_filing()
    filing.source_sha256 = "bad"
    chunks = [replace(chunk, source_sha256="bad") for chunk in sample_chunks()]

    with pytest.raises(ValueError, match="lowercase hexadecimal SHA-256"):
        seed.chunk_records(filing, chunks)


def test_build_seed_batch_sorts_manifest_and_output():
    """Sort manifest processing and output records deterministically."""
    filings = {
        "AMD": sample_filing("AMD-FY2023"),
        "NVDA": sample_filing("NVDA-FY2024"),
    }
    calls = []
    progress = []

    def parser(entry):
        """Record and parse one manifest entry."""
        calls.append(("parse", entry.document.issuer))
        return filings[entry.document.issuer], {}

    def chunker(filing):
        """Record and chunk one parsed filing."""
        calls.append(("chunk", filing.source.document.issuer))
        return sample_chunks(filing.source.document.document_id)

    entries = [
        sample_source("NVDA-FY2024"),
        sample_source("AMD-FY2023"),
    ]
    batch = seed.build_seed_batch(
        entries,
        expected_documents=2,
        parser=parser,
        chunker=chunker,
        on_progress=progress.append,
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
    assert [(update.current, update.total, update.message) for update in progress] == [
        (0, 2, "Parsing selected filings"),
        (1, 2, "AMD-FY2023"),
        (2, 2, "NVDA-FY2024"),
    ]


def test_build_seed_batch_enforces_expected_manifest_size():
    """Reject a manifest whose document count differs from the contract."""
    with pytest.raises(ValueError, match="expected 20 selected documents, found 0"):
        seed.build_seed_batch([], expected_documents=20)


def test_parse_seed_filings_orders_entries_and_calls_parser_once():
    """Parse each sorted manifest entry exactly once."""
    calls = []

    def parser(entry):
        """Record one sorted parse and return its filing."""
        calls.append(entry.document.document_id)
        return sample_filing(entry.document.document_id), {}

    entries = [
        sample_source("NVDA-FY2024"),
        sample_source("AMD-FY2023"),
        sample_source("AMD-FY2022"),
    ]
    filings = seed.parse_seed_filings(entries, expected_documents=3, parser=parser)

    assert tuple(filing.source.document.document_id for filing in filings) == tuple(calls)


def test_parse_seed_filings_validates_count_before_parsing():
    """Validate manifest size before invoking the parser."""
    calls = []

    def parser(entry):
        """Record an unexpected parser invocation."""
        calls.append(entry)
        return sample_filing(), {}

    with pytest.raises(ValueError, match="expected 20 selected documents, found 0"):
        seed.parse_seed_filings([], expected_documents=20, parser=parser)

    assert calls == []


def test_parse_once_batch_exactly_matches_build_seed_batch():
    """Keep parse-once and combined batch construction equivalent."""

    def parser(entry):
        """Build one filing for parse-once equivalence."""
        return sample_filing(entry.document.document_id), {}

    def chunker(filing):
        """Build chunks for parse-once equivalence."""
        return sample_chunks(filing.source.document.document_id)

    entries = [
        sample_source("NVDA-FY2024"),
        sample_source("AMD-FY2023"),
    ]
    combined = seed.build_seed_batch(
        entries,
        expected_documents=2,
        parser=parser,
        chunker=chunker,
    )
    filings = seed.parse_seed_filings(entries, expected_documents=2, parser=parser)
    parse_once = seed.build_seed_batch_from_filings(filings, chunker=chunker)

    assert parse_once == combined


def test_reusing_parsed_filing_across_chunk_sizes_does_not_mutate_it():
    """Reuse parsed filings across chunk configurations without mutation."""
    filing = sample_filing()
    filing.source_length = 1_000
    filing.sections[0].status = "parsed"
    filing.sections[0].blocks = [
        Block("paragraph", "a" * 400, source_pos=10, end_pos=410),
        Block("paragraph", "b" * 400, source_pos=410, end_pos=810),
    ]
    filings = (filing,)
    snapshot = deepcopy(filings)

    small_batch = seed.build_seed_batch_from_filings(
        filings,
        chunker=lambda parsed: chunk_filing(parsed, ChunkConfig(target_tokens=64)),
    )
    large_batch = seed.build_seed_batch_from_filings(
        filings,
        chunker=lambda parsed: chunk_filing(parsed, ChunkConfig(target_tokens=256)),
    )

    assert len(small_batch.chunks) == 2
    assert len(large_batch.chunks) == 1
    assert filings == snapshot


def test_seed_batch_revalidates_cross_record_provenance():
    """Reject chunk digests that differ from their document source."""
    document, chunks = seed.filing_records(sample_filing(), sample_chunks())
    mismatched = replace(chunks[0], source_sha256="b" * 64)
    with pytest.raises(ValueError, match="source SHA-256 differs from document"):
        seed.SeedBatch((document,), (mismatched, chunks[1]), (sample_filing(),))


def test_chunk_record_rejects_inconsistent_index_text():
    """Reject indexed text that differs from context and body composition."""
    _document, chunks = seed.filing_records(sample_filing(), sample_chunks())
    with pytest.raises(ValueError, match="inconsistent index text"):
        replace(chunks[0], index_text="stale combined text")


def test_records_reject_an_unsupported_language():
    """Refuse to build rows whose language no retrieval path would ever match."""
    document, chunks = seed.filing_records(sample_filing(), sample_chunks())

    with pytest.raises(ValueError, match="language"):
        replace(document, language="fr")
    with pytest.raises(ValueError, match="unsupported language"):
        replace(chunks[0], language="")


def test_chunk_records_tag_rows_with_the_registry_language():
    """Stamp every row with the language its registry publishes in."""
    document, chunks = seed.filing_records(sample_filing(), sample_chunks())

    assert document.values()["language"] == "en"
    assert {record.values()["language"] for record in chunks} == {"en"}


def test_registry_chunker_applies_one_shared_token_budget():
    """Use the same token budget for both registry adapters."""
    paragraphs = [
        Block("paragraph", "가" * 400, source_pos=40 * i, end_pos=40 * i + 30) for i in range(1, 4)
    ]
    base = sample_filing()
    section = Section(
        part="I",
        item="1",
        canonical_title="Business",
        reported_title="Item 1. Business",
        blocks=paragraphs,
    )
    dart = replace(
        base,
        source=replace(
            base.source,
            document=filing_document(registry="dart", document_id=base.source.document.document_id),
        ),
        sections=[section],
        item_index=[],
    )
    sec = replace(base, sections=[section])

    dart_text = [c for c in seed.registry_chunker(dart) if c.kind == "text"]
    sec_text = [c for c in seed.registry_chunker(sec) if c.kind == "text"]

    assert len(dart_text) == len(sec_text) == 1
    assert dart_text[0].body == sec_text[0].body


def test_chunk_record_mirrors_the_database_lexical_text_check():
    """Reject the shapes the ck_chunks_lexical_text_language CHECK would reject."""
    _document, chunks = seed.filing_records(sample_filing(), sample_chunks())

    with pytest.raises(ValueError, match="lexical_text is required"):
        replace(chunks[0], lexical_text="")  # en row: '' is NOT NULL in SQL terms
    with pytest.raises(ValueError, match="lexical_text is blank"):
        replace(chunks[0], language="ko", lexical_text="   ")


def test_raw_artifact_and_decoded_parse_hashes_remain_distinct(tmp_path):
    """Persist raw byte identity separately from canonical decoded UTF-8 provenance."""
    path = tmp_path / "source.xml"
    text = "사업보고서"
    path.write_bytes(text.encode("cp949"))
    source = filing_source(path, document=filing_document(registry="dart"), encoding="cp949")
    filing = replace(
        sample_filing(),
        source=source,
        source_length=len(text),
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    structure = seed.structure_values(filing)
    assert structure["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert structure["source_sha256"] != structure["artifact_sha256"]
    assert structure["parse_status"] == filing.parse_status
    assert structure["item_index"] == filing.item_index
    assert "parse_status" not in structure["structure"]
    assert "item_index" not in structure["structure"]


def test_seed_batch_rejects_identity_and_parse_pointer_disagreement():
    """Bind identity-only document rows and chunks to their exact selected source parse."""
    filing = sample_filing()
    document, chunks = seed.filing_records(filing, sample_chunks())
    with pytest.raises(ValueError, match="identity differs"):
        seed.SeedBatch((replace(document, aliases=("different",)),), chunks, (filing,))
    with pytest.raises(ValueError, match="different source parse"):
        seed.SeedBatch(
            (document,), (replace(chunks[0], structure_id="b" * 64), chunks[1]), (filing,)
        )
