# M1.3 Verification

## Completion Criteria

- Every body Block in the twenty filings has a valid span within the canonical source.
- The filing and every Chunk share the same `source_sha256`.
- The text body is an ordered subsequence of the cited source slice.
- Each renderable source table produces exactly one table chunk.
- Table-header tokens exist in the source, and data-row order is preserved.
- Every non-heading source body Block is consumed by exactly one chunk.
- Chunk spans do not overlap, follow source order, and have dense ordinals.
- Per-document and aggregate chunk counts match the golden baseline.
- Source-code blocks and constant values match local canonical files when present and the pinned `reference_revision` reference otherwise.

## Test Matrix

| File | Verification Target | Count |
|---|---|---:|
| `test_01_contract.py` | config, immutable schema, fail-closed span | 7 |
| `test_02_block_spans.py` | canonical reader, hash, Block round-trip | 5 |
| `test_03_text.py` | source identity, paragraph, source group/context, INTC corpus, order, overlap | 10 |
| `test_04_tables.py` | source table and chunk 1:1, span, row width | 4 |
| `test_05_roundtrip.py` | text/table provenance, bounds, exact-once | 4 |
| `test_06_golden.py` | per-document and aggregate corpus baseline | 2 |
| Total | M1.3 suite | 32 |

## Baseline

| Kind | Count |
|---|---:|
| text chunks | 8,083 |
| table chunks | 1,089 |
| all chunks | 9,172 |

## Commands

```bash
uv run pytest tests/chunk -q
uv run python scripts/check_doc_code.py
uv run ruff check --no-fix app tests scripts
uv run pytest -q
```

The top-level repository plan records the final full-suite result after the M1.4 tests are added. This document's fixed contract is the M1.3 suite with 32 passing tests and the twenty-document golden baseline.

## Visual Inspection

```bash
uv run python -m app.ingestion.chunk --doc NVDA-FY2024 --limit 3
uv run python -m app.ingestion.chunk --doc INTC-FY2022 --kind table --limit 2
```

- Are the context header and body separated by a blank line?
- Has the synthetic title been kept out of the body?
- Is the table chunk a complete Markdown table?
- Is the span a half-open interval within the source bounds?
- Do ordinals increase in output order?

## First Checks on Failure

| Symptom | First Check |
|---|---|
| Missing Block span | `read_source()`, `line_offsets()`, `block_source_spans()` |
| INTC overlap/context leakage | xref `source_group`, `source_heading`, `section_units()` reset |
| Table round-trip failure | M1.2 rowspan/colspan expansion and the source-table 1:1 policy |
| Source-hash mismatch | Check whether the file was read through a path other than the canonical reader |
| Incorrect ordinal order | `chunk_filing()` stable span sort and renumbering |
| Golden-count change | Confirm that the policy change was intentional and update the findings and bugs documents together |

## Canonical Implementation Grading

```bash
uv run pytest tests/chunk -v
```

Run this command after each tutorial layer. Missing symbols may skip while implementation is in progress; completion requires all thirty-two tests to pass from `app/ingestion/chunk.py`.
