
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
