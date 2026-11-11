# Decision and requirement ledger

Canonical record of this project's agreed decisions and requirements. Sessions
consult this file at session start or intake and on any requirement change; a
conflict between new instructions and an `active` entry is surfaced to the user
before proceeding, and the resolution is recorded here.

Entries are appended under `## Entries` and never deleted; a superseded entry keeps
its original text and gains `superseded-by` pointing at the replacing id.

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

### D-9 — OPS orchestration is removed from this project
- status: active
- category: workflow
- date: 2026-11-11
- source: user instruction in the 2026-11-11 maintenance session
- decision: Project rules no longer use the sungyongcho-ops account, opsctl and the other ops commands, OPS-managed rule blocks and their .ops/project.json fingerprints, or the DEV/OPS purpose labels; commits, pushes, PRs, status labels and work-state records use the personal identity through plain gh, and the OPS-record clause of D-1 no longer applies.

### D-10 — Untagged DART cells take statement scope from the report's own declarations
- status: active
- category: interface
- date: 2026-10-26
- source: commit 25a16a19 on mcp-and-langgraph (user instruction recorded in the 2026-10-26 fact-tag log; entry added by the 2026-11-11 audit)
- decision: For DART tables without fact tags, parsing reads the statement kind, scope and basis that the report itself declares (section codes, table-group classes and summary headings) into parsed_tables.statement_kind, statement_scope and statement_basis; cells of a declared consolidated statement are entity-wide, cells of a separate statement are scope_qualified, and cells of notes, equity-change statements and undeclared tables are scope_unknown; this narrows D-8's "untagged cells keep the text rules" for scope only and is an exception to D-3's schema-freeze clause for this change only.

### D-11 — An answer's figures are read by answer rules and cited text by filing rules
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: In a model's written answer an identifier (note or item reference, period, date, form name) is only a bounded short shape, and a number that is longer than that shape or carries a unit (percent sign, scale word, currency not followed by another number) is an amount to be checked wherever it stands; a cited passage or header is the filing's own text and keeps the filing rules, so a reference number in it is never a fact; a unitless short number after a reference word, a bare 1900-2099 integer and amounts written without digits remain outside the check and are listed as known limits.

### D-12 — Stored table readings are served only by the code that read them
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: A stored table whose builder identity or resolver identity (which now includes the fact reader) differs from the running code is stale: its cell catalog is served as unavailable, the figure check on every path receives no cells and no body for it, paid agent runs of the live script are refused before the attempt is claimed, and schema check, the corpus status and /ready report the stale count without degrading readiness; evaluation snapshots keep serving their frozen readings; consequently any change to the table-reading files requires re-indexing before table-based answers verify again, and a deployment that changes those files must ship re-indexed data.

### D-13 — A table chunk is never read as running text by the figure check
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: The figure check builds its evidence for every cited chunk through one rule shared by the agent path and the review workflow: running text gives its body, a table chunk with usable current readings gives its body and those cells, and a table chunk without usable readings (stale, or stored without table rows) gives neither, because reading a table's text as prose was measured to be looser than its cells, not stricter.

### D-14 — A tagged cell's standard concept must be one its row label's item accepts
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: For a cell tagged with a us-gaap or ifrs-full concept, the item read from the row label stands only when that concept is in the item's accepted-concept table; otherwise the cell has no established item and records a concept override, because 38 of the 957 known cells of the local corpus were another concept under a matching label (change in receivables, pro forma revenue and net income); company-extension concepts and DART dart_ codes keep the row-label rule; this narrows D-8's "items still come only from row labels" for tagged cells.

### D-15 — A table cell is known only when its own text, tag and table establish it
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: The table reader holds, and the reading the figure check compares carries the hold for, a percentage whose sign sits in its own cell, a figure with malformed digit grouping or one its single tag disputes, a cell scale word against a table that declares a scale, and an unsigned figure under a loss-only label (status only; magnitudes still compare); a value's sign comes from its notation or its inline XBRL tag; for untagged cells a header naming a period shorter than a fiscal year dates nothing, a column that is not the reported amount, a row under a part of the entity and a row with a second label are scope_unknown, a caption's single year dates only a table's one value column, and a column whose tagged cell moves the year leaves its untagged cells undated; the status set is unchanged.

### D-16 — The cell-selection gate reports only what it checked and asks for one cell per item and year
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: A not_found proposal is accepted only after a retrieval tool has returned in the question (zero hits count); a selected cell is checked against its claim and the question before a unit hold is reported; a percentage cell, a cell only partly in its chunk, a cell without one item or one fiscal year, and a second cell for the same item and fiscal year are returned to the model; the period-mismatch and no-item reports state only what was checked and every report's rationale follows the answer's language; the question's items are read around the issuer names the application already knows (items_named(issuers=...)), a qualifier or unknown word beside an item names no item, and words that restate the entity scope are not qualifiers.

### D-17 — The live experiment script fails closed on mode, money and results
- status: active
- category: tooling
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: scripts/mcp/live.py refuses MODE=prod at both entry points, counts model and embedding usage observed above its reservation against the cap and refuses the next send that no longer fits, ends a search over the embedding cap as a system failure instead of a model-facing tool error, reports why a question ended without an answer, checks the key and the issuer's names before the attempt is claimed, and leaves a result file for every way a claimed run can end.
