# M1.2 Spec

> Code: `app/ingestion/tables.py` · Verification: [05-verify.md](05-verify.md) Previous stage: [`m1-1-parser/`](../m1-1-parser/00-README.md) (10-K → Item section parser)

## In one sentence

**SEC tables are layout tables, not data tables.** The core of this module is therefore **removing layout**, not serialization.

---

## 1. Input facts and design decisions

[Finding 01](01-findings.md) owns the full measurements. The essential fact is that an SEC table is a print layout, not a logical data grid. This module therefore contracts for **meaning-preserving serialization after layout collapse**, not simple serialization.

### What this means

This is the real structure of the NVDA-FY2024 percentage income statement. A table with **three logical columns**:

```
r0   n=12  [''] [''] [''] [''] [''] [''] [''] [''] [''] [''] [''] ['']
r1   n=2   [''x3] ['Year Ended'x9]
r2   n=4   [''x3] ['Jan 28, 2024'x3] [''x3] ['Jan 29, 2023'x3]
r3   n=6   ['Revenue'x3] ['100.0'x2] ['%'] [''x3] ['100.0'x2] ['%']
```

arrives with **twelve physical columns**: label (colspan 3), value (colspan 2), unit, and spacer (colspan 3). `r0` is a pure spacer row whose twelve cells are all empty.

**Serializing this HTML directly to markdown produces a wide grid that is 63.6% empty at the median.** That is worse for retrieval than the source text. Collapse must therefore come first.

---

## 2. Pipeline

```
L2 to_grid              colspan/rowspan -> dense matrix
L3 drop_empty           remove empty axes         (12 -> 5 columns, p50)
L4 merge_unit_columns   fold '$'/'%' columns into values
L5 split_header         infer header rows         (no <th> exists)
L6 to_markdown          serialize markdown
L7 table_to_markdown    compose the entry point
```

### L2 — Grid expansion

**Key decision: do not copy the text of a spanned cell.** Keep it only in the top-left position and leave the rest empty. Copying would **count every number twice** in this corpus because value cells use `colspan`.

The `(r, col) in filled` check skips positions already occupied by a rowspan. Because `filled` tracks both occupancy and text, no separate occupancy map is needed.

### L3·L4 — Collapse ★

Total cells fell from L2 **221,730** → L3 **69,241** → L4 **66,575 (30.0%)**. Together, empty-axis removal and unit-column merging show that layout occupied **70%** of the grid.

| | Before | After |
|---|---|---|
| Column p50 | 12 | **5** |
| Column p90 | 30 | **11** (10 after L4) |
| Column max | 66 | **25** |

This stage also filters **twenty-six** tables with no content at all (all pure spacers). They occur only for AMD and INTC, with zero for MU and NVDA, directly exposing company-specific layout differences.

### L4 — Unit columns

Fold `$` **before** the number and `%` **after** it, following reading order. Without this step, **two hundred seventy-nine** symbol-only columns remain after collapse.

### L5 — Header inference

Because there are zero `<th>` elements, inference uses shape alone:

> **Header rows are leading rows with an empty label column and text in the remaining columns.**

Data rows always begin with a line-item name, which makes this rule discriminative. Multirow headers ("Year Ended" above "Jan 28, 2024") are combined by column so the chunk text retains **which period each number belongs to**.

If nothing matches, return `([], grid)`: do not invent an empty header; **let the caller decide.**

---

## 3. Result

The same table becomes:

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

To inspect it directly:

```bash
uv run python -m app.ingestion.tables --doc NVDA-FY2024
```

To regenerate the corpus-wide measurements and per-document golden tuples:

```bash
uv run python -m scripts.measure_tables
```

---

## 4. Two decisions and their rationale

### Do not populate `Block.text`

The draft-plan contract was `Block(kind="table", html=...)` → `Block(text=<markdown>)`. **It changed.**

`parser.py` creates table blocks as `Block("table", "", html=str(el))`, leaving `text` empty. The coverage metric is calculated as `body = sum(len(b.text) ...)`. Populating it with markdown would invalidate **all twenty COVERAGE golden values.**

This module therefore remains **a pure function over HTML**. It does not modify `Block`; the chunker (M1.3) calls `table_to_markdown(block.html)` when needed.

This is a benefit, not a side effect:
- table rendering cannot perturb the coverage metric
- the parser knows nothing about markdown, preserving the principle that **lower layers do not know higher layers**

### Do not normalize parenthesized negatives

Do not convert `(1,234)` to `-1234`. All 3 thousand seventy-three instances pass through unchanged.

- **Citations must match the source.** Chunks must not differ from what readers see in the filing.
- **Ingestion-time normalization is irreversible.** Query-time normalization is reversible.

If this decision proves wrong, fix the query side; a mistake at ingestion requires reingestion. **Concentrate the risk on the reversible side.**

---

## 5. Designed · Not implemented

| Name | Status |
|---|---|
| table caption extraction | ✗ — a preceding paragraph outside the table is sometimes the caption; M1.3 handles it as a context header |
| footnote-symbol separation | ✗ — references such as `(1)` remain unchanged even when mixed into a cell |
| column alignment (`---:`) | ✗ — alignment metadata is not useful for retrieval |

`UNIT_MARKERS` includes `€`, `¥`, and `£`, but this corpus (U.S. 10-K filings) contains only `$` and `%`.
