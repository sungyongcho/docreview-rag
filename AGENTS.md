# AGENTS.md — DocReview

## Editable operating rules

Primary readers: `gpt-6-astra` and `fable-5.1`. Use this concise contract rather than
adding model-specific rituals or generic checklists.

- Assigned issue implementers are workers: read [WORKER.md](WORKER.md) first. Its role
  rules govern delivery, queue management, staffing, integration and PR reviews.
- Workers and models are replaceable; project continuity lives in assignments, issues,
  PRs, preserved commits and reproducible tests, not a surviving conversation. Successors
  preserve verified evidence and improve outcomes through affected tests. A different model
  or a new conversation alone proves neither progress nor independent review.
- Complete the approved outcome with the smallest reliable diff. Preserve foreign
  staged, unstaged, untracked and ignored work. No unsolicited cleanup or refactoring.
- Inspect the named behavior, its definitions, direct callers and relevant tests.
  Read an instruction or source once; reopen only when it changed or a concrete
  uncertainty requires it. Do not repeatedly scan the repository or issue backlog.
- Reuse the tester's passing evidence while code, inputs and environment remain valid.
  Implementation → review → commit → PR is not a reason to repeat investigation or
  tests. Review only the new delta after a relevant change; never hide a failed gate.
- Resolve discoverable facts directly and make routine choices autonomously. Continue
  an approved sequence without repeated permission. Ask only for material ambiguity,
  changed scope/risk or an action outside existing authorization.
- Match staffing to total work: use one agent for coupled work; delegate bounded,
  independent ownership when it saves time. The user authorizes routine staffing
  changes within runtime limits. Keep shared contracts and Git writes with one owner.
- Keep status concise: outcome, meaningful change, blocker or next required action.
  Report checks as passed, failed, blocked or not run. No repeated unchanged updates.
- Keep task-specific queues, commit IDs and test counts in the PR/task, not these rules.
  Do not turn discoveries into instruction edits without a user request.

## Project-specific contract — uneditable by default

**Edit boundary:** change this section only when the user explicitly requests the
corresponding project-rule change. Ordinary implementation or instruction cleanup is
not permission to weaken, relocate or relabel protected rules. Apply the same boundary
to WORKER.md. Higher-priority instructions and explicit user directions still prevail.

### Authority and delivery

- Ordinary worker implementation ends with PR delivery and its review result. An explicitly
  user-designated `conflict-resolver` may fix, verify and squash-merge only its authorized PR
  set through the sequence protocol in WORKER.md. A review label alone grants no merge,
  deployment or local-main authority.
- Successful review comments must start with exactly `Self-review: LGTM` for work the
  reviewer authored or `Review: LGTM` for another worker's work. Authorized conflict resolution
  uses `Conflict resolution: LGTM`, bound to head/base/tree and sequence revision/order.
  These are the only approval headings; preserve original authors and actual worker IDs.
  Conflict approval is not independent human review or authorization by itself.
- Non-worker maintainers follow the user-authorized commit-it tracking/delivery flow
  (installed skill, currently 3.0.0). Reread its current source and references when
  another conversation may have updated it; these repository rules still override it.
  Scoped implementation authorization covers issue tracking, commit, ordinary push,
  PR, verified squash merge and checkout synchronization only for that maintainer role.
- Creating/deleting issues, changing issue scope, assigning people, merging or
  synchronizing a checkout must never be inferred for an ordinary worker from the general
  maintainer workflow. Ordinary workers may maintain only their assigned ownership/status
  comments and their managed labels under WORKER.md; this exception does not authorize
  issue-body edits. Explicit user-approved takeover also authorizes recording that scoped
  ownership transfer without another approval or a reply from the previous worker.
- For the maintainer's configured automation, code/configuration commits use
  `Sungyong Cho <dev@sungyongcho.com>` as both author and committer; development
  pushes and PR creation authenticate as `sungyongcho`.
- `sungyongcho-ops` records authorized intake, ownership and handoffs, status, actual pushed
  commit SHAs and PR links, managed labels, and automated COMMENT reviews. Use the central
  OPS policy and guarded commands described in WORKER.md. DEV/OPS classify work purpose;
  OCCUPIED/REVIEW_READY mirror verified state across issues and PRs. Preserve unrelated
  labels. Account separation does not expand worker authority.
- Preserve existing history and active assignments. External contributors retain
  their own identities; do not switch global credentials or foreign worktrees.
- Destructive user-data actions, credentials, deployment, protection changes, meaningful
  paid work and rewriting published history require their own authorization.
- Communicate in Korean. Write code, comments, docstrings and GitHub messages in English;
  preserve required Korean UI text and paired Korean/English guides.

### Git and tracking

- `main` is stable/default. `v1` is a frozen parentless legacy archive: never modify it
  or merge it into main. `v2.0.0` identifies `61cb17b49b0b6bf0745b6fb7cfdd16b67d101731`.
- Branches: `<type>/<actual-issue-number>-<description>`. A directly requested,
  issue-free documentation PR may use `docs/<description>`; do not invent an issue.
  Use release tags, not product-version prefixes on ordinary branches.
- Commit/PR titles use English Conventional Commits: `<type>(<scope>): <outcome>`.
  Commit bodies contain Summary, Changes, Verification and applicable `Refs`. Conflict
  resolution commits and squash messages also preserve the sequence metadata in WORKER.md.
  No internal assembly-stage labels, unsolicited breaking-change markers or attribution
  footers. Stage explicit paths and use files for multiline commit/PR text.
- Link every delivered issue. `Closes` means its full scope is complete; use `Refs` for
  partial delivery. Opening a PR is not permission to close an issue directly.
- For authorized issue intake, reuse related issues and use Problem / outcome, Scope,
  Acceptance checks with observable checkboxes. Workers only read this issue record.
- Keep `core.hooksPath=.githooks` in clones. Never bypass hooks or hide foreign changes
  with stash/reset. Fetch before integration/publication and inspect divergence.
- The maintainer's canonical local branches are main/v1; worker backup refs are retained
  under WORKER.md. Legacy assemble/zero/new workflows and checkpoint stamping are retired.
- Living drafts #37 (`docs/29-project-ideas`, `ideas.md`) and #38
  (`docs/30-development-log`, `docs/DEVELOPMENT_STORY_OUTLINE.md`) retain user wording and
  only their own file. Never merge them without a specific request; general merge
  requests exclude them. Do not overwrite their authors' active changes.
- Genuine Dependabot maintenance is authorized for non-worker maintainers: inspect exact
  author/head/diff and compatibility, pass relevant gates, then use the normal verified
  squash policy. Close only with a concrete reason; never bypass protection or suppress
  advisories. Workers do not manage unrelated Dependabot PRs.

### Engineering and verification

- Import from defining modules. Package `__init__.py` files do not re-export symbols
  except `app/retrieval`; do not add unnecessary package files or import compatibility shims.
- Mirror implementation tests: `app/X/y.py` → `tests/X/test_y.py`. Multi-module behavior
  uses `tests/X/test_NN_<behavior>.py`, numbered per directory. Share helpers through
  support modules, never import one test module from another.
- Document private/nested helpers too. Test docstrings are 1–3 lines without NumPyDoc
  sections. Reuse nearby fixtures; do not reproduce production logic inside tests.
- ORM models in `app/db/models.py` precede persistence users; schema contracts live in
  `tests/db/test_models.py`. Preserve source, chunk, citation and selection identity.
- Start with relevant behavioral checks and scoped Ruff/format, then affected type/build
  checks. Verify checker availability; do not repeat the retired claim that it is absent.
  Always review the diff and run `git diff --check` before delivery.
- SQL/schema/pgvector changes require actual isolated PostgreSQL verification with
  `-m live_postgres --require-live-postgres`. Mock or skipped checks are not live proof.
  Never use the user's database as a disposable fixture or run concurrent DB writers.
- Full clean-checkout/image gates require release impact or an explicit requirement.
  Run required checks once for the final relevant state; reuse valid results thereafter.

### Documentation and runtime

- Changed user flows update affected `docs/TUTORIAL/en/` and `docs/TUTORIAL/ko/`; update
  README/CLI guidance only when affected. If no tutorial impact, explain that in the PR.
- Preserve screenshot assets unless the user requests captures. For missing visual
  evidence, add `### SCREENSHOT NEEDED` and an adjacent HTML comment naming the feature,
  exact state, locale and expected evidence. Never present old/synthetic images as proof.
  Requested captures use actual states, light mode and both locales unless narrowed.
- Local Compose uses `docker/docker-compose.yml`; the dev/prod overlays set runtime and
  preview behavior. Deployment uses `deploy/gcp/docker-compose.deploy.yml`, separately
  authorized. `.env` does not choose Compose files. A changed public bundle mode needs a build.
- `MODE` selects the OpenAI key slot (development `OPENAI_API_KEY_LOCAL`, production
  `OPENAI_API_KEY_PROD`); production rejects local engines. `DOCREVIEW_ADMIN_MODE` controls
  backend authority; `NEXT_PUBLIC_ADMIN_MODE` controls the web bundle. Keep them distinct.
- Diagnose typed failures: workflow budget (`resource`, `limit`, `observed`, `blocked_node`),
  provider failure (`status`, `attempts`, `details`, optional numeric budget/source), or
  node error (`error_type`, `message`, `node`). Wall-clock seconds are not token counts;
  provider and workflow ceilings can differ. Never guess which resource failed.
- Jobs are queued/running or succeeded/failed/cancelled/interrupted. Interrupted work
  does not resume automatically; failed/interrupted jobs may expose an explicit retry.
