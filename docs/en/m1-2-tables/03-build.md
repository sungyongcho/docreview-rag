# M1.2 Build — Making Financial Statements Searchable

## The homework M1.1 deferred

When M1.1 met a data table, it left this behind.

```python
Block(kind="table", text="", html="<table>...</table>")
```

`text` is empty. The HTML was preserved whole, but **there is no searchable text.** As it stands, a question like "what was NVIDIA's 2024 gross margin?" will never reach a financial statement.

Tables are not incidental in a 10-K. NVDA-FY2024's Item 15 alone holds 34 tables, and **the numbers people ask about most** — revenue, income, segment results — live almost entirely inside them. Fail to read tables and half of this system is dead.

## Can we just feed it the HTML?

You could hand the raw HTML to an embedding model. Do that and most of the token budget goes to `<td>`, `colspan`, and `style="padding-left:9pt"`. The numbers that matter are buried in that noise.

So "convert the HTML to markdown" is the next idea. But that framing hides the real problem.

## SEC tables are print layouts, not data tables

This is the starting point for the whole module. Open a real income statement and it is logically three columns — label, this year, last year. In the HTML it arrives as **twelve columns**.

```
col 0    col 1-2   col 3    col 4-5   col 6    col 7-9   col 10-11  col 12
(empty)  (label)   (empty)  ($)       (value)  (empty)   (value)    (%)
```

Why? Because this HTML was built on the assumption it would be **printed on paper**, not displayed. Spacer columns indent line items, a column holding only `$` aligns the currency marker, and headers span the full width with `colspan="12"`. It is the way print layout was done with tables before CSS, preserved intact inside regulatory filings.

What happens if you convert that HTML literally to markdown? A twelve-column table where two-thirds of the cells are empty. Pipe characters and whitespace push the real content apart, making it a **worse** retrieval input than the original HTML.

So what this module actually does is **remove layout**, not convert. Serialization is a single final step; the five layers before it strip print decoration.

## Starting conditions

Start after the full M1.1 suite passes and `data/corpus/manifest.json` points to the 20-filing corpus. Begin from an empty `app/ingestion/tables.py`: write L1 first, run its test, then stack L2 through L7 in the same file. The generated section at the end is an appendix for comparing the finished file, not a starting point.

---

## The journey of one table

M1.1 leaves a `Block.html`. It passes through six transformations before it becomes the markdown that M1.3 will embed and store:

```
Block.html                    raw SEC HTML with 12 physical columns
    │
    ▼
L2  to_grid()                 dense matrix — spans expanded, text at top-left only
    │                          221,730 total cells across the corpus
    ▼
L3  drop_empty()              spacer rows and columns removed
    │                          → 69,241 cells (31.2% of L2)
    ▼
L4  merge_unit_columns()      "$" and "%" folded into their values
    │                          → 66,575 cells (30.0% of L2)
    ▼
L5  split_header()            header rows inferred from shape (no <th> exists)
    │
    ▼
L6  to_markdown()             rectangular markdown with escaped pipes
    │
    ▼
L7  table_to_markdown()       public entry point — compose and fail safely
```

Only the final markdown crosses into M1.3. Everything before it is internal.

Use the table below as a bookmark. Every command appears only after its code can be imported and exercised.

| Layer | Responsibility | Learning action | Focused test |
|---|---|---|---|
| L1 | public input/output contract | **Define the structure** | `-k "degenerate_input"` |
| L2 | span-aware rectangular grid | **Implement** the expansion yourself | `-k "grid_is_rectangular or rowspan or colspan"` |
| L3 | empty row/column removal | **Implement** the removal rule yourself | `-k "collapse_never_widens"` |
| L4 | currency/percent unit merge | **Implement** the merge direction yourself | `-k "unit_columns"` |
| L5 | shape-based header inference | **Implement** the inference yourself | `-k "header"` |
| L6 | stable Markdown serialization | **Write the field mapping, then inspect escaping** | `-k "income_statement or parenthesized_negatives or markdown_rows or cell_pipes"` |
| L7 | fail-safe public pipeline | **Write the structure, then inspect call order** | full `test_09_tables.py` |

Only three of these seven layers contain a real algorithm — L2, L4, and L5. The rest are arrangement, and reading them as arrangement rather than as more algorithm is what keeps this module from feeling like seven equally hard problems.

---

## L1 — Make the front door work

The first test is not asking for a clever renderer. It asks whether the public function accepts `str | None` and returns `""` for unusable input instead of raising. There is no grid algorithm yet, so a non-empty table deliberately raises `NotImplementedError`. That keeps an unfinished implementation from pretending that valid input was empty.

**Why start here and not with the grid?** A common mistake in data-pipeline code is to build all the transforms first, then wire them to the outside world at the end. That means every intermediate function is tested through the final entry point — and if the entry point has a bug (wrong argument type, missing null check, a crash on empty input), you discover it only after writing hundreds of lines. Starting with the entry point's contract means the boundary is stable from the first minute.

Create the canonical `app/ingestion/tables.py` and write this scaffold.

#### Create `app/ingestion/tables.py` — public-contract scaffold

```python
"""10-K financial tables -> markdown."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

Grid = list[list[str]]

# Glyphs that SEC layout tables place in a column of their own. A column holding
# nothing but these is presentation, not data, so it is folded into its value column.
UNIT_MARKERS = frozenset({"$", "%", "€", "¥", "£"})


def table_to_markdown(html: str | None) -> str:
    """Return an empty string for unusable input while later layers are unfinished."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not isinstance(table, Tag) or not table.get_text(" ", strip=True):
        return ""
    raise NotImplementedError("non-empty tables are implemented in L2-L7")
```

Only now can the L1 test import the module and call the real public function.

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "degenerate_input" -q
```

`1 passed` means the boundary exists. If you see `ModuleNotFoundError`, check the path. If an invalid input raises, inspect the order of the three early returns. The corpus measurement tool comes after the renderer is complete.

**What you have now:** a function that handles `None`, empty strings, and contentless tables without crashing, and that honestly refuses to process real tables until you build the pipeline. One test passes, thirty-two are skipped. The dashboard is live.

---

## L2 — Expand spans into a dense grid

### The problem

HTML tables use `colspan` and `rowspan` to make one cell visually occupy multiple grid positions. In SEC filings, this is the primary layout mechanism — our corpus has 57,617 `colspan` occurrences across 1,200 tables. Consider this fragment:

```html
<tr>
  <td colspan="3">Revenue</td>
  <td colspan="2">26,974</td>
  <td>$</td>
  <td colspan="3"></td>
  <td colspan="2">26,914</td>
  <td>$</td>
</tr>
```

This is one row with three values (label, this year, last year), but HTML gives it twelve grid positions.

### The trap: text duplication

The naive approach is to copy each cell's text into every position it occupies. That feels natural — if a cell spans three columns, put its text in all three. But in SEC tables, **values carry the spans**, not labels. The number `26,974` has `colspan="2"`. Copying it into both positions means the retrieval index contains `26,974` twice for the same cell. Worse, a search for that number now returns two hits pointing to the same location. The correct approach: **keep text only in the top-left position and fill the rest with empty strings.**

### The other trap: ragged tables

Eighty of the 1,200 tables have rows with different declared widths. A header might declare twelve columns via `colspan`, while a data row declares only ten. If you assume every row has the same width, `drop_empty` in L3 will crash with an `IndexError` on column access. The solution: track the furthest coordinate reached across all rows and pad every row to that width. This falls out naturally from the `filled` dictionary approach below — no special ragged-table code is needed.

### The code

Define the grid code immediately above the temporary entry point.

#### Target file: `app/ingestion/tables.py`

<!-- src: app/ingestion/tables.py::_span,to_grid -->
```python
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
```

### How the algorithm works, step by step

The `filled` dictionary maps `(row, column)` coordinates to cell text. Walk each `<tr>` and each `<td>/<th>` inside it:

1. **Skip occupied positions.** The `while (r, col) in filled` loop walks past positions a `rowspan` from a previous row already claimed, advancing `col`. Without it, a two-row `rowspan` would overwrite the cell below.

2. **Place text at top-left only.** The nested `for dr / for dc` loops fill every position covered by the span. The condition `text if dr == 0 and dc == 0 else ""` ensures the cell's text appears once.

3. **Advance past the span.** After filling, `col += cspan` moves the column cursor to the next available position in this row.

4. **Build the rectangular grid.** After all rows are processed, the maximum coordinates in `filled` determine `height` and `width`. The final list comprehension with `filled.get((r, c), "")` produces a dense matrix, padding any missing positions.

### Why a dictionary and not a 2D list

Since this builds a grid, `[[""] * width for _ in range(height)]` looks natural. But that requires **knowing the final dimensions before you start.**

Trap 2 means you do not. With per-row declared widths differing, finding the maximum needs a full pre-pass. The code doubles.

A dictionary has no such problem. Coordinates are keys, so no size is fixed in advance, and insertion and "is this position taken?" use the same structure. Dimensions fall out at the end from `max(...)`.

**Collecting into a dictionary and converting to a dense structure at the end** is usually the cleanest pattern for filling a sparse coordinate space of unknown size.

### Run it

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "grid_is_rectangular or rowspan or colspan" -q
```

When all selected tests pass, ragged HTML has become rectangular and span text appears only once. On failure, inspect the `(row, column)` occupancy map of the smallest table, starting with the loop that skips coordinates already claimed by a `rowspan`.

**What you have now:** 4 tests pass. Every table in the corpus is a dense, rectangular matrix where each value appears exactly once.

---

## L3 — Remove empty rows and columns

### The problem, visualized

After L2, the NVDA-FY2024 income statement grid looks like this (simplified):

```
col:  0    1    2    3         4       5    6    7    8         9       10   11
r0:  [ ]  [ ]  [ ]  [ ]      [ ]     [ ]  [ ]  [ ]  [ ]      [ ]     [ ]  [ ]    ← pure spacer
r1:  [ ]  [ ]  [ ]  [Year Ended...]  [ ]  [ ]  [ ]  [ ]      [ ]     [ ]  [ ]
r2:  [ ]  [ ]  [ ]  [Jan 28, 2024]   [ ]  [ ]  [ ]  [ ]      [Jan 29, 2023]  [ ]
r3:  [Revenue ][ ]  [ ]  [100.0]     [ ]  [%]  [ ]  [ ]      [100.0] [ ]  [%]
```

Columns 0, 1, 2, 6, 7, and 10 are empty in every row. Row 0 is empty in every column. They exist only because the filing used `colspan` to position text visually.

After L3:

```
col:  0          1              2    3              4
r1:  [ ]        [Year Ended..] [ ]  [ ]            [ ]
r2:  [ ]        [Jan 28, 2024] [ ]  [Jan 29, 2023] [ ]
r3:  [Revenue]  [100.0]        [%]  [100.0]        [%]
```

The spacer row is gone. Six empty columns are gone. The grid went from 12 columns to 5, and the data is now adjacent to its labels.

### Why only fully-empty axes

A column that has even one non-empty cell might contain evidence. The column with `%` in row 3 but empty in rows 1-2 survives because it has content somewhere. Removing partially-empty axes would silently delete data. **The rule is: remove an axis only when every cell is empty across the entire grid.**

### The code

Add the L3 divider and function after `to_grid()`.

#### Extend `app/ingestion/tables.py` — remove empty axes

```python
# ── L3. Collapse ────────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::drop_empty -->
```python
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
```

**Why `.strip()`?** Some cells contain whitespace characters (`&nbsp;`, tabs) that look empty but are not technically empty strings. Without `.strip()`, a cell with `"  "` keeps its column alive, and the golden cell counts will not match because columns that should disappear survive.

**Why return `[]` and not raise?** Twenty-six tables in the corpus have no content at all after removing empty axes — they are pure layout spacers. Returning an empty grid instead of raising lets the caller decide what to do (the entry point in L7 returns `""`).

### Try it

The combined collapse test also needs the next layer's `merge_unit_columns()`, so do not run it prematurely. Exercise this function with a tiny grid instead.

```bash
uv run python -c "from app.ingestion.tables import drop_empty; assert drop_empty([['', '', ''], ['Revenue', '', '1']]) == [['Revenue', '1']]"
```

A silent exit means only empty axes disappeared. If a value vanished, compare `keep` with the original columns and find the first omitted index.

**What you have now:** Still 4 tests pass (no new tests activate at L3 alone — the collapse tests need L4). But the function is ready for manual inspection.

---

## L4 — Merge dedicated unit columns

### The problem

After L3, the grid still contains columns whose only purpose is to display `$` before a number or `%` after it. In the corpus, 279 such columns survive after empty-axis removal. They hold no independent meaning — `$` is not a value, it is a presentation detail attached to the adjacent number. Leaving them as separate columns yields `| $ | 26,974 |` in the markdown instead of `| $ 26,974 |`, wasting retrieval tokens on isolated symbols.

### The design choice: direction follows reading order

Currency symbols read **before** their value: `$ 26,974`. Percent symbols read **after**: `72.7 %`. So `$` merges into the column to its right (`target = j + 1`), and `%` merges into the column to its left (`target = j - 1`). Getting this backwards would produce `26,974 $` or `% 72.7`, which is nonsensical.

### How to identify a unit column

A column is a unit column when **every non-empty cell in that column** is a member of `UNIT_MARKERS` (`$`, `%`, `€`, `¥`, `£`). If even one cell contains something else — a number, a label, whitespace-only — the column is not a unit column. This conservative rule prevents merging a column that happens to have a `$` in its header but actual data below.

### The code

Write the L4 divider first, then define the function below it.

#### Extend `app/ingestion/tables.py` — merge unit columns

```python
# ── L4. Units ───────────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::merge_unit_columns -->
```python
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
```

### Walking through the algorithm

1. **Transpose the grid into columns.** `cols[j]` is a list of all values in column `j`. This transposition lets us inspect each column independently without nested row/column loops.

2. **Identify unit columns.** Collect all non-empty cells. If they are all unit markers, this is a unit column.

3. **Determine direction.** If every marker is `%`, the column is trailing (merge left). All other unit markers are leading (merge right). This handles the common case where `$` and `€` appear before their values, and `%` appears after.

4. **Bounds check.** If the target column is out of range or was already dropped (another unit column already merged into it), skip this column. Without `target in dropped`, two adjacent unit columns would chain — the second would try to merge into the first, which is already gone.

5. **Merge cell by cell.** For each row, prepend or append the glyph to the target cell's value. The `.strip()` handles cases where the target cell is empty — `f"$ {value}".strip()` produces `"$"` instead of `"$ "`.

6. **Remove merged columns.** The final list comprehension rebuilds the grid without the dropped columns. Note that it reads `cols[j][i]` (column-major) and transposes back to row-major.

### Run it

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "collapse_never_widens or unit_columns" -q
```

Passing tests prove that collapse never widens a table and that `$` and `%` retain reading order. Print `values`, `trailing`, and `target` for the first failing column to expose a bad neighbor choice.

**What you have now:** 6 tests pass. The grid has been reduced from 221,730 cells to 66,575 (30.0% of the original). Seventy percent of what the HTML table contained was layout, not data.

---

## L5 — Infer the header shape

### One measurement that changed the whole design

A markdown table needs a header row. Headers in HTML are `<th>` tags, so finding those should do it — that was the plan, and then the corpus was measured.

**There is not a single `<th>`.** Not few: exactly zero across all 1,200 tables.

As established, this HTML is print layout. Bold text already looks like a header, so there was never a reason to reach for a semantic tag. It is the same story as the missing `<h1>` in M1.1.

That one fact decides all of L5. A `<th>`-based approach returns zero here forever, so a different signal is required.

This premise matters enough to pin with a test. `test_header_is_inferred_from_shape_not_from_th` asserts `soup.find("th") is None` for every document. **A measurement that a design rests on is worth freezing in a test.** If a document with `<th>` ever enters the corpus, that test says so first.

### Shape-based inference

Without semantic tags, the only remaining signal is the **shape of the data**. In SEC financial tables, a consistent pattern emerges:

- **Header rows** label the value columns ("Year Ended", "Jan 28, 2024") but leave the first column (the label column) empty, because the header describes what the **values** are, not what the **labels** are.
- **Data rows** always start with a line-item name ("Revenue", "Cost of revenue") in the first column.

This gives a clean rule: **collect leading rows where column 0 is empty and at least one other column has text.** Stop at the first row where column 0 is non-empty — that is the first data row.

### What about multi-row headers?

Many SEC tables have two or even three header rows. "Year Ended" spans the full width in row 1, while "Jan 28, 2024" and "Jan 29, 2023" appear in row 2 under their respective value columns. Both rows have an empty first column and populated value columns, so the shape rule naturally collects both. L6 will later join them per column, producing `"Year Ended Jan 28, 2024"` as a single header cell — keeping the period a number belongs to in the chunk text.

### When nothing matches

If the first row already has content in column 0, or if no row has content outside column 0, the rule finds nothing. In that case, `split_header` returns `([], grid)` — an empty header and the entire grid as body. **It does not invent a header.** The caller (L6) handles the fallback by promoting the first body row to the markdown header position, which keeps the table valid markdown.

### The code

Define the header function after the L5 divider.

#### Extend `app/ingestion/tables.py` — split headers

```python
# ── L5. Header ──────────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::split_header -->
```python
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
```

### The edge case: `n == len(grid)`

If every row in the grid has an empty first column, the loop would consume the entire grid as a header with no body. That produces a valid markdown table with only a header and a separator row — technically correct but useless. The `n == len(grid)` check prevents this by returning everything as body instead.

### Run it

```bash
uv run pytest tests/ingestion/test_09_tables.py -k "header" -q
```

The selected tests cover both a real header and no header at all. If body rows are consumed, inspect the first column and value cells in the first row where inference should have stopped.

**What you have now:** 8 tests pass. The grid is split into a header and body, with multi-row headers ready to be joined.

---

## L6 — Serialize markdown

### What this layer does and does not do

L6 translates the logical grid into markdown syntax. It does not change any values, remove any rows, or rearrange any columns. All the structural work was done in L2-L5. This layer is deliberately thin.

Two things need attention:

1. **Multi-row headers must be joined.** A two-row header with "Year Ended" in row 1 and "Jan 28, 2024" in row 2 must become one header cell: `"Year Ended Jan 28, 2024"`. This is done per column — join the non-empty values from each header row for that column position.

2. **Pipes inside cells must be escaped.** The `|` character is the markdown column delimiter. A cell containing `a|b` would produce `| a|b |`, which renderers interpret as three columns instead of one. Escaping it as `a\|b` preserves the cell boundary.

### The code

Add the L6 divider and both functions after `split_header()`.

#### Extend `app/ingestion/tables.py` — serialize markdown

```python
# ── L6. Serialize ───────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::_cell,to_markdown -->
```python
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
```

### Why `_cell` also collapses whitespace

The `" ".join(text.split())` call normalizes internal whitespace. SEC table cells sometimes contain `\n` or multiple spaces from iXBRL rendering. Normalizing here keeps the markdown rows uniform and prevents multi-line cell content from breaking the table structure.

### The fallback: no header found

When `split_header` returns `([], grid)`, the serializer promotes the first body row to the header position: `head, body = body[0], body[1:]`. This is a pragmatic choice — markdown tables require a header row followed by a separator row. Without a header, the table would not render. Promoting the first row sacrifices one data row but keeps the output valid.

### Try it

The public entry point is still temporary, so exercise the serializer directly.

```bash
uv run python -c "from app.ingestion.tables import to_markdown; md = to_markdown([['', '2024'], ['Revenue', 'a|b']]); assert '| Revenue | a\\|b |' in md"
```

A silent exit proves that row width and cell boundaries survived. If not, inspect the inferred `head` and first body row before looking at string joins.

**What you have now:** Still 8 tests pass (the serialization tests all go through `table_to_markdown`, which is still the L1 stub). But the serializer is ready.

---

## L7 — Fail-safe entry point

### Connecting the pipeline

Finally, replace the temporary L1 `table_to_markdown()` with the real implementation. This function parses HTML and connects all five transforms — `to_grid()`, `drop_empty()`, `merge_unit_columns()`, and `to_markdown()` — in one path.

The caller (M1.3's chunker) needs to know only this entry point. It hands in `Block.html` and gets back a markdown string, or an empty string when there is no content.

### The parenthesized-negatives decision

SEC filings represent negative numbers in parentheses: `(1,234)` means minus 1,234. A tempting optimization is to convert these to `-1234` during ingestion, making numeric search easier.

**This module does not do that.** Three reasons:

1. **Citations must match the source.** When the retrieval system shows a user "Revenue was (1,234)" with a citation pointing to the filing, the filing must actually say `(1,234)`. Converting to `-1234` breaks the citation contract.

2. **Ingestion-time normalization is irreversible.** Once you write `-1234` to the database, you cannot recover `(1,234)`. Query-time normalization (expanding `(1,234)` during search) is reversible.

3. **The risk concentrates on the safe side.** If this decision proves wrong, fix the query layer. A mistake at ingestion requires re-processing every document.

### The code

#### Extend `app/ingestion/tables.py` — public entry point

```python
# ── L7. Entry point ─────────────────────────────────────────────────────────
```

<!-- src: app/ingestion/tables.py::table_to_markdown -->
```python
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
```

### Why `drop_empty` runs before `merge_unit_columns`

The order matters. `drop_empty` removes entirely-blank columns. `merge_unit_columns` folds unit columns into their neighbors. If you reverse them, `merge_unit_columns` would try to find `$` columns in a grid still cluttered with empty spacer columns, and the neighbor detection (`target = j + 1`) might point to a spacer instead of the value column.

### Run it

```bash
uv run pytest tests/ingestion/test_09_tables.py -q
```

**This is the moment twenty-five tests activate at once.** The entry point connects every transform, and all the corpus-level tests that were waiting for `table_to_markdown` now run.

The whole file must pass with no skip caused by a missing symbol. Rerun one failure with `-vv` and locate the first helper whose `Grid` differs from its contract. Do not continue to M1.3 until this gate is green.

### What the result looks like

The NVDA-FY2024 percentage income statement, which arrived as twelve-column HTML with 63.6% empty cells, is now:

```
|  | Year Ended Jan 28, 2024 | Jan 29, 2023 |
| --- | --- | --- |
| Revenue | 100.0 % | 100.0 % |
| Cost of revenue | 27.3 | 43.1 |
| Gross profit | 72.7 | 56.9 |
| Operating expenses |  |  |
| Research and development | 14.2 | 27.2 |
| Total operating expenses | 18.6 | 41.3 |
| Operating income | 54.1 | 15.6 |
| Interest expense | (0.4) | (1.0) |
| Net income | 48.9 % | 16.2 % |
```

Three columns. No spacers. Headers joined. Parenthesized negatives preserved. This is searchable, embeddable, and faithful to the source.

That `Year Ended Jan 28, 2024` collapsed into one cell matters most. Search this table for `Gross profit` and **which fiscal year the number belongs to** now sits in the same chunk. Drop the header and only "72.7" would remain, producing an answer that cannot say which year it describes.

### What you should be able to explain now

- **Why does copying spanned text into every covered cell corrupt retrieval?**
  - **Answer:** SEC values often carry `colspan`. Because one table becomes one chunk, copying the text does not create separate hits; it repeats one fact inside `index_text`, overweights that token, and can distort lexical and embedding ranking. Only the top-left coordinate keeps the value.
- **Why is a dictionary keyed by coordinates used instead of a 2-D list?**
  - **Answer:** Rowspans and ragged rows mean the final width and height are unknown until all cells have been placed. A coordinate dictionary handles occupancy and arbitrary growth in one pass, then converts cleanly to a padded dense grid.
- **Which axis is removed only when it is entirely empty, and what is that protecting?**
  - **Answer:** Both rows and columns are removed only when every cell on that axis is blank. Keeping any partially populated axis prevents a lone value or unit marker from being silently deleted.
- **Why does a unit column merge in reading order rather than the other direction?**
  - **Answer:** Currency symbols precede their values, so they merge right, while percent signs follow values and merge left. Reversing those directions produces text such as `26,974 $` or `% 72.7`, which changes how the data reads.
- **What did measurement change about the header design?**
  - **Answer:** The corpus contained zero `<th>` elements, so semantic-tag detection could never work. Header inference therefore uses row shape: leading rows with an empty label column and populated value columns become the header.
- **Why does `drop_empty` have to run before `merge_unit_columns`?**
  - **Answer:** Unit merging chooses an immediate neighboring column. Removing spacer columns first makes that neighbor the actual numeric value instead of a blank layout column.

---

## What this module hands to the next one

M1.2 barely couples to anything else. **One pure function that takes an HTML string and returns a markdown string** is the whole of it.

That is deliberate. As the module docstring says, this code never touches `Block`. The M1.1 parser only leaves table blocks as `Block("table", "", html=...)`, and **the M1.3 chunker calls `table_to_markdown` at the moment it needs text.**

Splitting it that way buys two things.

- **Table rendering cannot move the parser's coverage metric.** Parser validation and table conversion fail independently.
- **The parser knows nothing about markdown.** Want to emit tables as JSON or some other format later and the parser is untouched.

The next chapter, M1.3, uses M1.1's block list together with this function to build citable chunks. Text blocks group by paragraph; a table block becomes a single chunk holding the markdown produced here — **because splitting a table makes its citation a lie.** That story is told in the next chapter.

---

## Finish the module with two working tools

The core pipeline is complete, but the finished file also carries its design rationale and a CLI for human inspection. First replace the short one-line docstring at the top of `app/ingestion/tables.py` with this one.

#### Update `app/ingestion/tables.py` — module rationale

```python
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

```

Next append the inspection CLI to the end of `app/ingestion/tables.py`.

#### Extend `app/ingestion/tables.py` — inspection CLI

```python
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
```

Finally implement the measurement tool at its canonical path, `scripts/measure_tables.py`. It does not generate implementation code; it recomputes golden measurements from the current corpus.

#### Create `scripts/measure_tables.py` — corpus measurement tool

```python
#!/usr/bin/env python3
"""Regenerate the M1.2 corpus measurements and per-document golden tuples."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from statistics import median

from bs4 import Tag

from app.ingestion.parser import leaf_blocks, normalize, read_source
from app.ingestion.tables import drop_empty, merge_unit_columns, table_to_markdown, to_grid

REPO = Path(__file__).resolve().parent.parent
PAREN_NUMBER = re.compile(r"^\(\s*[\d,.]+\s*\)$")


def _span(cell: Tag, name: str) -> int:
    try:
        return max(1, int(str(cell.get(name, 1)).strip() or 1))
    except TypeError, ValueError:
        return 1


def _percentile(values: list[int], fraction: float) -> int:
    """Return a deterministic nearest-rank percentile for a non-empty list."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _expanded_row_widths(table: Tag) -> list[int]:
    """Return declared row widths after colspan but before rectangular padding."""
    return [
        sum(_span(cell, "colspan") for cell in row.find_all(["td", "th"]))
        for row in table.find_all("tr")
    ]


def measure() -> tuple[dict[str, tuple[int, int, int, int]], dict[str, object]]:
    """Measure the fixed corpus without writing profiles or derived artifacts."""
    manifest = json.loads((REPO / "data/corpus/manifest.json").read_text())
    golden: dict[str, tuple[int, int, int, int]] = {}
    empty_ratios: list[float] = []
    before_widths: list[int] = []
    dropped_widths: list[int] = []
    after_widths: list[int] = []
    totals: Counter[str] = Counter()

    for entry in sorted(manifest, key=lambda item: (item["ticker"], item["report_date"])):
        doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
        raw = read_source(REPO / entry["file"])
        tables = [block for block in leaf_blocks(normalize(raw)) if block.name == "table"]
        empty_outputs = expanded_cells = dropped_cells = collapsed_cells = 0

        for table in tables:
            row_widths = _expanded_row_widths(table)
            if row_widths and len(set(row_widths)) > 1:
                totals["ragged_tables"] += 1

            cells = table.find_all(["td", "th"])
            if cells:
                empty_ratios.append(
                    sum(not cell.get_text(" ", strip=True) for cell in cells) / len(cells)
                )
            for cell in cells:
                colspan = _span(cell, "colspan")
                rowspan = _span(cell, "rowspan")
                if colspan > 1:
                    totals["colspan_occurrences"] += 1
                    totals["colspan_covered_cells"] += colspan
                if rowspan > 1:
                    totals["rowspan_occurrences"] += 1
                if PAREN_NUMBER.fullmatch(cell.get_text(" ", strip=True)):
                    totals["parenthesized_number_cells"] += 1

            grid = to_grid(table)
            dropped = drop_empty(grid)
            collapsed = merge_unit_columns(dropped)
            expanded_cells += sum(len(row) for row in grid)
            dropped_cells += sum(len(row) for row in dropped)
            collapsed_cells += sum(len(row) for row in collapsed)
            if grid:
                before_widths.append(len(grid[0]))
            if dropped:
                dropped_widths.append(len(dropped[0]))
            if collapsed:
                after_widths.append(len(collapsed[0]))
            if not table_to_markdown(str(table)):
                empty_outputs += 1

        golden[doc_id] = (len(tables), empty_outputs, expanded_cells, collapsed_cells)
        totals["tables"] += len(tables)
        totals["empty_outputs"] += empty_outputs
        totals["expanded_cells"] += expanded_cells
        totals["dropped_cells"] += dropped_cells
        totals["collapsed_cells"] += collapsed_cells

    summary: dict[str, object] = dict(totals)
    summary["median_raw_cell_empty_ratio"] = round(median(empty_ratios), 3)
    summary["expanded_widths"] = {
        "p50": _percentile(before_widths, 0.50),
        "p90": _percentile(before_widths, 0.90),
        "max": max(before_widths),
    }
    summary["empty_axes_removed_widths"] = {
        "p50": _percentile(dropped_widths, 0.50),
        "p90": _percentile(dropped_widths, 0.90),
        "max": max(dropped_widths),
    }
    summary["collapsed_widths"] = {
        "p50": _percentile(after_widths, 0.50),
        "p90": _percentile(after_widths, 0.90),
        "max": max(after_widths),
    }
    return golden, summary


if __name__ == "__main__":
    measured_golden, measured_summary = measure()
    print("TABLES = {")
    for measured_doc_id, values in measured_golden.items():
        print(f"    {measured_doc_id!r}: {values},")
    print("}")
    print("\nSUMMARY =")
    print(json.dumps(measured_summary, indent=2, sort_keys=True))
```



```bash
uv run python scripts/check_doc_code.py docs/en/m1-2-tables/03-build.md docs/ko/m1-2-tables/03-build.md
uv run ruff check --no-fix app/ingestion/tables.py tests/ingestion/test_09_tables.py scripts/measure_tables.py
uv run pytest tests/ingestion/test_09_tables.py -q
uv run python -m app.ingestion.tables --doc NVDA-FY2024
```

When all four commands pass, the CLI prints readable table Markdown for the requested filing. If one fails, resolve the first failure before moving on. A missing corpus means the M0 prerequisite is incomplete, not that this implementation may be skipped. The generated section at the end is not a hand-edit target.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M1.2 — Complete checkpoint

#### Create or replace `app/ingestion/tables.py`

<!-- file: app/ingestion/tables.py -->
```python
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
```

#### Create or replace `scripts/measure_tables.py`

<!-- file: scripts/measure_tables.py -->
```python
#!/usr/bin/env python3
"""Regenerate the M1.2 corpus measurements and per-document golden tuples."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from statistics import median

from bs4 import Tag

from app.ingestion.parser import leaf_blocks, normalize, read_source
from app.ingestion.tables import drop_empty, merge_unit_columns, table_to_markdown, to_grid

REPO = Path(__file__).resolve().parent.parent
PAREN_NUMBER = re.compile(r"^\(\s*[\d,.]+\s*\)$")


def _span(cell: Tag, name: str) -> int:
    try:
        return max(1, int(str(cell.get(name, 1)).strip() or 1))
    except TypeError, ValueError:
        return 1


def _percentile(values: list[int], fraction: float) -> int:
    """Return a deterministic nearest-rank percentile for a non-empty list."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _expanded_row_widths(table: Tag) -> list[int]:
    """Return declared row widths after colspan but before rectangular padding."""
    return [
        sum(_span(cell, "colspan") for cell in row.find_all(["td", "th"]))
        for row in table.find_all("tr")
    ]


def measure() -> tuple[dict[str, tuple[int, int, int, int]], dict[str, object]]:
    """Measure the fixed corpus without writing profiles or derived artifacts."""
    manifest = json.loads((REPO / "data/corpus/manifest.json").read_text())
    golden: dict[str, tuple[int, int, int, int]] = {}
    empty_ratios: list[float] = []
    before_widths: list[int] = []
    dropped_widths: list[int] = []
    after_widths: list[int] = []
    totals: Counter[str] = Counter()

    for entry in sorted(manifest, key=lambda item: (item["ticker"], item["report_date"])):
        doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
        raw = read_source(REPO / entry["file"])
        tables = [block for block in leaf_blocks(normalize(raw)) if block.name == "table"]
        empty_outputs = expanded_cells = dropped_cells = collapsed_cells = 0

        for table in tables:
            row_widths = _expanded_row_widths(table)
            if row_widths and len(set(row_widths)) > 1:
                totals["ragged_tables"] += 1

            cells = table.find_all(["td", "th"])
            if cells:
                empty_ratios.append(
                    sum(not cell.get_text(" ", strip=True) for cell in cells) / len(cells)
                )
            for cell in cells:
                colspan = _span(cell, "colspan")
                rowspan = _span(cell, "rowspan")
                if colspan > 1:
                    totals["colspan_occurrences"] += 1
                    totals["colspan_covered_cells"] += colspan
                if rowspan > 1:
                    totals["rowspan_occurrences"] += 1
                if PAREN_NUMBER.fullmatch(cell.get_text(" ", strip=True)):
                    totals["parenthesized_number_cells"] += 1

            grid = to_grid(table)
            dropped = drop_empty(grid)
            collapsed = merge_unit_columns(dropped)
            expanded_cells += sum(len(row) for row in grid)
            dropped_cells += sum(len(row) for row in dropped)
            collapsed_cells += sum(len(row) for row in collapsed)
            if grid:
                before_widths.append(len(grid[0]))
            if dropped:
                dropped_widths.append(len(dropped[0]))
            if collapsed:
                after_widths.append(len(collapsed[0]))
            if not table_to_markdown(str(table)):
                empty_outputs += 1

        golden[doc_id] = (len(tables), empty_outputs, expanded_cells, collapsed_cells)
        totals["tables"] += len(tables)
        totals["empty_outputs"] += empty_outputs
        totals["expanded_cells"] += expanded_cells
        totals["dropped_cells"] += dropped_cells
        totals["collapsed_cells"] += collapsed_cells

    summary: dict[str, object] = dict(totals)
    summary["median_raw_cell_empty_ratio"] = round(median(empty_ratios), 3)
    summary["expanded_widths"] = {
        "p50": _percentile(before_widths, 0.50),
        "p90": _percentile(before_widths, 0.90),
        "max": max(before_widths),
    }
    summary["empty_axes_removed_widths"] = {
        "p50": _percentile(dropped_widths, 0.50),
        "p90": _percentile(dropped_widths, 0.90),
        "max": max(dropped_widths),
    }
    summary["collapsed_widths"] = {
        "p50": _percentile(after_widths, 0.50),
        "p90": _percentile(after_widths, 0.90),
        "max": max(after_widths),
    }
    return golden, summary


if __name__ == "__main__":
    measured_golden, measured_summary = measure()
    print("TABLES = {")
    for measured_doc_id, values in measured_golden.items():
        print(f"    {measured_doc_id!r}: {values},")
    print("}")
    print("\nSUMMARY =")
    print(json.dumps(measured_summary, indent=2, sort_keys=True))
```

Run the checkpoint:

```bash
uv run pytest tests/ingestion/test_09_tables.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
