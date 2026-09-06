# Worker Contract

For user-assigned issue implementation, follow this contract before the general
workflow in AGENTS.md. It overrides conflicting repository rules about issue
management, merging, checkout changes, and cleanup. Other engineering and verification
requirements, explicit user instructions, and higher-priority rules still apply.

## Scope and delivery

- Solve assigned existing issues, verify the work, and publish a PR. Stop there:
  do not merge, close issues, or synchronize the user's checkout.
- Do not create, edit, assign, or manage issues or unrelated Dependabot PRs.
  Read relevant issues/comments and put implementation evidence in the PR.
- Propose directly related issues worth grouping, with a brief reason. Include easy
  related fixes within the authorized outcome; ask before materially expanding scope
  or risk. Link exact issue numbers; use `Closes` only for completed scope.
- Continue approved implementation, verification, commits, ordinary push, and PR
  publication without repeated approval. Ask only for material ambiguity or a
  separate authorization boundary.

## Isolation and integration

- Fetch `origin`; create a dedicated branch and worktree from current `origin/main`.
  Use `<type>/<issue-number>-<description>` for assigned issues. Only directly requested
  documentation-only work without an assigned issue may use `docs/<description>`, as
  allowed by AGENTS.md. Never invent or create an issue merely to name a branch.
- Place worker worktrees in a persistent directory outside the user's checkout,
  preferably `<repository-path>.worktrees/<branch-slug>`. Do not use `/tmp`, `/var/tmp`,
  or another automatically cleaned directory for worktrees retained as backups.
  Temporary directories are suitable only for disposable verification resources.
- Keep edits, builds, dependencies, and tests in that worktree or disposable resources.
  Isolate service ports, Compose projects, databases, volumes, and caches. Preserve
  the user's existing checkout, branch, files, terminal environment, and services.
  Never stash, reset, switch branches, or restart shared services there.
- Immediately before PR publication or updates, fetch and merge the latest
  `origin/main` into the worker branch, resolve conflicts, and rerun affected checks.
  Confirm that fetched main is an ancestor of the PR head. If main advances before
  publication, repeat integration. If a merge commit is created, name it
  `chore(merge): sync <worker-branch> with main`. Do not rebase or force-push by default.
- Worker delivery ends at the codebase PR. Never merge or cherry-pick worker changes
  into local `main`, advance its ref, pull/synchronize it, or perform PR integration
  on the user's behalf. Integrating `origin/main` means updating the worker branch
  only; maintainers own integration into `main`.
- Publish only after integration succeeds; report unresolved conflicts or failed
  checks honestly. Include changes, verification, and relevant limitations in the PR.

## Efficient verification

- Map the changed behavior to directly relevant tests, callers, and contracts. Run
  the smallest meaningful regression first, then affected static checks and builds.
  Documentation-only agent rules need link/diff checks, not application suites.
- During fixes, rerun failing tests first; before delivery cover the full affected
  scope. A last-failed run is not a substitute for that scope's verification.
- Reuse passing evidence only while relevant source, configuration, dependencies,
  generated inputs, and runtime assumptions remain unchanged. After main integration,
  rerun checks affected by the integrated changes rather than every passing suite.
- Batch independent checks when resources are isolated. Never run concurrent writers
  against one database, generated-output directory, dependency installation, or cache.
- Measure slow checks with pytest `--durations=10` or runner timing before optimizing.
  Vitest already supports file parallelism; do not assume more workers are faster.
- Avoid repeated dependency installation and generation when inputs are unchanged,
  but preserve required generation/validation. Review shared scripts before bypassing
  lifecycle hooks. Full clean-checkout/image verification requires relevant release
  impact or an explicit requirement; never omit a required gate to save time.

## Worktree backups

- Retain completed worktrees in persistent storage after PR publication as local backups.
- During later work, under disk pressure, remove the oldest completed worktrees only
  after verifying their commits are preserved in the published PR's remote branch
  and no unique staged, unstaged, untracked, or ignored content would be lost.
- Use normal Git worktree removal; never force removal or delete active work.
  Preserve remote branches, PRs, user data, credentials, and shared Docker resources.
  If safe cleanup cannot be established, retain the backup and report the blocker.
