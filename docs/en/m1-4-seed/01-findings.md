# M1.4 Findings

This file records the evidence that shaped the persistence design. Normative requirements live in [02-spec.md](02-spec.md), while implementation failures live in [04-bugs.md](04-bugs.md).

## F1 — The corpus is a fixed 20-document input

`data/corpus/manifest.json` contains four issuers across five filing years. M1.4 sorts the manifest by ticker and report date before parsing, then sorts records by `doc_id` and chunk ordinal. The seed command defaults to exactly 20 expected documents and fails before a database transaction if the manifest count differs.

Decision: corpus completeness is an input validation rule, not an eventual database count assertion after a partial write.

Regression: `tests/db/test_04_corpus.py` compares every prepared `doc_id` with `tests/db/golden.py`.

## F2 — M1.3 produces both narrative and table records

The M1.3 golden file is the authority for per-document `(total, text, table)` counts. M1.4 derives its aggregate goldens from that file instead of copying a second editable count. The current checked-in baseline is 9,172 chunks: 8,083 text and 1,089 table chunks.

Decision: the corpus preparation test proves that every M1.3 chunk becomes one M1.4 record and that table kind survives conversion.

Regression: `tests/db/test_04_corpus.py` checks each document and both kinds.

## F3 — Evidence and retrieval context have different trust levels

M1.3 exposes `body`, `context_header`, and computed `content`. Only `body` is source-derived evidence. Persisting only the combined value would prevent downstream code from separating citable text from synthetic context.

Decision: store both components plus `index_text`; expose `content` only as an ORM alias for the combined column.

Regression: `tests/db/test_02_records.py` checks all three values independently.

## F4 — Source coordinates require snapshot identity

A character span is meaningful only against the decoded source that produced it. Every document therefore stores `source_length` and `source_sha256`; every chunk repeats the hash and stores `start_char` plus `end_char`.

Decision: record conversion rejects malformed hashes, cross-document chunks, hash mismatch, empty bodies, non-dense ordinals, and spans outside the document length before opening a transaction.

Regression: `tests/db/test_02_records.py` exercises each fail-closed path.

## F5 — One giant chunk insert is not a production-safe default

The corpus contains thousands of chunks and each row has eleven explicit values. A single multi-value statement would approach driver or PostgreSQL parameter limits and create an unnecessarily large statement.

Decision: document rows use one small upsert, while chunk rows use deterministic batches of 500 by default. All batches remain inside one transaction.

Regression: `tests/db/test_03_upserts.py` forces a one-row batch size and verifies one begin, one commit, and all expected statements.

## F6 — Upsert alone does not remove obsolete rows

If a later deterministic chunking configuration produces fewer chunks, conflict updates do not touch old ordinals beyond the new maximum. Those rows would remain searchable even though they no longer belong to the current corpus.

Decision: after upserting dense current ordinals, delete every row whose ordinal is greater than or equal to the current count for that document. The delete is part of the same transaction.

Regression: the transaction test observes one cleanup statement per document; the optional PostgreSQL test proves stable counts across identical reruns.

## F7 — Indexed-text changes invalidate vectors

M1.4 does not calculate embeddings, but a rerun can encounter embeddings previously filled by M2. Preserving a vector after changing its source text would create silent semantic corruption.

Decision: the conflict update uses a PostgreSQL `CASE`. It keeps the stored embedding when old and excluded `index_text` are equal and sets it to `NULL` otherwise.

Regression: the compiled-statement test checks the `CASE`; the optional PostgreSQL test checks both preservation and invalidation against a temporary table.

## F8 — Transaction ownership must be unambiguous

Implicit commits or caller-owned nested transactions make partial-write behavior hard to reason about. Parsing inside a transaction would also hold database resources during the expensive corpus transformation.

Decision: preparation completes first. `persist_seed_batch()` requires an idle session and owns exactly one `session.begin()` context. Success commits; any exception rolls back all writes.

Regression: `tests/db/test_03_upserts.py` covers commit, rollback, and active-session rejection without a live database.
