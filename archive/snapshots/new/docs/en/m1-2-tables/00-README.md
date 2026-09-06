# M1.2 Overview — SEC table HTML → markdown

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

> Input: M1.1 `Block(kind="table").html` Output: a markdown string for retrieval Status: twenty filings, 1 thousand two hundred table Blocks, thirty-three tests

## In one sentence

**A pure transformer that removes physical layout columns from SEC tables and produces markdown while preserving the meaning of numbers, rows, and headers.**

## Pipeline

1. Expand `rowspan` and `colspan` into a dense grid. 2. Remove rows and columns that contain no content. 3. Merge dedicated `$` and `%` columns into value columns in reading order. 4. Infer leading header rows by shape even without `<th>`. 5. Escape pipes and serialize rectangular markdown.

## Reading order

| Order | Document | Purpose |
|---|---|---|
| 1 | [01-findings.md](01-findings.md) | corpus measurements and design rationale |
| 2 | [02-spec.md](02-spec.md) | inputs, outputs, invariants, and non-goals |
| 3 | [03-build.md](03-build.md) | L1~L7 implementation order and real code |
| 4 | [04-bugs.md](04-bugs.md) | failure causes and regression prevention |
| 5 | [05-verify.md](05-verify.md) | tests, golden values, and manual checks |

## Quick verification

```bash
uv run pytest tests/ingestion/test_09_tables.py -q
uv run python -m scripts.measure_tables
uv run python -m app.ingestion.tables --doc NVDA-FY2024
uv run pytest tests/ingestion/test_09_tables.py -v
```

## Final decisions

- Do not change `Block.text`. Keep parser coverage separate from table rendering.
- Preserve parenthesized negatives exactly as written in the source.
- Reduce layout-only tables to an empty string.
- M1.3_ preserves the table markdown as one source-cited chunk.
- `scripts/measure_tables.py` owns measurement regeneration; `tests/ingestion/golden.py` owns the regression baseline.
