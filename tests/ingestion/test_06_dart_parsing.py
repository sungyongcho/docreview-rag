"""Assembled DART ingestion: manifest → registry parse → chunking with citations."""

import json
from pathlib import Path

import pytest

from app.ingestion.chunk import chunk_filing
from app.ingestion.dart import DART_PARTS
from app.ingestion.parser import ParsedFiling, read_source
from app.ingestion.registry import resolve_registry
from tests.ingestion.chunk.support import is_subsequence, source_text, tokens

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def dart_corpus() -> dict[str, tuple[ParsedFiling, str]]:
    """Parse every archived DART filing named by the committed DART manifest."""
    manifest_path = _REPOSITORY_ROOT / "data/corpus/dart-manifest.json"
    if not manifest_path.exists():
        pytest.skip("data/corpus/dart-manifest.json is required for DART corpus tests")

    corpus = {}
    for entry in json.loads(manifest_path.read_text()):
        path = _REPOSITORY_ROOT / entry["file"]
        if not path.exists():
            pytest.skip(f"DART corpus file is missing: {entry['file']}")
        localized = entry | {"file": str(path)}
        registry = resolve_registry(localized)
        assert registry.name == "dart"
        filing, _ = registry.parse(localized)
        corpus[filing.doc_id] = (filing, read_source(path))
    return corpus


def test_both_issuers_parse_into_the_twelve_registry_divisions(dart_corpus) -> None:
    """Each filing yields the full DART table of contents, in filing order."""
    assert set(dart_corpus) == {"005930-FY2024", "000660-FY2024"}
    for filing, _ in dart_corpus.values():
        assert [section.part for section in filing.sections] == list(DART_PARTS)
        assert [section.canonical_title for section in filing.sections] == list(DART_PARTS.values())
        assert filing.parse_status == "parsed"
        assert filing.warnings == []


def test_dart_blocks_stay_ordered_inside_the_archived_source(dart_corpus) -> None:
    """Block spans are in bounds and never overlap across the whole filing."""
    for document, (filing, raw) in dart_corpus.items():
        previous_end = -1
        for section in filing.sections:
            for block in section.blocks:
                assert block.source_pos is not None and block.end_pos is not None
                assert 0 <= block.source_pos < block.end_pos <= len(raw)
                assert block.source_pos >= previous_end, f"{document}: overlapping span"
                previous_end = block.end_pos


def test_dart_chunks_carry_the_document_source_identity(dart_corpus) -> None:
    """Every chunk cites the filing's own SHA-256 and a span inside the source."""
    for filing, raw in dart_corpus.values():
        chunks = chunk_filing(filing)
        assert chunks, filing.doc_id
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
        for chunk in chunks:
            assert chunk.source_sha256 == filing.source_sha256
            assert 0 <= chunk.start_char < chunk.end_char <= len(raw)


def test_dart_citations_use_the_registry_section_labels(dart_corpus) -> None:
    """Citations spell the DART numeral and division name, never an SEC Item."""
    for filing, _ in dart_corpus.values():
        for chunk in chunk_filing(filing):
            assert chunk.citation.startswith(f"{filing.issuer} FY{filing.fiscal_year} · ")
            label = chunk.citation.split(" · ", 1)[1]
            numeral, _, title = label.partition(". ")
            assert DART_PARTS.get(numeral) == title, chunk.citation
            assert chunk.context_header.count(label) == 1, chunk.context_header
            assert "Item" not in chunk.citation
            assert "Item" not in chunk.context_header


def test_dart_text_chunks_stay_grounded_in_their_source_slice(dart_corpus) -> None:
    """Korean chunk bodies re-tokenize from the exact source span they cite."""
    for document, (filing, raw) in dart_corpus.items():
        text_chunks = [chunk for chunk in chunk_filing(filing) if chunk.kind == "text"]
        assert text_chunks, document
        for chunk in text_chunks:
            cited = tokens(source_text(raw, chunk.start_char, chunk.end_char))
            body = tokens(chunk.body)
            assert body, f"{document}: chunk {chunk.ordinal} tokenized to nothing"
            assert is_subsequence(body, cited), (
                f"{document}: chunk {chunk.ordinal} body is not grounded in its span"
            )


def test_dart_table_chunks_render_markdown_from_source_tables(dart_corpus) -> None:
    """Table chunks exist and their cited spans contain the source table markup."""
    for document, (filing, raw) in dart_corpus.items():
        table_chunks = [chunk for chunk in chunk_filing(filing) if chunk.kind == "table"]
        assert table_chunks, document
        for chunk in table_chunks:
            assert "|" in chunk.body
            assert "<TABLE" in raw[chunk.start_char : chunk.end_char].upper()
