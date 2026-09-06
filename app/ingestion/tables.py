"""Convert HTML filing tables into dense grids and markdown."""

from dataclasses import dataclass
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
DATE_CAPTION_RE = re.compile(r"^\(\s*기준일\s*[:：]\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일\s*\)$")


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


def merge_unit_columns(
    grid: Grid, *, column_memberships: list[tuple[int, ...]] | None = None
) -> Grid:
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
                    existing = out[row_i][target]
                    ordered = (label, existing) if col < target else (existing, label)
                    out[row_i][target] = " ".join(
                        dict.fromkeys(text for text in ordered if text.strip())
                    )

        if column_memberships is not None:
            for target in targets:
                column_memberships[target] = tuple(
                    sorted(set(column_memberships[target] + column_memberships[col]))
                )
        dropped[col] = True
        for target in targets:
            merged_into[target] = True

    keep = [i for i, skip in enumerate(dropped) if not skip]
    if column_memberships is not None:
        column_memberships[:] = [column_memberships[col] for col in keep]
    return [[out[row_i][col] for col in keep] for row_i in range(height)]


def _annotation_texts(values: list[str]) -> list[str] | None:
    """Join split date cells only when all text matches explicit date/unit grammar."""
    joined = " ".join(values)
    pattern = re.compile(f"(?:{UNIT_CAPTION_RE.pattern[1:-1]}|{DATE_CAPTION_RE.pattern[1:-1]})")
    matches = [match.group(0) for match in pattern.finditer(joined)]
    if pattern.sub("", joined).strip() or not any(
        UNIT_CAPTION_RE.fullmatch(text) for text in matches
    ):
        return None
    return matches


def _caption_row_indices(grid: Grid) -> set[int]:
    """Recognize explicit unit captions and their adjacent reference dates only."""
    texts = [[cell.strip() for cell in row if cell.strip()] for row in grid]
    # DART splits '(기준일 :', the date, and ')' over three cells. Joining them
    # requires the complete explicit grammar, so ordinary numeric rows cannot
    # become annotations merely because another row contains a unit declaration.
    if _annotation_texts([value for row in texts for value in row]) is not None:
        return {index for index, row in enumerate(texts) if row}
    return {index for index, row in enumerate(texts) if _annotation_texts(row) is not None}


def split_unit_captions(grid: Grid) -> tuple[list[str], Grid]:
    """Extract explicit units and accompanying reference dates without losing text."""
    caption_rows = _caption_row_indices(grid)
    values = [
        cell.strip()
        for index, row in enumerate(grid)
        if index in caption_rows
        for cell in row
        if cell.strip()
    ]
    captions = _annotation_texts(values) if values else []
    assert captions is not None
    return list(dict.fromkeys(captions)), [
        row for index, row in enumerate(grid) if index not in caption_rows
    ]


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


def is_unit_caption(text: str) -> bool:
    """Whether the stripped text is exactly one DART unit annotation."""
    return bool(UNIT_CAPTION_RE.match(text.strip()))


def render_table(table: str | Tag | None) -> tuple[list[str], str]:
    """Render one table into ``(captions, markdown)`` from a single parse.

    ``markdown`` is exactly what :func:`table_to_markdown` returns: when the table
    has data rows its unit captions stay prepended inline. ``captions`` is non-empty
    only for a caption-only table — the case :func:`table_captions` reports — which
    renders no markdown of its own. A chunker that needs both answers per table can
    therefore call this once instead of running the parse pipeline twice.
    """
    node = _table_node(table)
    if node is None:
        return [], ""
    captions, grid = split_unit_captions(drop_empty(to_grid(node)))
    grid = drop_empty(grid)
    if not grid:
        # A caption-only table: nothing renders, so the annotations travel out
        # for the caller to attach to the table that follows.
        return captions, ""
    markdown = to_markdown(merge_unit_columns(grid))
    if not markdown:
        return [], ""
    if captions:
        markdown = "\n".join([*captions, markdown])
    return [], markdown


@dataclass(frozen=True, slots=True)
class SourceCell:
    """One original HTML cell and its zero-based source grid coverage."""

    row: int
    column: int
    rowspan: int
    colspan: int
    text: str


@dataclass(frozen=True, slots=True)
class TableCell:
    """One rendered column value with the original cells that contribute to it."""

    column: int
    text: str
    sources: tuple[SourceCell, ...]


@dataclass(frozen=True, slots=True)
class TableRow:
    """One retained source row after unit and spacer normalization."""

    source_row: int
    cells: tuple[TableCell, ...]


@dataclass(frozen=True, slots=True)
class StructuredTable:
    """Normalized rendering plus explicit original row, column, and span ownership."""

    captions: tuple[str, ...]
    headers: tuple[TableRow, ...]
    rows: tuple[TableRow, ...]
    caption_cells: tuple[SourceCell, ...] = ()

    def render(self, rows: tuple[TableRow, ...] | None = None) -> str:
        """Render selected body rows without reclassifying their values as headers."""
        selected = self.rows if rows is None else rows
        if not selected:
            return ""
        width = max(len(row.cells) for row in (*self.headers, *selected))
        head = [
            " ".join(row.cells[col].text for row in self.headers if row.cells[col].text)
            for col in range(width)
        ]

        def line(values: list[str]) -> str:
            """Escape a complete row using the established markdown rules."""
            escaped = [
                " ".join(value.replace("\\", "\\\\").replace("|", "\\|").split())
                for value in values
            ]
            return "| " + " | ".join(escaped) + " |"

        lines = [*self.captions, line(head), line(["---"] * width)]
        lines.extend(line([cell.text for cell in row.cells]) for row in selected)
        return "\n".join(lines)


def structured_table(table: str | Tag | None) -> StructuredTable:
    """Retain source cell relationships while applying the existing table transforms."""
    node = _table_node(table)
    if node is None:
        return StructuredTable((), (), ())
    grid = to_grid(node)
    if not grid:
        return StructuredTable((), (), ())
    source_cells: list[SourceCell] = []
    occupied: dict[int, int] = {}
    for row_index, row in enumerate(_rows(node)):
        col = 0
        for cell in row.find_all(list(CELL_TAGS), recursive=False):
            while occupied.get(col, -1) >= row_index:
                col += 1
            rowspan, colspan = _span(cell, "rowspan"), _span(cell, "colspan")
            source_cells.append(SourceCell(row_index, col, rowspan, colspan, _cell_text(cell)))
            if rowspan > 1:
                for covered in range(col, col + colspan):
                    occupied[covered] = row_index + rowspan - 1
            col += colspan
    retained = [i for i, row in enumerate(grid) if any(value.strip() for value in row)]
    columns = [i for i in range(len(grid[0])) if any(row[i].strip() for row in grid)]
    compact = [[grid[row][col] for col in columns] for row in retained]
    captions, _ = split_unit_captions(compact)
    caption_indices = _caption_row_indices(compact)
    caption_source_rows = {retained[index] for index in caption_indices}
    caption_cells = tuple(
        cell for cell in source_cells if cell.row in caption_source_rows and cell.text
    )
    data_indices = [index for index in range(len(compact)) if index not in caption_indices]
    retained = [retained[index] for index in data_indices]
    compact = [compact[index] for index in data_indices]
    if not compact:
        return StructuredTable(tuple(captions), (), (), caption_cells)
    used = [i for i in range(len(columns)) if any(row[i].strip() for row in compact)]
    compact = [[row[i] for i in used] for row in compact]
    memberships = [(columns[i],) for i in used]
    compact = merge_unit_columns(compact, column_memberships=memberships)
    coverage: dict[tuple[int, int], list[SourceCell]] = {}
    for cell in source_cells:
        for row_index in range(cell.row, min(cell.row + cell.rowspan, len(grid))):
            for column in range(cell.column, min(cell.column + cell.colspan, len(grid[0]))):
                coverage.setdefault((row_index, column), []).append(cell)
    rows = tuple(
        TableRow(
            source_row,
            tuple(
                TableCell(
                    col,
                    value,
                    tuple(
                        dict.fromkeys(
                            cell
                            for original in memberships[col]
                            for cell in coverage.get((source_row, original), ())
                        )
                    ),
                )
                for col, value in enumerate(values)
            ),
        )
        for source_row, values in zip(retained, compact, strict=True)
    )
    header_count = len(split_header(compact)[0])
    return StructuredTable(tuple(captions), rows[:header_count], rows[header_count:], caption_cells)


def table_captions(table: str | Tag | None) -> list[str]:
    """Return the unit annotations of a caption-only table.

    DART writes many units as a one-cell table immediately ahead of the data table
    they describe. Such a table renders no markdown of its own, so its captions are
    returned for the caller to carry into the next table's context; a table that has
    data rows keeps its captions inline and returns nothing here.
    """
    return render_table(table)[0]


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
    return render_table(table)[1]


if __name__ == "__main__":  # pragma: no cover - eyeball helper
    import argparse
    from pathlib import Path

    from app.ingestion.manifest import Manifest
    from app.ingestion.parser import leaf_blocks, normalize

    ap = argparse.ArgumentParser(description="Render filing tables as markdown.")
    ap.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    ap.add_argument("--manifest", type=Path, default=Path("data/corpus/manifest.json"))
    ap.add_argument("--contains", default="Gross profit", help="pick tables containing this text")
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--selection", required=True)
    a = ap.parse_args()

    manifest_path = a.manifest
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path} not found; run this from the repository root")

    manifest = Manifest.read(manifest_path)
    sources = manifest.selected_sources(a.selection, manifest_path.parent)
    entry = next((source for source in sources if source.document.document_id == a.doc), None)
    if entry is None:
        known = ", ".join(source.document.document_id for source in sources)
        raise SystemExit(f"unknown doc {a.doc!r}; selected documents: {known}")

    soup = normalize(entry.read())
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
