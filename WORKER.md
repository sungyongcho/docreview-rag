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
  inspect the final diff and immediately post `Self-review: LGTM` if no blocker remains.
- Review corrections must state the actual issue, exact file/diff line, trigger and
  expected result, concrete fix direction and recheck. Use `Changes requested` with
  CORRECTNESS, CONTRACT, DATA_INTEGRITY, AUTHORIZATION, PERFORMANCE, VERIFICATION or
  INTEGRATION as applicable; do not invent defects or issue numbers.
- Keep reviews concise and bound to the reviewed head. Inspect only the changed delta
  when it moves; do not repost the same review. Successful reviews start with exactly
  `Self-review: LGTM` for own work or `Review: LGTM` for another worker's work. No other
  approval wording is allowed; retain specific change requests for blockers.

## Project-specific contract — uneditable by default

**Edit boundary:** change this section only on an explicit user request targeting the
corresponding rule. Do not weaken or move protected rules during routine maintenance.
User directions and higher-priority instructions still prevail.

### Role and authorization

- This contract overrides conflicting AGENTS.md issue-management, merge, checkout,
  staffing and cleanup rules for assigned workers. Engineering requirements still apply.
- Solve assigned work, verify it, publish its PR/review result, then continue the approved
  queue. Never create, assign or close issues, edit their title/body/scope, or manage
  unrelated Dependabot PRs. The owned status-comment exception below is narrowly authorized.
- Follow AGENTS.md branch/message/issue-link rules, including issue-free documentation PRs.
- Approved implementation includes scoped commits, ordinary pushes and PR publication;
  do not ask again. Publication of `Self-review: LGTM`, `Review: LGTM`, or specific change
  requests is also authorized. None authorizes merge, deployment or local-main integration.
- Never merge/cherry-pick into local main, advance its ref, pull it, switch the user's
  checkout, stash/reset user work or restart shared services. Maintainers own main.
- Shared GitHub authorship is not worker ownership. Use a comment review when formal
  self-review is disallowed. Neither approval label applies to unfinished work or a pending
  required check.

### Automation identity setup

- Setup status: `IN_PROGRESS`. `sungyongcho-ops` uses
  `OPS | Sungyong Cho <ops@sungyongcho.com>` for authorized automation in
  `sungyongcho/docreview-rag-agent` and `sungyongcho/dither-fm` only. Repository role
  rules still govern every action; machine authentication is not maintainer authority.
- The public profile, verified email, collaborator write access and separate CLI
  profiles are configured. Authenticator-app 2FA is enabled. Dedicated SSH authentication
  and signing keys and isolated Git configuration are prepared locally; GitHub key
  registration, passkey enrollment and remote delivery verification remain pending.
- Plain `gh` keeps the personal `sungyongcho` profile. Use `gh-ops` for authorized
  bot API/PR/review operations, with an explicit `--repo`. It removes inherited
  `GH_TOKEN`/`GITHUB_TOKEN` and selects `$HOME/.config/gh-ops`; credentials remain in
  the system keyring. It does not configure Git authorship or transport.
- Configure only a new or explicitly transitioned owned worktree. Do not change global
  identity, shared `origin` URLs, personal checkouts or another worker's configuration.
  Existing assignments retain their identity until their owner completes the transition.
  A clone must already enable `extensions.worktreeConfig`; inspect shared Git settings
  and obtain setup authorization before enabling it in an unconfigured clone.
- On this configured host, set the following with `git config --worktree`:

  | Setting | Value |
  | --- | --- |
  | `user.name` | `OPS \| Sungyong Cho` |
  | `user.email` | `ops@sungyongcho.com` |
  | `gpg.format` | `ssh` |
  | `user.signingkey` | `$HOME/.ssh/id_ed25519_ops_sign` (expand the path) |
  | `commit.gpgsign` | `true` |
  | `gpg.ssh.allowedSignersFile` | `$HOME/.config/gh-ops/allowed_signers` (expand the path) |
  | `remote.ops.url` | `git@github-ops:sungyongcho/docreview-rag-agent.git` |
  | `remote.ops.fetch` | `+refs/heads/*:refs/remotes/ops/*` |
  | `remote.pushDefault` | `ops` |

  Reset the inherited HTTPS helper list in that worktree, then add the bot helper:

  ```sh
  git config --worktree --replace-all credential.https://github.com.helper ''
  git config --worktree --add credential.https://github.com.helper '!gh-ops auth git-credential'
  ```

- `github-ops` selects the dedicated authentication key with `IdentitiesOnly yes`,
  batch mode and strict checking against the pinned GitHub host key. Fetch from `origin`
  and push the owned branch explicitly with `git push -u ops <branch>`. Confirm the
  effective push URL; an inherited `remote.ops.pushurl` must not redirect it. Never
  silently fall back to personal credentials or regenerate missing keys during delivery.
- At a publication checkpoint verify the CLI actor (`gh-ops api user --jq .login`),
  actual author/committer (`git var GIT_AUTHOR_IDENT` / `GIT_COMMITTER_IDENT`), SSH
  greeting (`ssh -T github-ops`) and local signature (`git verify-commit HEAD`). GitHub's
  successful SSH greeting normally exits 1. Verify the published commit's author,
  committer and signature and the PR/comment actor through GitHub. Reuse unchanged
  evidence within the same checkpoint; report a mismatch as a blocker.
- Preserve the named Worker ID and exact review labels. Keep private keys, tokens and
  recovery material outside repositories and logs. This setup does not authorize history
  rewriting, extra repositories, ownership transfer, merge or local-main integration.

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
  Publish `Self-review: LGTM` for the verified head. Other workers may review that
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
  only the coordinator reconciles closure. Workers do not merge or advance local main.
- GitHub author identity comes from the authenticated account/App, not the commit
  email. A shared bot still requires the `Worker` field. Account/App/token setup is
  separately authorized; never silently change authentication to publish a status.

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
