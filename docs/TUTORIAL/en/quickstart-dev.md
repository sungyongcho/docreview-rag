# Quick Start — DEV ONLY

This guide prepares filings and search indexes in a running local DEV instance. First complete [Environment setup](environment.md#qs-setup) and open Build. No downloaded filings, database rows, chunks, or embeddings are assumed; the tracked manifest alone does not mean a source is on disk.

Choose CLI or Web for the same seven preparation steps. Switching tabs does not execute work. Service readiness and data readiness are separate; reuse anything already complete in the same environment.

### SCREENSHOT NEEDED
<!-- Feature: DEV Quick Start document split; locale=en; light mode; show Quick Start — DEV ONLY title and wrench, Environment setup prerequisite link, and keyboard-operable CLI/Web tabs with the selected checkpoint. Existing step captures are retained and do not prove this new document header. -->

<!-- quickstart-cli -->

## CLI {#qs-cli}

### 1. Verify the empty environment {#qs-cli-1}

Run from the cloned repository. Confirm prompted operations and wait for each job before the next command.

```bash
rag-corpus inspect
rag-corpus readiness
```

**Complete when:** API responds; database is connected; schema is compatible; writable is true. A genuinely empty test database has zero documents and chunks.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 2. Download NVIDIA SEC FY2024 {#qs-cli-2}

Run from the cloned repository. Confirm prompted operations and wait for each job before the next command.

```bash
rag-corpus acquire_edgar --identifier NVDA --year 2024
rag-corpus status
```

**Complete when:** One NVIDIA FY2024 report is available. The job reports `manifest.json` and selection `sec-08b5f645cc174083`, which identifies exactly this report.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 3. Download Samsung DART FY2024 {#qs-cli-3}

Run from the cloned repository. Confirm prompted operations and wait for each job before the next command.

```bash
rag-corpus acquire_dart --identifier 005930 --year 2024
rag-corpus status
```

**Complete when:** One Samsung FY2024 report is available. The job reports `manifest.json` and selection `dart-1a4f24de25a92617`. Fiscal year 2024 normally refers to an annual report filed in 2025.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 4. Parse, chunk, and store both reports {#qs-cli-4}

Run from the cloned repository. Confirm prompted operations and wait for each job before the next command.

```bash
rag-corpus inspect
rag-corpus ingest_manifest --manifest manifest.json --selection sec-08b5f645cc174083 --expected-documents 1
rag-corpus status
rag-corpus ingest_manifest --manifest manifest.json --selection dart-1a4f24de25a92617 --expected-documents 1
rag-corpus status
```

**Complete when:** Both selected sources ingest successfully. The database contains the two target reports with nonzero chunk counts. Inspect a chunk and its source identity rather than expecting a fixed chunk total.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 5. Generate OpenAI embeddings {#qs-cli-5}

Run from the cloned repository. Confirm prompted operations and wait for each job before the next command.

```bash
rag-corpus inspect
rag-corpus backfill_embeddings
rag-corpus status
```

**Complete when:** Job succeeded; pending_embeddings is zero; both reports have embeddings produced by the configured OpenAI model. Matching dimensions alone do not prove matching model identity.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 6. Build the BM25 index {#qs-cli-6}

Run from the cloned repository. Confirm prompted operations and wait for each job before the next command.

```bash
rag-corpus rebuild_bm25
rag-corpus status
```

**Complete when:** Job succeeded, progress is complete, and bm25_ready is true. A successful download or embedding job alone does not establish BM25 readiness.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 7. Confirm readiness before asking {#qs-cli-7}

Run from the cloned repository. Confirm prompted operations and wait for each job before the next command.

```bash
rag-corpus inspect
rag-corpus readiness
```

**Complete when:** Data and index preparation are complete. Model configuration is present, but an answer call and answer quality have not been tested.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

<!-- quickstart-web -->

## Web {#qs-web}

### 1. Verify the empty environment {#qs-web-1}

Open **System → System status** and click **Refresh**. Confirm DEV, database connection, compatible schema, and OpenAI embedding configuration. An empty corpus is expected.

<!-- capture:quickstart-01-en -->

![A fresh DEV environment with a compatible schema and zero documents/chunks.](../assets/quickstart/01-empty.en.png)

*A fresh DEV environment with a compatible schema and zero documents/chunks.*

**Complete when:** API responds; database is connected; schema is compatible; writable is true. A genuinely empty test database has zero documents and chunks.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 2. Download NVIDIA SEC FY2024 {#qs-web-2}

Open **Build → Pipeline → Filings** and use **Clear selection** to limit this exercise. In **Search/add company or year**, search for `NVDA`, choose NVIDIA, then check `2024`. An on-disk pair enters the selection immediately; a missing pair appears under **To be added**. Confirm that only the intended pair is pending, choose **Sync selection**, and wait for success in **Build → Jobs**.

### SCREENSHOT NEEDED
<!-- Feature: current filings-matrix-and-exact-year-selection; locale=en; light mode; show the exact controls and selected report pairs described above. Existing acquisition/ingest captures remain historical evidence; preserve assets. -->

<!-- capture:quickstart-02-en -->

![The real NVDA FY2024 acquisition completed and recorded its source selection.](../assets/quickstart/02-sec.en.png)

*The real NVDA FY2024 acquisition completed and recorded its source selection.*

**Complete when:** One NVIDIA FY2024 report is available. The job reports `manifest.json` and selection `sec-08b5f645cc174083`, which identifies exactly this report.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 3. Download Samsung DART FY2024 {#qs-web-3}

Return to **Filings** and keep the downloaded NVIDIA pair selected. Use **Change company**, then **Search/add company or year** to choose `005930` and check `2024`. Confirm **To be added** lists only the missing Samsung pair, choose **Sync selection**, and wait for its DART job in **Jobs**. Ready pairs remain selected without another download.

### SCREENSHOT NEEDED
<!-- Feature: current filings-matrix-and-exact-year-selection; locale=en; light mode; show the exact controls and selected report pairs described above. Existing acquisition/ingest captures remain historical evidence; preserve assets. -->

DART first downloads its issuer-code index. This endpoint can be slow: watch the byte progress in Jobs and do not submit another download while it is running.

<!-- capture:quickstart-03-en -->

![Samsung 005930 and fiscal year 2024 selected before acquisition.](../assets/quickstart/03-dart-input.en.png)

*Samsung 005930 and fiscal year 2024 selected before acquisition.*

![Samsung FY2024 acquisition succeeded and recorded its source selection.](../assets/quickstart/03-dart.en.png)

*Samsung FY2024 acquisition succeeded and recorded its source selection.*

**Complete when:** One Samsung FY2024 report is available. The job reports `manifest.json` and selection `dart-1a4f24de25a92617`. Fiscal year 2024 normally refers to an annual report filed in 2025.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 4. Parse, chunk, and store both reports {#qs-web-4}

After each download completes, preparation state refreshes automatically. Open **Parse & chunk**, confirm that both intended downloaded reports appear under **Selected documents**, and choose **Parse & chunk selected sources** once. Wait for the ingest job to succeed. For manual per-selection ingestion, open **Advanced**, find the two selections under `manifest.json` (`sec-08b5f645cc174083` for NVIDIA and `dart-1a4f24de25a92617` for Samsung), verify their sources, and use **Ingest** for each instead of also running the primary action.

### SCREENSHOT NEEDED
<!-- Feature: current shared-parse-action-and-manual-advanced-alternative; locale=en; light mode; show the exact controls and selected report pairs described above. Existing acquisition/ingest captures remain historical evidence; preserve assets. -->

The catalog can describe other reports. The selected document and source counts determine completion for this exercise.

<!-- capture:quickstart-04-en -->

![Both reports are parsed and retain their source identities; embeddings are not yet generated.](../assets/quickstart/04-chunks.en.png)

*Both reports are parsed and retain their source identities; embeddings are not yet generated.*

![A real Samsung chunk retains its original text, source character offsets, and SHA-256.](../assets/quickstart/04-chunk-detail.en.png)

*A real Samsung chunk retains its original text, source character offsets, and SHA-256.*

**Complete when:** Both selected sources ingest successfully. The database contains the two target reports with nonzero chunk counts. Inspect a chunk and its source identity rather than expecting a fixed chunk total.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 5. Generate OpenAI embeddings {#qs-web-5}

Choose **Embeddings**. Verify the OpenAI provider and pending chunk count. Review the cost notice, then run the embedding action. Follow **Jobs** until success; the call covers all pending chunks in this database.

<!-- capture:quickstart-05-en -->

![The embedding job completed for the two selected reports.](../assets/quickstart/05-embeddings.en.png)

**Complete when:** Job succeeded; pending_embeddings is zero; both reports have embeddings produced by the configured OpenAI model. Matching dimensions alone do not prove matching model identity.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 6. Build the BM25 index {#qs-web-6}

Choose **BM25** and run its build action. Wait for success in **Jobs**. This indexes the parsed text; it does not generate an answer.

<!-- capture:quickstart-06-en -->

![The real BM25 rebuild succeeded for all parsed chunks from both reports. This index is independent of embedding generation.](../assets/quickstart/06-bm25.en.png)

*The real BM25 rebuild succeeded for all parsed chunks from both reports. This index is independent of embedding generation.*

**Complete when:** Job succeeded, progress is complete, and bm25_ready is true. A successful download or embedding job alone does not establish BM25 readiness.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

### 7. Confirm readiness before asking {#qs-web-7}

Open **System status** and **Build → Documents**. Verify both reports have chunks, embedding coverage is complete, and BM25 is ready. Confirm the OpenAI answer engine is configured. Do not submit a question yet.

<!-- capture:quickstart-07-en -->

![The runtime reports that document preparation and indexes are ready.](../assets/quickstart/07-ready.en.png)

![Both reports have complete embedding coverage.](../assets/quickstart/07-documents.en.png)

**Complete when:** Data and index preparation are complete. Model configuration is present, but an answer call and answer quality have not been tested.

**If blocked:** inspect the job error in Jobs or `rag-corpus status`; correct credentials, missing sources, or provider configuration before retrying. See [troubleshooting](troubleshooting.md).

<!-- quickstart-end -->

## Ready for the next tutorial {#qs-next}

[Next: test retrieval and inspect evidence](retrieval.md#step-8)

No question or answer was executed in Quick Start. After inspecting retrieval evidence, continue to [the first answer](answers.md#step-9).

Parsing stores documents and chunks; it does not compute BM25. In Build step 4, use **Compute BM25**
for the first run or **Recompute BM25** after a recorded run. Complete this explicit job after chunk
changes before asking with Balanced/hybrid. Hybrid also requires zero pending embeddings.

### SCREENSHOT NEEDED
<!-- Feature: explicit first BM25 computation after both report ingests and hybrid Ask blocked until embeddings and BM25 finish; locale=en; light mode; preserve existing assets. -->
