# Turn sources into searchable evidence

Parsing creates documents and citable chunks. Embeddings support semantic matching; BM25 supplies
lexical statistics. The two index paths can be prepared independently after chunking. A green connection
indicator is not proof that either index matches the current corpus.

## 5. Parse and create chunks {#step-5}

- **Goal:** store a chosen manifest's reports as searchable, traceable chunks.
- **Prerequisites:** compatible DB/schema and every required source file from [acquisition](acquisition.md#step-4).
- **Screen:** Build → Pipeline → Parse & chunk → Change….
- **Inputs:** select the manifest row whose source and document counts match the intended scope.
  For the one-filing exercise, prepare `tutorial-manifest.json` using the
  [CLI example](cli.md#prepare-one-nvidia-filing); its extraction block does not download or ingest.
- **Primary action:** **Ingest** on that manifest's row.
- **Visible result:** a job records progress and document/chunk counts; Documents shows the ingested report.
- **Completion:** the job succeeds, the expected document identity is present, and its chunk count is positive.
- **Recovery:** inspect missing-file or schema errors in Jobs. Correct that prerequisite before retrying;
  do not erase the database to resolve an unknown cause. See [troubleshooting](troubleshooting.md).
- **Next:** [prepare embeddings](#step-6), or skip it when the current embedding identity is already ready.

An Ingest row processes its whole manifest, including existing entries. Do not use **Ingest all manifests**
for a one-report exercise. The operation upserts documents and recomputes BM25; it does not fill missing
provider embeddings. Work already completed by CLI against this same DB should be reused.

## 6. Prepare embeddings {#step-6}

- **Goal:** prepare vectors produced by the intended embedding model.
- **Prerequisites:** chunks exist; the selected embedding provider is configured and available.
- **Screen:** Build → Pipeline → Embeddings.
- **Inputs:** inspect provider, model identity, dimensions, prepared count, and pending count.
  The tutorial's semantic path uses the configured OpenAI embeddings; deterministic test vectors do not
  establish semantic quality. Check the current policy in [CLI configuration](cli.md#installation-and-configuration).
- **Primary action:** **Backfill embeddings**, only when needed and after accepting its stated scope and cost.
- **Visible result:** Jobs reports the backfill; refresh readiness after it finishes.
- **Completion:** embeddings match the active provider/model identity and the pending count is zero.
- **Recovery:** a provider failure, incompatible identity, or a connection failure needs its own diagnosis.
  Check [runtime evidence](runtime.md) and [troubleshooting](troubleshooting.md) before trying again.
- **Next:** [verify BM25](#step-7).

Backfill covers missing or mismatched embeddings throughout the database. The acquisition company/year
selection does not limit this operation to that report. OpenAI backfill can incur cost. Do not run it just
to reproduce a screenshot or to make an already-ready stage green again.

## 7. Prepare BM25 {#step-7}

- **Goal:** make keyword retrieval statistics agree with the current chunks.
- **Prerequisites:** chunks exist. Embeddings and an answer model are not required for this preparation.
- **Screen:** Build → Pipeline → Lexical index (BM25).
- **Inputs:** inspect the current statistics and readiness state; there is no company selection for this rebuild.
- **Primary action:** **Rebuild BM25**, only if statistics are missing or invalidated.
- **Visible result:** the job completes and the BM25 readiness indicator updates.
- **Completion:** BM25 is ready for the current corpus. If ingestion already refreshed it, inspection completes this step.
- **Recovery:** inspect database/schema errors and the job result; see [troubleshooting](troubleshooting.md).
- **Next:** [test retrieval](retrieval.md#step-8).

BM25 rebuilding does not call an answer model or OpenAI. Hybrid retrieval needs both its configured lanes;
read the readiness description to distinguish hybrid availability from vector-only availability.
Retrieval evaluation depends on an index and evaluation dataset, not on generating an answer first.
