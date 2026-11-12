# Decision and requirement ledger

Record of this project's standing decisions about the code. A session reads the
entries for the area it changes. A user instruction that contradicts an `active`
entry replaces it: the entry is marked superseded, the new one is appended and the
report says so.

Entries are appended under `## Entries`; a superseded entry keeps its original text
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

### D-1 — Repository renamed to docreview-rag
- status: active
- category: scope
- date: 2026-09-12
- source: PR #213
- decision: This repository was renamed from docreview-rag-agent to docreview-rag; OPS records reconcile it by the numeric repository id, and the dashboard/registry use the canonical slug.
- note: D-9: the OPS-record clause no longer applies.

### D-2 — Unreachable code and its tests are removed
- status: active
- category: scope
- date: 2026-09-25
- source: PR #220
- decision: Code that no entry point reaches (the served app, the documented CLIs, the deploy and release scripts, the evaluation harness and the web app) is deleted together with the tests that cover only it; every deletion carries evidence and three independent reachability verdicts in docs/refactor-2026-09.md.
- note: D-36: docs/refactor-2026-09.md and its evidence appendix were removed; the report stays in the history of PR #220.

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
- note: D-10 narrows untagged scope; D-14 narrows the item of a tagged standard concept; D-25 lets a tag's explicit sign resolve ambiguous notation.

### D-9 — OPS orchestration is removed from this project
- status: active
- category: workflow
- date: 2026-11-11
- source: user instruction in the 2026-11-11 maintenance session
- decision: Project rules no longer use the sungyongcho-ops account, opsctl and the other ops commands, OPS-managed rule blocks and their .ops/project.json fingerprints, or the DEV/OPS purpose labels; commits, pushes, PRs, status labels and work-state records use the personal identity through plain gh, and the OPS-record clause of D-1 no longer applies.
- note: D-35: the status-label and work-state clause no longer applies.

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
- note: D-31 names the two states a stale or incomplete table is served as (stale_reading, missing_records) in place of "unavailable".

### D-13 — A table chunk is never read as running text by the figure check
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: The figure check builds its evidence for every cited chunk through one rule shared by the agent path and the review workflow: running text gives its body, a table chunk with usable current readings gives its body and those cells, and a table chunk without usable readings (stale, or stored without table rows) gives neither, because reading a table's text as prose was measured to be looser than its cells, not stricter.
- note: D-23 adds that a table chunk supplies no narrative fallback at all, including its context header.

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
- note: D-18 replaces the sub-year-header and non-amount-column clauses; D-19 replaces "magnitudes still compare"; D-25 replaces the direction hold of a tagged cell; D-26 replaces the part-row clause; D-27 narrows "a column whose tagged cell moves the year".

### D-16 — The cell-selection gate reports only what it checked and asks for one cell per item and year
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: A not_found proposal is accepted only after a retrieval tool has returned in the question (zero hits count); a selected cell is checked against its claim and the question before a unit hold is reported; a percentage cell, a cell only partly in its chunk, a cell without one item or one fiscal year, and a second cell for the same item and fiscal year are returned to the model; the period-mismatch and no-item reports state only what was checked and every report's rationale follows the answer's language; the question's items are read around the issuer names the application already knows (items_named(issuers=...)), a qualifier or unknown word beside an item names no item, and words that restate the entity scope are not qualifiers.
- note: D-18 and D-20 replace the qualifier-beside-an-item clause; D-22 states the mixed-year rule; D-30 restates the report and language clauses; D-33 renames the unit hold.

### D-17 — The live experiment script fails closed on mode, money and results
- status: active
- category: tooling
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (user direction to fix the audited defects without stopgaps; audit reports and corpus measurement recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: scripts/mcp/live.py refuses MODE=prod at both entry points, counts model and embedding usage observed above its reservation against the cap and refuses the next send that no longer fits, ends a search over the embedding cap as a system failure instead of a model-facing tool error, reports why a question ended without an answer, checks the key and the issuer's names before the attempt is claimed, and leaves a result file for every way a claimed run can end.
- note: D-32 moves the issuer-name check to app.query.scope and renames the accounted budget fields.

### D-18 — An untagged column and a question's item are established only when every word is understood
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (third study preflight rehearsal on 56bfd8b8 found the earlier rules were lists of forbidden shapes that further shapes walked past; recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: The table reader establishes an untagged column as a fiscal year's reported whole-entity amount only when its header, after the year or year-end date, the unit declaration and a closed vocabulary of full-fiscal-year words are taken out, leaves nothing: a remaining period word leaves the year not established (period_unknown) and any other remaining word leaves the scope not established (scope_unknown); a question's item is named only when every other word of its sentence is a filler, connective, question word, fiscal year, entity-scope word, issuer name the application passed or another item, and a period shorter than a fiscal year always qualifies the item; these allow-lists replace D-15's clauses on sub-year headers and non-amount columns and D-16's clause on qualifiers beside an item, whose lists of forbidden words they supersede.
- note: D-20 replaces the question clause; D-21 states what "year-end date" checks and the several-year header rule; D-24 owns period forms; D-26 gives scope_unknown its causes.

### D-19 — A figure is verified only in the direction its cell states
- status: active
- category: interface
- date: 2026-11-11
- source: 2026-11-11 audit session on mcp-and-langgraph (third study preflight rehearsal on 56bfd8b8 found the earlier rules were lists of forbidden shapes that further shapes walked past; recorded in the Second Brain log 2026-11-11-audit-defect-fixes)
- decision: The figure check compares direction as well as magnitude: a stored reading carries the sign its notation or inline XBRL tag states, a level claim states a loss when its figure is written negative or its item words are a loss phrase of the vocabulary, a claim and a cell that agree in magnitude, unit and period but not in direction are not verified, and where the cell's or the claim's direction is not established the claim is withheld; the withheld-answer sentence and its rationale, defined once beside the verdict, say that the unit or the sign could not be confirmed; this replaces D-15's "magnitudes still compare"; wordings such as "a loss of" and "적자" name no item and stay unverified, and change claims are not compared by direction.
- note: D-33 replaces the withheld-answer sentence and rationale clause with typed causes; D-25 adds that a tag's sign resolves ambiguous notation.

### D-20 — A question's item is read by the question reader's own closed vocabulary
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: The question reader names an item only when every other word of the sentence is in its own closed vocabulary — request, report and citation words, bounded annual-filing source constructions (from, per, in or according to an annual report, 10-K, 20-F or 사업보고서), entity-scope words, issuer names the application passed, fiscal years, a recognised annual period form, other items and a unit word after the item — and it inherits nothing from the answer reader's fillers and connectives; a month, any other date, a comparison, a segment, a basis and a period shorter than a fiscal year name no item; an explicit two-digit FY or fiscal year means 2000–2099 on the question, header and answer readers; this replaces the question clause of D-18.

### D-21 — A header dates a column by one year, read by form
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: A column under a header that names several years is dated by the one single-year leaf header among them, and a cell that still carries several years or none confirms no claim and creates no period mismatch; an untagged header date is read by its form and is not compared with the filing's fiscal year end, so "year-end date" in D-18 means a date form the header reader removes; when a header's annual ending carries an explicit fiscal-year identifier that identifier dates the column, and an ending without one keeps its written calendar year because no issuer fiscal calendar is inferred.

### D-22 — A cell selection that mixes an asked year with another year is returned
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: When a cell selection contains a cell of an asked fiscal year and a cell of another year, the off-year cell is returned to the model; a selection whose years are all unasked is a period mismatch; withholding is reported only after each held cell matches its claim, the asked item and, when any selected cell is of an asked year, an asked year, so it outranks a period mismatch only then.

### D-23 — One eligibility rule decides which table cell is a comparable amount
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: The written-answer check and the cell-selection gate share one reading-owned rule: a cell is a comparable amount only when it holds one complete original monetary figure for one item, one fiscal year and the whole entity; a share count, ratio, percentage or per-share tag, a cell with several figures or a footnote digit, and a cell only partly inside its chunk neither confirm a claim nor create a period mismatch; uncertainty in unit, currency or direction alone withholds; a table chunk supplies no narrative fallback from its body or its context header, and running text confirms only a claim that states and requests no period.

### D-24 — Period forms are classified once for questions, headers and answers
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: app/figures/periods.py owns the classification of a stated period as annual, shorter than a year, a date or none, and the annual forms: an explicit fiscal-year ending in English or Korean, a complete annual duration (52 or 53 weeks, twelve months) with the noun it modifies, and a full-year date range of 364, 365, 366 or 371 inclusive days; readers keep their own identifier and amount grammars but consume these spans; an answer sentence that names a month, another date, a period shorter than a year or an unspecified period is not confirmed by an annual cell and every figure of that sentence is refused without a period mismatch; an English month word is a date only beside a day or year number or after a dating preposition; in an answer an explicit fiscal-year identifier inside an annual ending owns the year of that ending.

### D-25 — A fact tag's sign resolves ambiguous notation
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: When one matching monetary fact tag states an explicit sign, the stored reading carries that signed value even where the cell's notation (a triangle, parentheses) is ambiguous, and interpretation and checking consume that value; a direction hold remains only when neither the text nor a tag establishes direction; this replaces D-15's hold on an unsigned figure for tagged cells and extends D-19.

### D-26 — Whole-entity scope follows understood structure, and unknown scope states its cause
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: An untagged child row under a label-only parent heading is whole-entity only when every structural parent is a complete item phrase or a closed statement-section name, and an unresolved ancestor leaves it scope_unknown until an entity-wide fact tag establishes the cell; scope_unknown carries a typed cause (declaration, header word, part row, second label, unknown parent) with a cause-specific reason kept in the existing override and reason columns, so a header or structural hold never states that the filing declared no scope; this replaces D-15's part-row clause and the name-only-segment limit.

### D-27 — An opening balance does not undate a column's closing year
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: A column's untagged cells are undated by a tagged cell only when that tag's period has the ending role and conflicts with the column's year: an instant established as an opening balance by a parsed duration boundary or an understood opening label keeps its own year without moving the column, an instant whose role is unknown establishes no column-wide conflict, and the ending role must be shown by a closing label, a literal header end date or the header year's duration end; the context dates already stored are joined for this without a schema change; this narrows D-15's "a column whose tagged cell moves the year".

### D-28 — Financial items are defined once
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: app/figures/items.py defines each financial item's key, accepted English and Korean phrases, accepted standard concepts and its English and Korean output labels; the question, row-label and answer readers and the cell-answer assembly consume that one definition, question-only synonyms and separate concept and label maps are removed, and every emitted label reads back as the same item.

### D-29 — Conflicting identities for one chunk or cell end the run
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: Within one question the chunk and cell ledgers keep identical repeats and keep a same-key disagreement until the next question; a disagreement ends the agent loop, the middleware path and the cell path alike as a system failure before another model call or a final answer, a malformed evidence extraction is a redacted system failure on every path, and one module (app/agent/ledger.py) owns the merge.

### D-30 — Reports state only what a check established, in the caller's resolved language
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: A period-mismatch report names the mismatched written figures or selected cells and the fiscal years they were found for and never states that the filing lacks the requested year; not-found and cannot-resolve reports state checked facts or attribute the proposal to the model; every boundary that authors a localized report (agent loop, middleware, workflow, cell selection and their report builders) requires the caller's resolved locale as a keyword with no default, and no reader infers the language from the answer text; this restates the report and language clauses of D-16 for every path.

### D-31 — A cell catalog says why it has no cells
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: The cell catalog of a fetched chunk is available, not_table, missing_records (the stored table rows are missing) or stale_reading (the table was read by other builder or resolver code, with the stored and the running identity pairs); the two non-available table states give no selectable cells and give the figure check neither body nor cells; evaluation snapshots keep serving their frozen readings; this replaces the single "unavailable" state of D-12.

### D-32 — The live experiment accounts money by request and takes issuer names from the application
- status: active
- category: tooling
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: Issuer-name enumeration lives in app.query.scope beside ManifestScopeIndex and raises query-domain errors that only script entry points turn into a process exit before claiming a run; the live script's accounted_usd is the sum over requests of the larger of the reserved estimate and the observed cost, a response whose usage is unknown keeps its reservation, the token and response counters are named for what they count, and a refusal before sending ends as budget_exceeded rather than provider_error; no alias for the old field names is kept (D-3: no stored consumer).

### D-33 — A figure that can be neither confirmed nor refuted is withheld with typed causes
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (survey of conflicting documents and code, repaired without stopgaps; survey and implementation reports recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: The figure-check verdict is withheld and carries a non-empty, ordered, closed tuple of causes from scale, currency and direction, established by the comparison that could not decide; the cell statuses that withhold map to their cause beside the status definitions; the shared English and Korean sentence and rationale name only the causes that occurred (the scale cause is worded as the unit); the public label stays UNVERIFIED, the workflow reason code is figures_withheld and agent results and states use withheld; the name unit_unverified, its constants and its fixed unit-or-sign sentence are removed without an alias because no stored record carried them (checked 2026-11-11: no row in the local database, never on main); this replaces the sentence clause of D-19.

### D-34 — The years a question asks for are read by the shared period forms
- status: active
- category: interface
- date: 2026-11-12
- source: 2026-11-12 consolidation session on mcp-and-langgraph (review of the evaluation lessons found the requested-year reader apart from D-20 and D-24; recorded in the Second Brain log 2026-11-12-doc-code-consolidation)
- decision: app.query.periods reads a question's requested fiscal years from four-digit years, relative wording resolved against the question date, and the explicit fiscal identifiers and identified annual endings of app/figures/periods.py, so an explicit two-digit FY asks for 2000–2099 and the end date of an ending that carries an identifier is not a second requested year; identifiers joined by a hyphen straight after a digit or by a slash are a range of two years on every reader, so such a header dates no column; a two-digit number followed by a hyphen and one letter (10-K, 20-F) is a filing form number and no year; a follow-up that names a year in any of these forms removes every such form from the turn it continues, and the follow-up detector accepts a two-digit identifier as it accepts a four-digit one.

### D-35 — The OPS-era role files are removed
- status: active
- category: workflow
- date: 2026-11-12
- source: user instruction in the 2026-11-12 consolidation session on mcp-and-langgraph
- decision: WORKER.md, MODERATOR.md, INTERACTIVE.md and AUTO.md are deleted together with the AGENTS.md rules that existed only for their roles: worker delivery and review states, the OCCUPIED/REVIEW_READY/MERGE_READY label flow, reviewer, resolver and moderator authority, INTERACTIVE sessions and the shared-defaults block; the maintainer flow through commit-it, the commit identity, the Git, engineering, documentation and runtime rules and this ledger remain.

### D-36 — Stale and overlapping documents are removed
- status: active
- category: scope
- date: 2026-11-12
- source: user instruction in the 2026-11-12 consolidation session on mcp-and-langgraph
- decision: A document stays in the repository only while something current reads it: the README, the paired tutorials, the deployment guides, the development story the web app serves, AGENTS.md and this ledger; docs/README_archive.md, docs/refactor-2026-09.md with its evidence appendix, docs/draft.en.md, docs/draft.ko.md, docs/draft/DEVELOPMENT_STORY_OUTLINE_draft.md, tests/RULES.md and NOTES.md are deleted, and the test-layout rules live in AGENTS.md.

### D-37 — The study branch lands on main by rebase merge
- status: active
- category: workflow
- date: 2026-11-12
- source: user instruction in the 2026-11-12 consolidation session on mcp-and-langgraph
- decision: mcp-and-langgraph is rebase-merged into main once study and implementation are complete, and main and the running service stay unchanged until then; AGENTS.md holds only rules that apply now, in one editable-on-request file, and names no model other than the gpt-6-astra study session.

### D-38 — A later filing decides which stored text is evidence
- status: active
- category: interface
- date: 2026-11-12
- source: issue #231; user decisions in the 2026-11-12 session on feat/231-amendment-evidence (DART is included, the design that ties filings together is new, embedding calls for it are approved)
- decision: Every filing a registry holds for a report period is recorded in filing_versions as soon as acquisition lists it, grouped by registry, issuer id and report period, and a stored chunk is evidence only while app.amendments.policy.eligible_chunk admits it; that one predicate restricts live ranking before any rank limit, every read of a chunk by id (the agent's fetch and final-answer review, pinned selections), snapshot creation, the index fingerprint and golden authoring, while a snapshot keeps serving what it froze; a later whole report (every DART filing, a second 10-K) replaces the earlier one as soon as it is known, a 10-K/A applies per Item only through an operator review that decides replace, add or withhold for every Item its chunks carry, and the whole report period is held while an amendment is unreviewed, no report is known or two filings of one kind share an order key (the DART receipt number or the EDGAR acceptance time; an amendment always follows its report), and listing the filings again completes a missing EDGAR acceptance time only for filings of one kind that share a report period, leaving every other recorded entry as it was; a document with no recorded version is not evidence, so a database indexed earlier runs `python -m scripts.schema filings` once; a review is withdrawn when its amendment is indexed again from another source or with an undecided Item; held evidence is reported as such (evidence_holds on retrieval and on the administrator's retrieval preview, the evidence_held workflow reason, holds in tool results) instead of reading as absence, and a search that names only replaced documents of a report period is told so with the reason replaced.
- note: BM25 corpus statistics still count held and replaced chunks; that shifts term weights slightly and never returns such a chunk.
