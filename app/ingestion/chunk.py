"""Segment parsed sections into retrieval chunks with source spans and citations."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Literal

from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.registry import section_label
from app.ingestion.tables import (
    SourceCell,
    StructuredTable,
    TableCell,
    TableRow,
    is_unit_caption,
    structured_table,
)
from app.ingestion.tokens import MAX_INPUT_CHARACTERS, InputBudget

ChunkKind = Literal["text", "table"]

SOURCE_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)


def compose_index_text(context_header: str, body: str) -> str:
    """Compose indexed text using the canonical context-body separator.

    The persistence boundary must use the same double-newline separator.
    """
    return f"{context_header}\n\n{body}" if context_header else body


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Tunable parameters for structure-aware chunking."""

    target_tokens: int = 2_048
    max_tokens: int = 8_192
    max_chars: int = MAX_INPUT_CHARACTERS
    model: str = "text-embedding-3-large"
    token_counter: Callable[[str], int] | None = None

    def __post_init__(self) -> None:
        """Validate complete-input budgets through the shared token contract."""
        _ = self.budget

    @property
    def budget(self) -> InputBudget:
        """Return the shared tokenizer and complete-input size policy."""
        return InputBudget(
            self.model, self.target_tokens, self.max_tokens, self.max_chars, self.token_counter
        )


@dataclass(frozen=True, slots=True)
class CellFragment:
    """Membership in a normalized cell; text offsets are not HTML source offsets."""

    row: int
    column: int
    text_start: int
    text_end: int
    sources: tuple[SourceCell, ...]


@dataclass(frozen=True, slots=True)
class CaptionSource:
    """Bind caption text to its actual enclosing source block and original cells."""

    start_char: int
    end_char: int
    text: str
    cells: tuple[SourceCell, ...] = ()


@dataclass(frozen=True, slots=True)
class TableFragment:
    """Source rows and cell text intervals carried by one table retrieval unit."""

    header_rows: tuple[int, ...]
    cells: tuple[CellFragment, ...]
    header_cells: tuple[SourceCell, ...] = ()
    caption_sources: tuple[CaptionSource, ...] = ()


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
    table_fragment: TableFragment | None = None
    # Offsets within the normalized unit body, never within source HTML.
    text_fragment: tuple[int, int] | None = None

    @property
    def stable_key(self) -> str:
        """Identify source and rendered evidence independently of display ordinal."""
        payload = [
            self.doc_id,
            self.source_sha256,
            self.start_char,
            self.end_char,
            self.kind,
            self.body,
            self.context_header,
            asdict(self.table_fragment) if self.table_fragment else None,
            self.text_fragment,
        ]
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

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
    table: StructuredTable | None = None
    caption_sources: tuple[CaptionSource, ...] = ()


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


def section_units(
    section: Section,
    config: ChunkConfig,
    context_header: Callable[[str | None], str] | None = None,
) -> list[Unit]:
    """Group blocks without crossing source groups, headings, or tables.

    Paragraphs join up to the complete-input target. Oversized structural units are
    split by the filing builder. Blank paragraphs are ignored, and a paragraph
    that is nothing but a unit caption becomes the next table's context.
    """
    units: list[Unit] = []
    pending: list[Block] = []
    # Unit annotations harvested from caption-only tables and caption paragraphs.
    # They describe exactly the next table, so anything that intervenes — a heading,
    # a non-caption paragraph, a new source group, or the annotated table itself —
    # clears them; letting one live longer stamps a wrong monetary scale onto every
    # later table under the same heading.
    pending_captions: list[str] = []
    pending_caption_sources: list[CaptionSource] = []
    narrative_headings: list[str] = []
    heading_run = False
    active_group: int | None = None
    budget = config.budget
    add_unit = units.append
    strip = str.strip
    heading_kind = "heading"
    table_kind = "table"
    text_kind = "text"

    def flush_pending() -> None:
        """Emit the buffered paragraphs as one chunk and reset the buffer."""
        nonlocal pending
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

    for block in section.blocks:
        if active_group != block.source_group:
            flush_pending()
            active_group = block.source_group
            narrative_headings = [block.source_heading] if block.source_heading else []
            heading_run = False
            pending_captions = []
            pending_caption_sources = []

        if block.kind == heading_kind:
            flush_pending()
            if not heading_run:
                narrative_headings = []
            narrative_headings.append(block.text)
            heading_run = True
            pending_captions = []
            pending_caption_sources = []
            continue

        if block.kind == table_kind:
            flush_pending()
            table = structured_table(block.html)
            markdown = table.render()
            captions = table.captions if not markdown else ()
            if markdown:
                heading = " · ".join([*narrative_headings, *pending_captions]) or None
                caption_sources = tuple(pending_caption_sources)
                if table.captions:
                    start, end = _source_span([block])
                    caption_sources += (
                        CaptionSource(start, end, "\n".join(table.captions), table.caption_cells),
                    )
                add_unit(Unit(table_kind, markdown, [block], heading, table, caption_sources))
                heading_run = False
                pending_captions = []
                pending_caption_sources = []
                continue
            # A caption-only table annotates the one table that follows it, so its
            # unit travels as context instead of being dropped with the empty markdown.
            if captions:
                start, end = _source_span([block])
                pending_caption_sources.append(
                    CaptionSource(start, end, "\n".join(captions), table.caption_cells)
                )
            for caption in captions:
                if caption not in pending_captions:
                    pending_captions.append(caption)
            continue

        text = block.text
        if not strip(text):
            continue
        if is_unit_caption(text):
            # DART's dominant caption form is a bare paragraph line right before the
            # data table. Buffered as narrative it dangles at the end of a text chunk
            # and never reaches that table, so it travels as pending caption context
            # instead. The heading run stays open because a caption sitting between a
            # heading and its table must not break the run. When a non-caption
            # paragraph or a heading follows instead, the clearing rules below drop
            # the caption entirely — the same fate a dangling caption-only table meets.
            caption = strip(text)
            start, end = _source_span([block])
            pending_caption_sources.append(CaptionSource(start, end, caption))
            if caption not in pending_captions:
                pending_captions.append(caption)
            continue
        heading_run = False
        pending_captions = []
        pending_caption_sources = []

        if pending and not budget.accepts(
            compose_index_text(
                context_header(" · ".join(narrative_headings) or None)
                if context_header
                else " · ".join(narrative_headings),
                "\n\n".join([*(item.text for item in pending), text]),
            ),
            target=True,
        ):
            flush_pending()

        pending.append(block)

    flush_pending()
    return units


def _citation(filing: ParsedFiling, section: Section) -> str:
    """Return the issuer, fiscal year, and section citation.

    Each registry names its own section codes — EDGAR writes ``Item 7`` where DART
    writes a Roman numeral — so the label comes from the registry rather than from a
    format string that would spell every corpus the EDGAR way.
    """
    item = (
        section_label(filing.source.document.registry, section.item)
        if section.item
        else "Unnumbered section"
    )
    return f"{filing.source.document.issuer} FY{filing.source.document.fiscal_year} · {item}"


def _context_header(
    filing: ParsedFiling, section: Section, narrative_heading: str | None = None
) -> str:
    """Build context that remains useful when a chunk is retrieved in isolation."""
    citation = _citation(filing, section)
    parts = [citation]
    title = section.canonical_title or section.reported_title
    # A registry whose section label already spells the title (DART's "I. 회사의 개요")
    # would otherwise repeat it back to back in every indexed chunk.
    if title and not citation.endswith(title):
        parts.append(title)
    if narrative_heading and narrative_heading != title:
        parts.append(narrative_heading)
    return " · ".join(parts)


def _text_pieces(text: str, context: str, budget: InputBudget) -> list[str]:
    """Pack complete sentences, rejecting an indivisible input above the hard bounds."""
    if budget.accepts(compose_index_text(context, text), target=True):
        return [text]
    atoms = re.split(r"(?<=[.!?。！？])(?=\s)|(?<=\n)(?=\n)", text)
    pieces: list[str] = []
    pending = ""
    for atom in atoms:
        if not atom:
            continue
        if not budget.accepts(compose_index_text(context, atom)):
            raise ValueError(
                "An indivisible sentence and its context exceed the embedding token/character "
                "limit; shorten the source sentence or supply a structural parser boundary."
            )
        if pending and not budget.accepts(compose_index_text(context, pending + atom), target=True):
            pieces.append(pending)
            pending = ""
        pending += atom
    if pending:
        pieces.append(pending)
    return pieces


def _table_pieces(
    table: StructuredTable,
    context: str,
    budget: InputBudget,
    caption_sources: tuple[CaptionSource, ...] = (),
) -> list[tuple[str, TableFragment]]:
    """Pack rows, then cells and sentences, preserving enclosing source ownership."""
    result: list[tuple[str, TableFragment]] = []
    pending: list[TableRow] = []
    header_cells = tuple(
        dict.fromkeys(
            source
            for row in table.headers
            for cell in row.cells
            for source in cell.sources
            if source.text
        )
    )

    def fits(rows: tuple[TableRow, ...], *, target: bool = True) -> bool:
        """Measure the complete repeated headings, units, headers, and selected rows."""
        return budget.accepts(compose_index_text(context, table.render(rows)), target=target)

    def membership(rows: tuple[TableRow, ...]) -> TableFragment:
        """Record complete normalized cells and their original source relationships."""
        return TableFragment(
            tuple(row.source_row for row in table.headers),
            tuple(
                CellFragment(row.source_row, cell.column, 0, len(cell.text), cell.sources)
                for row in rows
                for cell in row.cells
            ),
            header_cells,
            caption_sources,
        )

    def flush() -> None:
        """Emit accumulated complete rows without re-inferring their headers."""
        if pending:
            rows = tuple(pending)
            result.append((table.render(rows), membership(rows)))
            pending.clear()

    if fits(table.rows):
        return [(table.render(), membership(table.rows))]
    for row in table.rows:
        if fits((row,)):
            if pending and not fits((*pending, row)):
                flush()
            pending.append(row)
            continue
        flush()
        # A wide row is represented as multiple sparse rows with the same row id.
        # Column headers remain in every fragment; the original label repeats when
        # it fits, so values remain meaningful without claiming new HTML spans.
        for cell in row.cells:
            if not cell.text:
                continue
            blank = tuple(replace(value, text="") for value in row.cells)
            label = row.cells[0]
            base = list(blank)
            if cell.column != 0 and label.text:
                base[0] = label
            candidate = list(base)
            candidate[cell.column] = cell
            candidate_row = replace(row, cells=tuple(candidate))
            if fits((candidate_row,)):
                result.append((table.render((candidate_row,)), membership((candidate_row,))))
                continue
            # Avoid making a long narrative label mandatory context for all values.
            if cell.column != 0:
                base[0] = blank[0]
            atoms = re.split(r"(?<=[.!?。！？])(?=\s)", cell.text)
            offset = 0
            text = ""
            start = 0

            def emit(
                text: str,
                start: int,
                *,
                base: list[TableCell] = base,
                cell: TableCell = cell,
                row: TableRow = row,
                label: TableCell = label,
            ) -> None:
                """Emit a sentence-aligned interval of this normalized source cell."""
                if not text:
                    return
                values = list(base)
                values[cell.column] = replace(cell, text=text)
                part = replace(row, cells=tuple(values))
                members = [
                    CellFragment(
                        row.source_row, cell.column, start, start + len(text), cell.sources
                    )
                ]
                if cell.column != 0 and values[0].text:
                    members.append(
                        CellFragment(row.source_row, 0, 0, len(label.text), label.sources)
                    )
                result.append(
                    (
                        table.render((part,)),
                        TableFragment(
                            tuple(header.source_row for header in table.headers),
                            tuple(members),
                            header_cells,
                            caption_sources,
                        ),
                    )
                )

            for atom in atoms:
                values = list(base)
                values[cell.column] = replace(cell, text=atom)
                if not fits((replace(row, cells=tuple(values)),), target=False):
                    raise ValueError(
                        f"Table row {row.source_row}, column {cell.column}: an indivisible "
                        "sentence with repeated headers exceeds the embedding token/character "
                        "limit; supply a finer structural source boundary."
                    )
                values[cell.column] = replace(cell, text=text + atom)
                if text and not fits((replace(row, cells=tuple(values)),)):
                    emit(text, start)
                    text = ""
                    start = offset
                text += atom
                offset += len(atom)
            emit(text, start)
    flush()
    return result


def chunk_filing(filing: ParsedFiling, config: ChunkConfig | None = None) -> list[Chunk]:
    """Build source-ordered chunks from source-identified parsed sections.

    Reject invalid source identity, skip non-parsed sections, and assign dense ordinals.
    """
    if filing.source_length <= 0:
        raise ValueError(f"{filing.source.document.document_id} has no canonical source length")
    if SOURCE_SHA256_RE.fullmatch(filing.source_sha256) is None:
        raise ValueError(f"{filing.source.document.document_id} has no canonical source SHA-256")
    cfg = config or ChunkConfig()
    chunks: list[Chunk] = []

    def append(
        section: Section,
        kind: ChunkKind,
        body: str,
        blocks: list[Block],
        narrative_heading: str | None = None,
        table_fragment: TableFragment | None = None,
        text_fragment: tuple[int, int] | None = None,
    ) -> None:
        """Record one chunk with its section, kind, and source blocks."""
        start, end = _source_span(blocks, filing.source_length)
        if table_fragment is not None:
            for caption in table_fragment.caption_sources:
                if not 0 <= caption.start_char < caption.end_char <= filing.source_length:
                    raise ValueError("caption source span exceeds the canonical document")
                if caption.end_char > start and (caption.start_char, caption.end_char) != (
                    start,
                    end,
                ):
                    raise ValueError("caption source must precede or belong to its data table")
        chunks.append(
            Chunk(
                doc_id=filing.source.document.document_id,
                item=section.item,
                kind=kind,
                ordinal=len(chunks),
                body=body,
                context_header=_context_header(filing, section, narrative_heading),
                citation=_citation(filing, section),
                start_char=start,
                end_char=end,
                source_sha256=filing.source_sha256,
                table_fragment=table_fragment,
                text_fragment=text_fragment,
            )
        )

    for section in filing.sections:
        if section.status != "parsed":
            continue

        def unit_context(heading: str | None, section: Section = section) -> str:
            """Measure grouping with the complete filing and section context."""
            return _context_header(filing, section, heading)

        for unit in section_units(section, cfg, unit_context):
            context = _context_header(filing, section, unit.narrative_heading)
            if unit.table is not None:
                pieces = _table_pieces(unit.table, context, cfg.budget, unit.caption_sources)
                for body, membership in pieces:
                    append(
                        section, unit.kind, body, unit.blocks, unit.narrative_heading, membership
                    )
            else:
                offset = 0
                for body in _text_pieces(unit.body, context, cfg.budget):
                    append(
                        section,
                        unit.kind,
                        body,
                        unit.blocks,
                        unit.narrative_heading,
                        text_fragment=(offset, offset + len(body)),
                    )
                    offset += len(body)

    # Heading-based sections already arrive in source order. Xref sections arrive
    # in SEC Item order instead, and one Item can own multiple narrative ranges.
    # A stable span sort restores document order before ordinals are materialized.
    chunks.sort(key=lambda chunk: (chunk.start_char, chunk.end_char))
    return [replace(chunk, ordinal=ordinal) for ordinal, chunk in enumerate(chunks)]


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import argparse
    from pathlib import Path
    from unittest.mock import patch

    from app.ingestion.manifest import Manifest
    from app.ingestion.registry import resolve_registry

    parser = argparse.ArgumentParser(description="Inspect structure-aware filing chunks.")
    parser.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    parser.add_argument("--manifest", type=Path, default=Path("data/corpus/manifest.json"))
    parser.add_argument("--kind", choices=("text", "table"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--selection", required=True)
    args = parser.parse_args()

    manifest = Manifest.read(args.manifest)
    sources = manifest.selected_sources(args.selection, args.manifest.parent)
    entry = next((source for source in sources if source.document.document_id == args.doc), None)
    if entry is None:
        known = ", ".join(source.document.document_id for source in sources)
        raise SystemExit(f"unknown doc {args.doc!r}; selected documents: {known}")
    with patch("app.ingestion.edgar.save_profile"):
        parsed, _ = resolve_registry(entry).parse(entry)
    selected = [chunk for chunk in chunk_filing(parsed) if not args.kind or chunk.kind == args.kind]
    for chunk in selected[: args.limit]:
        print(f"\n{'─' * 80}\n#{chunk.ordinal} {chunk.kind} [{chunk.start_char}, {chunk.end_char})")
        print(chunk.content)
