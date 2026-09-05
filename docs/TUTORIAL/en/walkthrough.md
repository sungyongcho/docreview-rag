# From your first filing to a cited answer

Prepare NVIDIA filings, inspect retrieved evidence, and verify your first answer against the original report.
This walkthrough follows the actual screens of your local development environment.
The ASCII text logo identifies this interface as v2.

Data and runtime state prepared with `rag-dev` are also visible in the dashboard connected to that environment.
Check completed work in the dashboard and continue from there; do not repeat ingestion or embedding just to
switch between the terminal and the UI. Downloading source files and ingesting them into the DB are separate steps.

The default path uses **OpenAI embeddings and answers**. Downloads and ingestion do not call OpenAI.
Embedding, questions, and evaluations can incur charges. The screenshots were captured from the actual
local service on 2026-09-05. Both language editions share these Korean-interface images; click an image
on the website to open it at full size. The capture environment reuses 30 existing filings and prior runs,
so its counts differ from a fresh database. Its embedding provider is `deterministic`: a Done badge in
these images does not establish OpenAI readiness or semantic-search quality. Follow the OpenAI setup
and each **Screen check** in this guide.

Use the 한국어 / EN switch to change interface and documentation language. Stored questions, answers,
filings, and raw logs are not translated or rewritten. Code-card copy buttons copy the original code without
language labels or decorative prompts.

## 1. Open the development environment

**Purpose:** start with working tools, keys, and a local database.

For a first installation, complete [installation and configuration](cli.md#installation-and-configuration)
and [initial schema setup](cli.md#initial-schema-setup). Only these prerequisites require the terminal;
source acquisition and ingestion happen in the screens below. Keep and reuse an existing compatible database.

After [loading the project commands](cli.md#register-commands-and-open-help), start the services:

```bash
rag-dev up --build -d
```

Open [DocReview RAG](http://localhost:8000/docreview-rag-agent/). If `APP_PORT` differs, adjust the URL.
You do not need a separate port 3000 page. Reuse services that are already running.

**On screen:** confirm DEV mode, then open System → System status. Check API, DB, schema, and OpenAI
availability. Move to Build → Pipeline.

The pipeline combines a dependency graph and the selected step’s execution panel. The compact runtime
summary expands to show connection and schema details. Selecting a node opens its inputs, actions, and real job events;
it does not execute anything. Both embedding and BM25 readiness feed hybrid retrieval. When an index is
incomplete, check which retrieval lanes are available. Evaluation also requires a golden dataset. Graph
readiness is separate from the execution progress of an individual question. Server job events and terminal
CLI references are explicitly separate. Completed steps have a gently blinking green indicator; failed
steps use red. Reduced-motion preferences disable the animation. Color does not replace the status text.

**Screen check:** DEV mode and healthy API/DB connectivity, without schema errors. Connectivity does not
mean the corpus or embeddings are ready.

**Completion:** continue when the services and schema are ready. Otherwise use [diagnostics](cli.md#troubleshooting).

![System status with DEV mode, database, schema, and corpus readiness](../assets/01-system-status.jpg)

*System → System status. Check the connection and schema first. A model listed in policy is separate from the identity of stored vectors.*

![Pipeline connecting filings, chunks, embeddings, BM25, answers, and evaluation](../assets/02-pipeline.jpg)

*Build → Pipeline. Selecting a node opens its execution panel. Existing completed work can be reused.*

## 2. Check existing data

**Purpose:** reuse completed preparation and run only missing work.

**On screen:** refresh the pipeline. Read document/chunk counts, embedding provider, pending embeddings,
and BM25 readiness. Open Documents and look for `NVDA-FY2024`, the fiscal year ending January 28, 2024.

Documents and Jobs start with the full list. Select a row to inspect its details. When the content area
is narrower than 1100 px, details replace the list; use Back to documents or Back to jobs to return with
filters, selection, and list scroll position preserved. On wide screens, drag the divider or focus it and
use arrow keys (Shift for larger steps); double-click to restore the default. The list starts at 360 px,
can resize within 320–600 px while retaining at least 560 px for details, and remembers the chosen width.
Company labels pair actual codes with names from the manifests. Public Documents contains only published snapshot documents.

**Screen check:** verify document identity and a nonzero chunk count. Other issuers or years do not need to
be deleted. If the source, document, and current OpenAI embeddings are ready, skip the corresponding steps.
An embedding count alone does not verify the producing model identity.

**Completion:** identify the remaining work. CLI ingestion into the same DB appears here, even though a
CLI operation may not appear in Jobs because it did not use the web queue.

![NVDA-FY2024 document search, source information, 437 chunks, and embedding identity](../assets/03-document.jpg)

*Search for NVDA-FY2024 and select its row. These 437 captured vectors have a deterministic identity; verify OpenAI readiness separately in step 5.*

## 3. Download NVIDIA filings

**Purpose:** obtain actual SEC source files. This does not ingest them into the database.

**On screen:** select Filings. Its execution panel shows the expanded Change… inputs; enter:

| Input | Value |
|---|---|
| Registry | SEC EDGAR |
| Tickers / stock codes | `NVDA` |
| Fiscal years | `2024` |

Search an existing company by code or name and select it, or type a new ticker and press Enter. DART
accepts six-digit stock codes. Fiscal years become removable chips; you can enter a single year or
an ascending range such as `2023-2025`. For this exercise, keep only NVDA and 2024.

Run **Download missing filings**, inspect the task in Jobs, wait for `succeeded`, and refresh Pipeline.
A real SEC contact in `.env` is required.

**Scope:** the web action uses the main `manifest.json`. Fiscal years control discovery; existing NVDA entries
for other years may also be downloaded if their source files are missing. Do not interpret `2024` as a one-file
limit. For exactly one filing, use the [one-filing CLI example](cli.md#prepare-one-nvidia-filing) and check its
result here instead.

**Screen check:** job success, downloaded filing count, and source readiness. The global Filings stage can
remain incomplete when other companies in the main manifest have missing sources.

**Completion:** every source named by the manifest you will ingest must exist. CLI acquisition performs the
same source-preparation step; database storage happens next.

![SEC EDGAR acquisition form with NVDA and 2024 entered](../assets/04-sec-inputs.jpg)

*Filings → Change…. This captures configured inputs; no download was started for the screenshot.*

## 4. Ingest the source into documents and chunks

**Purpose:** parse the downloaded report, create citable chunks, and persist them.

**Before starting:** verify development services and schema. The main manifest contains companies besides
NVIDIA; do not ingest that entire manifest after downloading only NVDA.

Use the short [one-filing manifest preparation](cli.md#prepare-one-nvidia-filing) to create
`tutorial-manifest.json`. The Python block only extracts a list; it does not download or ingest anything.
Skip its download command when you already acquired the file in the web UI.

**On screen:** refresh Pipeline and select Parse & chunk. In its expanded Change… area, check the source and document
counts beside `tutorial-manifest.json`, then click **Ingest on that row**. Do not use Ingest all manifests for
this one-filing exercise. Wait for job success, then open Documents.

**Screen check:** `NVDA-FY2024` and a positive chunk count. The operation's document count refers to its
manifest; existing documents remain in the database.

**Completion:** proceed to embedding. Ingestion also recalculates BM25, but it does not fill OpenAI vectors.
The `app.cli ingest --manifest …` command performs this storage step too; do not repeat a completed CLI ingest.

![Per-manifest counts and individual Ingest buttons](../assets/05-manifest-ingest.jpg)

*Parse & chunk → Change…. This environment has two default manifests. For the one-filing exercise, create tutorial-manifest.json and use its own row here, not Ingest all manifests.*

![Status, progress, and result of an existing successful SEC ingestion job](../assets/08-jobs.jpg)

*An existing 21-filing SEC ingestion job is selected. Its scope differs from the one-filing exercise; read both status and the actual result message.*

## 5. Prepare embeddings and BM25

**Purpose:** enable semantic and lexical retrieval.

**Paid operation:** configure `EMBEDDING_PROVIDER=openai` and a valid development key. The current model
is `text-embedding-3-large` at 384 dimensions. Inspect provider and pending counts before running.
Backfill processes missing or mismatched embeddings **throughout the DB**, not just the selected filing.
Reuse current embeddings instead of running backfill twice.

**On screen:** select Embeddings and run **Backfill embeddings**. Wait for Jobs to succeed, then refresh
and verify zero pending embeddings. Next inspect Lexical index (BM25). Reuse ready statistics; only run
**Rebuild BM25** if they are missing or invalidated. BM25 rebuilding does not call OpenAI.

**Screen check:** current provider, ready embedding count, pending zero, and BM25 ready. These are readiness
checks, not proof that an evaluation has been completed.

**Completion:** proceed to retrieval inspection. The CLI `retrieve --provider openai --embed-missing …`
also backfills but then performs a query; the web backfill button only prepares embeddings.

![Embedding provider, prepared and pending counts, and the cost notice](../assets/06-embeddings.jpg)

*The capture shows deterministic with zero pending chunks. This is not OpenAI readiness. Apply the OpenAI configuration, check the current provider and pending count, then run only if needed.*

![BM25 ready state and rebuild action](../assets/07-bm25.jpg)

*Inspect readiness in the Lexical index (BM25) node. A ready index does not need another rebuild.*

## 6. Read evidence before generating an answer

**Purpose:** confirm that relevant evidence is retrieved.

**On screen:** open Measure → Search trial and enter:

```text
What drove NVIDIA data center revenue growth in fiscal 2024?
```

Choose Hybrid, BM25, `k=5`, and no reranker. Run **Preview retrieval**. OpenAI query embeddings can incur
cost. This does not require rebuilding the corpus.

**Screen check:** examine component rankings, document IDs, excerpts, and final ranks. Read whether the
retrieved NVIDIA text actually addresses the growth drivers.

**Completion:** move to the conversation when relevant evidence is present. Preview review is a separate
answer-model call; do not click it merely to inspect retrieval.

The CLI retrieval command also returns evidence, but Search trial has no equivalent input to `--doc-id`.
Its profile and any other documents in the DB can therefore produce different ranks and results.

![NVIDIA FY2024 retrieval question with hybrid, BM25, and k 5](../assets/09-retrieval-inputs.jpg)

*This is the retrieval form before execution; the right-hand area has no preview result yet. Preview retrieval and Preview answer are separate actions.*

## 7. Configure and ask your first question

**Purpose:** obtain an answer with verifiable source citations.

**On screen:** open a new conversation. Above the input, choose OpenAI as the answer engine and set the
corpus/filters to SEC and NVIDIA FY2024. The current OpenAI answer model is `gpt-5.6-terra`. Send:

```text
What drove NVIDIA's data center revenue growth in FY2024? Cite evidence from the filing.
```

Before sending, open **Settings details / request preview**. It opens a right-side drawer on desktop and
a full-screen dialog on mobile. Compare Balanced, Korean, Accuracy, and Custom presets there. The displayed differences come from the effective retrieval settings. Inspect the
filters, prompt composition, and request payload; retrieved evidence is only selected after execution begins.
This is a preview of the next request. The completed result records server-applied settings when available.
The ? controls beside corpus scope and presets work with hover, keyboard focus, or touch. Selecting
Custom opens the retrieval editor. Conversation filters offer actual companies, languages, report types,
and fiscal years within the selected SEC/DART scope; an empty selection leaves that field unrestricted.
With Auto, wait for **Server-confirmed scope** in execution progress to see the actual registry, company
codes, and years chosen by the server. Until that event arrives, the scope remains unconfirmed.

**Sending can incur embedding, translation, and answer-model costs.** Wait for the request to finish.
The exact answer wording is not deterministic.

**Screen check:** open citation cards and inspect document identity, fiscal year, and original excerpts.
Do not rely on the `SUPPORTED` badge alone. Verify that the evidence supports the asserted growth drivers.
Open **Execution summary** to follow five phases:

| Phase | What it checks |
|---|---|
| 1. Understand the question | Determine intent and filing scope. |
| 2. Retrieve evidence | Fetch candidate evidence from the prepared corpus. |
| 3. Select relevant evidence | Evaluate whether candidates support the question. |
| 4. Verify answer and citations | Check claims and citations against the sources. |
| 5. Prepare the result | Return the verified outcome. |

Green completion indicators require actual server events. Before an event arrives the interface waits;
a phase that did not run is never filled in as complete. Returning to an earlier phase resets later indicators.
Casual conversation does not use the retrieval phase list. **Stop request** interrupts the current request.
Open **Run trace** for its ID, usage, and failure category. Completed execution does not by itself mean that
the document evidence was sufficient.

**Execution performance** separates browser request time from server execution time. It shows recorded
stage durations, model calls and attempts, and provider token counts. When a local provider returns timing
data, model loading, input processing, generation, and generated tokens per second appear separately.
Missing measurements, including CPU/GPU placement, remain **Not collected**. The active phase and elapsed
time follow real events; there is no estimated completion time. Older saved runs can lack these fields.
No live Gemma timing measurement was performed for this guide.

**Completion:** the first exercise is complete when the answer is supported by the NVIDIA excerpts and the
run has no operational failure. `NOT_IN_DOCS` means insufficient document evidence and is distinct from
connectivity or provider errors. A CLI search result alone is not a generated answer.

![Existing NVIDIA data-center answer and FY2024 source citation cards](../assets/15-cited-answer.jpg)

*This is an actual saved answer to an earlier English question, not a newly executed tutorial question. Wording and citation scope depend on the query and settings. Check document IDs, fiscal years, and source passages. The execution summary marks only phases actually performed in this saved run in green.*

## 8. Change settings and evaluate

### Try Ollama answers

**Purpose:** keep the retrieval index and compare a local answer engine.

Ollama is a separately installed server. Check [local-model connectivity](cli.md#diagnose-local-model-connectivity)
first. Retrieval embeddings remain OpenAI, so this is not a fully offline or free path.

In Settings → Local LLM, enter a backend-reachable Server URL and click **Connect & save**. A Docker app
connecting to Ollama on the same PC normally uses `http://host.docker.internal:11434`, without `/v1`.
Then select Local LLM and a discovered answer-capable model in the conversation settings above the input.
Saving a connection does not automatically switch the answer engine.

**Screen check and completion:** inspect connection, model, and engine, then repeat the question and verify
citations. A successful connection alone does not establish answer quality. Disconnect persists an off state;
Restore defaults uses startup settings. See [connection cleanup](cli.md#reset-local-connection-settings).

![Ollama server address, connect, disconnect, and reset controls](../assets/13-local-model.jpg)

*Settings → Local LLM. Existing connection settings were inspected without changing them. Embedding-only models are marked unavailable for answers.*

### Add DART

**Purpose:** include Korean business reports.

Set a real `DART_API_KEY` and run `rag-dev up -d` to apply it. Reuse existing data when ready.
Select Filings and use its Change… inputs to select DART, stock code `005930`, and fiscal year `2024`. Download missing filings,
wait for success, and refresh. In Parse & chunk, inspect the `dart-manifest.json` row before clicking Ingest.
That row processes the entire manifest, including existing entries.

**Screen check and completion:** verify the Samsung FY2024 document, fill pending embeddings if needed
(a paid action), and confirm BM25. Ask a question naming the company and year and check its citations.
The CLI follows the same download → ingest → embedding sequence.

### Run a quick evaluation

**Purpose:** measure retrieval against questions with known source evidence.

Measure follows **1. Search trial → 2. Golden dataset → 3. Run evaluation → 4. Compare and save**.
Inspect one question, check its gold source spans, then run and compare under matching conditions.
Recall@k, hit rate, and MRR measure retrieval; they do not prove that the final answer is factually correct.

Open Golden dataset and inspect its questions and source readiness. A one-filing corpus is not a valid basis
for judging a suite covering other companies. Prepare all required source files, chunks, and embeddings first.

Open Run evaluation to see the evaluation runs list. Choose **New evaluation**, select a suite and
revision in the setup dialog, and use **Quick · current index** in the advanced options. Click
**Queue evaluation**. The queued job appears in the list; select it to inspect actual progress and settings.
Query embedding may incur charges. Once succeeded, inspect its result metrics and individual cases.
From Result details, enter a Snapshot label and choose **Save result as snapshot** to preserve the result
with current search data. Publishing a saved snapshot is a separate action.

The new suites are `sec-en_v2_astra`, `sec-ko_v2_astra`, and `sec-mixed_v2_astra`, with 20 evidence-aligned
English, Korean, and mixed-language questions each. They remain agent-curated and awaiting human approval.
Before interpreting a difference as language parity, check that company, fiscal year, and scope clues also
match across questions. Shared source spans alone do not establish equivalent question scope.
Click a question to inspect its details. **Source JSON · read-only** displays the canonical data; it is not
an editor. Create an editable draft to change questions, then save, validate, and publish. Published revisions
are immutable; selecting one does not make the source JSON editable.

**Screen check and completion:** verify suite, corpus coverage, hits/misses, and relevant ranks. In Compare
and save, select a baseline and candidate with matching suite, golden/corpus identity, and k. Example view is
illustrative, not an actual evaluation. A snapshot preserves search data plus an evaluation result for reuse.
Evaluation settings apply to the next new evaluation and do not change existing results.

![Mixed-language SEC suite and read-only details of a selected question](../assets/10-golden-question.jpg)

*Select a question row to inspect its question, reference answer, and classification. Editing starts with Create draft; no draft was created or published for this capture.*

![Evaluation setup with a suite and Quick current-index mode](../assets/11-evaluation-inputs.jpg)

*Open New evaluation from the runs list to inspect setup before queueing. An existing result is not evidence that the newly selected suite has been evaluated.*

![Baseline and candidate selectors, comparison, and saved snapshots](../assets/12-compare.jpg)

*Comparison requires two distinct compatible results. Only one result was available during capture, so no comparison was run and no illustrative metrics were presented as actual results.*

### Find help for a control

Open Help and use **Search all help** to search local topics by keyword, then narrow the **Help section**
when needed. **Recommended** follows the controls currently visible on your screen. A result for another
workspace offers **Go to** that screen. Searching help does not call an answer model.

## 9. Stop and continue later

**Purpose:** retain the exercise data while stopping the service.

```bash
rag-dev down
```

On the next `rag-dev up -d`, Documents and browser conversations should remain. Do not download or embed
prepared data again. Optionally inspect [local prod preview](cli.md#development-and-local-prod-preview).

Deletion is optional. Read [shutdown and selective cleanup](cli.md#shutdown-and-selective-cleanup) for the
separate boundaries of browser conversations, DB volume, source files, and connection settings.

**Completion:** record where the exercise succeeded or failed and share feedback. When a screen or workflow changes, update its screenshot and instructions together without exposing keys or personal data.

![Data and help showing browser conversation cleanup and database preservation](../assets/14-browser-data.jpg)

*Clear conversations in Data and help affects browser conversations. It is separate from DB, source, and connection cleanup; no deletion was performed for this capture.*

## When you need to reset everything

At the top left of the Pipeline header, open the red **Reset runtime data** control with its chevron.
Reset requires the authenticated local dev operator. Availability checks inspect the same runtime files
and active jobs as deletion preview, and show **Last checked**. A blocked check displays the diagnosis,
path and permission details, and manual remediation commands where applicable. The check does not
change file ownership or permissions; review any proposed ACL command with the owner before applying it.
After addressing the reported condition, check again.

Finish active work first. **Wipe everything** opens the final deletion question. The preview identifies
the DB volume, tables, files, and preserved sources. **Cancel** closes it without deleting data.
**There is no automatic backup and no undo.** Type `WIPE <project-name>` exactly, then confirm the final action.
The DB, downloaded sources, generated evaluation artifacts, and saved connections are cleared; after server
success, clear DocReview browser data and return to setup. Code, keys, `.env`, documents/images, and
manifest/golden/profile sources are preserved. Changed targets or external DBs are refused. On partial failure,
read the completed stages before retrying. Reset is never required merely to start this tutorial.

![Actual reset warning refusing execution for an inaccessible local settings file](../assets/17-reset-blocked.jpg)

*The preview refused reset because the operator could not remove local-llm.json. It did not proceed to typed confirmation. Check ownership and permissions first; neither permissions nor data were changed during capture.*
