"""Segment parsed sections into retrieval chunks with source spans and citations."""

from dataclasses import dataclass, replace
import re
from typing import Literal

from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.tables import table_to_markdown

ChunkKind = Literal["text", "table"]

DEFAULT_TARGET_TEXT_CHARS = 1_200
SOURCE_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)


def compose_index_text(context_header: str, body: str) -> str:
    """Compose indexed text using the canonical context-body separator.

    The persistence boundary must use the same double-newline separator.
    """
    return f"{context_header}\n\n{body}" if context_header else body


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Tunable parameters for structure-aware chunking."""

    target_text_chars: int = DEFAULT_TARGET_TEXT_CHARS

    def __post_init__(self) -> None:
        """Reject nonpositive chunk-size targets."""
        if self.target_text_chars <= 0:
            raise ValueError("target_text_chars must be positive")


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrieval unit whose citation survives re-chunking."""

    doc_id: str
    item: str | None
    kind: ChunkKind
    ordinal: int
    body: str
    context_header: str
    citation: str
    start_char: int
    end_char: int
    source_sha256: str = ""

    @property
    def content(self) -> str:
        """Text sent to indexing: repeated context followed by source-derived body."""
        return compose_index_text(self.context_header, self.body)


@dataclass(frozen=True, slots=True)
class Unit:
    """One source-ordered grouping of blocks that becomes exactly one chunk."""

    kind: ChunkKind
    body: str
    blocks: list[Block]
    narrative_heading: str | None


def _source_span(blocks: list[Block], source_length: int | None = None) -> tuple[int, int]:
    """Validate ordered, non-overlapping blocks and return their enclosing span.

    Gaps are allowed because the parser can omit page headers and footers from one
    narrative source group. The returned interval therefore cites the enclosing
    source range rather than claiming that every character becomes chunk body text.
    """
    if not blocks or any(block.source_pos is None or block.end_pos is None for block in blocks):
        raise ValueError("cannot create a chunk without complete source spans")

    groups = {block.source_group for block in blocks}
    if len(groups) != 1:
        raise ValueError("cannot create a chunk across source groups")

    previous_end: int | None = None
    for block in blocks:
        start, end = block.source_pos, block.end_pos
        assert start is not None and end is not None
        if not 0 <= start < end:
            raise ValueError(f"invalid block source span: [{start}, {end})")
        if previous_end is not None and start < previous_end:
            raise ValueError("chunk blocks are out of source order or overlap")
        if source_length is not None and end > source_length:
            raise ValueError(
                f"block source span ends beyond source length: {end} > {source_length}"
            )
        previous_end = end

    start = blocks[0].source_pos
    end = blocks[-1].end_pos
    assert start is not None and end is not None
    return start, end


def section_units(section: Section, config: ChunkConfig) -> list[Unit]:
    """Group blocks without crossing source groups, headings, or tables.

    Paragraphs join up to the soft target but never split. Consecutive headings become
    context, tables remain standalone, and blank paragraphs are ignored.
    """
    units: list[Unit] = []
    pending: list[Block] = []
    pending_chars = 0
    narrative_headings: list[str] = []
    heading_run = False
    active_group: int | None = None
    target_chars = config.target_text_chars
    add_unit = units.append
    to_markdown = table_to_markdown
    strip = str.strip
    heading_kind = "heading"
    table_kind = "table"
    text_kind = "text"
    para_sep_chars = 2

    def flush_pending() -> None:
        nonlocal pending, pending_chars
        if not pending:
            return

        add_unit(
            Unit(
                kind=text_kind,
                body="\n\n".join(block.text for block in pending),
                blocks=pending,
                narrative_heading=" · ".join(narrative_headings) or None,
            )
        )
        pending = []
        pending_chars = 0

    for block in section.blocks:
        if active_group != block.source_group:
            flush_pending()
            active_group = block.source_group
            narrative_headings = [block.source_heading] if block.source_heading else []
            heading_run = False

        if block.kind == heading_kind:
            flush_pending()
            if not heading_run:
                narrative_headings = []
            narrative_headings.append(block.text)
            heading_run = True
            continue

        if block.kind == table_kind:
            flush_pending()
            markdown = to_markdown(block.html)
            if markdown:
                heading = " · ".join(narrative_headings) or None
                add_unit(Unit(table_kind, markdown, [block], heading))
                heading_run = False
            continue

        text = block.text
        if not strip(text):
            continue
        heading_run = False

        block_chars = len(text)
        if pending and pending_chars + para_sep_chars + block_chars > target_chars:
            flush_pending()

        if pending:
            pending_chars += para_sep_chars + block_chars
        else:
            pending_chars = block_chars
        pending.append(block)

    flush_pending()
    return units


def _citation(filing: ParsedFiling, section: Section) -> str:
    """Return the issuer, fiscal year, and section citation."""
    item = f"Item {section.item}" if section.item else "Unnumbered section"
    return f"{filing.issuer} FY{filing.fiscal_year} · {item}"


def _context_header(
    filing: ParsedFiling, section: Section, narrative_heading: str | None = None
) -> str:
    """Build context that remains useful when a chunk is retrieved in isolation."""
    parts = [_citation(filing, section)]
    title = section.canonical_title or section.reported_title
    if title:
        parts.append(title)
    if narrative_heading and narrative_heading != title:
        parts.append(narrative_heading)
    return " · ".join(parts)


def chunk_filing(filing: ParsedFiling, config: ChunkConfig | None = None) -> list[Chunk]:
    """Build source-ordered chunks from source-identified parsed sections.

    Reject invalid source identity, skip non-parsed sections, and assign dense ordinals.
    """
    if filing.source_length <= 0:
        raise ValueError(f"{filing.doc_id} has no canonical source length")
    if SOURCE_SHA256_RE.fullmatch(filing.source_sha256) is None:
        raise ValueError(f"{filing.doc_id} has no canonical source SHA-256")
    cfg = config or ChunkConfig()
    chunks: list[Chunk] = []

    def append(
        section: Section,
        kind: ChunkKind,
        body: str,
        blocks: list[Block],
        narrative_heading: str | None = None,
    ) -> None:
        start, end = _source_span(blocks, filing.source_length)
        chunks.append(
            Chunk(
                doc_id=filing.doc_id,
                item=section.item,
                kind=kind,
                ordinal=len(chunks),
                body=body,
                context_header=_context_header(filing, section, narrative_heading),
                citation=_citation(filing, section),
                start_char=start,
                end_char=end,
                source_sha256=filing.source_sha256,
            )
        )

    for section in filing.sections:
        if section.status != "parsed":
            continue
        for unit in section_units(section, cfg):
            append(
                section,
                unit.kind,
                unit.body,
                unit.blocks,
                unit.narrative_heading,
            )

    # Heading-based sections already arrive in source order. Xref sections arrive
    # in SEC Item order instead, and one Item can own multiple narrative ranges.
    # A stable span sort restores document order before ordinals are materialized.
    chunks.sort(key=lambda chunk: (chunk.start_char, chunk.end_char))
    return [replace(chunk, ordinal=ordinal) for ordinal, chunk in enumerate(chunks)]


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import argparse
    import json
    from pathlib import Path
    from unittest.mock import patch

    from app.ingestion.parser import parse_filing

    parser = argparse.ArgumentParser(description="Inspect structure-aware 10-K chunks.")
    parser.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    parser.add_argument("--kind", choices=("text", "table"))
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(
        item for item in manifest if f"{item['ticker']}-FY{item['report_date'][:4]}" == args.doc
    )
    with patch("app.ingestion.parser.save_profile"):
        parsed, _ = parse_filing(entry)
    selected = [chunk for chunk in chunk_filing(parsed) if not args.kind or chunk.kind == args.kind]
    for chunk in selected[: args.limit]:
        print(f"\n{'─' * 80}\n#{chunk.ordinal} {chunk.kind} [{chunk.start_char}, {chunk.end_char})")
        print(chunk.content)
