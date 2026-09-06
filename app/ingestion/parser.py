"""Parse raw SEC 10-K filings into normalized sections and blocks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Literal
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from app.ingestion.xref import (
    assign_items,
    find_missing,
    find_tables,
    in_tables,
    item_for_page,
    locate_sections,
    page_map,
    parse_toc,
    parse_xref,
)

SegmentType = Literal["number", "sec_canonical", "custom_title", "xref", "undefined"]
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
    """One SEC filing section and its extracted blocks and provenance."""

    part: str | None  # "I".."IV"
    item: str | None  # "1A"
    canonical_title: str  # SEC canonical title
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
    """Top-level output contract containing the complete parse of one filing."""

    doc_id: str  # "NVDA-FY2024"
    ticker: str
    cik: str
    form: str
    filing_date: str
    report_period: str
    fiscal_year: int
    accession: str
    source_url: str
    source_length: int = 0  # Unicode code points in the canonical decoded source
    source_sha256: str = ""  # SHA-256 of the exact source bytes
    sections: list[Section] = field(default_factory=list)
    item_index: list[dict] = field(default_factory=list)  # xref-only source index
    parse_status: str = "parsed"  # parsed | needs_profile_update
    warnings: list[str] = field(default_factory=list)
    profile_used: str = "saved"  # bootstrap | saved | relearned
    segment_type: str = ""
    # Validation measurements kept here so the CLI does not parse the filing twice.
    n_blocks: int = 0
    n_chars: int = 0  # total document text length, used as the coverage denominator


CANONICAL = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Reserved",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Foreign Jurisdictions That Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}
ORDER = list(CANONICAL)  # dict preserves insertion order in Python 3.7+
PART_OF = {
    **dict.fromkeys(["1", "1A", "1B", "1C", "2", "3", "4"], "I"),
    **dict.fromkeys(["5", "6", "7", "7A", "8", "9", "9A", "9B", "9C"], "II"),
    **dict.fromkeys(["10", "11", "12", "13", "14"], "III"),
    **dict.fromkeys(["15", "16"], "IV"),
}


ITEM_RE = re.compile(
    r"^\s*item\s+(?P<num>1[0-6]|[1-9])(?P<suffix>[A-C])?\s*[.\-–—:]?\s*(?P<title>.*)$",
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

# L7 heading walk
HEADING_MAX_CHARS = 300  # longer blocks cannot be headings; run this cheapest filter first
SUBHEADING_MAX_CHARS = 80  # maximum length for a level-2 narrative subheading
REPORTED_TITLE_MAX = 150  # maximum stored Section.reported_title length
CANON_MIN_CHARS = 8  # shorter SEC-title candidates match by accident (B11)
CANON_PREFIX_CHARS = 14  # require this many characters for prefix matches (B11)

# L9 detection cascade
NUMBER_MIN_HITS = 5  # fewer matches indicate cross-references, not headings
OUTSIDE_TABLE_MIN_HITS = 15  # inspect tables when too few matches exist outside them (F4)
TOC_MIN_ITEMS = 10  # minimum Item candidates required to classify a TOC
TOC_DENSITY = 0.15  # candidates clustered within this document fraction indicate a TOC (B16)
XREF_MIN_ENTRIES = 10  # minimum entries required for a cross-reference index
XREF_MIN_TOC_ROWS = 5  # minimum rows required for a table of contents

# L8 xref assembly
ORPHAN_MIN_BLOCKS = 3  # discard shorter orphan ranges as fragments (B07)
JOINED_TITLE_MAX = 300  # maximum reported_title after joining narrative titles
PAGE_HEADER_MAX_CHARS = 60  # short, frequent text is a page header (F11)
PAGE_HEADER_MIN_REPEATS = 10  # "Table of Contents" appears 113 times

# L10 status classification
CLASSIFY_SCAN_CHARS = 400  # inspect only this many leading section characters
REF_MAX_BLOCKS = 3  # more blocks indicate body content, not a reference-only section

# L12 validation
CORE_THIN_BLOCKS = 20  # fewer blocks means a core Item has no body
CORE_THIN_COUNT = 2  # this many thin core Items indicate TOC headings were selected (B10)
XREF_THIN_BLOCKS = 5  # thin-section threshold for xref filings
XREF_THIN_RATIO = 0.3  # fail when thin sections exceed this ratio


def read_source(path: str | Path) -> str:
    """Read a filing source file as a UTF-8 string.

    Parameters
    ----------
    path
        Path-like value to the source HTML file.

    Returns
    -------
    str
        Entire file contents decoded with UTF-8.
    """
    return Path(path).read_bytes().decode("utf-8")


def source_digest(source: str) -> str:
    """Compute a deterministic digest for the raw source text.

    Parameters
    ----------
    source
        Raw filing text.

    Returns
    -------
    str
        SHA-256 hex digest string.
    """
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def line_offsets(html: str) -> list[int]:
    """Collect cumulative character offsets for each line start.

    Parameters
    ----------
    html
        Raw source text.

    Returns
    -------
    list[int]
        Offsets of line starts in absolute characters.
    """
    out, off = [], 0
    for line in html.splitlines(keepends=True):
        out.append(off)
        off += len(line)
    return out


def source_pos(el: Tag, offsets: list[int]) -> int | None:
    """Resolve the absolute source position for an element.

    Parameters
    ----------
    el
        Parsed BeautifulSoup element carrying `sourceline` and `sourcepos`.
    offsets
        Start offsets for each source line.

    Returns
    -------
    int | None
        Absolute character index if source metadata exists, otherwise ``None``.
    """
    if el.sourceline is None or el.sourcepos is None:
        return None
    return offsets[el.sourceline - 1] + el.sourcepos


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
    """Heuristically classify a table as financial data.

    Parameters
    ----------
    tbl
        Candidate table tag.

    Returns
    -------
    bool
        ``True`` when table shape and numeric density match a data table pattern.
    """
    cells = tbl.find_all(["td", "th"])
    if len(cells) < DATA_TABLE_MIN_CELLS:
        return False
    texts = [c.get_text(" ", strip=True) for c in cells]
    if any(len(t) > LAYOUT_CELL_CHARS for t in texts):  # a long prose cell means layout
        return False
    numeric = sum(1 for t in texts if t and len(t) < NUMERIC_CELL_CHARS and re.search(r"\d", t))
    return numeric >= max(DATA_TABLE_MIN_NUMERIC, len(cells) // DATA_TABLE_NUMERIC_DIVISOR)


def leaf_blocks(soup: BeautifulSoup) -> list[Tag]:
    """Extract leaf content blocks used by downstream segmentation.

    Parameters
    ----------
    soup
        Parsed BeautifulSoup document.

    Returns
    -------
    list[Tag]
        Ordered list of block-level elements considered leaf nodes for parsing.
    """
    data_ids: set[int] = set()
    for t in soup.find_all("table"):
        if _is_data_table(t) and not any(id(p) in data_ids for p in t.find_parents("table")):
            data_ids.add(id(t))  # keep only the outermost nested table

    out = []
    for el in soup.find_all(["div", "p", "table"]):
        inside_data = any(id(p) in data_ids for p in el.find_parents("table"))
        if el.name == "table":
            if not inside_data and (id(el) in data_ids or el.find(["div", "p", "table"]) is None):
                out.append(el)  # keep a data table or legacy leaf table as one block
        elif not inside_data and el.find(["div", "p", "table"]) is None:
            out.append(el)
    return out


def _inline_css(el: Tag) -> str:
    """Read inline CSS declarations from an element and small descendants.

    Parameters
    ----------
    el
        Candidate block element.

    Returns
    -------
    str
        Space-joined inline CSS snippets.
    """
    styles: list[str] = []

    own_style = el.get("style")
    if isinstance(own_style, str):
        styles.append(own_style)

    for span in el.find_all("span", limit=2):
        span_style = span.get("style")
        if isinstance(span_style, str):
            styles.append(span_style)

    return " ".join(styles)


def block_props(el: Tag) -> dict:
    """Compute compact style-derived features for a block element.

    Parameters
    ----------
    el
        Candidate block element.

    Returns
    -------
    dict
        Font and layout features used by heading heuristics.
    """
    css = _inline_css(el)  # element style plus up to two nested span styles

    def num(pattern: str) -> float:
        m = re.search(pattern, css)
        return float(m.group(1)) if m else 0.0

    mw = re.search(r"font-weight:\s*(\d+|bold)", css)
    weight = mw.group(1) if mw else "400"
    return {
        "font_weight": 700 if weight == "bold" else int(weight),
        "font_size": num(r"font-size:\s*([\d.]+)pt"),
        "margin_top": num(r"margin-top:\s*([\d.]+)pt"),
        "margin_bottom": num(r"margin-bottom:\s*([\d.]+)pt"),
        "text_align": (m.group(1) if (m := re.search(r"text-align:\s*(\w+)", css)) else ""),
        "tag": el.name,
        "in_table": el.find_parent("table") is not None,
    }


def matches_rule(el: Tag, rule: dict) -> bool:
    """Check whether element properties satisfy a single rule predicate.

    Parameters
    ----------
    el
        Candidate element.
    rule
        Property constraints to enforce.

    Returns
    -------
    bool
        ``True`` when all constraints are met.
    """
    props = block_props(el)
    for key, expected in rule.items():
        actual = props.get(key)
        if actual is None:
            continue  # an unknown key adds no constraint
        if key == "in_table":
            if not expected and actual:  # constrain only when False is expected
                return False
        elif isinstance(expected, bool) or isinstance(actual, bool):
            if actual != expected:
                return False
        elif isinstance(expected, int | float):
            if actual < expected:
                return False  # numeric rules are minimum thresholds
        elif actual != expected:
            return False
    return True


def matches_any(el: Tag, rules: list[dict]) -> bool:
    """Check whether an element matches at least one rule.

    Parameters
    ----------
    el
        Candidate element.
    rules
        Rule list.

    Returns
    -------
    bool
        ``True`` when any rule matches.
    """
    return any(matches_rule(el, r) for r in rules)


def body_after(blocks: list[Tag], idx: int, span: int = 8) -> int:
    """Sum trailing text length across a short block window.

    Parameters
    ----------
    blocks
        Ordered parsed leaf blocks.
    idx
        Starting index.
    span
        Number of following blocks to include.

    Returns
    -------
    int
        Total character count of the following blocks' text.
    """
    return sum(
        len(blocks[j].get_text(" ", strip=True))
        for j in range(idx + 1, min(idx + 1 + span, len(blocks)))
    )


def _norm_title(s: str) -> str:
    """Normalize a title to lowercase letters and spaces only.

    Parameters
    ----------
    s
        Raw title string.

    Returns
    -------
    str
        Normalized title.
    """
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def match_canonical(text: str) -> str | None:
    """Match a title against canonical SEC Item names.

    Parameters
    ----------
    text
        Candidate title.

    Returns
    -------
    str | None
        Matched Item number, or ``None`` if none.
    """
    t = _norm_title(text)
    if len(t) < CANON_MIN_CHARS:  # guard 1: defer when the candidate is too short
        return None
    for item, canon in CANONICAL.items():
        c = _norm_title(canon)
        if t == c:
            return item
        # Guard 2: permit prefix matching only with enough characters.
        if len(c) >= CANON_PREFIX_CHARS and (
            t.startswith(c[:CANON_PREFIX_CHARS]) or c.startswith(t[:CANON_PREFIX_CHARS])
        ):
            return item
    return None


def find_item(el: Tag, text: str, seg: dict) -> str | None:
    """Find which SEC Item this block belongs to.

    Parameters
    ----------
    el
        Candidate element.
    text
        Block text.
    seg
        Segmentation strategy descriptor.

    Returns
    -------
    str | None
        Item number for heading blocks, otherwise ``None``.
    """
    # First determine which Item the text names.
    match seg["type"]:
        case "number":
            m = ITEM_RE.match(text)
            item = (m.group("num") + (m.group("suffix") or "")).upper() if m else None
        case "sec_canonical":
            item = match_canonical(text)  # compare against the canonical SEC title table
        case "custom_title":
            low = text.strip().lower()
            item = next(
                (e["item"] for e in seg["order"] if e["title"].strip().lower() == low),
                None,
            )
        case _:
            return None
    if item is None:
        return None

    # Then use presentation alone to decide whether it is a heading.
    return item if matches_any(el, seg["rules"]) else None


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


def _body_block(
    el: Tag,
    text: str,
    start_char: int | None = None,
    end_char: int | None = None,
    source_group: int = 0,
    source_heading: str | None = None,
) -> Block:
    """Convert a source element into a parsed `Block`.

    Parameters
    ----------
    el
        Source element.
    text
        Element text.
    start_char
        Source start offset.
    end_char
        Source end offset.
    source_group
        Group index for contiguous narrative ranges.
    source_heading
        Optional narrative heading associated with this block.

    Returns
    -------
    Block
        Parsed block object.
    """
    if el.name == "table":
        return Block(
            "table",
            "",
            html=str(el),
            source_pos=start_char,
            end_pos=end_char,
            source_group=source_group,
            source_heading=source_heading,
        )
    if len(text) <= SUBHEADING_MAX_CHARS and block_props(el)["font_weight"] >= 700:
        return Block(
            "heading",
            text,
            level=2,
            source_pos=start_char,
            end_pos=end_char,
            source_group=source_group,
            source_heading=source_heading,
        )  # narrative subheading
    return Block(
        "paragraph",
        text,
        source_pos=start_char,
        end_pos=end_char,
        source_group=source_group,
        source_heading=source_heading,
    )


def segment_by_heading(
    blocks: list[Tag],
    seg: dict,
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> list[Section]:
    """Build sections by sequential heading detection.

    Parameters
    ----------
    blocks
        Leaf content blocks.
    seg
        Segmentation strategy rules.
    offsets
        Optional line offsets.
    source_end
        Optional final source end offset.

    Returns
    -------
    list[Section]
        Detected Item sections in order.
    """
    texts = [b.get_text(" ", strip=True) for b in blocks]
    source_spans = block_source_spans(blocks, offsets, source_end)
    sections: list[Section] = []
    current: Section | None = None

    for i, el in enumerate(blocks):
        text = texts[i]
        if not text:
            continue
        # A long paragraph cannot be a heading; apply the cheapest filter first.
        item = find_item(el, text, seg) if len(text) < HEADING_MAX_CHARS else None

        if item:
            if current is not None:  # the previous section ends here
                current.block_range = (current.block_index or 0, i)
            current = Section(
                part=PART_OF.get(item),
                item=item,
                canonical_title=CANONICAL.get(item, ""),
                reported_title=text[:REPORTED_TITLE_MAX],
                block_index=i,
                source_pos=source_pos(el, offsets) if offsets else None,
            )
            sections.append(current)
        elif current is not None:
            current.blocks.append(_body_block(el, text, *source_spans[i]))
        # Before the first Item, discard cover and TOC blocks that belong to no section.
    if current is not None:
        current.block_range = (current.block_index or 0, len(blocks))
    return sections


def _looks_like_toc(blocks: list[Tag]) -> bool:
    """Detect whether block layout resembles a table of contents.

    Parameters
    ----------
    blocks
        Leaf blocks.

    Returns
    -------
    bool
        ``True`` when Item candidates are densely clustered early in the filing.
    """
    idx = [
        i
        for i, el in enumerate(blocks)
        if (t := el.get_text(" ", strip=True)) and len(t) < HEADING_MAX_CHARS and ITEM_RE.match(t)
    ]
    if len(idx) < TOC_MIN_ITEMS:
        return False
    return idx[-1] - idx[0] < len(blocks) * TOC_DENSITY


def detect_number(blocks: list[Tag]) -> dict:
    """Apply heading-based segmentation strategy.

    Parameters
    ----------
    blocks
        Leaf blocks extracted from filing body.

    Returns
    -------
    dict
        Strategy descriptor; empty mapping if this strategy does not apply.
    """

    def collect(allow_table: bool) -> list[tuple[int, float]]:
        out = []
        for el in blocks:
            t = el.get_text(" ", strip=True)
            if not t or len(t) > HEADING_MAX_CHARS or not ITEM_RE.match(t):
                continue
            if not allow_table and el.find_parent("table") is not None:
                continue
            props = block_props(el)
            if props["font_weight"] < 700:  # unstyled matches are TOC entries or references
                continue
            out.append((props["font_weight"], props["font_size"]))
        return out

    outside, inside = collect(False), collect(True)
    hits, in_table = (outside, False) if len(outside) >= OUTSIDE_TABLE_MIN_HITS else (inside, True)
    # When table-contained headings are required, confirm the table is not a TOC.
    if len(hits) < NUMBER_MIN_HITS or (in_table and _looks_like_toc(blocks)):
        return {}

    # Use the loosest rule covering every observation; a mean or mode drops valid headings.
    return {
        "type": "number",
        "rules": [
            {
                "font_weight": min(w for w, _ in hits),
                "font_size": min(s for _, s in hits),
                "in_table": in_table,
            }
        ],
    }


def detect_xref(soup: BeautifulSoup, blocks: list[Tag]) -> dict:
    """Apply cross-reference-index segmentation strategy.

    Parameters
    ----------
    soup
        Parsed document.
    blocks
        Leaf blocks.

    Returns
    -------
    dict
        Strategy descriptor; empty mapping if the xref pattern is not detected.
    """
    xref_tbl, toc_tbl = find_tables(soup)
    if xref_tbl is None or toc_tbl is None:
        return {}
    if len(parse_xref(xref_tbl)) < XREF_MIN_ENTRIES or len(parse_toc(toc_tbl)) < XREF_MIN_TOC_ROWS:
        return {}
    return {"type": "xref"}


def segment_by_xref(
    soup: BeautifulSoup,
    blocks: list[Tag],
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> tuple[list[Section], list[dict]]:
    """Assemble sections from cross-reference index and TOC tables.

    Parameters
    ----------
    soup
        Parsed document.
    blocks
        Leaf blocks.
    offsets
        Optional line offsets.
    source_end
        Optional final source offset.

    Returns
    -------
    tuple[list[Section], list[dict]]
        Parsed sections and raw xref index records.
    """
    xref_tbl, toc_tbl = find_tables(soup)
    source_spans = block_source_spans(blocks, offsets, source_end)
    entries = parse_xref(xref_tbl)
    toc = parse_toc(toc_tbl)
    item_index = [
        {
            "item": e.item,
            "reported_title": e.reported_title,
            "pages": e.spans,
            "status": e.status,
            "reference_source": e.reference_source,
        }
        for e in entries
    ]

    skip = in_tables(blocks, [xref_tbl, toc_tbl])  # TOC and index tables are not body text
    freq = Counter(b.get_text(" ", strip=True) for b in blocks)
    located = locate_sections(blocks, toc, skip)
    assigned = assign_items(located, entries)

    # Search the body for Items omitted from the TOC, such as Legal Proceedings in notes.
    for title, page, bi in find_missing(blocks, entries, set(assigned.values()), skip):
        if bi not in assigned:
            located.append((title, page, bi))
            assigned[bi] = next(e.item for e in entries if e.reported_title == title)
    located.sort(key=lambda t: t[2])
    footer_at = {p: i for i, p in page_map(blocks)}  # page -> footer block

    # A narrative section ends before the next section; image headings can shift the boundary.
    spans: list[tuple[str, str, int, int]] = []  # (item, narrative title, start, end)
    for k, (title, page, bi) in enumerate(located):
        end = located[k + 1][2] if k + 1 < len(located) else len(blocks)
        item = assigned.get(bi)
        if item is None:
            continue
        entry = next(e for e in entries if e.item == item)
        hi = (entry.covering(page) or (page, page))[1]  # end page of this section's range
        next_page = located[k + 1][1] if k + 1 < len(located) else 10**9
        clamp = footer_at.get(hi)
        # Clamp only when the next heading starts more than one page later. A heading on
        # the next page indicates spillover rather than an orphan (measured FY2021 Item 7A).
        if clamp is not None and bi < clamp + 1 < end and next_page > hi + 1:
            orphan_lo, orphan_page = clamp + 1, hi + 1
            end = clamp + 1
            # Assign an orphan range to the Item owning that page (FY2022 pages 72-80 -> Item 8).
            if (
                k + 1 < len(located)
                and (owner := item_for_page(orphan_page, entries))
                and located[k + 1][2] - orphan_lo >= ORPHAN_MIN_BLOCKS  # discard fragments
            ):
                spans.append((owner, CANONICAL.get(owner, ""), orphan_lo, located[k + 1][2]))
        spans.append((item, title, bi, end))
    spans.sort(key=lambda s: s[2])

    # Merge narrative sections assigned to one Item in document order without duplicates.
    by_item: dict[str, list[tuple[str, int, int]]] = {}
    for item, title, lo, hi in spans:
        by_item.setdefault(item, []).append((title, lo, hi))

    sections: list[Section] = []
    for e in entries:
        parts = by_item.get(e.item, [])
        sec = Section(
            part=PART_OF.get(e.item),
            item=e.item,
            canonical_title=CANONICAL.get(e.item, ""),
            reported_title=("; ".join(t for t, _, _ in parts) if parts else e.reported_title)[
                :JOINED_TITLE_MAX
            ],
            status=e.status,
            reference_source=e.reference_source,
            block_index=parts[0][1] if parts else None,
            block_range=(min(p[1] for p in parts), max(p[2] for p in parts)) if parts else None,
            source_pos=(source_pos(blocks[parts[0][1]], offsets) if parts and offsets else None),
        )
        for source_group, (_title, lo, hi) in enumerate(parts):
            for j in range(lo, hi):
                if j in skip:
                    continue
                text = blocks[j].get_text(" ", strip=True)
                if not text:
                    continue
                # Page footers such as "71" and repeated page headers are not body text.
                if re.fullmatch(r"\d{1,3}", text) or (
                    len(text) < PAGE_HEADER_MAX_CHARS and freq[text] >= PAGE_HEADER_MIN_REPEATS
                ):
                    continue
                sec.blocks.append(
                    _body_block(
                        blocks[j],
                        text,
                        *source_spans[j],
                        source_group=source_group,
                        source_heading=_title,
                    )
                )
        sections.append(sec)
    return sections, item_index


def detect_segmentation(soup: BeautifulSoup, blocks: list[Tag]) -> dict:
    """Select the first successful segmentation strategy.

    Parameters
    ----------
    soup
        Parsed document.
    blocks
        Leaf blocks.

    Returns
    -------
    dict
        Selected segmentation strategy descriptor.
    """
    return detect_number(blocks) or detect_xref(soup, blocks) or {"type": "undefined"}


EMPTY_RE = re.compile(r"^\s*(none|not applicable|n/?a)\.?\s*$", re.I)
REF_RE = re.compile(
    r"(incorporated (herein )?by reference|is set forth in|will be (contained|included) in"
    r"|information (required by|regarding).{0,80}(proxy|incorporated|set forth))",
    re.I,
)


def classify_sections(sections: list[Section]) -> None:
    """Apply status heuristics to short heading-based sections.

    Parameters
    ----------
    sections
        Parsed sections in document order.
    """
    for s in sections:
        text = " ".join(b.text for b in s.blocks if b.kind == "paragraph")[
            :CLASSIFY_SCAN_CHARS
        ].strip()
        if not text:
            continue
        if EMPTY_RE.match(text):
            s.status = "empty_disclosure"
        elif len(s.blocks) <= REF_MAX_BLOCKS and REF_RE.search(text):
            s.status = "incorporated_by_reference"


def segment(
    soup: BeautifulSoup,
    blocks: list[Tag],
    seg: dict,
    offsets: list[int] | None = None,
    source_end: int | None = None,
) -> tuple[list[Section], list[dict]]:
    """Dispatch to the selected segmentation strategy.

    Parameters
    ----------
    soup
        Parsed document.
    blocks
        Leaf blocks.
    seg
        Strategy descriptor.
    offsets
        Optional line offsets.
    source_end
        Optional final source offset.

    Returns
    -------
    tuple[list[Section], list[dict]]
        Sections and optional index metadata.
    """
    match seg["type"]:
        case "xref":
            return segment_by_xref(soup, blocks, offsets, source_end)
        case "undefined":
            return [], []
        case _:
            sections = segment_by_heading(blocks, seg, offsets, source_end)
            classify_sections(sections)  # distinguish valid short disclosures from bugs
            return sections, []


def build_profile(soup: BeautifulSoup, blocks: list[Tag], doc_id: str) -> dict:
    """Build a parsing profile from a filing sample.

    Parameters
    ----------
    soup
        Parsed document.
    blocks
        Leaf blocks.
    doc_id
        Filing identifier for profile metadata.

    Returns
    -------
    dict
        Parsing profile object.
    """
    seg = detect_segmentation(soup, blocks)
    sections, _ = segment(soup, blocks, seg)
    items = [s.item for s in sections if s.item]

    # xref does not store expected_items because each year's index states them directly.
    validation: dict = {"must_have": ["1A", "7", "8"]}
    if seg["type"] not in ("xref", "undefined"):
        validation = {
            "expected_items": len(items),
            "must_have": ["1", "1A", "7", "8"],
        }
    return {
        "segmentation": seg,
        "validation": validation,
        "learned_from": doc_id,
        "learned_by": "bootstrap",
        "learned_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


PROFILES = Path("data/profiles")


def load_profile(ticker: str, year: int) -> dict | None:
    """Load a year-specific profile from disk.

    Parameters
    ----------
    ticker
        Company ticker key.
    year
        Filing year.

    Returns
    -------
    dict | None
        Parsed profile if available, otherwise ``None``.
    """
    path = PROFILES / f"{ticker}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data["profiles"].get(str(year)) or data["profiles"].get(data["default_year"])


def save_profile(ticker: str, year: int, profile: dict) -> None:
    """Persist a profile and refresh default year tracking.

    Parameters
    ----------
    ticker
        Company ticker key.
    year
        Filing year.
    profile
        Profile payload to store.
    """
    PROFILES.mkdir(parents=True, exist_ok=True)
    path = PROFILES / f"{ticker}.json"
    data = (
        json.loads(path.read_text())
        if path.exists()
        else {"ticker": ticker, "default_year": str(year), "profiles": {}}
    )
    data["profiles"][str(year)] = profile
    data["default_year"] = max(data["profiles"], key=int)
    # Store years in ascending order for human readability.
    data["profiles"] = dict(sorted(data["profiles"].items(), key=lambda kv: int(kv[0])))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


CORE_ITEMS = ("1", "1A", "7", "8")


def _validate_xref(sections: list[Section], index: list[dict], exp: dict) -> list[str]:
    """Validate xref filings by indexed item coverage.

    Parameters
    ----------
    sections
        Parsed sections.
    index
        Cross-reference index entries.
    exp
        Validation expectations.

    Returns
    -------
    list[str]
        Validation problem messages.
    """
    problems: list[str] = []
    explained = {s.item for s in sections if s.item and (s.blocks or s.status != "parsed")}
    if missing := sorted({e["item"] for e in index} - explained):
        problems.append(f"설명되지 않은 item: {missing}")
    if miss := sorted(set(exp["must_have"]) - {s.item for s in sections if s.blocks}):
        problems.append(f"핵심 item 누락: {miss}")
    thin = sorted(
        s.item
        for s in sections
        if s.item is not None and s.status == "parsed" and len(s.blocks) < XREF_THIN_BLOCKS
    )
    if index and len(thin) > len(index) * XREF_THIN_RATIO:
        problems.append(f"얇은 섹션 과다: {thin}")
    return problems


def validate(sections: list[Section], profile: dict, index: list[dict] | None = None) -> list[str]:
    """Validate parsed sections and return all problems.

    Parameters
    ----------
    sections
        Parsed sections.
    profile
        Active parse profile.
    index
        Optional xref index when `profile["segmentation"]["type"] == "xref"`.

    Returns
    -------
    list[str]
        Validation failures; empty when validation passes.
    """
    seg, exp = profile["segmentation"], profile["validation"]
    if seg["type"] == "xref":
        return _validate_xref(sections, index or [], exp)
    items = [s.item for s in sections if s.item]
    problems: list[str] = []

    if len(items) != exp["expected_items"]:
        problems.append(f"item 개수 {len(items)} != 기대 {exp['expected_items']}")

    # Use custom_title array order when present; otherwise use canonical SEC order.
    ranking = [e["item"] for e in seg["order"]] if seg["type"] == "custom_title" else ORDER
    rank = {v: i for i, v in enumerate(ranking)}
    checked = [i for i in items if i in rank]
    if checked != sorted(checked, key=lambda i: rank[i]):
        problems.append("item 순서가 어긋남")

    if dup := sorted({i for i in items if items.count(i) > 1}):
        problems.append(f"중복: {dup}")

    if miss := sorted(set(exp["must_have"]) - set(items)):
        problems.append(f"핵심 item 누락: {miss}")

    # Fail even with perfect structure when body content is absent, as with TOC headings.
    thin = sorted(
        s.item
        for s in sections
        if s.item is not None
        and s.item in CORE_ITEMS
        and s.status == "parsed"
        and len(s.blocks) < CORE_THIN_BLOCKS
    )
    if len(thin) >= CORE_THIN_COUNT:
        problems.append(f"목차로 보임(본문 없는 핵심 item): {thin}")

    return problems


def parse_filing(entry: dict) -> tuple[ParsedFiling, dict]:
    """Parse one filing with load/build/relearn validation loop.

    Parameters
    ----------
    entry
        Manifest entry containing filing metadata and source path.

    Returns
    -------
    tuple[ParsedFiling, dict]
        Parsed filing object and effective profile.
    """
    ticker, year = entry["ticker"], int(entry["report_date"][:4])
    doc_id = f"{ticker}-FY{year}"
    raw = read_source(entry["file"])
    soup = normalize(raw)
    blocks = leaf_blocks(soup)
    offsets = line_offsets(raw)

    out = ParsedFiling(
        doc_id=doc_id,
        ticker=ticker,
        cik=str(entry.get("cik", "")),
        form="10-K",
        filing_date=entry.get("filing_date", ""),
        report_period=entry.get("report_date", ""),
        fiscal_year=year,
        accession=entry.get("accession", ""),
        source_url=entry.get("url", ""),
        source_length=len(raw),
        source_sha256=source_digest(raw),
        n_blocks=len(blocks),
        n_chars=sum(len(b.get_text(" ", strip=True)) for b in blocks),
    )

    profile = load_profile(ticker, year)
    out.profile_used = "saved"
    if profile is None:
        profile = build_profile(soup, blocks, doc_id)
        save_profile(ticker, year, profile)
        out.profile_used = "bootstrap"

    sections, index = segment(soup, blocks, profile["segmentation"], offsets, len(raw))
    problems = validate(sections, profile, index) if sections else ["섹션 0개"]

    if problems:
        # On failure, relearn from this filing and store only this year after success (F4).
        relearned = build_profile(soup, blocks, doc_id)
        r_sections, r_index = segment(soup, blocks, relearned["segmentation"], offsets, len(raw))
        r_problems = validate(r_sections, relearned, r_index) if r_sections else ["섹션 0개"]
        if not r_problems:
            save_profile(ticker, year, relearned)  # save only a successful profile
            profile, sections, index, problems = relearned, r_sections, r_index, r_problems
            out.profile_used = "relearned"

    out.sections = sections
    out.item_index = index
    out.warnings = problems
    out.parse_status = "parsed" if not problems else "needs_profile_update"
    out.segment_type = profile["segmentation"]["type"]
    return out, profile


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="10-K 파서 — 단계별 확인용")
    ap.add_argument("--ticker", help="한 회사만 (예: NVDA)")
    ap.add_argument("--file", help="파일 하나만 (경로)")
    ap.add_argument("--blocks", action="store_true", help="1~2단계: 블록화 결과")
    ap.add_argument("--sections", action="store_true", help="섹션별 본문량·표 개수")
    ap.add_argument(
        "--headings", action="store_true", help="각 Item 헤딩의 블록 번호·원본 오프셋·뒤따르는 본문"
    )
    ap.add_argument(
        "--coverage", action="store_true", help="섹션 본문 합 / 문서 전체 — 버려진 텍스트를 잡는다"
    )
    ap.add_argument(
        "--items", action="store_true", help="SEC Item 목록 대조 — 헤딩 누락·오탐을 잡는다"
    )
    ap.add_argument("--profile", action="store_true", help="학습된 프로파일 JSON")
    a = ap.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    targets = [e for e in manifest if not a.ticker or e["ticker"] == a.ticker]
    if a.file:
        targets = [e for e in manifest if e["file"] == a.file]
    if not targets:
        raise SystemExit(f"대상 없음 (ticker={a.ticker} file={a.file})")

    stats: dict[str, int] = {}
    for entry in sorted(targets, key=lambda e: (e["ticker"], e["report_date"])):
        # Handle stages 1-2 separately because they precede parsing.
        if a.blocks:
            soup = normalize(read_source(entry["file"]))
            blocks = leaf_blocks(soup)
            tables = [b for b in blocks if b.name == "table"]
            doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
            print(
                f"{doc_id:12} 블록 {len(blocks):5,}  표블록 {len(tables):4}  "
                f"문서표 {len(soup.find_all('table')):4}"
            )
            continue

        r, profile = parse_filing(entry)
        stats[r.segment_type] = stats.get(r.segment_type, 0) + 1

        if a.profile:
            print(f"--- {r.doc_id} ({r.profile_used}) ---")
            print(json.dumps(profile, indent=2, ensure_ascii=False))
            continue

        if a.headings:
            raw = read_source(entry["file"])
            print(f"--- {r.doc_id} ({r.segment_type}) ---")
            for sec in r.sections:
                head = raw[sec.source_pos : sec.source_pos + 46] if sec.source_pos else ""
                body = next((b.text for b in sec.blocks if b.kind == "paragraph"), "")
                print(
                    f"  {sec.item or '-':4} blk{str(sec.block_index):>6} "
                    f"pos{str(sec.source_pos):>10}  {sec.reported_title[:42]}"
                )
                print(f"       원본 {head!r}")
                print(f"       본문 {body[:54]!r}")
            continue

        if a.items:
            # Coverage cannot detect a missing heading because the prior section absorbs
            # its text. Compare against the SEC Item list to validate boundaries.
            got = [s.item for s in r.sections if s.item]
            missing = [i for i in ORDER if i not in got]
            extra = [i for i in got if i not in ORDER]
            # Items 1C (added 2023), 9C (added 2021), and optional 16 may be absent.
            odd = [m for m in missing if m not in ("1C", "9C", "16")]
            print(
                f"{r.doc_id:12} {len(got):2}개  누락={missing or '-'}  "
                f"과잉={extra or '-'}{'  ★' if (odd or extra) else ''}"
            )
            continue

        body = sum(len(b.text) for s in r.sections for b in s.blocks)
        tbl_chars = sum(
            len(BeautifulSoup(b.html, "html.parser").get_text(" ", strip=True))
            for s in r.sections
            for b in s.blocks
            if b.kind == "table" and b.html
        )

        if a.coverage:
            pct = (body + tbl_chars) / r.n_chars * 100 if r.n_chars else 0
            print(
                f"{r.doc_id:12} 전체 {r.n_chars:>9,}  섹션 {body + tbl_chars:>9,}  "
                f"커버 {pct:5.1f}%{'   ★낮음' if pct < 90 else ''}"
            )
            continue

        items = [s.item for s in r.sections if s.item]
        tbl = sum(1 for s in r.sections for b in s.blocks if b.kind == "table")
        print(
            f"{r.doc_id:12} {r.parse_status:20} type={r.segment_type:9} "
            f"{r.profile_used:10} items={len(items):2} 본문={body:>8,} 표={tbl:3}"
        )
        for w in r.warnings:
            print(f"               ⚠ {w}")

        if a.sections:
            for s in r.sections:
                n = sum(len(b.text) for b in s.blocks)
                t = sum(1 for b in s.blocks if b.kind == "table")
                flag = "" if s.status == "parsed" else f"  [{s.status}]"
                print(
                    f"     Item {s.item or '-':4} {n:>8,}자 표{t:3}  {s.reported_title[:52]}{flag}"
                )

    if not (a.blocks or a.profile or a.headings):
        print(f"\n집계: {stats}")
