"""Your turn: 10-K table HTML -> markdown.

Graded by the same tests as the reference:

    TABLES_MODULE=app.ingestion.tables_mine uv run pytest tests/ingestion/test_09_tables.py

Tests for functions you have not written yet **skip instead of fail**, so the pytest
output doubles as a progress board. Build in this order (see
docs/en/m1-1-parser/03-build.md for
the equivalent walkthrough of the parser):

    L2  to_grid(table)              expand colspan/rowspan into a dense matrix
    L3  drop_empty(grid)            remove all-empty rows and columns
    L4  merge_unit_columns(grid)    fold '$'/'%'-only columns into their value
    L5  split_header(grid)          infer header rows -> (header, body)
    L6  to_markdown(grid)           serialize
    L7  table_to_markdown(html)     entry point wiring L2-L6 together

Before writing any of it, go look at the input:

    uv run python -m app.ingestion.tables --doc NVDA-FY2024

The measurement that drives the whole design: the median table has 63.6% empty raw
cells, there is no `<th>` anywhere in the corpus, and `colspan` appears 57,617 times.
These tables are laid out for print, not for data. Collapse the layout before you
serialize.
"""
