"""M1.3 completion gate: every chunk can be traced back to source HTML."""

import re

from tests.chunk.support import counter_contains, is_subsequence, source_text, tokens


def _cells(markdown_row: str) -> list[str]:
    return [
        cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", markdown_row.strip("|"))
    ]


def test_text_chunk_body_is_an_ordered_source_subsequence(corpus, chunks_by_doc):
    for doc_id, (_filing, raw) in corpus.items():
        for chunk in chunks_by_doc[doc_id]:
            if chunk.kind != "text":
                continue
            visible = source_text(raw, chunk.start_char, chunk.end_char)
            assert is_subsequence(tokens(chunk.body), tokens(visible)), (
                f"{doc_id} chunk {chunk.ordinal}: text body is not in its cited span"
            )


def test_table_rows_and_header_cells_exist_in_source(corpus, chunks_by_doc):
    """Data rows retain order; merged multi-row headers use token containment.

    M1.2 joins header rows by column, so a combined header can differ from the
    original global row order. The cell vocabulary must still come from source.
    """
    for doc_id, (_filing, raw) in corpus.items():
        for chunk in chunks_by_doc[doc_id]:
            if chunk.kind != "table":
                continue
            visible_tokens = tokens(source_text(raw, chunk.start_char, chunk.end_char))
            lines = chunk.body.splitlines()
            for cell in _cells(lines[0]):
                assert counter_contains(visible_tokens, tokens(cell)), (
                    f"{doc_id} chunk {chunk.ordinal}: synthetic table header token"
                )
            data_tokens = [token for row in lines[2:] for token in tokens(row)]
            assert is_subsequence(data_tokens, visible_tokens), (
                f"{doc_id} chunk {chunk.ordinal}: table rows are not ordered in its cited span"
            )


def test_every_chunk_span_is_inside_its_document(corpus, chunks_by_doc):
    for doc_id, (filing, raw) in corpus.items():
        for chunk in chunks_by_doc[doc_id]:
            assert 0 <= chunk.start_char < chunk.end_char <= len(raw)
            assert chunk.source_sha256 == filing.source_sha256
            assert chunk.body


def test_every_source_body_block_is_consumed_exactly_once(C, corpus, chunks_by_doc):
    for doc_id, (filing, _raw) in corpus.items():
        chunks = chunks_by_doc[doc_id]
        for section in filing.sections:
            for block in section.blocks:
                empty_paragraph = block.kind == "paragraph" and not block.text.strip()
                if block.kind == "heading" or empty_paragraph:
                    continue
                if block.kind == "table" and not C.table_to_markdown(block.html):
                    continue
                expected_kind = "table" if block.kind == "table" else "text"
                matches = [
                    chunk
                    for chunk in chunks
                    if chunk.kind == expected_kind
                    and chunk.start_char <= block.source_pos
                    and block.end_pos <= chunk.end_char
                ]
                assert len(matches) == 1, (
                    f"{doc_id}: {block.kind} [{block.source_pos}, {block.end_pos}) "
                    f"was consumed {len(matches)} times"
                )
