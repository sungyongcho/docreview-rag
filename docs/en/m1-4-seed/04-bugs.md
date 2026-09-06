# M1.4 Bugs

Each entry records a symptom, root cause, fix, and regression guard.

## B01 — Reruns duplicated chunks

Status: fixed.

Symptom: inserting the same corpus twice could double chunk rows.

Root cause: a plain insert did not express the deterministic identity already present in the model.

Fix: use PostgreSQL conflict updates keyed by `(doc_id, ordinal)` and retain the named unique constraint.

Regression: `test_chunk_upsert_targets_doc_ordinal_and_never_writes_embeddings`.

## B02 — Rechunking left searchable ghost rows

Status: fixed.

Symptom: a document that changed from 500 chunks to 480 still had old rows 480 through 499.

Root cause: upsert updates existing keys and inserts new keys, but it cannot infer which old keys are no longer part of the input.

Fix: require dense ordinals and delete `ordinal >= current_count` inside the same transaction.

Regression: the transaction statement-count test and PostgreSQL count check.

## B03 — Synthetic context became indistinguishable from evidence

Status: fixed.

Symptom: a downstream citation could not tell whether a sentence came from the filing or from a repeated retrieval header.

Root cause: the old schema stored only one combined `content` value.

Fix: persist `body`, `context_header`, and `index_text`; keep `content` as an alias only.

Regression: `test_filing_records_keep_body_context_index_text_and_metadata`.

## B04 — Source spans could outlive their snapshot

Status: fixed.

Symptom: a valid-looking offset could be applied to replaced source bytes.

Root cause: document rows did not identify source length or hash.

Fix: persist source length and SHA-256 on documents, repeat the hash on chunks, and validate the relationship before writing.

Regression: parameterized provenance failures in `test_02_records.py`.

## B05 — One bulk statement risked parameter overflow

Status: fixed.

Symptom: a full-corpus insert could exceed driver limits or allocate a very large SQL statement.

Root cause: thousands of rows were treated as one values clause.

Fix: issue deterministic chunk batches of 500 inside the corpus transaction.

Regression: `test_persist_seed_batch_owns_one_transaction_and_batches_chunks`.

## B06 — Failure after one document produced a partial corpus

Status: fixed.

Symptom: earlier rows could commit even when a later chunk statement failed.

Root cause: transaction ownership was implicit or per-document.

Fix: prepare first, then own one explicit transaction over documents, chunks, and stale-row cleanup. Reject sessions that already have a transaction.

Regression: rollback and nested-transaction tests in `test_03_upserts.py`.

## B07 — Text changed while an old embedding survived

Status: fixed after integration review.

Symptom: a conflict update replaced `index_text` but left an embedding calculated from the old text. Vector retrieval could return semantically stale results.

Root cause: omitting `embedding` from the update always preserves its stored value, even when the indexed input changes.

Fix: assign embedding with a PostgreSQL `CASE`: preserve it for equal `index_text`, otherwise set it to `NULL`. M1.4 still never generates a vector.

Regression: `test_chunk_upsert_invalidates_only_stale_embeddings` and the optional live PostgreSQL preservation/invalidation exercise.

## B08 — Schema creation was mistaken for migration

Status: documented limitation.

Symptom: `create_all` against a database containing the old tables would leave missing columns unchanged.

Root cause: SQLAlchemy metadata creation is additive for missing tables, not an alteration planner.

Fix: make schema creation opt-in and describe it as fresh-schema bootstrap only. Use a reviewed migration or disposable reset for an existing schema.

Regression: command help and this documented boundary.
