"""Convert HTML filing tables into dense grids and markdown."""

from bs4 import BeautifulSoup, Tag

Grid = list[list[str]]

UNIT_MARKERS = frozenset({"$", "%", "€", "¥", "£"})


def to_grid(table: Tag) -> Grid:
    """Expand an HTML table into a dense matrix with span handling.

    A spanned cell keeps text at the anchor position, while covered cells stay
    empty.

    Parameters
    ----------
    table
        Parsed table node.

    Returns
    -------
    Grid
        Dense matrix of cell text.
    """

    def _span(cell: Tag, name: str) -> int:
        """Parse an HTML span attribute into a normalized integer.

        Parameters
        ----------
        cell
            Target table cell.
        name
            Attribute name, typically ``colspan`` or ``rowspan``.

        Returns
        -------
        int
            Normalized integer (defaults to ``1`` on missing/invalid values).
        """
        raw = cell.get(name)
        if not isinstance(raw, str):
            return 1
        raw = raw.strip()
        if not raw:
            return 1
        try:
            value = int(raw)
        except ValueError:
            return 1
        return 1 if value < 1 else value

    rows: list[list[str]] = []
    # active rowspans: last row index covered in each column
    open_rowspan_until: list[int] = []
    max_col = 0

    _span_local = _span
    for r, tr in enumerate(table.find_all("tr", recursive=False)):
        row: list[str] = []
        col = 0
        cells = tr.find_all(["td", "th"], recursive=False)
        row_append = row.append

        for cell in cells:
            # Skip columns occupied by rowspans started in earlier rows.
            open_until = open_rowspan_until
            while col < len(open_until) and open_until[col] >= r:
                if col >= len(row):
                    row_append("")
                col += 1

            text = cell.get_text(" ", strip=True)
            cspan = _span_local(cell, "colspan")
            rspan = _span_local(cell, "rowspan")
            end = col + cspan

            missing = end - len(row)
            if missing > 0:
                row.extend([""] * missing)

            row[col] = text
            if rspan > 1:
                if end > len(open_until):
                    open_until.extend([-1] * (end - len(open_until)))
                end_row = r + rspan - 1
                for c in range(col, end):
                    if open_until[c] < end_row:
                        open_until[c] = end_row

            col = end
            if col > max_col:
                max_col = col

        # Preserve trailing open rowspans in columns beyond current row width.
        while len(row) < len(open_rowspan_until) and open_rowspan_until[len(row)] >= r:
            row_append("")

        rows.append(row)

    if not rows:
        return []

    if max_col:
        # Pad short rows so matrix is rectangular.
        for row in rows:
            if len(row) < max_col:
                row.extend([""] * (max_col - len(row)))
    return rows


def drop_empty(grid: Grid) -> Grid:
    """Drop rows and columns with no non-empty values.

    Parameters
    ----------
    grid
        Dense input matrix.

    Returns
    -------
    Grid
        Matrix after removing all-empty rows and columns.
    """
    rows = [r for r in grid if any(c.strip() for c in r)]
    if not rows:
        return []
    keep = [j for j in range(len(rows[0])) if any(r[j].strip() for r in rows)]
    return [[r[j] for j in keep] for r in rows]


def merge_unit_columns(grid: Grid) -> Grid:
    """Merge symbol-only columns into adjacent numeric columns.

    Parameters
    ----------
    grid
        Column-aligned matrix.

    Returns
    -------
    Grid
        Matrix with unit columns merged and removed.
    """
    if not grid:
        return grid

    height = len(grid)
    width = len(grid[0])
    dropped = [False] * width
    out = [row[:] for row in grid]
    markers = UNIT_MARKERS

    for col in range(width):
        if dropped[col]:
            continue

        has_unit = False
        all_percent = True
        used_cells: list[tuple[int, str]] = []

        for row_i in range(height):
            row = out[row_i]
            value = row[col]
            if not value:
                continue
            marker = value.strip()
            if not marker:
                continue
            if marker not in markers:
                has_unit = False
                break
            has_unit = True
            if marker != "%":
                all_percent = False
            used_cells.append((row_i, marker))

        if not has_unit:
            continue

        target = col - 1 if all_percent else col + 1
        if target < 0 or target >= width or dropped[target]:
            continue

        if all_percent:
            for row_i, marker in used_cells:
                row = out[row_i]
                target_value = row[target]
                row[target] = target_value + (" " + marker if target_value else marker)
        else:
            for row_i, marker in used_cells:
                row = out[row_i]
                target_value = row[target]
                row[target] = marker + (" " + target_value if target_value else marker)

        dropped[col] = True

    keep = [i for i, skip in enumerate(dropped) if not skip]
    return [[out[row_i][col] for col in keep] for row_i in range(height)]


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
        inferred as header rows and ``body`` contains the remaining rows.

    Notes
    -----
    There is no ``<th>`` in this corpus, so header rows are inferred by shape:
    header rows have an empty label column and non-empty value-label columns, while
    data rows start with a non-empty item label.
    """
    if not grid:
        return [], []

    n = 0
    strip = str.strip
    for row in grid:
        if not row or strip(row[0]):
            break
        for cell in row[1:]:
            if strip(cell):
                break
        else:
            break
        n += 1

    if n == 0 or n == len(grid):
        return [], grid
    return grid[:n], grid[n:]


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

    Raises
    ------
    None.
        This function does not raise.

    Notes
    -----
    Multi-row headers (``"Year Ended"`` over ``"Jan 28, 2024"``) are merged
    per column so the date context is preserved in chunk text.
    """

    def _cell(text: str) -> str:
        # Escape pipes and normalize spaces for a single markdown table cell.
        raw = str(text).replace("\\|", "|")
        return " ".join(raw.replace("|", "\\|").split())

    if not grid:
        return ""

    header, body = split_header(grid)
    if header:
        cols = max((len(r) for r in header), default=0)
        head = [
            _cell(" ".join(r[j] for r in header if j < len(r) and r[j].strip()))
            for j in range(cols)
        ]
        rows = body
    else:
        if not body:
            return ""
        cols = len(body[0])
        head = [_cell(body[0][j]) for j in range(cols)]
        rows = body[1:]

    # Build one markdown row with fixed width to tolerate ragged rows.
    def _row(row: list[str]) -> str:
        return "| " + " | ".join(_cell(row[j]) if j < len(row) else "" for j in range(cols)) + " |"

    lines = [_row(head), "| " + " | ".join("---" for _ in range(cols)) + " |"]
    lines += [_row(row) for row in rows]

    return "\n".join(lines)


def table_to_markdown(html: str | None) -> str:
    """Convert an HTML table fragment into markdown text.

    Parameters
    ----------
    html
        Raw HTML fragment possibly containing a table. ``None`` or empty input
        returns an empty string.

    Returns
    -------
    str
        Empty string when no table or no content remains, otherwise markdown
        text generated from the table.

    Raises
    ------
    None
        This function does not raise.

    Notes
    -----
    Numbers are passed through verbatim: ``(1,234)`` remains parenthesized rather
    than becoming ``-1234``. The citation has to match what a reader sees in the
    filing, and normalizing here would be irreversible; query-side normalization
    should be handled outside this function.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not isinstance(table, Tag):
        return ""
    grid = drop_empty(to_grid(table))
    if not grid:
        return ""
    return to_markdown(merge_unit_columns(grid))


if __name__ == "__main__":  # pragma: no cover - eyeball helper
    import argparse
    import json
    from pathlib import Path

    from app.ingestion.parser import leaf_blocks, normalize, read_source

    ap = argparse.ArgumentParser(description="Render 10-K tables as markdown.")
    ap.add_argument("--doc", default="NVDA-FY2024", help="doc_id, e.g. NVDA-FY2024")
    ap.add_argument("--contains", default="Gross profit", help="pick tables containing this text")
    ap.add_argument("--limit", type=int, default=2)
    a = ap.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    entry = next(e for e in manifest if f"{e['ticker']}-FY{e['report_date'][:4]}" == a.doc)
    soup = normalize(read_source(entry["file"]))
    shown = 0
    for el in leaf_blocks(soup):
        if el.name != "table" or a.contains not in el.get_text(" ", strip=True):
            continue
        print(f"\n{'─' * 70}\n{a.doc}\n{'─' * 70}")
        print(table_to_markdown(str(el)))
        shown += 1
        if shown >= a.limit:
            break
    if not shown:
        print(f"no table in {a.doc} contains {a.contains!r}")
