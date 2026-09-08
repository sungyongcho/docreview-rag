
<!-- ops:project:INTERACTIVE.md:v1 -->
# INTERACTIVE — user-directed implementation and delivery

INTERACTIVE is a peer role to WORKER and MAINTAINER, selected by an explicit user
instruction for a named repository, task and scope. A role name or existing label alone
is not authorization. Ordinary workers retain their existing rules.

## User intent and iteration

The user's latest explicit request or correction in this session is the authoritative
requirement. Agent-invented changes are not user requirements. Compare the current
implementation with related issues when delivering a PR; do not restore obsolete
requirements merely to satisfy an old checklist.

Within the approved scope, repeat inspection, implementation and relevant verification
without asking for each ordinary step. The session grant includes personal commits,
ordinary push, PR updates, disclosed session self-review, verified merge and safe
fast-forward adoption of the named local main checkout. Credential changes, deployment,
paid work, destructive data actions and rewriting published history require their own
scope. Runtime/tool approvals remain effective.

## One writer per overlapping scope

Before editing, inspect current assignments, related PRs and target paths. Record exact
file/behavior ownership in the session issue and tell overlapping workers what changed.
Unrelated workers continue. If an overlapping writer is active, pause only the overlap,
preserve both checkpoints and use the guarded OPS handoff under the user's succession
grant. Never claim a writer stopped merely because a label or old message says so.
Recheck ownership before subsequent writes. Late conflict reports reopen this check.

Compare other implementations in a separate checkout/server port when useful; do not
silently replace the runtime the user is viewing. Latest user intent wins a conflicting
behavior decision, not every file or unrelated change in the INTERACTIVE branch.

## Issue and PR records

Use one session issue titled `ISSUE - INTERACTIVE #N` (N is the session ordinal, not a
fabricated GitHub issue number). Group PRs by a verified user-visible outcome. Preserve
original issue authors and historical evidence. Ordinary conversation is not copied to
GitHub. Keep one concise readiness/outcome summary.

Include `Requirement changes` only when old requirements differ:

| Source issue | Previous requirement | Latest user request and evidence | Disposition |
| --- | --- | --- | --- |
| #123 | Earlier behavior | Latest explicit session request | Complete, superseded, delta #456, or retain |

A completely fulfilled issue closes after verified merge. A wholly superseded issue
closes as not planned with the latest requirement/PR reference. If still-valid work
remains, create/link a concrete delta issue with acceptance criteria first, preserve
active owner lineage, then close the original. Do not copy unresolved unrelated work
into a closing PR. Unknown intent stays unresolved; no score or elaborate triage system.

## Delivery

Editing or failed verification stays OCCUPIED. Completion requires scoped code review,
relevant passing tests and recorded user-request evidence. User visual confirmation and
automated checks are separate evidence; neither invents independent review.

Use `opsctl interactive ready --file REQUEST.json`, then `merge` and `sync` with the
same request. The request pins repository, PR, session task, scope, exact head/base,
changed files, local checkout, verification, requirement decisions and explicit user
authority. An INTERACTIVE completion uses `Self-review: LGTM` with session disclosure.
No separate reviewer task is required. MERGE_READY is the verified destination of a
completed change group, never the status of every keystroke.

Changed head/base/checks or actual competing writes require renewed affected evidence.
Do not blindly refresh an expected SHA and overwrite another writer. After the personal
merge, reconcile remote receipts before retrying and fast-forward only a clean named
local main. Never stash/reset or replace dirty/divergent main. Recheck the visible result
and tell affected workers the new base; do not update their checkouts for them.

Session records and grants are audit evidence, not cryptographic proof of user input.
<!-- /ops:project:INTERACTIVE.md -->
