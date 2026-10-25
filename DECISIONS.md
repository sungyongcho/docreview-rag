
<!-- ops:project:DECISIONS.md:v1 -->
# Decision and requirement ledger

Canonical record of this project's agreed decisions and requirements. Sessions
consult this file at session start or intake and on any requirement change; a
conflict between new instructions and an `active` entry is surfaced to the user
before proceeding, and the resolution is recorded here.

`opsctl project check` verifies the managed block fingerprint recorded in
`.ops/project.json` and validates every entry's structure. Entries are appended
under `## Entries` and never deleted; a superseded entry keeps its original text
and gains `superseded-by` pointing at the replacing id.

## Entries

Each entry is one `### D-<number> — <title>` heading followed by bullet fields:

- `status`: `active` or `superseded` (required)
- `category`: one lowercase slug such as `hosting`, `scope`, `authority`,
  `workflow`, `interface` or `tooling` (required)
- `date`: decision date `YYYY-MM-DD` (required)
- `source`: issue, PR, document or session reference (required)
- `decision`: the agreed text on one line (required)
- `superseded-by`: `D-<id>` of the replacing entry (required when `superseded`)
- `note`: optional one-line clarification
<!-- /ops:project:DECISIONS.md -->

### D-1 — Repository renamed to docreview-rag
- status: active
- category: scope
- date: 2026-09-12
- source: PR #213
- decision: This repository was renamed from docreview-rag-agent to docreview-rag; OPS records reconcile it by the numeric repository id, and the dashboard/registry use the canonical slug.

### D-2 — Unreachable code and its tests are removed
- status: active
- category: scope
- date: 2026-09-25
- source: PR #220
- decision: Code that no entry point reaches (the served app, the documented CLIs, the deploy and release scripts, the evaluation harness and the web app) is deleted together with the tests that cover only it; every deletion carries evidence and three independent reachability verdicts in docs/refactor-2026-09.md.

### D-3 — Compatibility and legacy code stays only for a live consumer
- status: active
- category: scope
- date: 2026-09-25
- source: PR #220
- decision: Backward-compatibility paths, shims, migrations, duplicated logic and single-caller indirection are removed unless a live consumer needs them: the deployed API and web app, the deploy and release scripts, the evaluation harness, or data already stored in the database, in data/ files or in browser storage. Stored records stay readable; no schema change and no narrowing of a type that reads persisted data.

### D-4 — BM25 settings precedence
- status: active
- category: interface
- date: 2026-09-25
- source: PR #220
- decision: A retrieval plan uses the BM25 values it states (a Custom profile or a saved preset), then the server settings BM25_K1, BM25_B and BM25_IDF, then the built-in defaults; built-in presets that repeat a default inherit the server settings, and the resolved profile always carries the values actually applied.

### D-5 — The served entry point is app.release.space
- status: active
- category: interface
- date: 2026-09-25
- source: PR #220
- decision: The only served application is app.release.space:app (app/release/app.py); the superseded app.main factory, the app.cli serve subcommand and the module CLIs documented only in the archived README are removed, and ingestion enters only through the corpus job API.

### D-6 — Tests are pruned without losing coverage of live behaviour
- status: active
- category: workflow
- date: 2026-09-25
- source: PR #220
- decision: Tests that repeat another test's behaviour, pin wording or implementation details, or cover only deleted code are removed with per-test coverage evidence; app/ and scripts/ line and branch coverage stays at or above the pre-pruning measurement, and no assertion about live behaviour is loosened.

### D-7 — Table structures are canonical relational records
- status: active
- category: interface
- date: 2026-10-25
- source: mcp-and-langgraph Day 5A 6.5 A (learning branch session decision)
- decision: Ingestion stores each table, its source cells, its normalized cells with their interpretation, and chunk-to-cell memberships as relational records built once at chunking, and the table_fragment JSONB of chunks and snapshot_chunks is removed after a verified backfill; this is an exception to D-3's schema-freeze clause for this change only, and chunk stable_key, chunk ids, embeddings and the corpus identity digest keep their current inputs.

### D-8 — Cell facts come from the filing's own fact tags
- status: active
- category: interface
- date: 2026-10-26
- source: mcp-and-langgraph Day 5A follow-up (learning branch session decision, design 2026-10-26-cell-fact-tags)
- decision: Parsing keeps SEC inline XBRL facts and DART ACODE/ACONTEXT tags, and the period terms a DART filing declares, as relational records; a tagged cell's currency, scale, fiscal year and dimensional scope come from its tag and override the text reading with the override recorded, dimensional values are not selectable, items still come only from row labels, untagged cells keep the text rules with no general currency or period assumption, and published evaluation snapshots keep their stored readings; this is an exception to D-3's schema-freeze clause for this change only, and chunk stable_key, chunk ids and embeddings keep their current inputs.
