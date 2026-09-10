# Turn sources into searchable evidence

## Published pipeline statistics

PROD shows actual chunk and embedding counts for the selected published documents. Loading, an empty catalog and a failed listing are distinct states, never sample results. BM25 keyword statistics are computed over the server corpus by language; scope selection restricts candidates without rebuilding those statistics. Existing evaluation results and snapshot comparisons keep their original scope.


When verified downloaded originals outnumber ingested documents in a registry, Parse & chunk retains completion for existing data and displays **Complete · new originals available**. Select the new originals to process them. Running jobs still show their actual progress; the additional-source notice clears after the current counts agree.

## Return from terminal preparation

When a prerequisite needs terminal work, the selected preparation step displays its diagnosis, terminal instructions, a copyable command and the expected result. Complete that command in this checkout, return to the same step, and click **Check updated status**. Continue only when the reported prerequisite has actually changed; the refresh button does not execute setup or fabricate completion.

Schema checking is read-only. Empty-schema preparation preserves existing databases and refuses incompatible schemas. Unarchived historical jobs remain visible in the unified Jobs view; an old ingestion request without a selection ID cannot be retried. Start a new ingestion from a current manifest selection instead.


The terminal panel is compact and collapsible. It opens for a prerequisite blocking the selected step. Source acquisition can remain available while indexing needs schema recovery; open setup checks to inspect that separate condition. Company and year suggestions open directly below their input and may temporarily cover hints or quick-add controls.

Every pipeline stage can be inspected: Filings, Parse & chunk, Embeddings, BM25, Ask, Answer model, and Evaluate. The diagnosis distinguishes ready to run, already complete, blocked, running/queued, and unknown/checking. Missing sources lead to Filings; missing chunks lead to Parse & chunk; missing indexes or answer configuration lead to their own stage. An unknown response is not success. **Go to prerequisite step** opens the relevant step without starting it; use that step’s compact terminal panel and recheck when needed.

### SCREENSHOT NEEDED
<!-- feature=schema-and-terminal-handoff-recheck; mode=dev; locale=en; theme=light; state=blocked-and-resolved-prerequisite-states; expected-evidence=diagnosis-copyable-command-check-updated-status-control-and-recorded-result -->

> [!DEV]
> Ingestion, embedding backfill, and BM25 rebuilds run in DEV mode only. Reading an existing readiness indicator does not perform those operations.

Parsing creates documents and citable chunks. Embeddings support semantic matching; BM25 supplies
lexical statistics. The two index paths can be prepared independently after chunking. A green connection
indicator is not proof that either index matches the current corpus.

## 5. Parse and create chunks {#step-5}

> [!GOAL]
> Store the explicitly selected reports as searchable, traceable chunks.
>
> **Prerequisites** compatible DB/schema and every required source file from [acquisition](acquisition.md#step-4) · **Done** the job succeeds, the expected document identity is present, and its chunk count is positive.

Open **Build → Pipeline → Parse & chunk → Selected documents**. Review the compact SEC/DART → company → year summary carried over from Filings; the header counts documents, ready/missing sources, companies and fiscal years. The visible **Change selection in Filings** button and a removed year update both steps because they share the same selection.

1. Select **Parse & chunk selected sources** once for the entire current selection. Selected filing IDs are verified as a complete set before queueing, and the queue pins immutable source inputs, so later deletion or reacquisition in Filings does not alter an existing job.
2. Watch the action bar replace the primary button with shared job progress and **Cancel** when supported. **Open Documents** shows the ingested report and **View all jobs** opens the job records.
3. Confirm that the job succeeded, the expected document identity is present, and its chunk count is positive. Missing or changed intended originals block new parsing until downloaded or explicitly reselected; missing-file or schema errors must be corrected in Jobs before retrying, and the database is never erased to resolve an unknown cause. See [troubleshooting](troubleshooting.md).
4. Continue to [prepare embeddings](#step-6), or skip it when the current embedding identity is already ready.

Each Ingest action processes only its explicit selection while the common catalog remains intact. The operation stores source-linked structures and chunks and leaves embeddings and BM25 to Build steps 3 and 4; changing chunks invalidates existing BM25 statistics. Reuse work already completed by CLI against this same DB.

## 6. Prepare embeddings {#step-6}

> [!GOAL]
> Prepare vectors produced by the intended embedding model.
>
> **Prerequisites** chunks exist and the selected embedding provider is configured and available · **Done** embeddings match the active provider/model identity and the pending count is zero.

Open **Build → Pipeline → Embeddings** and inspect the provider, model identity, dimensions, prepared count, and pending count. The tutorial's semantic path uses the configured OpenAI embeddings, so deterministic test vectors do not establish semantic quality; check the current policy in [CLI configuration](cli.md#installation-and-configuration).

1. Select **Backfill embeddings**, only when needed and after accepting its stated scope and cost. Jobs reports the backfill, so refresh readiness after it finishes.
2. Confirm that embeddings match the active provider/model identity and that the pending count is zero. Backfill covers missing or mismatched embeddings throughout the database, and the acquisition company/year selection does not limit this operation to that report.
3. If a provider failure, incompatible identity, or connection failure occurs, diagnose it separately using [runtime evidence](runtime.md) and [troubleshooting](troubleshooting.md) before trying again.
4. Continue by [verifying BM25](#step-7).

OpenAI backfill can incur cost; do not run it just to reproduce a screenshot or to make an already-ready stage green again.

The orange traffic-cone duration note below the cost notice is always visible in Build step 3, before, during, and after a run, for every provider. It is informational: clicking or using the keyboard does not activate it.

> Embedding a fresh clone, an enlarged corpus or an empty index can take a long time.

## 7. Prepare BM25 {#step-7}

> [!GOAL]
> Make keyword retrieval statistics agree with the current chunks.
>
> **Prerequisites** chunks exist; embeddings and an answer model are not required for this preparation · **Done** the explicit BM25 job succeeds and BM25 is ready for the current corpus.

Open **Build → Pipeline → Lexical index (BM25)** and inspect the current statistics and readiness state; there is no company selection for this rebuild.

1. Select **Compute BM25** for the first computation, or **Recompute BM25** when a previous computation is recorded. Run it after each parse/chunk operation, and note that manual recompute remains available when ready.
2. Confirm that the job completes and the BM25 readiness indicator updates; completion means the explicit BM25 job succeeded and BM25 is ready for the current corpus.
3. If database or schema errors appear, inspect the job result and see [troubleshooting](troubleshooting.md) before retrying.
4. Continue to [test retrieval](retrieval.md#step-8).

BM25 rebuilding does not call an answer model or OpenAI. Hybrid retrieval needs both its configured lanes, so read the readiness description to distinguish hybrid availability from vector-only availability. Retrieval evaluation depends on an index and evaluation dataset, not on generating an answer first.

## Continuing the Filings selection

The compact summary shows each company/year once; raw document IDs are in chip details rather
than primary labels. Large selections collapse to eight companies per registry with **Show all
companies**. Click a year to remove it from both steps. Missing sources explain why parsing is
disabled and must be downloaded in Filings first. The primary button carries the ready-document
count; Documents is secondary and Jobs is a tertiary action. **Advanced** is a styled disclosure
for manual manifest selections, without repeating the default count. Its individual Ingest actions
remain available independently of the default draft.

The primary action records one immutable manifest/selection reference for exactly the selected downloaded documents. Jobs and retries retain that reference even if you later change the draft. Missing files or unrequested company/year pairs are never silently dropped. **Advanced** retains existing manifest rows and per-selection **Ingest** controls; use it for a separately named selection rather than the default flow.

### SCREENSHOT NEEDED
<!-- feature=parse-chunk-compact-selection-summary; mode=dev; locale=en; theme=light; state=multi-company-selection-with-missing-sources-and-running-job; expected-evidence=header-totals-change-selection-primary-count-badge-missing-source-explanation-shared-progress-cancel-and-collapsed-advanced -->

## Job progress and evaluation queue {#job-progress}

The step card and running badge show reported overall job progress. The execution panel shows the
overall bar and current-stage bar separately, with their elapsed times. Overall completion uses stage
weights, not an estimate of time remaining, and reaches 100%
only on success. Single-unit schema, document-storage and BM25 stages show an indeterminate bar while
running. Current-item counts appear only when the server reports them; legacy jobs do not invent overall progress.

Quick evaluation can wait behind queued or running corpus preparation when every missing index has
its preparation job queued. A toast names the work it waits for; the Jobs record retains the waiting
message. Submitting the same active evaluation shows an existing-queue notice and **Open Jobs**.
Database, schema, write-access and missing-index blockers remain visible next to the disabled action.
A missing BM25 index requires step 4; queueing an evaluation never computes it automatically.

### SCREENSHOT NEEDED
<!-- feature=bm25-and-evaluation-progress; mode=dev; locale=en; theme=light; state=explicit-bm25-recompute-and-evaluation-waiting-states; expected-evidence=compute-recompute-actions-overall-and-current-stage-progress-indeterminate-schema-stage-and-evaluation-waiting-notices -->

## Answer model (Build step 6)

Build shows separate **OpenAI** and **Local** rows. Green means ready to answer, amber means configured with a limitation (missing key, unloaded model, slow CPU below 15 tok/s, or a server problem), and grey means not configured. The step is complete when at least one visible engine is green; both lights also appear on the flow map. Each row names its current model; OpenAI shows the key slot and Local shows the server protocol, reported CPU/GPU placement and last measured generation speed. Missing placement or timing is labelled unknown/unmeasured. CPU measurements expire after 15 minutes and are shown only while the measured model is loaded.

Use **Open System status** for OpenAI or **Open Local LLM settings** to connect a server. Select a model beside the conversation input. The composer uses the same lights and reason tooltips; amber choices remain selectable, while the existing request validation still explains unavailable models or connections. A fresh start refreshes the preserved Ollama inventory through normal status polling. If the models volume was removed, the local row reports **Model download required** once the empty server is reachable.

Step 2 keeps physical missing-file counts separate from **Needs repair**. DART requires both the current XML and its matching ZIP. If either current file is missing or damaged, download the same filing again before parsing. All selected missing or blocked filings show their exact diagnostic, including duplicate registrations and unsupported paths that require explicit cleanup or reset.

### Updating while using the local web app

Parsing/chunking, embedding, and BM25 jobs wait for active questions to finish before
changing search data. New questions pause during that interval; the composer keeps
your draft and shows a short update notice. Downloading originals alone does not
pause search. Each live retrieval reads its readiness checks and candidate lists
from one repeatable-read database transaction.

After an update, the server checks the selected retrieval strategy before calling
an embedding model: vector search needs current embeddings; BM25 search needs
current keyword statistics; hybrid BM25 search needs both. Complete the indicated
pipeline step before retrying. There is no new database snapshot selector.

This coordination covers the single-process web API and its corpus jobs. Run
standalone ingestion/indexing CLI commands while web questions are stopped; those
separate processes do not participate in the web job admission gate.

During web updates, the header beside Notifications shows a blue animated search-pause indicator. Hover or focus to read the job and reported percentage; click for details and View jobs. Missing percentages remain indeterminate. Job progress updates in place inside Notifications. A green check briefly confirms search readiness; orange means another preparation step is required and red indicates a failed update. The pipeline shows its status once beside the stage title.
