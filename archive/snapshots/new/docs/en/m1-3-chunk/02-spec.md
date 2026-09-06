# M1.3 Spec

## 1. Input Contract

`chunk_filing()` accepts the M1.1_ `ParsedFiling`. Without a positive `source_length` and a sixty-four-character lowercase hexadecimal `source_sha256`, the implementation cannot prove which immutable source snapshot a span belongs to, so it fails with `ValueError` instead of returning an empty result.

- Filing: `source_length`, `source_sha256`
- Block: `kind`, `text`, optional `html`
- Block provenance: `source_pos`, `end_pos`, `source_group`, `source_heading`

If any coordinate is missing, reversed, overlapping, or outside the document bounds, or if a chunk candidate crosses source groups, the implementation fails with `ValueError` instead of guessing.

## 2. Coordinate Contract

- The source is decoded directly from the exact bytes as UTF-8_, without universal-newline translation.
- `start_char` and `end_char` are Unicode code-point indexes into the decoded Python string.
- The interval `[start_char, end_char)` is half-open.
- `source_sha256` is the SHA-256_ of the exact source bytes.
- Citation identity is at least `(doc_id, source_sha256, start_char, end_char)`.

## 3. Output Contract

`Chunk` is an immutable value object.

| Field | Meaning |
|---|---|
| `doc_id` | Stable corpus document ID |
| `item` | SEC Item or `None` |
| `kind` | `text` or `table` |
| `ordinal` | Dense document order within the current materialization |
| `body` | Source-derived evidence |
| `context_header` | Synthetic retrieval context built from the filing, Item, and title |
| `citation` | Human-readable filing + Item label |
| `start_char`, `end_char` | Half-open interval in the canonical source |
| `source_sha256` | Source snapshot containing the coordinates |
| `content` | Computed `context_header + body` property used for indexing |

The ordinal changes when the document is re-chunked, so it is not a persistent citation key.

## 4. Text-Chunking Invariants

1. A chunk never crosses an Item, table, narrative heading, or `source_group` boundary. 2. A paragraph is never split internally. 3. A paragraph longer than the target remains one oversized chunk. 4. Each source body Block is consumed by exactly one text chunk. 5. The body tokens are an ordered subsequence of the visible tokens in the cited source slice. 6. A heading is passed to `context_header`, not copied into the body.

## 5. Table-Chunking Invariants

1. If M1.2 `table_to_markdown()` returns an empty value, the table is layout-only and is discarded. 2. Each renderable source table produces exactly one table chunk. 3. A table chunk's span exactly matches its source table's span. 4. The Markdown header tokens are contained in the source token multiset. 5. Data-row tokens retain their original order within the source. 6. Table rows are not split without row-level source coordinates.

## 6. Ordering and Overlap Invariants

- Results are in stable source order by `(start_char, end_char)`.
- Ordinals are `0..len(chunks)-1`.
- Distinct chunk spans do not overlap.
- Every non-heading source body Block is consumed by exactly one chunk.

## 7. Configuration and Failure Contract

| Input | Result |
|---|---|
| `target_text_chars <= 0` | `ValueError` |
| Missing or invalid source length/hash | `ValueError` |
| Missing, reversed, or overlapping Block span | `ValueError` |
| Mixed source groups | `ValueError` |
| Span beyond the document length | `ValueError` |
| Empty paragraph | No chunk |
| Layout-only table | No chunk |
| paragraph/table longer than the target | Oversized chunk that preserves boundaries |

## 8. Deferred to Later Milestones

- M1.4: document/chunk primary key, transaction, idempotent upsert
- M3: Optimal tokenizer-based text target and retrieval ablation
- Follow-up provenance work: Table-row source coordinates and safe row splitting
- M5/M6: Citation API and source viewer UI
