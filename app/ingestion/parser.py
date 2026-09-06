"""Source-anchored parsing contract shared by every registry adapter.

Holds the neutral data contract (``Block``, ``Section``, ``ParsedFiling``) and the
source-fidelity helpers -- reading, hashing, offset math, HTML normalization, and
leaf-block extraction -- that every registry parser builds on. Registry-specific
segmentation lives in the adapter modules (``app.ingestion.edgar``,
``app.ingestion.dart``); nothing here knows one registry's markup from another's.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Literal
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from app.ingestion.manifest import FilingSource
from app.ingestion.tables import CELL_TAGS

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
    # Validation measurements kept here so the CLI does not parse the filing twice.
    n_blocks: int = 0
    n_chars: int = 0  # total document text length, used as the coverage denominator


HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
LEAF_BLOCK_TAGS = ("div", "p", "table", *HEADING_TAGS)
STYLESHEET_WEIGHT_KEY = "_parser_stylesheet_font_weight"
STYLESHEET_RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}")
STYLESHEET_WEIGHT_RE = re.compile(
    r"font-weight\s*:\s*(?P<weight>bold(?:er)?|[1-9]00)\b",
    re.I,
)
SIMPLE_CLASS_SELECTOR_RE = re.compile(
    r"(?:(?P<tag>[a-z][\w-]*))?\.(?P<class>[a-z_][\w-]*)\Z",
    re.I,
)

# -- Tuning constants ---------------------------------------------------------
# None of these values is arbitrary. All were measured on the 20-document corpus.
# Measure again before changing one.
# Evidence notation: F = docs/en/m1-1-parser/01-findings.md, B = docs/en/m1-1-parser/04-bugs.md
#
# Declare equal values separately when their meanings differ (for example,
# LAYOUT_CELL_CHARS and HEADING_MAX_CHARS are both 300). Either can change alone,
# and named constants prevent a search for `300` from editing the wrong threshold.

# L3 blockification: distinguish data tables from layout tables (F9)
DATA_TABLE_MIN_CELLS = 6  # fewer cells indicate a layout fragment
LAYOUT_CELL_CHARS = 300  # any cell this long makes the table a layout table
# Check length before numeric density to exclude Intel infographic tables (B05).
NUMERIC_CELL_CHARS = 30  # longer text is prose containing a number, not a numeric cell
DATA_TABLE_MIN_NUMERIC = 4  # minimum number of numeric cells
DATA_TABLE_NUMERIC_DIVISOR = 4  # numeric cells must also be at least one quarter of all cells

REPORTED_TITLE_MAX = 150  # maximum stored Section.reported_title length


def read_source(path: str | Path) -> str:
    """Return a filing source file decoded as UTF-8."""
    return Path(path).read_bytes().decode("utf-8")


def source_digest(source: str) -> str:
    """Return the SHA-256 hex digest of raw source text."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def line_offsets(html: str) -> list[int]:
    r"""Return the absolute character offset of each line start.

    Lines are split on ``\n`` alone, because the ``sourceline`` values these offsets
    are indexed by come from ``HTMLParser``, which counts only that separator.
    ``str.splitlines`` also breaks on ``\r``, ``\x0b``, ``\x0c``, ``\x1c``-``\x1e``,
    ``\x85`` and the Unicode line separators, and every such character would shift the
    remaining offsets while leaving spans monotonic and in bounds — a silently wrong
    citation rather than a failure.
    """
    out, off = [], 0
    for line in html.split("\n"):
        out.append(off)
        off += len(line) + 1
    return out


def source_pos(el: Tag, offsets: list[int]) -> int | None:
    """Return an element's absolute source offset, or None when unavailable."""
    if el.sourceline is None or el.sourcepos is None:
        return None
    return offsets[el.sourceline - 1] + el.sourcepos


def _record_stylesheet_font_weights(soup: BeautifulSoup) -> None:
    """Attach non-serialized font weights from simple internal class rules."""
    for style in soup.find_all("style"):
        css = re.sub(r"/\*.*?\*/", "", style.get_text(" ", strip=False), flags=re.S)
        for rule in STYLESHEET_RULE_RE.finditer(css):
            weights = STYLESHEET_WEIGHT_RE.findall(rule.group("body"))
            if not weights:
                continue
            raw_weight = weights[-1].lower()
            weight = 700 if raw_weight in {"bold", "bolder"} else int(raw_weight)
            for selector in rule.group("selectors").split(","):
                match = SIMPLE_CLASS_SELECTOR_RE.fullmatch(selector.strip())
                if match is None:
                    continue
                tag_name = match.group("tag")
                class_name = match.group("class")
                matches = (
                    soup.find_all(tag_name, class_=class_name)
                    if tag_name
                    else soup.find_all(class_=class_name)
                )
                for tag in matches:
                    tag.__dict__[STYLESHEET_WEIGHT_KEY] = weight


def normalize(html: str) -> BeautifulSoup:
    """Normalize HTML into a `BeautifulSoup` tree while removing non-rendered nodes.

    html.parser with `store_line_numbers=True` is kept to preserve source offsets
    for validation and reprojection.

    Parameters
    ----------
    html
        Raw filing HTML.

    Returns
    -------
    BeautifulSoup
        Parsed tree with non-body rendering artifacts removed.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "html.parser", store_line_numbers=True)
    _record_stylesheet_font_weights(soup)
    for tag in soup.find_all(["script", "style", "noscript", "img"]):
        tag.decompose()  # remove the node and all descendants
    # Drop ix:header entirely. It is a non-rendered machine-readable iXBRL region
    # containing XBRL context definitions (34,148 chars in measured MU-FY2024 and
    # 59,005 in INTC-FY2019). Unwrapping would release all of it into the first body block.
    for tag in soup.find_all("ix:header"):
        tag.decompose()
    for tag in soup.find_all(lambda tag: bool(tag.name and tag.name.startswith("ix:"))):
        tag.unwrap()  # remove other iXBRL tags while preserving their text and numbers
    return soup


def _is_data_table(tbl: Tag) -> bool:
    """Return whether a table has the shape and numeric density of financial data."""
    cells = tbl.find_all(list(CELL_TAGS))
    if len(cells) < DATA_TABLE_MIN_CELLS:
        return False
    texts = [c.get_text(" ", strip=True) for c in cells]
    if any(len(t) > LAYOUT_CELL_CHARS for t in texts):  # a long prose cell means layout
        return False
    numeric = sum(1 for t in texts if t and len(t) < NUMERIC_CELL_CHARS and re.search(r"\d", t))
    return numeric >= max(DATA_TABLE_MIN_NUMERIC, len(cells) // DATA_TABLE_NUMERIC_DIVISOR)


def leaf_blocks(soup: BeautifulSoup, tags: Sequence[str] = LEAF_BLOCK_TAGS) -> list[Tag]:
    """Extract leaf content blocks used by downstream segmentation.

    Parameters
    ----------
    soup
        Parsed BeautifulSoup document.
    tags
        Block-level tag names a registry treats as content. The default is the EDGAR
        HTML vocabulary; a registry whose documents carry their own block tags passes
        its own so the data-table detection here is not reimplemented against it.

    Returns
    -------
    list[Tag]
        Ordered list of block-level elements considered leaf nodes for parsing.
    """
    block_tags = list(tags)
    data_ids: set[int] = set()
    for t in soup.find_all("table"):
        if _is_data_table(t) and not any(id(p) in data_ids for p in t.find_parents("table")):
            data_ids.add(id(t))  # keep only the outermost nested table

    out = []
    for el in soup.find_all(block_tags):
        inside_data = any(id(p) in data_ids for p in el.find_parents("table"))
        if el.name == "table":
            if not inside_data and (id(el) in data_ids or el.find(block_tags) is None):
                out.append(el)  # keep a data table or legacy leaf table as one block
        elif not inside_data and el.find(block_tags) is None:
            out.append(el)
    return out


def block_source_spans(
    blocks: list[Tag], offsets: list[int] | None, source_end: int | None = None
) -> list[tuple[int | None, int | None]]:
    """Compute source spans for each ordered block.

    Parameters
    ----------
    blocks
        Ordered leaf blocks.
    offsets
        Line-start offsets, or ``None`` if unavailable.
    source_end
        Optional end offset for the final block.

    Returns
    -------
    list[tuple[int | None, int | None]]
        Ordered half-open source spans.
    """
    if offsets is None:
        return [(None, None) for _ in blocks]

    starts = [source_pos(block, offsets) for block in blocks]
    spans: list[tuple[int | None, int | None]] = [(None, None)] * len(starts)
    next_start = source_end
    for i in range(len(starts) - 1, -1, -1):
        start = starts[i]
        spans[i] = (start, next_start)
        if start is not None:
            next_start = start
    return spans
