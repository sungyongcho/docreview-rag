# M1.4 Spec

## 1. Scope

M1.4 shall convert the repository's parsed 20-filing corpus and all current M1.3 chunks to PostgreSQL rows. It shall persist source provenance, document metadata, retrieval text, and table kind with deterministic rerun behavior.

M1.4 shall not generate embeddings, select an embedding model, call an embedding provider, or implement retrieval.

## 2. Document schema

`documents.doc_id` is the primary key. Each row shall contain:

- `ticker`, numeric `cik`, `fiscal_year`, `form`
- `filing_date`, `report_period`, `accession`, and source `url`
- `parse_status`, restricted to `parsed` or `needs_profile_update`
- `item_index` JSON containing original xref entries, per-Item status, and reference source
- positive `source_length`
- a 64-character lowercase hexadecimal `source_sha256`

The hash identifies the exact source snapshot. The length bounds chunk coordinates in the canonical decoded Python string; coordinates are not UTF-8 byte offsets.

`item_index` may be empty for heading-based filings. For xref filings it is the evidence for Items whose status is `empty_disclosure` or `incorporated_by_reference` and therefore have no source body from which M1.3 could create a chunk.

## 3. Chunk schema

`chunks.id` is a surrogate primary key. `(doc_id, ordinal)` is the deterministic upsert key. Each row shall contain:

- nullable SEC `item`
- `kind`, restricted to `text` or `table`
- nonnegative, dense `ordinal`
- nonempty source-derived `body`
- possibly empty synthetic `context_header`
- `index_text`, equal to the M1.3 chunk `content`
- `start_char`, `end_char`, and `source_sha256`
- human-readable `citation`
- nullable `embedding`
- generated `content_tsv` over `index_text`

The span is half-open and shall satisfy `0 <= start_char < end_char <= documents.source_length`. The chunk hash shall equal its document hash. `content` is an ORM alias for `index_text`, not a duplicated database column.

## 4. Deterministic record conversion

For a fixed manifest, parser implementation, chunk implementation, and source snapshot, record conversion shall produce equal immutable records in equal order.

Preparation shall:

1. validate the expected manifest count before parsing; 2. sort manifest entries by ticker and report date; 3. parse and chunk every entry; 4. validate document metadata and source identity; 5. validate every chunk against its document; 6. sort documents by `doc_id` and chunks by `(doc_id, ordinal)`; and 7. reject duplicate documents, unknown chunk documents, duplicate keys, or sparse ordinals.

No database transaction shall be open during preparation.

## 5. PostgreSQL upserts

The document statement shall use:

```sql
ON CONFLICT (doc_id) DO UPDATE
```

The chunk statement shall use:

```sql
ON CONFLICT (doc_id, ordinal) DO UPDATE
```

Both statements shall update every mutable persisted input field. The chunk insert and record dictionaries shall omit `embedding` and `content_tsv`: embedding is not produced in M1.4, and PostgreSQL computes the search vector.

The embedding conflict assignment shall obey this truth table:

| Stored `index_text` equals new `index_text` | Resulting embedding |
|---|---|
| yes | preserve the stored value, including `NULL` |
| no | set to `NULL` |

This is a cache-invalidation boundary between M1.4 and M2. M2 may fill null embeddings after the seed transaction commits.

## 6. Transaction semantics

`persist_seed_batch()` owns one transaction over the complete batch. Callers shall provide an `AsyncSession` with no active transaction. The operation order is:

1. upsert all document rows; 2. upsert chunk rows in bounded batches; 3. remove stale trailing ordinals for every included document; and 4. commit on clean context exit.

Any validation, SQL, connection, or constraint error shall escape and cause rollback. The function shall never call `commit()` or `rollback()` outside the transaction context.

An empty document batch is valid and performs no writes. A nonpositive chunk batch size is invalid.

## 7. Stale-row policy

Because ordinals are validated as dense from zero, the current valid set for a document is `[0, chunk_count)`. After upsert, rows with `ordinal >= chunk_count` shall be deleted for that document. Rows belonging to documents absent from the input batch are outside the operation's scope and shall not be deleted.

## 8. Schema lifecycle

The command may call SQLAlchemy `create_all` when `--create-schema` is explicit. This may create missing tables and indexes, but it shall not be presented as a migration mechanism. An installation with an older schema must use a reviewed migration or a fresh disposable database.

## 9. Completion gates

- Exactly 20 prepared document records match the golden document identities.
- Prepared chunk totals match the current M1.3 golden data, including table chunks.
- Model, conversion, statement, transaction, and canonical-package tests pass without a DB.
- The optional PostgreSQL test skips cleanly when unavailable.
- When PostgreSQL is available, two identical writes keep row counts stable.
- Same-text reruns preserve an existing embedding; changed text clears it.
- Ruff passes on every M1.4 Python file.
