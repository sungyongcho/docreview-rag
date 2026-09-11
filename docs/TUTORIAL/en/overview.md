# DocReview RAG guide

DocReview connects SEC and DART filings to answers you can verify against the original text. You can follow a claim back to its citation, inspect the retrieval that supplied the evidence, and compare recorded retrieval evaluations. The manual follows those tasks across the app; Help explains an individual control while you are using it.

To try the running service, begin with [Quick Start](quickstart.md). To run a fresh clone, begin with [Environment setup](environment.md#qs-setup). All 17 guides are readable in DEV and PROD; a DEV badge identifies an operation that requires a development environment.

## Where to start {#start}

| Your starting point | Follow this path | Result |
|---|---|---|
| A running public instance | [Quick Start](quickstart.md) → [Answers](answers.md) → [Documents](documents.md) and [Snapshots](snapshots.md) | Read a supported answer, verify its sources, and inspect published results. |
| A fresh clone or empty local database | [Environment setup](environment.md#qs-setup) → [Quick Start for DEV MODE](quickstart-dev.md) | Start DEV and prepare two example filings for retrieval. |
| An existing local corpus | [Documents](documents.md#step-2) → the missing [preparation step](quickstart-dev.md) | Reuse downloaded sources, chunks, compatible embeddings, and BM25. |

The public portfolio covers NVIDIA and AMD FY2019–FY2024 and Samsung Electronics and SK hynix FY2022–FY2024: 18 filings. A new DEV installation does not inherit those prepared database rows or downloaded sources. Its default filing selection describes intended work; it does not prove that work has run.

An empty filtered list and an empty public catalog are also different from an empty database. Check the current filters and [document visibility](documents.md#visibility) before deciding what is missing.

CLI and Web share results when they use the same database, source directory, and effective configuration. The corpus helper submits the same jobs as Build; direct tools that bypass the queue may have no Jobs entry. Inspect what is already complete before repeating a download, ingestion, index build, or paid model call.

## Twelve-step learning path {#learning-path}

Use this sequence for the full local exercise. The navigation groups usage before preparation, while the numbered steps keep their procedure order. Begin with [Part 1: Setup](environment.md#qs-setup); continue through [DEV preparation](quickstart-dev.md), then search, answers, settings, and evaluation. Skip work already complete in this environment.

<!-- tutorial-steps -->

Parsing creates the chunks used by two independent indexes: semantic embeddings and lexical BM25. Hybrid retrieval needs both; vector retrieval needs compatible embeddings, and lexical retrieval needs BM25. Evaluation additionally needs a dataset with expected evidence. You can evaluate retrieval before generating an answer.

## Find the right workspace {#workspaces}

| Workspace | Task and result |
|---|---|
| Conversation | Ask a scoped question, follow the run, and verify claims through citations and retrieved candidates. |
| Build → Pipeline | Inspect preparation dependencies, then run the missing stage in DEV. Selecting a node only opens that stage. |
| Build → Documents | Find a filing, inspect its identity and chunks, and check stored embedding coverage. |
| Build → Jobs | Follow queued work through progress, completion, a recorded error, or an explicit retry. |
| Measure | Try retrieval and run evaluations in DEV; inspect published snapshots and comparisons in PROD. |
| System → System status | Separate API, database, schema, corpus, and model availability before diagnosing a blocked task. |

Corpus preparation, dataset editing, live evaluation, and local-model setup require DEV. Public visitors can read eligible documents and published snapshots and use the configured OpenAI answer service within its allowance. [Settings](settings.md) explains request choices; [Runtime](runtime.md) explains what the execution records establish.

## Use Help and the documentation {#help}

1. Open **Help** when you need the meaning of a visible control. Recommended topics reflect the current screen; search accepts Korean and English and can cover the current screen or all sections.
2. Open a topic to read its summary and **What to do** steps. **Go to this control** focuses the control or takes you to its screen. This navigation does not execute its action.
3. Choose **Read the full guide** when you need the complete task, its prerequisites, or the meaning of its result. **Back** in Help restores the previous search, filter, and scroll position.

The documentation menu preserves the 17-guide reading path. Previous/next links continue that path, and changing language keeps the same document. Code cards copy the original command, and wide tables scroll horizontally. Source text, questions, answers, model names, and logs retain their original language.

For a failure, use [Troubleshooting](troubleshooting.md) to connect the recorded symptom to a specific check. For implementation context, read [Architecture](architecture.md). Use the [CLI reference](cli.md) when a task requires a terminal.

### Back, forward and shared locations

Use the header's **Back** and **Forward** arrows to return between the conversation and an inspection screen. Click the current location to choose an entry in **Navigation history**; arrow keys, Home/End, Enter, and Escape operate the list. On a narrow screen it opens as a bottom sheet.

App navigation and browser history share the same sequence. Returning restores retained controls, conversation drafts, focus, and scroll. A new navigation after going back replaces the forward path; leaving unsaved evaluation questions still requires confirmation.

The URL identifies the workspace, tab, selected preparation stage or evaluation result, and local conversation. Reload restores that location. A conversation missing from this browser falls back to its most recent saved conversation. Message text and drafts are never included in the URL.

### SCREENSHOT NEEDED
<!-- feature=manual-navigation-and-task-return; mode=prod; locale=en; theme=light; state=return-from-document-to-retained-conversation; expected-evidence=header-history-and-restored-draft -->

## Terms at a glance {#terms}

| Term | One-line meaning | Details |
|---|---|---|
| Chunk | A source span that can be cited | [Parse and chunk](indexing.md#step-5) |
| Embedding | A chunk vector used for semantic search | [Prepare embeddings](indexing.md#step-6) |
| BM25 | The lexical scoring method for keyword search | [Prepare BM25](indexing.md#step-7) |
| Hybrid · RRF | Rank fusion across vector and keyword paths | [Retrieval settings](settings.md#presets) |
| Golden set · suite | An evaluation dataset with designated ground truth | [Evaluation suites](evaluation.md#suites) |
| Snapshot | An immutable record of the index at evaluation time | [Snapshots](snapshots.md) |
| `NOT_IN_DOCS` | A deliberate non-answer when evidence is insufficient | [Answer outcomes](answers.md) |
| Run limits | Per-question ceilings on iterations, tokens and time | [Reading limits](runtime.md#limits) |

## Browser storage {#browser-storage}

PROD stores conversations, defaults, filters, presets, language/theme, and Help preferences in this browser and origin. They are not synchronized. Before clearing site data, open **Settings → Data & help → Browser storage** and export a backup. The [storage guide](settings.md#browser-storage) explains the inventory, import, and clearing scopes. DEV retains its own storage behavior.

## Public OpenAI allowance

The public policy allows 2 requests per minute and 5 per rolling 24 hours per IP, with a shared $0.10 allowance per UTC day and a $0.005 ceiling per model call. The configured text model is `gpt-5.6-luna`; semantic search uses `text-embedding-3-large` at 384 dimensions. **Limits & availability** reports the server's current availability, not an account invoice or a promised number of answers.

Answer calls and query embeddings reserve allowance immediately before the OpenAI call. Keyword-only retrieval and saved-result reads do not use it. IP windows expire with time; the shared day resets at UTC midnight. The reservation ledger at `data/runtime/public-ai-limits.sqlite3` survives application restarts on the same persistent volume. It coordinates processes on one host, not multiple independent hosts. [Environment setup](environment.md#production-deployment) describes that deployment boundary.
