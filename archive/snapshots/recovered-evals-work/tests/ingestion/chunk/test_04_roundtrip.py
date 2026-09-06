"""Source round-trip tests for emitted chunks."""

from bs4 import BeautifulSoup

from app.ingestion.tables import table_to_markdown
from tests.ingestion.chunk.support import (
    counter_contains,
    is_subsequence,
    markdown_cells,
    source_text,
    tokens,
)


def _ungrounded_table_tokens(
    data_tokens: list[str], visible_tokens: list[str], compact_tokens: list[str]
) -> set[str]:
    """Return rendered tokens absent as whole tokens from both source views."""
    vocabulary = set(visible_tokens) | set(compact_tokens)
    return set(data_tokens) - vocabulary


def _compact_cell_tokens(source_html: str) -> list[str]:
    """Tokenize cells after joining only their own inline text fragments."""
    soup = BeautifulSoup(source_html, "html.parser")
    return [
        token
        for cell in soup.find_all(["th", "td"])
        for token in tokens(" ".join("".join(cell.strings).split()))
    ]


def test_text_chunk_body_is_an_ordered_source_subsequence(corpus, chunks_by_doc):
    """Keep text chunk body tokens ordered within the cited source span."""
    for doc_id, (_filing, raw) in corpus.items():
        for chunk in chunks_by_doc[doc_id]:
            if chunk.kind != "text":
                continue
            visible = source_text(raw, chunk.start_char, chunk.end_char)
            assert is_subsequence(tokens(chunk.body), tokens(visible)), (
                f"{doc_id} chunk {chunk.ordinal}: text body is not in its cited span"
            )


def test_table_rows_and_header_cells_exist_in_source(corpus, chunks_by_doc):
    """Every rendered table token remains grounded in the cited source span.

    Table shape and multiplicity are protected by the renderer's focused tests.
    """
    for doc_id, (_filing, raw) in corpus.items():
        for chunk in chunks_by_doc[doc_id]:
            if chunk.kind != "table":
                continue
            source_html = raw[chunk.start_char : chunk.end_char]
            visible_tokens = tokens(source_text(raw, chunk.start_char, chunk.end_char))
            compact_tokens = _compact_cell_tokens(source_html)
            lines = chunk.body.splitlines()
            for cell in markdown_cells(lines[0]):
                assert counter_contains(visible_tokens, tokens(cell)), (
                    f"{doc_id} chunk {chunk.ordinal}: synthetic table header token"
                )
            data_tokens = [token for row in lines[2:] for token in tokens(row)]
            missing = _ungrounded_table_tokens(data_tokens, visible_tokens, compact_tokens)
            assert not missing, f"{doc_id} chunk {chunk.ordinal}: synthetic table data token"


def test_table_token_grounding_rejects_raw_substrings():
    """Reject an invented short token that appears only inside a source token."""
    assert _ungrounded_table_tokens(["9"], tokens("2019"), tokens("2019")) == {"9"}


def test_every_chunk_span_is_inside_its_document(corpus, chunks_by_doc):
    """Keep every nonempty chunk span and digest inside its source document."""
    for doc_id, (filing, raw) in corpus.items():
        for chunk in chunks_by_doc[doc_id]:
            assert 0 <= chunk.start_char < chunk.end_char <= len(raw)
            assert chunk.source_sha256 == filing.source_sha256
            assert chunk.body


def test_every_source_body_block_is_consumed_exactly_once(corpus, chunks_by_doc):
    """Consume every substantive source body block in exactly one chunk."""
    for doc_id, (filing, _raw) in corpus.items():
        chunks = chunks_by_doc[doc_id]
        for section in filing.sections:
            if section.status != "parsed":
                continue
            for block in section.blocks:
                empty_paragraph = block.kind == "paragraph" and not block.text.strip()
                if block.kind == "heading" or empty_paragraph:
                    continue
                if block.kind == "table" and not table_to_markdown(block.html):
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


def test_every_heading_with_following_content_becomes_context(corpus, chunks_by_doc):
    """Preserve each heading path element as context for its following body block."""
    for doc_id, (filing, _raw) in corpus.items():
        chunks = chunks_by_doc[doc_id]
        for section in filing.sections:
            if section.status != "parsed":
                continue
            for index, heading in enumerate(section.blocks):
                if heading.kind != "heading":
                    continue
                following = next(
                    (
                        block
                        for block in section.blocks[index + 1 :]
                        if block.source_group == heading.source_group
                        and block.kind != "heading"
                        and (block.kind != "paragraph" or bool(block.text.strip()))
                        and (block.kind != "table" or bool(table_to_markdown(block.html)))
                    ),
                    None,
                )
                if following is None:
                    continue
                expected_kind = "table" if following.kind == "table" else "text"
                matches = [
                    chunk
                    for chunk in chunks
                    if chunk.kind == expected_kind
                    and chunk.start_char <= following.source_pos
                    and following.end_pos <= chunk.end_char
                ]
                assert len(matches) == 1
                assert heading.text in matches[0].context_header, (
                    f"{doc_id}: heading {heading.text!r} is absent from following context"
                )
