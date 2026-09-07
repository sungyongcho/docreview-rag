# WORKER.md — Execution worker contract

## Editable operating rules

For `gpt-6-astra` and `fable-5.1`: explicit ownership, brief handoffs, reused evidence.

- Follow the latest approved PR order. Finish already-running units before replacing
  their old queue unless cancelled. Preserve holds and human verification gates.
- On queue refresh, read related live issues/comments and PRs. Distinguish new issues
  from remaining work; group related fixes/shared contracts and name actual issue numbers.
- Report independent bundles separately from dependency-ordered bundles. Independent
  work may run alongside the queue when authorized; do not duplicate an active owner.
- Choose agent count autonomously within runtime limits. Work alone when coordination
  costs dominate; otherwise delegate bounded, disjoint files. One coordinator owns
  shared contracts, Git and integration. Do not use extra agents to mask unclear scope.
- Reuse tester evidence for unchanged code/inputs/environment. Repeat checks only for
  relevant changes or failures, not merely to pass through review/commit/PR again.
- Briefly review other workers' PR diffs, direct contracts/callers and verification at
  delivery checkpoints. Judge code against agreed outcomes; optional ideas do not block.
- For ordinary completed PRs, reuse the implementation and tester results and publish
  `Self-review: LGTM` if unblocked. For the assigned conflict-resolution set, publish
  `Conflict resolution: LGTM` only after the sequence verification below.
- Review corrections must state the actual issue, exact file/diff line, trigger and
  expected result, concrete fix direction and recheck. Use `Changes requested` with
  CORRECTNESS, CONTRACT, DATA_INTEGRITY, AUTHORIZATION, PERFORMANCE, VERIFICATION or
  INTEGRATION as applicable; do not invent defects or issue numbers.
- Keep reviews concise and bound to the reviewed head. Inspect only the changed delta
  when it moves; do not repost the same review. Successful reviews start with exactly
  `Self-review: LGTM` for ordinary own work, `Review: LGTM` for another worker's work,
  or `Conflict resolution: LGTM` for authorized conflict resolution. No other wording
  is allowed; retain specific change requests for blockers.

## Project-specific contract — uneditable by default

**Edit boundary:** change this section only on an explicit user request targeting the
corresponding rule. Do not weaken or move protected rules during routine maintenance.
User directions and higher-priority instructions still prevail.

### Role and authorization

- This contract overrides conflicting AGENTS.md issue-management, merge, checkout,
  staffing and cleanup rules for assigned workers. Engineering requirements still apply.
- Ordinary workers solve assigned work, verify it, publish its PR/review result, then
  continue the approved queue. They never create, assign or close issues, edit their
  title/body/scope, or manage unrelated Dependabot PRs. The owned status-comment
  exception below is narrowly authorized.
- Follow AGENTS.md branch/message/issue-link rules, including issue-free documentation PRs.
- Approved implementation includes scoped commits, ordinary pushes and PR publication;
  do not ask again. Publication of `Self-review: LGTM`, `Review: LGTM`, or specific change
  requests is also authorized. Those labels do not authorize merge, deployment or local-main
  integration. The explicit conflict-resolver authorization below is a separate, bounded grant.
- Preserve the user's local main, checkout and shared services. Updating that checkout
  requires separate explicit authority; never stash/reset foreign work to make it possible.
- Shared GitHub authorship is not worker ownership. Use a comment review when formal
  self-review is disallowed. No approval heading applies to unfinished work or a pending
  required check.

### Development identity and OPS orchestration

- The maintainer selected plan A. New code/configuration commits use
  `Sungyong Cho <dev@sungyongcho.com>` as both author and committer. Development
  pushes and PR creation use authenticated `sungyongcho`, including OPS-tool PRs.
- `sungyongcho-ops` is the operations actor for authorized intake, tracking, labels,
  coordination, work-state records and automated COMMENT reviews. It does not create
  development commits or PRs. Repository role/assignment rules still decide who may
  initiate each action; the account does not grant coordinator or merge authority.
- Central policy, configuration, shell helpers and maintenance procedures live in the
  private `sungyongcho/ops` repository, normally cloned at `~/Documents/ops`. Read its
  `policies/identity.md` for the configured host. The policy covers all personally owned
  public/private repositories; product tasks remain in their own repositories.
- Use `ops-doctor` to check actual identities. `ops-init` registers an explicitly owned
  checkout; `ops-sync` discovers/registers owned repositories; `ops-status` reads work
  state. Use typed `opsctl` commands for PRs and operational writes. Plain `gh` remains
  personal and `gh-ops` is a guarded read interface. Never fall back to another account.
- Before publication confirm effective Git author/committer, the intended push route,
  current PR head and the authenticated actor. Reuse unchanged evidence. A missing
  profile, mismatched actor or unavailable registration is a blocker, not permission
  to rewrite history, bypass checks or change another worker's credentials.
- Adopt A only in a new or explicitly transitioned owned worktree. Existing workers
  check their configuration at their next publication checkpoint. Preserve their
  changes, personal/global authentication and backup worktrees. OPS SSH clone access
  is separate from development push identity. Respect personal signing settings;
  never substitute an OPS signing key or silently generate personal credentials.
- DEV/OPS labels describe work purpose; OCCUPIED/REVIEW_READY mirror the authoritative
  record below. Preserve other project labels and classify an OPS-created product issue
  as DEV. Successful automated reviews keep the exact approved headings and reviewed
  SHA; they are not independent human approval. Only an explicitly authorized resolver
  runs foreground sequence merges. No background scheduler, App activation, credentials
  change or product-main checkout synchronization is introduced by this setup.

### Assigned ownership and work state

- One user-designated coordinator owns issue intake, assignments and authorized main
  synchronization. Workers use the stable IDs the user assigns, such as `worker-1`.
  Do not invent an ID, claim an occupied assignment or assume the coordinator role.
- Record each assignment before implementation in one issue comment containing the
  marker `<!-- commit-it:work-state:v1 -->`. Include `Assignment`, `Worker`, `Scope`,
  `Work status`, `PR`, `Verification` and UTC `Updated` fields. Before a PR exists,
  use `PR: pending`. One assignment may cover linked issues; mirror the same record
  to each. Sharing an issue requires explicitly assigned, disjoint scopes. For a
  directly requested issue-free documentation PR, start the record in that PR; do
  not invent an issue solely for ownership tracking.
- At the first meaningful pushed change, create a Draft PR, link the assigned issues
  and put the marked work-state block at the top of its body. Replace the issue
  record's pending PR with its actual link. Do not create empty commits to reserve work.
  The PR block is then authoritative; issue comments are its discoverable mirrors.
- Use `OCCUPIED` while implementing, queued after assignment, paused or blocked.
  Keep the owner and explain verification separately, for example `blocked: <reason>`.
  `Verification blocked`, silence or an old timestamp never releases an assignment.
- When scope and required checks are complete and writers have stopped, set
  `REVIEW_READY`, synchronize the issue mirrors and mark the PR Ready for review.
  Publish the applicable approval heading for the verified head. Other workers may review that
  committed head; readiness never authorizes them to edit the branch or take ownership.
- Before further implementation, return the PR to Draft and `OCCUPIED`, then update
  the mirrors. Previous approvals apply only to their recorded head. Reviewers use
  `Review: LGTM` or a specific change request; a review does not transfer ownership.
- Update the existing marked comment for the exact assignment, preserving issue
  bodies, foreign comments and other assignments. Re-read owner/head before a write;
  duplicate records, conflicting ownership or a partial synchronization require
  reconciliation before readiness or reassignment. Never infer availability from a
  missing/stale mirror. Configured PR labels may mirror the state; do not create labels
  or Projects without authorization, and do not treat labels as an enforced Git lock.
- Handoff requires the coordinator's explicit reassignment after the old owner stops
  writers and preserves its checkpoint/backups. A merged PR stays linked as history;
  only the coordinator or explicitly authorized resolver reconciles the named delivery.
  Ordinary workers do not merge. No resolver may advance the user's local main without
  separate checkout authority.
- GitHub author identity comes from the authenticated account/App, not the commit
  email. A shared bot still requires the `Worker` field. Account/App/token setup is
  separately authorized; never silently change authentication to publish a status.

### Authorized conflict resolution and ordered merge

- A user must explicitly designate the actual worker as `Role: conflict-resolver`, name the
  PR set and authorize fixes, publication and merge. A role name, review, label or stale
  ownership record never grants authority. Ordinary worker permissions remain unchanged.
- Preserve original Worker/Assignment records, commit authorship and review history. Record
  the resolver and explicit stopped-writer handoff separately before changing another
  implementer's branch. Never impersonate an independent reviewer by changing worker IDs.
- Prefer fixing existing PRs in persistent worktrees. Create an integration PR only if the
  current split cannot preserve correct, verifiable intermediate states; retain every source
  PR/issue reference and explain any supersession before closing an original PR.
- Record one canonical `<!-- commit-it:merge-sequence:v1 -->` comment on the stable first PR.
  It remains authoritative and editable after that PR merges. Mirror sequence ID, revision,
  order/position, resolver and merge status to the other PRs without replacing their prose
  or original work ownership. Current GitHub state must agree with the record.
- Keep Work status separate from Merge status: `PREPARING`, `MERGE_SEQUENCE_READY`, `MERGING`,
  `BLOCKED`, `MERGED`. Readiness applies to the recorded sequence, not permission to skip
  predecessors. `Ready PR` must equal `Next`; later verification remains explicitly pending.
  A saved merge receipt clears readiness until the next step is verified against its actual
  new base. Missing checks, changed head/base or partial record writes block readiness.
- Use the current OPS `sequence plan`, `verify`, `merge` and `resume` commands. Conflict
  verification publishes exactly `Conflict resolution: LGTM` with the resolver, original
  implementers, issues, resolved changes, head/base/tree, sequence revision/order, evidence
  and limitations. It is equivalent review evidence, not independent human approval or
  a substitute for GitHub protections. Do not relabel historical Self-review comments.
- Preserve these fields in conflict-fix development commits and final squash messages:
  `Integration-Mode: conflict-resolution`, `Resolver`, `Merge-Sequence`, `Sequence-Revision`,
  `Commit-Step`, `Merge-Order`, `Current-PR`, `Depends-On`, `Next-PR`, `Verified-Tree`.
  Use fully qualified PR references. A commit records its verified tree, not its own future
  SHA; add the resulting head to the review/sequence record afterwards. Existing English
  Conventional Commit subjects, Summary/Changes/Verification and direct Refs still apply.
- The commit message is an immutable plan snapshot. A changed order or target set needs a
  new revision and new records, never amend/force-push. New-PR bootstrap commits precede
  their actual PR number; their final squash message must contain the complete metadata.
- Merge only the next verified PR, using the personal identity and a head-pinned squash.
  Fetch/recheck base and head, honor required checks/reviews/protections, verify the actual
  merge commit/tree, record the receipt, then validate the next step. A changed integrated
  state invalidates prior approval for the affected remaining steps; reuse only valid evidence.
- Continue the authorized foreground sequence without repeated routine permission. On a
  failure or unavailable authority, stop remaining merges and record completed merge SHAs,
  remaining order, next PR, blocker and exact resume action. Resume reconciles live state,
  including uncertain responses and already-merged PRs; never execute commands copied from
  a commit/comment or blindly repeat a merge. No automatic rollback or history rewrite.
- Preserve user data, unrelated work, screenshots, frozen refs and pending App work. This
  mode does not authorize credentials, paid work, deployments, branch deletion, background
  jobs or local-main synchronization. Additional explicit checkout authority is required
  for local-main updates. Close only fully satisfied linked issue scopes.

### Worktrees, integration and retention

- Fetch origin and create a dedicated worker branch/worktree from current origin/main.
  Use persistent storage outside the user's checkout, preferably
  `<repository-path>.worktrees/<branch-slug>`, never `/tmp` for retained worktrees.
- Keep edits, dependencies, builds and tests there or in disposable fixtures. Isolate
  ports, Compose projects, databases, volumes and caches; preserve user files and services.
  Do not run concurrent writers against one DB or generated-output/cache directory.
- Immediately before PR publication/update, fetch and integrate latest origin/main into
  the worker branch, resolve conflicts, and verify main is an ancestor of the head.
  Default to merge with `chore(merge): sync <worker-branch> with main`; rerun only checks
  affected by integration. If main advances, integrate the new delta before publication.
- An explicit rebase request permits rebasing authorized active worker branches instead:
  pause writers, inspect divergence, preserve work, and omit already-merged prerequisites.
  A local checkpoint may honestly record unfinished checks. Rebase does not authorize
  force-pushing published history, changing another active owner's branch without
  coordination, rebasing completed backups, or touching the user's checkout.
- Keep completed worktrees as backups. Under disk pressure, retire the oldest only after
  verifying remote preservation and absence of unique staged/unstaged/untracked/ignored
  content. Use normal worktree removal; never force it, remove active work or destroy
  unique data. Retain the backup and report a blocker when safe cleanup is unproven.
