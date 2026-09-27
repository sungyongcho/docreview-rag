# DocReview RAG guide

Ask about SEC and DART filings, verify original evidence, and compare search results. Try the public service without installing anything locally.

## What would you like to try? {#start}

<!-- guide-features -->

- **[Ask about a company](quickstart.md#qs-app-2)**

  Choose a filing, ask a question, and inspect the answer and execution summary.

  [Open conversation →](/docreview-rag/?view=review)

  [Quick Start](quickstart.md)

- **[Check an answer's sources](answers.md#inspection)**

  Open a cited passage to verify the claim, company, and year.

  [Browse filings →](/docreview-rag/?view=build&tab=documents)

  [Inspect answers](answers.md) · [Document guide](documents.md)

- **[Compare search results](snapshots.md#comparison)**

  Compare published snapshots to see which evidence search found or missed.

  [Open comparisons →](/docreview-rag/?view=measure&tab=compare)

  [Snapshot guide](snapshots.md) · [Understand retrieval](retrieval.md)

## Working on your own machine? {#local-start}

Read all 17 guides in either mode. DEV badges mark tasks that need a development environment. Choose your starting point below.

<!-- guide-local-paths -->

- **[Start from a fresh clone](environment.md#qs-setup)**

  Set up the environment and prepare two filings with [Quick Start for DEV MODE](quickstart-dev.md).

- **[Continue with existing data](documents.md#step-2)**

  Check sources, chunks, compatible embeddings, and BM25; run only the missing [preparation step](quickstart-dev.md).

The public corpus has 18 filings: NVIDIA and AMD FY2019–FY2024, plus Samsung Electronics and SK hynix FY2022–FY2024. Fresh DEV installations lack this corpus; their default selection only describes work to prepare.

An empty list does not mean an empty database. Check filters and [document visibility](documents.md#visibility) before rebuilding.

CLI and Web share results with the same database, source directory, and configuration. The corpus helper submits Build jobs; tools outside the queue may have no Jobs entry. Check existing results before downloads, ingestion, indexing, or paid calls.

## The full workflow, in three stages {#learning-path}

These 12 steps follow the preparation and review order. Open a step for prerequisites and expected results; skip completed work. To try the public service, start with the tasks above.

<!-- tutorial-steps -->

Chunks feed two indexes: embeddings and BM25. Hybrid search needs both; vector search needs compatible embeddings, and lexical search needs BM25. With a dataset of expected evidence, you can evaluate retrieval before generating answers.

## Find the right workspace {#workspaces}

| Workspace | Task and result |
|---|---|
| Conversation | Ask, follow the run, and verify answers through citations and retrieved candidates. |
| Build → Pipeline | Check dependencies and run missing stages in DEV. Selecting a node only opens its screen. |
| Build → Documents | Inspect filing details, chunks, and embedding coverage. |
| Build → Jobs | Check progress, completion, and errors; explicitly retry work when needed. |
| Measure | Run retrieval and evaluation in DEV; compare published snapshots in PROD. |
| System → System status | Check API, database, schema, corpus, and model status to locate a problem. |

Corpus preparation, dataset editing, live evaluation, and local-model setup require DEV. Public visitors can read eligible documents and published snapshots and use the configured OpenAI answer service within its allowance. [Settings](settings.md) explains request choices; [Runtime](runtime.md) explains what the execution records establish.

## Use Help and the documentation {#help}

1. Open **Help** when you need the meaning of a visible control. Recommended topics reflect the current screen; search accepts Korean and English and can cover the current screen or all sections.
2. Open a topic to read its summary and **What to do** steps. **Go to this control** focuses the control or takes you to its screen. This navigation does not execute its action.
3. Choose **Read the full guide** when you need the complete task, its prerequisites, or the meaning of its result. **Back** in Help restores the previous search, filter, and scroll position.

The documentation menu preserves the 17-guide reading path. Previous/next links continue that path, and changing language keeps the same document. Code cards copy the original command, and wide tables scroll horizontally. Source text, questions, answers, model names, and logs retain their original language.

For a failure, use [Troubleshooting](troubleshooting.md) to connect the recorded symptom to a specific check. For implementation context, read [Architecture](architecture.md). Use the [CLI reference](cli.md) when a task requires a terminal.

<!-- heading-alias: back-forward-and-shared-locations -->
### Back, forward and shared locations {#navigation}

Use the header's **Back** and **Forward** arrows to return between the conversation and an inspection screen. Click the current location to choose an entry in **Navigation history**; arrow keys, Home/End, Enter, and Escape operate the list. On a narrow screen it opens as a bottom sheet.

App navigation and browser history share the same sequence. Returning restores retained controls, conversation drafts, focus, and scroll. A new navigation after going back replaces the forward path; leaving unsaved evaluation questions still requires confirmation.

The URL identifies the workspace, tab, selected preparation stage or evaluation result, and local conversation. Reload restores that location. A conversation missing from this browser falls back to its most recent saved conversation. Message text and drafts are never included in the URL.

<!-- screenshot: manual-navigation-and-task-return -->

![Returning from a guide page restores the prior conversation and its recorded answer in PROD mode.](../assets/captures/manual-navigation-and-task-return.en.png)

*1. Restored question and answer · 2. Preserved conversation context*

## Browser storage {#browser-storage}

PROD stores conversations, defaults, filters, presets, language/theme, and Help preferences in this browser and origin. They are not synchronized. Before clearing site data, open **Settings → Data & help → Browser storage** and export a backup. The [storage guide](settings.md#browser-storage) explains the inventory, import, and clearing scopes. DEV retains its own storage behavior.

<!-- heading-alias: public-openai-allowance -->
## Public execution-request and AI cost limits {#allowance}

The public interface distinguishes **Execution requests remaining in this browser**, **Server requests shared by multiple visitors**, and the **Global AI cost limit**. Browser and server counts each allow 10 execution requests per minute and 50 per rolling 24 hours. Both use the public policy loaded from the server. If that policy cannot load, use its retry control before sending; browser defaults are not a substitute. The server's remaining counts describe shared capacity and do not replace the browser's own counts. Browser remaining requests and retry time appear beside the composer, in Search trial, and in the limits dashboard.

Conversation sends, reruns with selected evidence, and Search trial use the same browser allowance. Each request is recorded once immediately before transmission, including a streaming request. A locally blocked request or cancellation before transmission does not consume it. Errors and cancellations after transmission are not refunded or automatically retried. A local limit keeps your input and shows when you can send again. [Browser storage](settings.md#browser-storage) explains timestamp retention and tab synchronization.

The server independently counts accepted public `POST /retrieve`, `/review`, and `/review/stream` requests, including trailing-slash paths, before parsing the body or starting execution. Validation failures, cancellations, and runs without an AI call still count; keyword-only search therefore consumes a request. A rate-limited request adds no usage and does not extend the wait. Reading saved results, static pages, and other GET requests does not consume execution requests.

Visitors whose requests arrive through the same Worker egress IP share the server allowance. One visitor can exhaust that shared allowance. An egress IP is neither a stable visitor identity nor authentication for this site's Worker; the policy does not guarantee fair allocation or protection against distributed traffic. Request windows recover as each entry reaches 60 seconds or 24 hours, rather than at midnight.

All egress IPs share the separate $0.10 AI cost cap per UTC day, with a $0.005 ceiling per model call. Answers and query embeddings reserve cost immediately before each provider call; ambiguous provider failures retain the reservation. The daily cost allowance resets at UTC midnight. The configured text model is `gpt-5.6-luna`; semantic search uses `text-embedding-3-large` at 384 dimensions. **Limits & availability** reports capacity, not an account invoice or a promised number of answers.

The existing ledger at `data/runtime/public-ai-limits.sqlite3` preserves request history and cost reservations across application restarts on the same persistent volume. It coordinates processes on one host, not independent hosts. A ledger failure before the response starts blocks the request with `503`. If the cost ledger fails after SSE starts, the existing HTTP `200` cannot change: the stream sends an `allowance_unavailable` error followed by `done`, and the next provider call is blocked. See [limit troubleshooting](troubleshooting.md#public-limits) and the [deployment boundary](environment.md#production-deployment).

### SCREENSHOT NEEDED
<!-- Feature: public request and cost limits. State: PROD conversation and Limits & availability showing distinct browser remaining requests, shared server remaining requests, and global AI cost, plus a browser-limited draft with retry time. Locale: en, light mode. Expected evidence: real UI states showing the three separate limits and preserved input; no existing screenshot proves these changes. -->
