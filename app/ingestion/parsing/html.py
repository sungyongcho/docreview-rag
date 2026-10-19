"""Source-anchored parsing contract shared by every registry adapter.

Holds the neutral data contract (``Block``, ``Section``, ``ParsedFiling``) and the
source-fidelity helpers -- hashing, offset math, HTML normalization, and
leaf-block extraction -- that every registry parser builds on. Registry-specific
segmentation lives in the adapter modules (``app.ingestion.parsing.sec``,
``app.ingestion.parsing.dart``); nothing here knows one registry's markup from another's.
"""

from collections.abc import Sequence
import hashlib
from html.parser import HTMLParser
import re
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import NavigableString, PreformattedString

from app.ingestion.parsing.tables import CELL_TAGS

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
LEAF_BLOCK_TAGS = ("div", "p", "table", *HEADING_TAGS)
STYLESHEET_WEIGHT_KEY = "_parser_stylesheet_font_weight"
SOURCE_HTML_KEY = "_parser_source_html"
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
DATA_TABLE_NUMERIC_DIVISOR = 4  # numeric density is measured over nonempty cells

REPORTED_TITLE_MAX = 150  # maximum stored Section.reported_title length


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
    soup.__dict__[SOURCE_HTML_KEY] = html
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


class _UncoveredCellText(HTMLParser):
    """Anchor mixed layout-cell text runs that the selected DOM blocks omit.

    BeautifulSoup retains tag positions but not bare-string positions. Read raw
    data event positions only when needed, rather than guessing offsets for text
    before or after a nested table. Selected blocks remain the structure owner.
    """

    def __init__(self, covered: set[tuple[int | None, int | None]]) -> None:
        """Track source tag ancestry and accumulate only uncovered cell text."""
        super().__init__(convert_charrefs=True)
        self.covered = covered
        self.stack: list[tuple[str, bool]] = []
        self.pending: list[str] = []
        self.start: tuple[int, int] | None = None
        self.blocks: list[Tag] = []

    def flush(self) -> None:
        """Emit one inline text run at its exact original data-event start."""
        text = "".join(self.pending)
        if text.strip() and self.start is not None:
            line, column = self.start
            block = Tag(name="span", sourceline=line, sourcepos=column)
            block.append(text)
            self.blocks.append(block)
        self.pending.clear()
        self.start = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Separate structural boundaries while keeping inline words intact."""
        if self.getpos() in self.covered or tag in {*LEAF_BLOCK_TAGS, *CELL_TAGS, "br"}:
            self.flush()
        blocked = self.getpos() in self.covered or tag in {
            "script",
            "style",
            "noscript",
            "ix:header",
        }
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, blocked))

    def handle_endtag(self, tag: str) -> None:
        """End a structural run and leave the matching raw-source ancestor."""
        if tag in {*LEAF_BLOCK_TAGS, *CELL_TAGS}:
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        """Retain visible text inside cells outside all selected block ancestors."""
        if any(blocked for _, blocked in self.stack):
            return
        if not any(tag in CELL_TAGS for tag, _ in self.stack):
            return
        if self.start is None:
            self.start = self.getpos()
        self.pending.append(data)


def _uncovered_cell_text(soup: BeautifulSoup, blocks: list[Tag]) -> list[Tag]:
    """Recover mixed cell text only when the ordinary leaf pass left it uncovered."""
    selected = {id(block) for block in blocks}
    orphan = any(
        isinstance(node, NavigableString)
        and not isinstance(node, PreformattedString)
        and node.strip()
        and node.find_parent(list(CELL_TAGS)) is not None
        and not any(id(parent) in selected for parent in node.parents)
        for node in soup.descendants
    )
    if not orphan:
        return []
    raw = soup.__dict__.get(SOURCE_HTML_KEY)
    if raw is None:
        raise ValueError("mixed layout-cell extraction requires normalize() source positions")
    parser = _UncoveredCellText({(block.sourceline, block.sourcepos) for block in blocks})
    parser.feed(raw)
    parser.close()
    parser.flush()
    return parser.blocks


def _is_data_table(tbl: Tag) -> bool:
    """Return whether a table has the shape and numeric density of financial data."""
    # Nested grids own their cells. Counting those cells for an outer layout
    # table promotes the wrapper and flattens the inner row/column relationships.
    cells = [c for c in tbl.find_all(list(CELL_TAGS)) if c.find_parent("table") is tbl]
    if len(cells) < DATA_TABLE_MIN_CELLS:
        return False
    texts = [text for c in cells if (text := c.get_text(" ", strip=True))]
    if any(len(t) > LAYOUT_CELL_CHARS for t in texts):  # a long prose cell means layout
        return False
    # Empty spacer cells encode presentation, not evidence against a financial grid.
    numeric = sum(1 for t in texts if len(t) < NUMERIC_CELL_CHARS and re.search(r"\d", t))
    return numeric >= max(DATA_TABLE_MIN_NUMERIC, len(texts) // DATA_TABLE_NUMERIC_DIVISOR)


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
    table_ids: set[int] = set()
    tables = soup.find_all("table")
    data_tables = {id(t) for t in tables if _is_data_table(t)}
    for t in tables:
        # An independently shaped inner grid must not become one flattened outer
        # cell. Unselected wrapper text is recovered with its source positions.
        if any(id(inner) in data_tables for inner in t.find_all("table")):
            continue
        if not any(id(p) in table_ids for p in t.find_parents("table")) and (
            id(t) in data_tables or t.find(block_tags) is None
        ):
            table_ids.add(id(t))

    out = []
    # Rejected layout tables can mix paragraph blocks and bare cell text. Include
    # terminal cells too, instead of silently dropping their text.
    for el in soup.find_all([*block_tags, *CELL_TAGS]):
        if any(id(p) in table_ids for p in el.find_parents("table")):
            continue
        if el.name == "table":
            if id(el) in table_ids:
                out.append(el)
        elif el.find(block_tags) is None and (el.name not in CELL_TAGS or el.get_text(strip=True)):
            out.append(el)
    extra = _uncovered_cell_text(soup, out)
    if extra:
        out.extend(extra)
        out.sort(key=lambda block: (block.sourceline or 0, block.sourcepos or 0))
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
