# M1.2 Findings

Every value can be regenerated from the fixed twenty-document 10-K snapshot with `scripts/measure_tables.py`. `tests/ingestion/golden.py` is the machine-readable source of truth for the per-document regression tuples.

## F1. Table count and empty cells

The corpus contains 1 thousand two hundred table Blocks. The median per-table raw-cell empty ratio is 0 point six three six. In other words, about two-thirds of the cells in a typical table are layout whitespace, not content.

**Decision:** collapse the layout before serializing the HTML table to markdown.

## F2. Merged cells are a standard layout mechanism, not an exception

- `colspan > 1`: 57 thousand six hundred seventeen occurrences
- `rowspan > 1`: one hundred eighty-eight occurrences
- ragged tables with differing declared row widths: eighty

A financial table with three logical columns arrives with twelve or more physical columns that separate labels, values, units, and spacers.

**Decision:** expand spans into a dense grid, but place text only once in the top-left cell. Copying text into the remaining occupied cells would duplicate numbers.

## F3. There are no `<th>` elements

The entire corpus contains zero `<th>` elements. A header parser that looks only at tag names fails on every table.

**Decision:** treat leading rows with an empty label column and populated value columns as headers. If that shape is absent, do not invent a header; promote the first body row to the markdown header.

## F4. Empty-axis removal and unit-column merging are separate stages

The cell count decreases in this order.

| Stage | Cell count |
|---|---:|
| L2 span expansion | 221,730 |
| L3 empty-row and empty-column removal | 69,241 |
| L4 `$`/`%` column merging | 66,575 |

The final cell count is 30.0% of L2. Combining L3 and L4 in one measurement would hide which policy changed, so the measurement script reports the two stages separately.

## F5. Column-width distribution

| Stage | p50 | p90 | max |
|---|---:|---:|---:|
| L2 expansion | 12 | 30 | 66 |
| L3 empty-axis removal | 5 | 11 | 25 |
| L4 unit-column merging | 5 | 10 | 25 |

**Decision:** finish L3 and L4 before markdown serialization. Otherwise, most of the retrieval context is empty columns.

## F6. layout-only table

After collapse, twenty-six tables contain no content at all. They occur only in AMD and INTC layouts, not in MU or NVDA.

**Decision:** return an empty string instead of producing an error or placeholder markdown.

## F7. Parenthesized negatives

There are 3 thousand seventy-three numeric cells in the form `(1,234)`. Converting them to `-1234` during ingestion would make the citation text differ from the filing and could not be reversed.

**Decision:** M1.2_ preserves the source notation. If retrieval needs numeric normalization, handle it as reversible expansion at the query/retrieval boundary.

## F8. Representative full-table golden

The NVDA-FY2024 percentage income statement shrinks from twelve physical columns to three logical columns. The test checks equality of the complete markdown, from the header through the final `Net income` row, instead of comparing only a prefix.

**Decision:** corpus aggregates cover structural regression; the representative full table covers real cell text/header/order regression.
