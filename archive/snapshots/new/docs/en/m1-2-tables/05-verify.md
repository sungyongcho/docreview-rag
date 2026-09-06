# M1.2 Verification

> Specification: [02-spec.md](02-spec.md) · Code: `app/ingestion/tables.py`

## Run everything at once

```bash
uv run pytest tests/ingestion/test_09_tables.py     # 33 tests
uv run pytest                                        # full project suite
```

Inspect visually:

```bash
uv run python -m app.ingestion.tables --doc NVDA-FY2024
uv run python -m app.ingestion.tables --doc MU-FY2024 --contains "Total current assets"
```

## What this verifies

**Verify that the layout was removed, not merely that a conversion occurred.** Checking only that markdown was produced would allow a wide grid that is 63.6% empty at the median to pass.

| Metric | What it catches | What it **cannot** catch |
|---|---|---|
| ① collapse ratio (golden value) | insufficient layout removal / deleted content | incorrect content **inside** a cell |
| ② representative full-table comparison | header combination, unit merging, column order | layouts from other companies |
| ③ consistent markdown width | broken rendering | meaning |
| ④ degenerate input | crashes | — |

The key is that ① works in both directions: a **higher** cell count means insufficient collapse; a **lower** count means content was deleted.

## Golden values

In `tests/ingestion/golden.py`, `TABLES` is the **single source of truth**. Numbers in this document are human-readable copies.

```
(표블록, 빈 markdown, 전개 후 셀, 붕괴 후 셀)
```

Total: **221,730 → 69,241 → 66 thousand five hundred seventy-five cells (30.0%)** · **twenty-six** empty tables

The twenty-six empty tables are pure spacers with no content. They occur only in AMD (ten) and INTC (sixteen); **MU and NVDA have zero**. This is a company-specific layout difference, not a bug.

The command below regenerates both the totals above and every per-document `TABLES` tuple.

```bash
uv run python -m scripts.measure_tables
```

## Test map

| Test | Coverage | Corpus |
|---|---|---|
| `test_grid_is_rectangular` | L2 — eighty ragged tables become rectangular | ✅ |
| `test_rowspan_carries_down_without_duplicating_text` | L2 — no text duplication | ✗ |
| `test_colspan_keeps_text_in_first_cell_only` | L2 | ✗ |
| `test_collapse_matches_golden` | **L3·L4 — collapse ratio ★** | ✅ |
| `test_collapse_never_widens_a_table` | L3·L4 — monotonic decrease | ✅ |
| `test_unit_columns_are_folded_in_reading_order` | L4 — `$` before / `%` after | ✗ |
| `test_header_is_inferred_from_shape_not_from_th` | **L5 — assumes zero `<th>` elements** | ✅ |
| `test_header_rows_are_the_leading_rows_with_an_empty_label_column` | L5 | ✗ |
| `test_no_header_shape_returns_everything_as_body` | L5 — do not invent a header | ✗ |
| `test_income_statement_renders_as_expected` | **L6 — representative full-table comparison** | ✅ |
| `test_parenthesized_negatives_survive_verbatim` | L7 — preserve the source | ✅ |
| `test_markdown_rows_all_have_the_same_width` | L6 — renderable output | ✅ |
| `test_degenerate_input_never_raises` | L7 — no crashes | ✗ |
| `test_cell_pipes_are_escaped` | L6 | ✗ |

`test_header_is_inferred_from_shape_not_from_th` protects a **corpus fact**, not an implementation. If the code reverts to reading `<th>`, this assertion breaks first—and that implementation finds no headers at all.

## Implement it yourself

Create `app/ingestion/tables.py` directly; the same tests grade the canonical implementation:

```bash
uv run pytest tests/ingestion/test_09_tables.py
```

Tests that use functions not yet implemented are **skipped, not failed**, so the output serves as a progress dashboard. Measured with an empty stub:

```
1 passed, 32 skipped
```

The one passing test is `test_header_is_inferred_from_shape_not_from_th`. It inspects only the corpus without invoking the implementation, so it is active from the start.

## How many tests activate as each layer is filled in?

These values were measured directly by adding the reference code one layer at a time. **Use them to locate your current progress.**

```
누적 구현                    통과 / 33   비고
────────────────────────────────────────────────────────────
(빈 스텁)                        1      코퍼스 사실만
+L2 to_grid                      4      전개 3개가 켜진다
+L3 drop_empty                   4      ★0개 늘어난다 — 아래 주의
+L4 merge_unit_columns           6      단위 병합 + 단조감소
+L5 split_header                 8      헤더 2개
+L6 to_markdown                  8      ★여기도 0개
+L7 table_to_markdown           33      전부
```

**L3 and L6 provide zero test feedback.** Both collapse tests require `merge_unit_columns` (they activate together at L4 with +2), and every serialization test goes through `table_to_markdown`. Those two layers therefore cannot be graded while being written; inspect them manually:

```bash
uv run python -c "
from bs4 import BeautifulSoup
from app.ingestion.tables import to_grid, drop_empty
html = open('data/corpus/NVDA/2024-02-21_0001045810-24-000029.html').read()
t = BeautifulSoup(html, 'lxml').find_all('table')[40]
g = to_grid(t)
print('before', len(g[0]), 'x', len(g))
c = drop_empty(g)
print('after ', len(c[0]), 'x', len(c))
"
```

**The final twenty-five tests depend on `table_to_markdown` alone.** Do not be discouraged by having only eight after completing L6; connecting the entry point takes the count to thirty-three.

## Where to look when something is wrong

| Symptom | Cause |
|---|---|
| cell count after collapse is **above the golden** | the empty-column check omitted `strip()`; `&nbsp;` remains and prevents empty columns from being removed |
| cell count after collapse is **below the golden** | text was copied during `colspan` expansion, or empty-row removal also deleted a header row |
| numbers appear twice | the text of a spanned cell was copied across the full range in L2 |
| every header is empty | the code is looking for `<th>`; this corpus contains zero |
| first data row was promoted to the header | `split_header` is failing to return `([], grid)` |
| markdown rendering breaks | `|` inside a cell was not escaped |
