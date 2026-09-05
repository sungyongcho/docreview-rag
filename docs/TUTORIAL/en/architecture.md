# How the workflows connect

DocReview RAG v2 connects SEC and DART acquisition, citable document processing, retrieval, evidence review, and retrieval evaluation. The earlier interface is the v1.4 beta baseline; this guide describes v2. Product version terminology does not change stored dataset IDs, API fields, or repository URLs.

Use this map to find the layer responsible for a behavior. Start with the workflow document linked beside each area before reading implementation details.

## From filing to evidence and evaluation {#flow}

1. **Acquire source files.** SEC and DART acquisition write source files and manifest metadata. Company names are display metadata; stable issuer codes remain request identifiers.
2. **Parse and chunk.** The ingestion path interprets the filing and stores documents and source-linked chunks. A chunk keeps the document identity, source hash, and character span needed to check a citation.
3. **Prepare search paths.** Embeddings support vector search; BM25 statistics support lexical search. These are parallel preparation paths. Hybrid retrieval combines rankings and can rerank candidates according to the effective profile.
4. **Retrieve and review.** A review resolves question intent and filing scope, retrieves evidence, evaluates relevance, checks the answer and citations, and produces a result or structured failure. An evidence-only path can return candidates without a generated answer.
5. **Evaluate retrieval independently.** A golden dataset supplies known evidence spans. Evaluation records ranks and aggregate metrics against a specified search configuration. It needs suitable source data and an index, not a previously generated answer.
6. **Preserve a result and search data.** A matching quick evaluation can be saved as a snapshot. Publication separately determines what visitors can read.

## Implementation map {#implementation}

| Area | Main source locations | Workflow guide |
|---|---|---|
| Workspace navigation and retained state | `web/components/service-shell.tsx`, `retained-panel.tsx` | [Settings and return navigation](settings.md#filters) |
| Acquisition, parsing, and chunks | `app/ingestion/edgar_api.py`, `dart_api.py`, `parser.py`, `chunk.py` | [Acquisition](acquisition.md), [Indexing](indexing.md) |
| Search and scoped filtering | `app/retrieval/service.py`, `hybrid.py`, `lexical.py`, `vector.py`, `scope.py` | [Retrieval](retrieval.md) |
| Evidence-review workflow | `app/workflow/runner.py`, `gate.py`, `nodes.py` | [Answers](answers.md) |
| HTTP resources and streaming | `app/api/routes/`, especially `admin.py`, `stream.py`, `public_documents.py` | [Runtime](runtime.md) |
| Golden suites and experiments | `app/evals/admin.py`, `app/evals/snapshots.py` | [Evaluation](evaluation.md), [Snapshots](snapshots.md) |
| Run budgets and trace persistence | `app/observability/budget.py`, `stages.py`, `persistence.py` | [Execution measurements](runtime.md#timings) |
| Browser preferences and per-conversation profiles | `web/lib/storage.ts`, `web/lib/types.ts` | [Settings](settings.md) |

The browser sends the selected profile and keeps that submitted configuration separate from the next request's controls. Server-resolved scope and execution metadata travel back with the run. The UI displays recorded evidence; it does not establish a routing decision or timing by guessing locally.

## Storage, permissions, and public boundaries {#boundaries}

Source files and manifests, PostgreSQL documents/chunks, evaluation artifacts, and browser conversations are different stores. Downloading is not ingestion. Saving a browser conversation is not saving a search snapshot. Clearing browser conversations does not remove server documents.

| Resource | Boundary |
|---|---|
| `/admin/*` | Development/operator capabilities protect corpus mutation, evaluation, editing, and local connections. |
| `/public/documents` | Lists documents eligible through ready, published snapshot membership and source identity. |
| `/public/documents/facets` | Supplies choices and counts from that public catalog; optional `registry=sec` or `registry=dart` narrows the scope. |
| `/public/documents/{doc_id}` | Applies the same public boundary to document details and chunk previews. |
| `/snapshots` and `/snapshots/compare` | Expose published ready snapshots and compare existing artifacts. |
| `/runs/{run_id}` and `/runs/{run_id}/traces` | Read an identified persisted run and its traces; there is no run-list resource. |

Public rendering must not reveal unpublished totals, local paths, credentials, or administrator actions. Company names follow the same document visibility rules. The local operator that manages runtime reset is separate from the main API service; its permissions and lifecycle must be checked independently.

## Compatibility and deployment {#compatibility}

Issuer names and execution telemetry are additive metadata. Missing company names fall back to stable identifiers, and legacy runs can remain readable without timing or routing fields. `_v2_astra` suite IDs retain their exact values. The optional registry facet parameter keeps the existing combined-catalog default.

Stage telemetry is opt-in through `X-DocReview-Telemetry: stages`. Clients without the header keep the default stream sequence. Existing JSON persistence stores optional execution metadata without requiring a new field solely to fill a UI card.

The development stack serves the application and live documentation through port 8000 by default, with source mounts and reload behavior. Static production images contain the built application and localized docs instead. `MODE`, backend permissions, and the public/private web build are related but different settings; use [Environment setup](environment.md) and [CLI reference](cli.md) for the supported startup paths.

For a concrete failure, follow [Troubleshooting](troubleshooting.md) from symptom to evidence before changing another layer.
