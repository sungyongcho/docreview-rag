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
- For this worker's completed PR, reuse the implementation and tester results, briefly
  inspect the final diff and immediately post `OK` if no blocker remains.
- Review corrections must state the actual issue, exact file/diff line, trigger and
  expected result, concrete fix direction and recheck. Use `Changes requested` with
  CORRECTNESS, CONTRACT, DATA_INTEGRITY, AUTHORIZATION, PERFORMANCE, VERIFICATION or
  INTEGRATION as applicable; do not invent defects or issue numbers.
- Keep reviews concise and bound to the reviewed head. Inspect only the changed delta
  when it moves; do not repost the same review. Label own-code OK as `Self-review`.

## Project-specific contract — uneditable by default

**Edit boundary:** change this section only on an explicit user request targeting the
corresponding rule. Do not weaken or move protected rules during routine maintenance.
User directions and higher-priority instructions still prevail.

### Role and authorization

- This contract overrides conflicting AGENTS.md issue-management, merge, checkout,
  staffing and cleanup rules for assigned workers. Engineering requirements still apply.
- Solve assigned work, verify it, publish its PR/review result, then continue the approved
  queue. Never create/edit/assign/close issues or manage unrelated Dependabot PRs.
- Follow AGENTS.md branch/message/issue-link rules, including issue-free documentation PRs.
- Approved implementation includes scoped commits, ordinary pushes and PR publication;
  do not ask again. Review-result publication (`OK` / specific change requests) is also
  authorized. None of these authorizes merge, deployment or local-main integration.
- Never merge/cherry-pick into local main, advance its ref, pull it, switch the user's
  checkout, stash/reset user work or restart shared services. Maintainers own main.
- Shared GitHub authorship is not worker ownership. Use a comment review when formal
  self-review is disallowed. Never mark unfinished work or a pending required check OK.

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
