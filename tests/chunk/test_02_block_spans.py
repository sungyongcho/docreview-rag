"""L5 prerequisite: every parsed body block maps to the immutable source."""

import hashlib

from app.ingestion.parser import read_source, source_digest
from tests.chunk.support import source_text, tokens


def test_all_body_blocks_have_valid_spans(corpus):
    for doc_id, (filing, raw) in corpus.items():
        for section in filing.sections:
            previous = -1
            for block in section.blocks:
                assert block.source_pos is not None, f"{doc_id}: missing block start"
                assert block.end_pos is not None, f"{doc_id}: missing block end"
                assert 0 <= block.source_pos < block.end_pos <= len(raw)
                assert block.source_pos >= previous, f"{doc_id}: block order moved backward"
                previous = block.source_pos


def test_filing_coordinates_are_bound_to_the_source_snapshot(corpus):
    for filing, raw in corpus.values():
        assert filing.source_length == len(raw)
        assert filing.source_sha256 == source_digest(raw)


def test_text_block_round_trip(corpus):
    """Visible text from each paragraph/heading must be present in its source slice."""
    for doc_id, (filing, raw) in corpus.items():
        for section in filing.sections:
            for block in section.blocks:
                if block.kind == "table" or not block.text:
                    continue
                actual = tokens(source_text(raw, block.source_pos, block.end_pos))
                assert tokens(block.text) == actual[: len(tokens(block.text))], (
                    f"{doc_id}: block text does not begin at its cited source span"
                )


def test_table_block_span_contains_a_table(corpus):
    for doc_id, (filing, raw) in corpus.items():
        for section in filing.sections:
            for block in section.blocks:
                if block.kind == "table":
                    cited = raw[block.source_pos : block.end_pos].lower()
                    assert "<table" in cited, f"{doc_id}: table citation misses its table"


def test_canonical_reader_preserves_crlf_and_unicode_code_points(tmp_path):
    path = tmp_path / "source.html"
    source_bytes = "A\r\ncafé\r\n".encode()
    path.write_bytes(source_bytes)

    raw = read_source(path)
    start = raw.index("café")
    end = start + len("café")

    assert "\r\n" in raw
    assert raw[start:end] == "café"
    assert source_digest(raw) == hashlib.sha256(source_bytes).hexdigest()
    assert len(source_bytes) > len(raw)
