# M1.4 Overview — Idempotent PostgreSQL seed

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

M1.4 converts all 20 parsed SEC filings and their M1.3 chunks into validated database records, then persists the corpus with deterministic PostgreSQL upserts. The operation is atomic and safe to rerun. It does not create embeddings.

## One-sentence contract

`manifest -> ParsedFiling -> Chunk -> validated records -> one PostgreSQL transaction`

The document row fixes the immutable source snapshot and preserves parser/item status metadata, including xref-only evidence such as `Not applicable`. Each chunk row preserves the source evidence, synthetic retrieval context, combined indexed text, and half-open source span.

## Persisted boundary

| Value | Meaning |
|---|---|
| `body` | Source-derived evidence that may be cited |
| `context_header` | Synthetic filing, Item, and heading context |
| `index_text` | `context_header + "\n\n" + body`, or `body` when context is empty |
| `content` | ORM compatibility alias for `index_text`; it is not a second column |
| `[start_char, end_char)` | Python character coordinates into the canonical decoded source |
| `source_sha256` | Identity of the exact source snapshot that owns the coordinates |
| `parse_status` | Document-level parser validation result |
| `item_index` | Original xref entries, including per-Item status and reference source |
| `content_tsv` | PostgreSQL-generated English search vector over `index_text` |
| `embedding` | Nullable M2 field; M1.4 never generates one |

## Rerun behavior

- Documents conflict on `doc_id` and update all persisted metadata.
- Chunks conflict on `(doc_id, ordinal)` and update content plus provenance.
- Dense ordinals are validated before any transaction opens.
- Stale trailing ordinals are deleted inside the same transaction.
- An existing embedding is preserved only when `index_text` is unchanged. A text change sets the embedding to `NULL`, preventing M2 from serving a stale vector.
- Any statement failure rolls back the entire corpus batch.

## Reading order

1. [Measured findings](01-findings.md) 2. [Normative specification](02-spec.md) 3. [Layer-by-layer build guide](03-build.md) 4. [Bugs and design traps](04-bugs.md) 5. [Verification evidence](05-verify.md)

## Quick start

Run the focused tests without requiring PostgreSQL:

```bash
uv run pytest tests/db -q
```

Start PostgreSQL through the repository's environment, then rerun the same command to activate the optional integration test. Seed a fresh schema with:

```bash
uv run python -m app.ingestion.seed --create-schema
```

`--create-schema` creates missing tables only. It is not a schema migration tool and does not alter an older table definition.

Rerun the same canonical command after each tutorial layer. Missing seed-layer symbols skip cleanly until implemented. Model tests still pass because the shared M1.4 schema is the fixed input to the exercise.

## Ownership boundary

M1.3 owns parsing, chunk bodies, retrieval context, and source coordinates. M1.4 validates and persists those values. M2 owns embedding generation and repopulates only rows whose embedding is null. This milestone does not import an embedding provider or make a model request.
