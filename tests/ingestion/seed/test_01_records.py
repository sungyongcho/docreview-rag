"""Deterministic seed record-conversion tests."""

from copy import deepcopy
from dataclasses import replace
import hashlib
from typing import cast

import pytest

from app.ingestion.chunk import ChunkConfig, chunk_filing
from app.ingestion.parser import Block, Section
import app.ingestion.seed as seed
from tests.ingestion.edgar.support import build_numbered_body
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


def test_build_seed_batch_sorts_manifest_and_output(tmp_path):
    """Parse real selected sources and preserve their identity in sorted seed records."""
    entries = []
    for issuer, year in (("NVDA", 2024), ("AMD", 2023)):
        path = tmp_path / f"{issuer}.html"
        path.write_text(build_numbered_body(gap=2).replace("Body text", f"{issuer} disclosure."))
        entries.append(filing_source(path, document=sample_source(f"{issuer}-FY{year}").document))
    progress = []

    batch = seed.build_seed_batch(entries, expected_documents=2, on_progress=progress.append)

    assert [record.doc_id for record in batch.documents] == ["AMD-FY2023", "NVDA-FY2024"]
    assert [filing.source for filing in batch.filings] == list(reversed(entries))
    assert [record.doc_id for record in batch.chunks] == sorted(
        record.doc_id for record in batch.chunks
    )
    for source in entries:
        records = [r for r in batch.chunks if r.doc_id == source.document.document_id]
        assert records
        assert [record.ordinal for record in records] == list(range(len(records)))
        assert all(f"{source.document.issuer} disclosure." in record.body for record in records)
        assert all(record.source_sha256 == source.artifact.sha256 for record in records)
    assert [(update.current, update.total, update.message) for update in progress] == [
        (0, 2, "Parsing selected filings"),
        (1, 2, "AMD-FY2023"),
        (2, 2, "NVDA-FY2024"),
    ]


def test_parse_seed_filings_validates_count_before_parsing():
    """Reject the count before trying to read a source that is deliberately absent."""
    source = sample_source("NVDA-FY2024")
    with pytest.raises(ValueError, match="expected 20 selected documents, found 1"):
        seed.parse_seed_filings([source], expected_documents=20)


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
