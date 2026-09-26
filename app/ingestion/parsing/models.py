"""Source-bound parser output shared by registry adapters and chunking."""

from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.sources.models import FilingSource

ItemStatus = Literal["parsed", "empty_disclosure", "incorporated_by_reference"]


@dataclass
class Block:
    """One source-positioned structural block extracted from a filing."""

    kind: Literal["heading", "paragraph", "table"]
    text: str
    level: int | None = None  # 1=Item heading, 2=narrative subheading
    html: str | None = None  # raw table input for the M1.2 markdown converter
    source_pos: int | None = None  # start offset in the original HTML
    end_pos: int | None = None  # exclusive end offset in the original HTML
    source_group: int = 0  # contiguous narrative range within one Section
    source_heading: str | None = None  # title of that narrative range


@dataclass
class Section:
    """One filing section and its extracted blocks and provenance."""

    part: str | None  # top-level division of the filing: "I".."IV" in a 10-K
    item: str | None  # section code within that division: "1A"
    canonical_title: str  # title as the registry's own section list spells it
    reported_title: str  # title used by the filing
    blocks: list[Block] = field(default_factory=list)
    status: ItemStatus = "parsed"
    reference_source: str | None = None
    # Location proves where an Item was found instead of merely claiming it was found.
    block_index: int | None = None  # heading block number
    block_range: tuple[int, int] | None = None  # block range occupied by this section
    source_pos: int | None = None  # character offset in the original HTML


@dataclass
class ParsedFiling:
    """Top-level output contract containing the complete parse of one filing.

    Identity names the registry that published the filing and that registry's own keys,
    so a filing from another registry fills this contract without renaming a field.
    Reading a filing out of DART instead of EDGAR changes the values, not the shape.
    """

    source: FilingSource
    source_length: int = 0  # Unicode code points in the canonical decoded source
    source_sha256: str = ""  # SHA-256 of canonical decoded text encoded as UTF-8
    sections: list[Section] = field(default_factory=list)
    item_index: list[dict] = field(default_factory=list)  # xref-only source index
    parse_status: str = "parsed"  # parsed | needs_profile_update
    warnings: list[str] = field(default_factory=list)
    profile_used: str = "saved"  # bootstrap | saved | relearned
    segment_type: str = ""
