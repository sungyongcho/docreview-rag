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
  Use actual assigned issue numbers where applicable; never invent or create an issue
  merely to name a branch.
- Keep edits, builds, dependencies, and tests in that worktree or disposable resources.
  Isolate service ports, Compose projects, databases, volumes, and caches. Preserve
  the user's existing checkout, branch, files, terminal environment, and services.
  Never stash, reset, switch branches, or restart shared services there.
- Immediately before PR publication or updates, fetch and merge the latest
  `origin/main` into the worker branch, resolve conflicts, and rerun affected checks.
  Confirm that fetched main is an ancestor of the PR head. If main advances before
  publication, repeat integration. Do not rebase or force-push by default.
- Publish only after integration succeeds; report unresolved conflicts or failed
  checks honestly. Include changes, verification, and relevant limitations in the PR.

## Worktree backups

- Retain completed worktrees after PR publication as local backups.
- During later work, under disk pressure, remove the oldest completed worktrees only
  after verifying their commits are preserved in the published PR's remote branch
  and no unique staged, unstaged, untracked, or ignored content would be lost.
- Use normal Git worktree removal; never force removal or delete active work.
  Preserve remote branches, PRs, user data, credentials, and shared Docker resources.
  If safe cleanup cannot be established, retain the backup and report the blocker.
