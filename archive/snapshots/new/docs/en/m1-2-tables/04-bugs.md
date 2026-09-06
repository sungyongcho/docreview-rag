# M1.2 Bugs

## B01. Copied colspan text into every position

**Symptom:** numbers and labels repeated across the span width, contaminating retrieval text. **Cause:** the original cell text was copied into every occupied position in the dense grid. **Fix:** keep text only in the top-left position and occupy the rest with empty strings. **Regression tests:** `test_rowspan_carries_down_without_duplicating_text`, `test_colspan_keeps_text_in_first_cell_only`.

## B02. Trusted raw row lengths

**Symptom:** the L3 column scan failed with `IndexError` on ragged tables. **Cause:** SEC layouts with different declared row widths were treated as rectangular data. **Fix:** pad every grid row to the maximum width across all occupied coordinates. **Regression test:** `test_grid_is_rectangular`.

## B03. Used `<th>` as the header condition

**Symptom:** every table was treated as a body without a header. **Cause:** generic web-table assumptions were applied even though the entire corpus has zero `<th>` elements. **Fix:** infer headers from the shape of leading rows and return `([], grid)` when uncertain. **Regression tests:** three header tests.

## B04. Put table markdown into `Block.text`

**Symptom:** all twenty parser coverage golden values shifted. **Cause:** M1.1ʼs source visible-text metric and M1.2 retrieval rendering were mixed in one field. **Fix:** keep `tables.py` a pure HTML function and let M1.3ʼs chunker call it when needed. **Regression tests:** the complete existing M1.1 suite + M1.2 entry-point tests.

## B05. Converted parenthesized negatives to minus signs during ingestion

**Symptom:** markdown numbers differed from the filing's source notation. **Cause:** retrieval convenience took precedence over citation fidelity. **Fix:** preserve the parenthesized notation verbatim and defer normalization to the query side. **Regression test:** `test_parenthesized_negatives_survive_verbatim`.

## B06. The representative golden checked only the first five lines

**Symptom:** the representative test could pass even if rows after `Operating expenses` disappeared. **Cause:** it used `startswith()` against the full expected string. **Fix:** include everything through the final `Net income` row in the expected value and compare for equality. **Regression test:** `test_income_statement_renders_as_expected`.

## B07. Recorded L3 and L4 measurements as one value

**Symptom:** the documentation said L3 produced 66,575 cells, while the real L3 count was 69 thousand two hundred forty-one. **Cause:** only the final collapse was measured; the intermediate stage was not stored. **Fix:** make the measurement script report expanded, empty-axis-removed, and unit-folded counts separately. **Regression tool:** `scripts/measure_tables.py`.

## B08. A pipe inside a cell created a new column

**Symptom:** differing markdown row widths broke rendering. **Cause:** `|` in cell text was serialized unchanged. **Fix:** escape it as `\|` before constructing the row. **Regression tests:** `test_cell_pipes_are_escaped`, `test_markdown_rows_all_have_the_same_width`.
