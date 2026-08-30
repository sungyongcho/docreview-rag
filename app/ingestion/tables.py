"""Convert HTML filing tables into dense grids and markdown."""

import re

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString, PreformattedString

Grid = list[list[str]]

UNIT_MARKERS = frozenset({"$", "%", "€", "¥", "£", "₩"})

# Every element treated as one table cell. EDGAR HTML uses td/th; the DART viewer
# format adds TE (a plain cell) and TU (a unit-annotated cell), both direct children
# of TR. Sharing the tuple with the parser's data-table detection keeps "what counts
# as a cell" a single contract: a tag missing here would drop its column from every
# rendered table while the detection heuristic still counted the table as data.
CELL_TAGS = ("td", "th", "te", "tu")

# A larger span is a typo in the filing, not a table that wide. Without a ceiling one
# malformed attribute allocates span x rows empty strings and turns ingestion into an OOM.
MAX_SPAN = 1000

ROW_GROUP_TAGS = ("thead", "tbody", "tfoot")

# Text inside these children renders on its own line, so their boundaries are the only
# places a separator may be inserted. Inline children are concatenated verbatim.
BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
        "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
        "table", "td", "te", "th", "tr", "tu", "ul",
    }
)  # fmt: skip

TEXT_ALIGN_RE = re.compile(r"text-align\s*:\s*([a-zA-Z-]+)")

# A cell is a value when it carries a digit and nothing but number punctuation around it.
# "Dec 31, 2022" and "(In Millions)" are labels; "(1,234)" and "72.7 %" are values.
# ₩ joins the currency signs and △/▲ join the sign punctuation: Korean filings write
# negatives as △1,234, and without these characters every such cell reads as a label,
# which pushes real data rows into the inferred header.
NUMERIC_CELL_RE = re.compile(r"^[\s\d.,()\[\]%$€¥£₩+\-–—/△▲]*\d[\s\d.,()\[\]%$€¥£₩+\-–—/△▲]*$")

# A bare four-digit year is a column label, not a value, so it must not stop header
# inference in tables headed "(In millions) | 2024 | 2023".
YEAR_CELL_RE = re.compile(r"^(?:19|20)\d{2}$")

# DART tables carry their unit inside the grid as a spanned annotation row such as
# "(단위 : 백만원)". Left in place it reads as a labelled first row, which corrupts
# header inference; dropped it would silently strip the scale off every number.
UNIT_CAPTION_RE = re.compile(r"^\(\s*단위\s*[:：]?\s*[^)]*\)$")


def _cell_text(cell: Tag) -> str:
    """Return cell text, inserting a separator only at block boundaries.

    ``get_text(" ")`` puts a space between every adjacent node, which splits words the
    filing broke across ``<span>`` or ``<a>`` children (``"P art I"``) and detaches
    parentheses from negatives (``"( 257 )"``). Concatenating instead makes the result
    independent of how the tree happens to fragment its strings, so a live node and a
    re-parsed copy of the same node produce identical text.
    """
    parts: list[str] = []

    def walk(node: Tag) -> None:
        """Append the rendered text of every descendant node in document order."""
        for child in node.children:
            if isinstance(child, NavigableString):
                # Comments, doctypes, and CDATA are not rendered text.
                if not isinstance(child, PreformattedString):
                    parts.append(str(child))
            elif isinstance(child, Tag):
                block = child.name in BLOCK_TAGS
                if block:
                    parts.append("\n")
                walk(child)
                if block:
                    parts.append("\n")

    walk(cell)
    # str.split() also collapses the non-breaking spaces these filings use for layout.
    return " ".join("".join(parts).split())


def _align(cell: Tag) -> str:
    """Return the horizontal alignment of a cell, or ``""`` when unspecified."""
    style = cell.get("style")
    if isinstance(style, str):
        match = TEXT_ALIGN_RE.search(style)
        if match:
            return match.group(1).lower()
    legacy = cell.get("align")
    return legacy.strip().lower() if isinstance(legacy, str) else ""


def _span(cell: Tag, name: str) -> int:
    """Return a span value clamped to ``[1, MAX_SPAN]``, defaulting to one when invalid."""
    raw = cell.get(name)
    if not isinstance(raw, str):
        return 1
    try:
        value = int(raw.strip())
    except ValueError:
        return 1
    return min(max(value, 1), MAX_SPAN)


def _rows(table: Tag) -> list[Tag]:
    """Return the table's own rows, descending through row-group wrappers.

    ``find_all("tr", recursive=False)`` returns nothing when rows sit inside an explicit
    ``<tbody>``, which silently converts the whole table to an empty grid. Only direct
    children are followed, so rows of a nested table still belong to that nested table.
    """
    rows: list[Tag] = []
    for child in table.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "tr":
            rows.append(child)
        elif child.name in ROW_GROUP_TAGS:
            rows.extend(r for r in child.children if isinstance(r, Tag) and r.name == "tr")
    return rows


def to_grid(table: Tag) -> Grid:
    """Expand an HTML table into a dense matrix with span handling.

    Parameters
    ----------
    table
        Parsed table node.

    Returns
    -------
    Grid
        Dense matrix of cell text.

    Notes
    -----
    A spanned cell lands where it is rendered rather than always at its first column.
    These filings put ``colspan`` on right-aligned numeric cells to swallow the adjacent
    currency column, so ``<td colspan="2">16,621</td>`` occupies the same column as the
    ``60,922`` of a row that spells the ``$`` out separately.

    A centered spanning cell is a label written over several columns, so its text is
    copied to every column it covers that carries content elsewhere in the table.
    Layout-only spacer columns stay empty and are still removed by :func:`drop_empty`.
    """
    placed: Grid = []
    # Centered spans, resolved after the content columns of the table are known.
    spread: list[tuple[int, int, int, str]] = []
    # active rowspans: last row index covered in each column
    open_rowspan_until: list[int] = []
    max_col = 0

    for r, tr in enumerate(_rows(table)):
        row: list[str] = []
        col = 0

        for cell in tr.find_all(list(CELL_TAGS), recursive=False):
            # Skip columns occupied by rowspans started in earlier rows.
            while col < len(open_rowspan_until) and open_rowspan_until[col] >= r:
                col += 1

            text = _cell_text(cell)
            cspan = _span(cell, "colspan")
            rspan = _span(cell, "rowspan")
            end = col + cspan

            missing = end - len(row)
            if missing > 0:
                row.extend([""] * missing)

            align = _align(cell)
            if cspan > 1 and text and align == "center":
                spread.append((r, col, end, text))
            elif align == "right":
                row[end - 1] = text
            else:
                row[col] = text

            if rspan > 1:
                if end > len(open_rowspan_until):
                    open_rowspan_until.extend([-1] * (end - len(open_rowspan_until)))
                end_row = r + rspan - 1
                for c in range(col, end):
                    if open_rowspan_until[c] < end_row:
                        open_rowspan_until[c] = end_row

            col = end
            if col > max_col:
                max_col = col

        placed.append(row)

    # No cell reached any column, so there is nothing to make rectangular.
    if not max_col:
        return []

    # Pad short rows so the matrix is rectangular.
    for row in placed:
        if len(row) < max_col:
            row.extend([""] * (max_col - len(row)))

    has_content = [any(row[c].strip() for row in placed) for c in range(max_col)]
    for row_i, start, end, text in spread:
        covered = [c for c in range(start, end) if has_content[c]]
        for c in covered or [start]:
            placed[row_i][c] = text

    return placed


def drop_empty(grid: Grid) -> Grid:
    """Remove rows and columns that contain no non-empty values.

    Ragged input is tolerated: the width is taken from the widest row and missing
    cells read as empty.
    """
    rows = [r for r in grid if any(c.strip() for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    keep = [j for j in range(width) if any(j < len(r) and r[j].strip() for r in rows)]
    return [[r[j] if j < len(r) else "" for j in keep] for r in rows]


def merge_unit_columns(grid: Grid) -> Grid:
    """Merge symbol-only columns into an adjacent value column.

    Parameters
    ----------
    grid
        Column-aligned matrix.

    Returns
    -------
    Grid
        Matrix with unit columns merged and removed.

    Notes
    -----
    Only body rows decide whether a column holds units. A header label anchored above a
    symbol column (``"Average Price Paid per Share"`` over a ``$`` column) would
    otherwise disable the merge and leave the bare symbols in the output.

    Each marker chooses its own side from its own symbol rather than from a flag set
    once per column, so a column mixing ``$`` and ``%`` still yields ``"$ 100"`` and
    ``"5 %"`` instead of prefixing both onto the right-hand neighbour.
    """
    if not grid:
        return grid

    height = len(grid)
    width = max((len(row) for row in grid), default=0)
    if not width:
        return [row[:] for row in grid]

    out = [row + [""] * (width - len(row)) for row in grid]
    header_rows = len(split_header(out)[0])
    dropped = [False] * width
    merged_into = [False] * width

    for col in range(width):
        if dropped[col] or merged_into[col]:
            continue

        markers: list[tuple[int, str]] = []
        is_unit = True
        for row_i in range(header_rows, height):
            value = out[row_i][col].strip()
            if not value:
                continue
            if value not in UNIT_MARKERS:
                is_unit = False
                break
            markers.append((row_i, value))

        if not is_unit or not markers:
            continue

        left = col - 1 if col > 0 and not dropped[col - 1] else -1
        right = col + 1 if col + 1 < width and not dropped[col + 1] else -1
        if left < 0 and right < 0:
            continue

        targets: set[int] = set()
        for row_i, marker in markers:
            # Reading order is per cell: a percent sign follows its value, a currency
            # symbol precedes it. Only an unavailable side falls back to the other one.
            preferred, fallback = (left, right) if marker == "%" else (right, left)
            target = preferred if preferred >= 0 else fallback
            targets.add(target)
            value = out[row_i][target]
            if not value:
                out[row_i][target] = marker
            elif marker == "%":
                out[row_i][target] = f"{value} {marker}"
            else:
                out[row_i][target] = f"{marker} {value}"

        # Carry the dropped column's header text over when the target has none.
        for row_i in range(header_rows):
            label = out[row_i][col]
            if label.strip():
                for target in targets:
                    if not out[row_i][target].strip():
                        out[row_i][target] = label

        dropped[col] = True
        for target in targets:
            merged_into[target] = True

    keep = [i for i, skip in enumerate(dropped) if not skip]
    return [[out[row_i][col] for col in keep] for row_i in range(height)]


def split_unit_captions(grid: Grid) -> tuple[list[str], Grid]:
    """Extract unit-annotation rows from a grid before header inference sees them.

    Parameters
    ----------
    grid
        Dense matrix after span expansion and empty-column removal.

    Returns
    -------
    tuple[list[str], Grid]
        Deduplicated caption texts in row order, and the grid without those rows.
        A row is a caption when every non-empty cell matches the DART unit pattern;
        span expansion may have copied one annotation across several columns, so the
        texts of one row collapse to their distinct values.
    """
    captions: list[str] = []
    rows: Grid = []
    for row in grid:
        texts = [cell.strip() for cell in row if cell.strip()]
        if texts and all(UNIT_CAPTION_RE.match(text) for text in texts):
            for text in dict.fromkeys(texts):
                if text not in captions:
                    captions.append(text)
        else:
            rows.append(row)
    return captions, rows


def _is_value(cell: str) -> bool:
    """Return whether a cell reads as a number rather than as a label."""
    text = cell.strip()
    return bool(NUMERIC_CELL_RE.match(text)) and not YEAR_CELL_RE.match(text)


def split_header(grid: Grid) -> tuple[Grid, Grid]:
    """Split leading header rows from the body.

    Parameters
    ----------
    grid
        Parsed dense row/column matrix.

    Returns
    -------
    tuple[Grid, Grid]
        ``(header, body)`` where ``header`` contains consecutive initial rows
        inferred as header rows and ``body`` contains the remaining rows. Both hold
        copies, so mutating a returned row cannot corrupt the caller's grid.

    Notes
    -----
    There is no ``<th>`` in this corpus, so header rows are inferred by shape. A leading
    row that fills columns other than the label column is a header row while its label
    column stays empty, as in a ``"Year Ended"`` over ``"Jan 28, 2024"`` stack.

    Most filing tables instead label that column (``"Years Ended (In Millions)"``,
    ``"Period"``). One such row counts as a header when it holds no numeric value; a
    second one, or any row carrying a number, is data. A bare four-digit year counts as
    a label, since a row of years is a header rather than a row of amounts.
    """
    if not grid:
        return [], []

    n = 0
    labelled = False
    for row in grid:
        if not row or not any(cell.strip() for cell in row[1:]):
            break
        if row[0].strip():
            # A labelled row states column titles at most once; a second one is data.
            if labelled or any(_is_value(cell) for cell in row):
                break
            labelled = True
        n += 1

    if n == 0 or n == len(grid):
        return [], [row[:] for row in grid]
    return [row[:] for row in grid[:n]], [row[:] for row in grid[n:]]


def to_markdown(grid: Grid) -> str:
    """Serialize a collapsed grid as a markdown table.

    Parameters
    ----------
    grid
        Collapsed table grid after span expansion and cleanup.

    Returns
    -------
    str
        Markdown table serialization, or ``""`` when no rows remain.

    Notes
    -----
    Multi-row headers (``"Year Ended"`` over ``"Jan 28, 2024"``) are merged per column
    so the date context is preserved in chunk text.

    When :func:`split_header` infers no header the header row is left blank rather than
    promoted from the first row. A cover-page or checkbox table has no column titles to
    promote, and presenting its first row as labels states something the filing does not.
    """

    def _cell(text: str) -> str:
        """Escape one cell so a pipe or newline cannot add a column or a row."""
        # Escape backslashes before pipes so an escaped pipe cannot lose its backslash.
        raw = text.replace("\\", "\\\\").replace("|", "\\|")
        return " ".join(raw.split())

    if not grid:
        return ""

    header, body = split_header(grid)
    # Width comes from every row: a row wider than the header must not be truncated.
    cols = max((len(r) for r in grid), default=0)
    if not cols:
        return ""

    head = [
        _cell(" ".join(r[j] for r in header if j < len(r) and r[j].strip())) for j in range(cols)
    ]

    def _row(row: list[str]) -> str:
        """Render one padded, pipe-delimited row at the table's full width."""
        return "| " + " | ".join(_cell(row[j]) if j < len(row) else "" for j in range(cols)) + " |"

    lines = [_row(head), "| " + " | ".join("---" for _ in range(cols)) + " |"]
    lines += [_row(row) for row in body]

    return "\n".join(lines)


def _table_node(table: str | Tag | None) -> Tag | None:
    """Return the table element of a node or fragment, or ``None``."""
    if table is None:
        return None
    if isinstance(table, Tag):
        node = table if table.name == "table" else table.find("table")
    elif not table:
        return None
    else:
        node = BeautifulSoup(table, "html.parser").find("table")
    return node if isinstance(node, Tag) else None


def table_captions(table: str | Tag | None) -> list[str]:
    """Return the unit annotations of a caption-only table.

    DART writes many units as a one-cell table immediately ahead of the data table
    they describe. Such a table renders no markdown of its own, so its captions are
    returned for the caller to carry into the next table's context; a table that has
    data rows keeps its captions inline and returns nothing here.
    """
    node = _table_node(table)
    if node is None:
        return []
    captions, rest = split_unit_captions(drop_empty(to_grid(node)))
    return captions if not drop_empty(rest) else []


def table_to_markdown(table: str | Tag | None) -> str:
    """Convert an HTML table into markdown text.

    Parameters
    ----------
    table
        Parsed table node, or a raw HTML fragment possibly containing a table.
        ``None`` and empty input return an empty string. Passing the parsed node
        avoids re-parsing a fragment that has already been parsed.

    Returns
    -------
    str
        Empty string when no table or no content remains, otherwise markdown
        text generated from the table.

    Notes
    -----
    Numbers are passed through verbatim: ``(1,234)`` remains parenthesized rather
    than becoming ``-1234``. The citation has to match what a reader sees in the
    filing, and normalizing here would be irreversible; query-side normalization
    should be handled outside this function.
    """
    node = _table_node(table)
    if node is None:
        return ""
    grid = drop_empty(to_grid(node))
    if not grid:
        return ""
    captions, grid = split_unit_captions(grid)
    grid = drop_empty(grid)
    if not grid:
        return ""
    markdown = to_markdown(merge_unit_columns(grid))
    if not markdown:
        return ""
    return "\n".join([*captions, markdown]) if captions else markdown


if __name__ == "__main__":  # pragma: no cover - eyeball helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import leaf_blocks, normalize, read_source
    from app.ingestion.registry import resolve_registry

    ap = argparse.ArgumentParser(description="Render filing tables as markdown.")
    ap.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    ap.add_argument("--manifest", type=Path, default=Path("data/corpus/manifest.json"))
    ap.add_argument("--contains", default="Gross profit", help="pick tables containing this text")
    ap.add_argument("--limit", type=int, default=2)
    a = ap.parse_args()

    manifest_path = a.manifest
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path} not found; run this from the repository root")

    manifest = json.loads(manifest_path.read_text())

    def _doc_id(item: dict) -> str:
        """Return one manifest entry's document id through its own registry."""
        return resolve_registry(item).doc_id(item)

    entry = next((e for e in manifest if _doc_id(e) == a.doc), None)
    if entry is None:
        known = ", ".join(sorted(_doc_id(e) for e in manifest))
        raise SystemExit(f"unknown doc {a.doc!r}; known documents: {known}")

    soup = normalize(read_source(entry["file"]))
    shown = 0
    for el in leaf_blocks(soup):
        if el.name != "table" or a.contains not in el.get_text(" ", strip=True):
            continue
        print(f"\n{'─' * 70}\n{a.doc}\n{'─' * 70}")
        print(table_to_markdown(el))
        shown += 1
        if shown >= a.limit:
            break
    if not shown:
        print(f"no table in {a.doc} contains {a.contains!r}")
