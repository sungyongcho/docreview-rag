# M1.3 Overview — Structure-Aware Chunking and Source-Stable Citations

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

> Input: M1.1 `ParsedFiling` + M1.2 table Markdown converter Output: A list of searchable, storable `Chunk` objects Core principle: Citations use immutable source `[start_char, end_char)` coordinates and `source_sha256`, not chunk IDs.

## In One Sentence

**Convert text and tables into retrieval units without violating Section/Block structure, while separating synthetic retrieval context from source-derived content so every result resolves to the exact 10-K source snapshot.**

## Pipeline

1. The parser records the source snapshot length and SHA-256, along with a half-open span for each Block. 2. Text is grouped by paragraph without crossing Item, narrative heading, contiguous source group, or table boundaries. 3. Because row-level provenance is unavailable, each source table produces exactly one table chunk. 4. Filing, Item, and title metadata appear only in `context_header`, separate from the source-derived `body`. 5. Chunks are sorted by source span and then assigned dense ordinals. 6. M1.4_ stores `body`, `context_header`, and `index_text` separately for provenance and indexing, and exposes `content` only as an ORM alias for `index_text`.

## Reading Order

| Order | Document | Question Answered |
|---|---|---|
| 1 | [01-findings.md](01-findings.md) | Which boundaries and failure modes appeared in the real corpus? |
| 2 | [02-spec.md](02-spec.md) | What is the completion contract for `Chunk` and citations? |
| 3 | [03-build.md](03-build.md) | In what layer order should the implementation and verification proceed? |
| 4 | [04-bugs.md](04-bugs.md) | Which provenance bugs were prevented during implementation? |
| 5 | [05-verify.md](05-verify.md) | Which tests prove completion? |

## Quick Verification

```bash
uv run pytest tests/chunk -q
uv run python -m app.ingestion.chunk --doc NVDA-FY2024 --limit 3
```

## Responsibility Boundaries

- M1.1: Produces Items, Blocks, source snapshots, and coordinates.
- M1.2: Converts source table HTML into a Markdown body.
- M1.3: Produces retrieval units, retrieval context, and citation spans.
- M1.4: Stores documents and chunks idempotently in PostgreSQL.
- M3: Selects the chunk target and retrieval quality through ablation studies.

M1.3_ is complete when the **architecture preserves source citations across configuration changes**, not when it reaches a specific chunk size.
