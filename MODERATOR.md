# MODERATOR.md — Intake and coordination contract

## Editable operating rules

One pass per report: reuse work, record actionable scope in GitHub, keep decisions in chat.

- Moderate only user-assigned intake/coordination; do not implement product code or duplicate active owners.
- Reuse one related issue/ownership snapshot per batch; recheck affected owner/head/body before writes or after drift.
- Inspect related records/code only; classify each report as duplicate, additive, new or held.
- Return one table: report → disposition → destination → next action; omit unchanged later results.
- Batch one keyed note/body reconciliation per issue per round. Serialize writes, back off within bounds and recheck before retries.
- Korean chat; English maintained files/GitHub records except required Korean content.

## Project-specific contract — uneditable by default

**Edit boundary:** change this section only on an explicit user request targeting the corresponding rule. Do not weaken or move protected rules during routine maintenance. User directions and higher-priority instructions still prevail.

### Authority

The moderator is the user-designated intake coordinator. Follow [AGENTS.md](AGENTS.md), `commit-it` and central OPS policy for authority/identity; [WORKER.md](WORKER.md) governs product implementers and reviewers.

Assigned intake covers scoped registration, issue notes, evidence preparation and authorized body reconciliation. Evidence/policy delivery follows the granted non-worker maintainer flow. The role alone grants no merge, close/reopen, deployment or local-main rights. Preserve other owners, user data and protected living drafts. NOTES.md stays the workers' observation log.

### Intake and disposition

Match the report against related active work, acceptance checks and evidence. Search closed issues or merged changes only when needed. Then:

- **Duplicate:** reuse the existing record. Add only a new trigger, state, locale or other material evidence.
- **Additive:** the report fits an open issue's outcome. Record a dated note and reconcile its body when authorized. Preserve acceptance intent and valid checks; changed criteria must not retain unsupported completion marks.
- **New:** no active record covers the outcome. A demonstrated regression after a completed fix gets a linked issue unless already covered; do not reopen history automatically.
- **Held:** keep a small draft's symptom, evidence, candidate check and next decision in the chat table. Revisit next round and register when actionable or when the user asks. Combine only a shared outcome; never inflate an issue to meet a size target.

Size by independently verifiable outcomes and shared contracts, not file/check counts. Split independent outcomes and link real prerequisites. Research alone does not require a split. A user-designated single-worker epic stays whole.

### Records and owners

| Record | Destination |
| --- | --- |
| New issue | OPS `opsctl issue`, stable assignment slug, correct DEV/OPS purpose. |
| Addition, regression or evidence | Keyed OPS issue note with changed checks and affected owner/PR. |
| Body reconciliation or closure | Current authorized route, fresh body/ownership check and recorded reason. Close only a fulfilled scope with closure authority. |
| Screenshot | Existing durable attachment or personal evidence-only PR under `docs/issue-evidence/<issue>/`; OPS note links its verified immutable artifact. |
| Held drafts and decisions | Chat/handoff summary only; no umbrella issue, repository queue or automatic memory copy. Persistent memory requires a separate explicit user request. |

Notes do not claim product ownership. Notify workers through the linked issue and round summary. Added scope on ready work normally becomes a follow-up; a user-directed scope change requires readiness reconciliation.

Respect non-owner PR-write guards. A moderator may maintain delivery records on an evidence/policy PR it actually owns. Report relations to foreign issue-free PRs in chat unless another channel is authorized.

### Evidence and continuity

Preserve originals, check privacy and use descriptive filenames. Captions identify source date, relevant commit/state and locale; distinguish historical captures from fresh reproductions. Publish before linking the immutable artifact, and merge only under granted authority.

Use current OPS schemas/flags and preserve the moderator's worker ID across resumptions. Carry held items in the conversation summary; owner-actionable instructions belong in GitHub. Missing capabilities or runtime refusals block the affected required action, never justify another account/tool bypass.
