"""10-K financial tables -> markdown.

**The problem is not serialization, it is layout.** SEC filings render tables for
print, not for data: across this corpus's 1,200 table blocks, the median table has
63.6% empty raw cells, `<th>` never appears, and `colspan` is used 57,617 times
purely to position text. A three-column income statement ships as twelve physical
columns of label / value / unit / spacer.

Converting that HTML straight to markdown produces a wide, mostly-empty grid that is
worse for retrieval than the raw text. So the pipeline collapses layout first and
serializes last:

    L2 to_grid              colspan/rowspan -> dense matrix
    L3 drop_empty           remove all-empty rows and columns   (12 -> 5 cols, p50)
    L4 merge_unit_columns   fold '$'/'%'-only columns into their value
    L5 split_header         infer header rows (there is no <th> to read)
    L6 to_markdown          serialize

This module is a pure function over HTML. It does not touch `Block`: the parser
leaves table blocks as `Block("table", "", html=...)` and the chunker (M1.3) calls
`table_to_markdown` when it needs text. Keeping it out of the parser means table
rendering cannot shift the coverage metric, and the parser stays unaware of markdown.

For education/practice purposes, this is implemented directly with BeautifulSoup
instead of a converter library, to keep the collapse rules inspectable.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

Grid = list[list[str]]

# Glyphs that SEC layout tables place in a column of their own. A column holding
# nothing but these is presentation, not data, so it is folded into its value column.
UNIT_MARKERS = frozenset({"$", "%", "€", "¥", "£"})


def _span(cell: Tag, name: str) -> int:
    """`colspan`/`rowspan` as a positive int. Filings do emit junk values."""
    try:
        return max(1, int(str(cell.get(name, 1)).strip() or 1))
    except TypeError, ValueError:
        return 1


# ── L2. Grid ────────────────────────────────────────────────────────────────


def to_grid(table: Tag) -> Grid:
    """Expand a `<table>` into a dense matrix, resolving colspan and rowspan.

    A spanned cell keeps its text in the top-left position only; the covered
    positions become empty strings. Replicating the text instead would duplicate
    every number in the corpus, since values are what carry `colspan` here.

    Ragged tables (80 of 1,200) fall out for free: the matrix is sized from
    the furthest cell reached and short rows are padded.
    """
    filled: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(table.find_all("tr")):
        col = 0
        for cell in tr.find_all(["td", "th"]):
            while (r, col) in filled:  # skip positions already taken by a rowspan
                col += 1
            text = cell.get_text(" ", strip=True)
            cspan, rspan = _span(cell, "colspan"), _span(cell, "rowspan")
            for dr in range(rspan):
                for dc in range(cspan):
                    filled[(r + dr, col + dc)] = text if dr == 0 and dc == 0 else ""
            col += cspan
    if not filled:
        return []
    height = max(r for r, _ in filled) + 1
    width = max(c for _, c in filled) + 1
    return [[filled.get((r, c), "") for c in range(width)] for r in range(height)]


# ── L3. Collapse ────────────────────────────────────────────────────────────


def drop_empty(grid: Grid) -> Grid:
    """Drop rows and columns that hold no text anywhere.

    This is the step that does the real work: spacer rows, spacer columns and the
    indentation columns used for line-item nesting all disappear. Measured on this
    corpus the column count falls from p50=12 / max=66 to p50=5 / max=25, and 26
    tables turn out to be pure layout with no content at all.
    """
    rows = [r for r in grid if any(c.strip() for c in r)]
    if not rows:
        return []
    keep = [j for j in range(len(rows[0])) if any(r[j].strip() for r in rows)]
    return [[r[j] for j in keep] for r in rows]


# ── L4. Units ───────────────────────────────────────────────────────────────


def merge_unit_columns(grid: Grid) -> Grid:
    """Fold columns holding only a currency or percent glyph into their value.

    Direction follows how the glyph reads: `$` precedes its number, `%` follows it.
    Without this the corpus leaves 279 columns of bare symbols after collapsing.
    """
    if not grid:
        return grid
    width = len(grid[0])
    cols = [[row[j] for row in grid] for j in range(width)]

    dropped: set[int] = set()
    for j in range(width):
        values = [c.strip() for c in cols[j] if c.strip()]
        if not values or not all(v in UNIT_MARKERS for v in values):
            continue
        trailing = all(v == "%" for v in values)
        target = j - 1 if trailing else j + 1
        if not 0 <= target < width or target in dropped:
            continue
        for i, glyph in enumerate(cols[j]):
            if not glyph.strip():
                continue
            value = cols[target][i]
            cols[target][i] = f"{value} {glyph}".strip() if trailing else f"{glyph} {value}".strip()
        dropped.add(j)

    keep = [j for j in range(width) if j not in dropped]
    return [[cols[j][i] for j in keep] for i in range(len(grid))]


# ── L5. Header ──────────────────────────────────────────────────────────────


def split_header(grid: Grid) -> tuple[Grid, Grid]:
    """Split leading header rows from the body.

    There is no `<th>` in this corpus, so the header has to be inferred from shape:
    a header row labels the value columns and leaves the label column blank, while
    every data row starts with its line-item name. Leading rows matching that shape
    are the header.

    Returns `([], grid)` when nothing matches, so the caller decides the fallback.
    """
    n = 0
    for row in grid:
        if row[0].strip() or not any(c.strip() for c in row[1:]):
            break
        n += 1
    if n == 0 or n == len(grid):
        return [], grid
    return grid[:n], grid[n:]


# ── L6. Serialize ───────────────────────────────────────────────────────────


def _cell(text: str) -> str:
    """Make a cell safe for a markdown table row."""
    return " ".join(text.replace("|", "\\|").split())


def to_markdown(grid: Grid) -> str:
    """Serialize a collapsed grid as a markdown table.

    Multi-row headers ("Year Ended" over "Jan 28, 2024") are joined per column, so
    the period a number belongs to survives into the chunk text.
    """
    if not grid:
        return ""
    header, body = split_header(grid)
    if header:
        head = [" ".join(row[j] for row in header if row[j].strip()) for j in range(len(grid[0]))]
    else:  # no header shape: promote the first row so the table stays valid markdown
        head, body = body[0], body[1:]

    lines = [
        "| " + " | ".join(_cell(c) for c in head) + " |",
        "| " + " | ".join("---" for _ in head) + " |",
    ]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


# ── L7. Entry point ─────────────────────────────────────────────────────────


def table_to_markdown(html: str | None) -> str:
    """`Block(kind="table").html` -> markdown. Empty string when there is no content.

    Numbers are passed through verbatim: `(1,234)` stays parenthesized rather than
    becoming `-1234`. The citation has to match what a reader sees in the filing,
    and normalizing here would be irreversible; query-side normalization is not.
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
