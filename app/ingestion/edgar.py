"""Parse an EDGAR 10-K into the source-anchored section contract.

EDGAR publishes presentation-driven HTML, so everything here is heuristic:
heading detection from measured font styles, the canonical SEC Item vocabulary,
cross-reference and TOC assembly, and the learned per-issuer profiles that keep
those heuristics honest. What crosses the boundary is a ``ParsedFiling`` built
from the neutral contract in ``app.ingestion.parser`` -- the same shape the DART
adapter produces -- so nothing downstream reads EDGAR vocabulary.
"""

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Literal

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from app.ingestion.parser import (
    HEADING_TAGS,
    REPORTED_TITLE_MAX,
    STYLESHEET_WEIGHT_KEY,
    Block,
    ParsedFiling,
    Section,
    block_source_spans,
    leaf_blocks,
    line_offsets,
    normalize,
    read_source,
    source_digest,
    source_pos,
)
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


# EDGAR heading and segmentation thresholds. None of these values is arbitrary --
# all were measured on the 20-document corpus; measure again before changing one.
# Evidence notation: F = docs/en/m1-1-parser/01-findings.md, B = 04-bugs.md
# L7 heading walk
HEADING_MAX_CHARS = 300  # longer blocks cannot be headings; run this cheapest filter first
SUBHEADING_MAX_CHARS = 80  # maximum length for a level-2 narrative subheading

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


def doc_id(entry: dict) -> str:
    """Return the document ID derived from an EDGAR manifest entry.

    The ``"{issuer}-FY{year}"`` shape is the contract; reading it out of these particular
    manifest keys is EDGAR-specific, so another registry supplies its own reader.
    """
    return f"{entry['ticker']}-FY{entry['report_date'][:4]}"


def edgar_sort_key(entry: dict[str, Any]) -> tuple[str, ...]:
    """Order EDGAR entries by ticker, then report date."""
    return (str(entry.get("ticker", "")), str(entry.get("report_date", "")))


def edgar_section_label(item: str) -> str:
    """Return the SEC citation label for a section code, as EDGAR itself names it."""
    return f"Item {item}"


def _inline_css(el: Tag) -> str:
    """Return space-joined inline CSS from an element and up to two nested spans."""
    styles: list[str] = []

    own_style = el.get("style")
    if isinstance(own_style, str):
        styles.append(own_style)

    for span in el.find_all("span", limit=2):
        span_style = span.get("style")
        if isinstance(span_style, str):
            styles.append(span_style)

    return " ".join(styles)


def _stylesheet_font_weight(el: Tag) -> int:
    """Return an inferred internal-stylesheet weight inherited by a block."""
    node: Tag | None = el
    while node is not None:
        if weight := node.__dict__.get(STYLESHEET_WEIGHT_KEY):
            return int(weight)
        node = node.parent if isinstance(node.parent, Tag) else None
    return max(
        (int(span.__dict__.get(STYLESHEET_WEIGHT_KEY, 0)) for span in el.find_all("span", limit=2)),
        default=0,
    )


def _semantic_font_weight(el: Tag) -> int:
    """Return the browser-default bold weight for semantic heading markup."""
    if el.name in HEADING_TAGS or el.find_parent(["b", "strong"]) is not None:
        return 700
    text_nodes = [
        node for node in el.descendants if isinstance(node, NavigableString) and str(node).strip()
    ]
    if text_nodes and all(
        any(parent.name in {"b", "strong"} for parent in node.parents if parent is not el)
        for node in text_nodes
    ):
        return 700
    return 400


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
        """Return the first numeric group of one CSS pattern, or zero when absent."""
        m = re.search(pattern, css)
        return float(m.group(1)) if m else 0.0

    mw = re.search(r"font-weight:\s*(\d+|bold)", css)
    weight = mw.group(1) if mw else str(_stylesheet_font_weight(el) or 400)
    numeric_weight = 700 if weight == "bold" else int(weight)
    return {
        "font_weight": max(numeric_weight, _semantic_font_weight(el)),
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
    """Return whether an element matches at least one rule."""
    return any(matches_rule(el, r) for r in rules)


def body_after(blocks: list[Tag], idx: int, span: int = 8) -> int:
    """Return the text length of up to `span` blocks following `idx`."""
    return sum(
        len(blocks[j].get_text(" ", strip=True))
        for j in range(idx + 1, min(idx + 1 + span, len(blocks)))
    )


def _norm_title(s: str) -> str:
    """Return a title normalized to lowercase letters and spaces."""
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
        item = find_item(el, text, seg) if len(text) <= HEADING_MAX_CHARS else None

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
    """Return whether Item candidates are densely clustered near the filing start."""
    idx = [
        i
        for i, el in enumerate(blocks)
        if (t := el.get_text(" ", strip=True)) and len(t) <= HEADING_MAX_CHARS and ITEM_RE.match(t)
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
        """Collect the item numbers and their vertical positions from the blocks."""
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
    """Return an xref strategy descriptor, or an empty mapping when not detected."""
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
        has_next = k + 1 < len(located)
        end = located[k + 1][2] if has_next else len(blocks)
        item = assigned.get(bi)
        if item is None:
            continue
        entry = next(e for e in entries if e.item == item)
        hi = (entry.covering(page) or (page, page))[1]  # end page of this section's range
        next_page = located[k + 1][1] if has_next else 10**9
        clamp = footer_at.get(hi)
        # Clamp only when a following heading can bound or receive the tail. A heading
        # on the next page indicates spillover rather than an orphan (measured FY2021 Item 7A).
        if has_next and clamp is not None and bi < clamp + 1 < end and next_page > hi + 1:
            orphan_lo, orphan_page = clamp + 1, hi + 1
            end = clamp + 1
            # Assign an orphan range to the Item owning that page (FY2022 pages 72-80 -> Item 8).
            if (
                (owner := item_for_page(orphan_page, entries))
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
    """Return the first successful segmentation strategy."""
    return detect_number(blocks) or detect_xref(soup, blocks) or {"type": "undefined"}


EMPTY_RE = re.compile(r"^\s*(none|not applicable|n/?a)\.?\s*$", re.I)
REF_RE = re.compile(
    r"(incorporated (herein )?by reference|is set forth in|will be (contained|included) in"
    r"|information (required by|regarding).{0,80}(proxy|incorporated|set forth))",
    re.I,
)


def classify_sections(sections: list[Section]) -> None:
    """Assign status heuristics to short heading-based sections."""
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


def load_profile(issuer: str, year: int) -> dict | None:
    """Return a year-specific profile, falling back to the default, or None if absent."""
    path = PROFILES / f"{issuer}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data["profiles"].get(str(year)) or data["profiles"].get(data["default_year"])


def save_profile(issuer: str, year: int, profile: dict) -> None:
    """Persist a year-specific profile and refresh default-year tracking."""
    PROFILES.mkdir(parents=True, exist_ok=True)
    path = PROFILES / f"{issuer}.json"
    data = (
        json.loads(path.read_text())
        if path.exists()
        else {"issuer": issuer, "default_year": str(year), "profiles": {}}
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
        problems.append(f"unexplained items: {missing}")
    if miss := sorted(set(exp["must_have"]) - {s.item for s in sections if s.blocks}):
        problems.append(f"missing core items: {miss}")
    thin = sorted(
        s.item
        for s in sections
        if s.item is not None and s.status == "parsed" and len(s.blocks) < XREF_THIN_BLOCKS
    )
    if index and len(thin) > len(index) * XREF_THIN_RATIO:
        problems.append(f"too many thin sections: {thin}")
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
        problems.append(f"item count {len(items)} != expected {exp['expected_items']}")

    # Use custom_title array order when present; otherwise use canonical SEC order.
    ranking = [e["item"] for e in seg["order"]] if seg["type"] == "custom_title" else ORDER
    rank = {v: i for i, v in enumerate(ranking)}
    checked = [i for i in items if i in rank]
    if checked != sorted(checked, key=lambda i: rank[i]):
        problems.append("item order mismatch")

    if dup := sorted({i for i in items if items.count(i) > 1}):
        problems.append(f"duplicate items: {dup}")

    if miss := sorted(set(exp["must_have"]) - set(items)):
        problems.append(f"missing core items: {miss}")

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
        problems.append(f"appears to be a table of contents (core items without body text): {thin}")

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
    issuer, year = entry["ticker"], int(entry["report_date"][:4])
    document = doc_id(entry)
    raw = read_source(entry["file"])
    soup = normalize(raw)
    blocks = leaf_blocks(soup)
    offsets = line_offsets(raw)

    # This mapping is the EDGAR-specific half: manifest keys on the right, neutral
    # contract on the left. A DART reader writes its own mapping and stops here.
    out = ParsedFiling(
        doc_id=document,
        registry=entry.get("registry", "sec"),
        issuer=issuer,
        issuer_id=str(entry.get("cik", "")),
        filing_id=entry.get("accession", ""),
        form=entry.get("form", "10-K"),
        filing_date=entry.get("filing_date", ""),
        report_period=entry.get("report_date", ""),
        fiscal_year=year,
        source_url=entry.get("url", ""),
        source_length=len(raw),
        source_sha256=source_digest(raw),
        n_blocks=len(blocks),
        n_chars=sum(len(b.get_text(" ", strip=True)) for b in blocks),
    )

    profile = load_profile(issuer, year)
    bootstrapped = profile is None
    out.profile_used = "saved"
    if bootstrapped:
        profile = build_profile(soup, blocks, document)
        out.profile_used = "bootstrap"

    sections, index = segment(soup, blocks, profile["segmentation"], offsets, len(raw))
    problems = validate(sections, profile, index) if sections else ["no sections"]

    if bootstrapped and not problems:
        save_profile(issuer, year, profile)

    if problems:
        # On failure, relearn from this filing and store only this year after success (F4).
        relearned = build_profile(soup, blocks, document)
        r_sections, r_index = segment(soup, blocks, relearned["segmentation"], offsets, len(raw))
        r_problems = validate(r_sections, relearned, r_index) if r_sections else ["no sections"]
        if not r_problems:
            save_profile(issuer, year, relearned)  # save only a successful profile
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

    ap = argparse.ArgumentParser(description="10-K parser — step-by-step inspection")
    ap.add_argument("--ticker", help="one company only (e.g. NVDA)")
    ap.add_argument("--file", help="one file only (path)")
    ap.add_argument("--blocks", action="store_true", help="stages 1–2: block extraction results")
    ap.add_argument(
        "--sections", action="store_true", help="body length and table count by section"
    )
    ap.add_argument(
        "--headings",
        action="store_true",
        help="block number, source offset, and following body for each Item heading",
    )
    ap.add_argument(
        "--coverage",
        action="store_true",
        help="section body total / entire document — catches discarded text",
    )
    ap.add_argument(
        "--items",
        action="store_true",
        help="compare against the SEC Item list — catches missing and false-positive headings",
    )
    ap.add_argument("--profile", action="store_true", help="learned profile JSON")
    a = ap.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    targets = [e for e in manifest if not a.ticker or e["ticker"] == a.ticker]
    if a.file:
        targets = [e for e in manifest if e["file"] == a.file]
    if not targets:
        raise SystemExit(f"no targets (ticker={a.ticker} file={a.file})")

    stats: dict[str, int] = {}
    for entry in sorted(targets, key=lambda e: (e["ticker"], e["report_date"])):
        # Handle stages 1-2 separately because they precede parsing.
        if a.blocks:
            soup = normalize(read_source(entry["file"]))
            blocks = leaf_blocks(soup)
            tables = [b for b in blocks if b.name == "table"]
            print(
                f"{doc_id(entry):12} blocks {len(blocks):5,}  table blocks {len(tables):4}  "
                f"document tables {len(soup.find_all('table')):4}"
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
                print(f"       source {head!r}")
                print(f"       body   {body[:54]!r}")
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
                f"{r.doc_id:12} {len(got):2} items  missing={missing or '-'}  "
                f"extra={extra or '-'}{'  ★' if (odd or extra) else ''}"
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
                f"{r.doc_id:12} total {r.n_chars:>9,}  sections {body + tbl_chars:>9,}  "
                f"coverage {pct:5.1f}%{'   ★LOW' if pct < 90 else ''}"
            )
            continue

        items = [s.item for s in r.sections if s.item]
        tbl = sum(1 for s in r.sections for b in s.blocks if b.kind == "table")
        print(
            f"{r.doc_id:12} {r.parse_status:20} type={r.segment_type:9} "
            f"{r.profile_used:10} items={len(items):2} body={body:>8,} tables={tbl:3}"
        )
        for w in r.warnings:
            print(f"               ⚠ {w}")

        if a.sections:
            for s in r.sections:
                n = sum(len(b.text) for b in s.blocks)
                t = sum(1 for b in s.blocks if b.kind == "table")
                flag = "" if s.status == "parsed" else f"  [{s.status}]"
                print(
                    f"     Item {s.item or '-':4} {n:>8,} chars tables={t:3}  "
                    f"{s.reported_title[:52]}{flag}"
                )

    if not (a.blocks or a.profile or a.headings):
        print(f"\nsummary: {stats}")
