"""Parse the Items an EDGAR amendment (10-K/A) sets out.

An amendment restates only some Items of the report it amends, after a cover page
and usually an explanatory note. The whole-report parser in
``app.ingestion.parsing.sec`` cannot read one: it validates against a learned
per-issuer profile that expects every Item, and an amendment shares its issuer and
fiscal year with the report, so a profile learned from it would replace the report's.

This parser therefore reads and writes no profile. Only a styled, numbered heading
whose title agrees with its Item number starts an Item, and anything it cannot bound
with confidence is reported as a warning that leaves the filing not ready rather than
guessed at. Text outside every Item -- the cover page, the explanatory note, Part
headings and signatures -- stays in the source artifact and becomes no section.

Parsing establishes where each Item is in the source. Whether an Item replaces or
adds to the original report's disclosure is not decided here.
"""

from collections import Counter
import re

from bs4 import Tag

from app.ingestion.parsing.html import REPORTED_TITLE_MAX, block_source_spans
from app.ingestion.parsing.models import ParsedFiling, Section
from app.ingestion.parsing.sec import (
    CANONICAL,
    HEADING_MAX_CHARS,
    ITEM_RE,
    ORDER,
    PART_OF,
    REF_MAX_BLOCKS,
    block_props,
    body_block,
    classify_sections,
    item_code,
    norm_title,
    prepare_source,
)
from app.ingestion.parsing.tables import CELL_TAGS, MAX_SPAN
from app.ingestion.sources.models import FilingSource

PROFILE_USED = "amendment"  # no per-issuer profile is read, learned or saved
SEGMENT_TYPE = "amendment_number"

# Titles a filing may print for an Item besides the short canonical one: the title
# Form 10-K itself gives, an earlier title of the same Item, or a punctuation variant.
# The vocabulary stays explicit so that a heading whose number and title disagree is
# reported instead of accepted.
ALTERNATIVE_TITLES: dict[str, tuple[str, ...]] = {
    "6": ("Selected Financial Data",),
    "9C": ("Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",),
    "10": ("Directors, Officers and Corporate Governance",),
    "15": ("Exhibits, Financial Statement Schedules", "Exhibit and Financial Statement Schedules"),
}

# A Part heading or the signature page ends the Item before it without starting one.
BOUNDARY_RE = re.compile(r"(?:PART\s+(?:I|II|III|IV)|SIGNATURES?)\s*\.?", re.I)

# A short Item that only points at pages elsewhere ("begin on page F-1") leaves the
# content it refers to outside the Item.
PAGE_REFERENCE_RE = re.compile(r"\bpages?\s+[A-Z]?[-–]?\d+\b", re.I)
POINTER_RE = re.compile(
    r"\b(begins?|beginning|starts?|starting|see|refer|included|set forth|presented)\b", re.I
)

type SourceSpan = tuple[int | None, int | None]


def _table_is_valid(table: Tag) -> bool:
    """Tell whether a table's rows and spans can be read without repairing them.

    Parameters
    ----------
    table
        Table block inside an Item.

    Returns
    -------
    bool
        ``False`` for a table with no rows, a nested table, a row without cells, or a
        ``rowspan``/``colspan`` that is not a number in ``[1, MAX_SPAN]`` or that
        reaches past the last row.
    """
    rows = table.find_all("tr")
    if not rows or table.find("table") is not None:
        return False
    for row_index, row in enumerate(rows):
        cells = row.find_all(list(CELL_TAGS), recursive=False)
        if not cells:
            return False
        for cell in cells:
            for name in ("rowspan", "colspan"):
                value = str(cell.get(name, "1")).strip()
                if not value.isascii() or not value.isdecimal() or len(value) > len(str(MAX_SPAN)):
                    return False
                span = int(value)
                if not 1 <= span <= MAX_SPAN:
                    return False
                if name == "rowspan" and row_index + span > len(rows):
                    return False
    return True


def _heading_text(el: Tag) -> str:
    """Return a block's text as a heading would read.

    Inline runs are joined without a separator, because a filing may split one word
    across two runs; table cells are separated by a space; HTML whitespace collapses.

    Parameters
    ----------
    el
        Leaf block.

    Returns
    -------
    str
        Single-line text, empty when the block has none.
    """
    nodes = el.find_all(list(CELL_TAGS)) if el.name == "table" else [el]
    return " ".join(" ".join(node.get_text() for node in nodes).split())


def _item_match(text: str) -> re.Match[str] | None:
    """Match a line that may be a numbered Item heading.

    Parameters
    ----------
    text
        Heading text of one block.

    Returns
    -------
    re.Match[str] | None
        ``ITEM_RE`` match, or ``None`` for a long block and for a number that runs
        into further digits: ``Item 402`` cites Regulation S-K, not Item 4 of a 10-K.
    """
    match = ITEM_RE.match(text) if len(text) <= HEADING_MAX_CHARS else None
    if match is None or match.group("title")[:1].isdigit():
        return None
    return match


def _item_heading(el: Tag, match: re.Match[str]) -> tuple[str, str] | None:
    """Recognize a styled body heading whose title agrees with its Item number.

    Parameters
    ----------
    el
        Leaf block whose text matched as a numbered Item line.
    match
        The block's ``_item_match`` result.

    Returns
    -------
    tuple[str, str] | None
        Item code and the vocabulary title the heading matched, or ``None`` when the
        block links elsewhere, is not bold, names no known Item, or carries a title
        that is not this Item's. A table qualifies only as a single-row layout with
        exactly two filled cells: the bare number and the title.
    """
    if el.find("a", href=True) is not None:
        return None
    item = item_code(match)
    canonical = CANONICAL.get(item)
    if canonical is None or block_props(el)["font_weight"] < 700:
        return None
    title = norm_title(match.group("title"))
    matched_title = next(
        (
            name
            for name in (canonical, *ALTERNATIVE_TITLES.get(item, ()))
            if title == norm_title(name) or title.startswith(norm_title(name) + " ")
        ),
        None,
    )
    if matched_title is None:
        return None
    if el.name == "table":
        cells = [cell for cell in el.find_all(list(CELL_TAGS)) if cell.get_text(strip=True)]
        if not _table_is_valid(el) or len(el.find_all("tr")) != 1 or len(cells) != 2:
            return None
        number = ITEM_RE.fullmatch(_heading_text(cells[0]))
        if number is None or number.group("title"):
            return None
    return item, matched_title


def _anchor_targets(
    blocks: list[Tag], headings: dict[int, tuple[str, str]]
) -> dict[tuple[str, str], int]:
    """Index the anchors that recognized Item headings carry.

    Parameters
    ----------
    blocks
        Leaf blocks in document order.
    headings
        Recognized headings by block index, as ``(item, title)``.

    Returns
    -------
    dict[tuple[str, str], int]
        Heading block index by ``(anchor name, item)``.
    """
    targets: dict[tuple[str, str], int] = {}
    for index, (item, _title) in headings.items():
        for node in (blocks[index], *blocks[index].find_all(True)):
            for attribute in ("id", "name"):
                if value := node.get(attribute):
                    targets[(str(value), item)] = index
    return targets


def _is_toc_link(
    el: Tag, text: str, item: str, index: int, targets: dict[tuple[str, str], int]
) -> bool:
    """Tell whether an Item line is a contents entry for a heading further down.

    Parameters
    ----------
    el
        Leaf block whose text matched as a numbered Item line.
    text
        The block's heading text.
    item
        Item code the line names.
    index
        The block's position.
    targets
        Anchors of recognized headings, from ``_anchor_targets``.

    Returns
    -------
    bool
        ``True`` only when the whole line is one in-page link to a later recognized
        heading of the same Item. A link to another Item's heading proves nothing.
    """
    links = el.find_all("a", href=True)
    if len(links) != 1 or _heading_text(links[0]) != text:
        return False
    href = str(links[0].get("href", ""))
    return href.startswith("#") and targets.get((href[1:], item), -1) > index


def _segment(
    blocks: list[Tag], spans: list[SourceSpan], offsets: list[int]
) -> tuple[list[Section], list[str]]:
    """Cut the blocks into the Items their recognized headings bound.

    Parameters
    ----------
    blocks
        Leaf blocks in document order.
    spans
        Source span of each block.
    offsets
        Line-start offsets, used to record each table cell's source span.

    Returns
    -------
    tuple[list[Section], list[str]]
        Sections in document order and the problems met while cutting: an Item line
        that is not a recognized heading, or a table that cannot be read as it stands.
    """
    texts = [_heading_text(el) for el in blocks]
    matches = [_item_match(text) for text in texts]
    headings = {
        index: heading
        for index, (el, match) in enumerate(zip(blocks, matches, strict=True))
        if match is not None and (heading := _item_heading(el, match)) is not None
    }
    targets = _anchor_targets(blocks, headings)

    sections: list[Section] = []
    problems: list[str] = []
    current: Section | None = None
    for index, el in enumerate(blocks):
        text = texts[index]
        if not text:
            continue
        match = matches[index]
        if match is None and BOUNDARY_RE.fullmatch(text) is None:
            if current is not None:
                if el.name == "table" and not _table_is_valid(el):
                    problems.append(f"malformed amendment table at block {index}")
                current.blocks.append(
                    body_block(el, el.get_text(" ", strip=True), *spans[index], offsets=offsets)
                )
            continue
        # Contents entries precede the body, so one can only appear before the first Item.
        if match is not None and not sections:
            if _is_toc_link(el, text, item_code(match), index, targets):
                continue
        # Every other Item line, Part heading and signature page ends the open Item.
        if current is not None:
            current.block_range = (current.block_index or 0, index)
            current = None
        if match is None:
            continue
        if index not in headings:
            problems.append(f"uncertain amendment Item heading at block {index}: {text}")
            continue
        item, title = headings[index]
        current = Section(
            part=PART_OF[item],
            item=item,
            canonical_title=title,
            reported_title=text[:REPORTED_TITLE_MAX],
            block_index=index,
            source_pos=spans[index][0],
        )
        sections.append(current)
    if current is not None:
        current.block_range = (current.block_index or 0, len(blocks))
    return sections, problems


def _structure_problems(sections: list[Section], source_length: int) -> list[str]:
    """Check that the Items found form a usable, source-anchored set.

    Parameters
    ----------
    sections
        Sections in document order.
    source_length
        Length of the decoded source, the upper bound of every span.

    Returns
    -------
    list[str]
        One problem for each of: no Item at all, an Item that appears twice, Items out
        of SEC order, an Item without content, a short Item that only points at pages
        elsewhere, and an Item with a block whose span is missing or out of order.
    """
    problems: list[str] = []
    items = [section.item for section in sections if section.item is not None]
    if not items:
        problems.append("no confidently bounded amendment Items")
    if duplicates := sorted(item for item, count in Counter(items).items() if count > 1):
        problems.append(f"duplicate amendment Items: {duplicates}")
    if items != sorted(items, key=ORDER.index):
        problems.append("amendment Item order mismatch")
    for section in sections:
        if not section.blocks:
            problems.append(f"empty Item {section.item}")
        # A short pointer cannot establish ownership of an appendix after the signatures
        # or elsewhere. Its span is kept for inspection, but the Item is not ready while
        # the content it refers to is unassembled.
        text = " ".join(block.text for block in section.blocks)
        if (
            len(section.blocks) <= REF_MAX_BLOCKS
            and PAGE_REFERENCE_RE.search(text)
            and POINTER_RE.search(text)
        ):
            problems.append(f"unresolved amendment Item {section.item} page reference")
        if any(
            section.source_pos is None
            or block.source_pos is None
            or block.end_pos is None
            or not 0 <= section.source_pos < block.source_pos < block.end_pos <= source_length
            for block in section.blocks
        ):
            problems.append(f"invalid source span in Item {section.item}")
    return problems


def parse_amendment(source: FilingSource) -> tuple[ParsedFiling, dict]:
    """Parse the numbered Items one amendment sets out.

    Parameters
    ----------
    source
        Typed selected amendment and verified source artifact.

    Returns
    -------
    tuple[ParsedFiling, dict]
        Parsed filing and the fixed descriptor of this strategy. The filing is
        ``parsed`` only when every Item was bounded with confidence; otherwise it is
        ``needs_profile_update`` and its warnings say what was uncertain. ``item_index``
        stays empty, as it does for every heading-segmented report: only a
        cross-reference index fills it.

    Raises
    ------
    ValueError
        If the source is a whole report, which ``parse_filing`` parses, or was not
        published by the SEC.
    """
    metadata = source.document
    if metadata.kind != "amendment":
        raise ValueError(
            f"{metadata.document_id} is not an amendment ({metadata.form}); "
            "parse it with its registry's report parser"
        )
    prepared = prepare_source(source)
    blocks, offsets, out = prepared.blocks, prepared.offsets, prepared.filing
    spans = block_source_spans(blocks, offsets, out.source_length)

    sections, problems = _segment(blocks, spans, offsets)
    problems.extend(_structure_problems(sections, out.source_length))
    classify_sections(sections)

    out.sections = sections
    out.warnings = problems
    out.parse_status = "needs_profile_update" if problems else "parsed"
    out.profile_used = PROFILE_USED
    out.segment_type = SEGMENT_TYPE
    return out, {"segmentation": {"type": SEGMENT_TYPE}, "validation": {"must_have": []}}
