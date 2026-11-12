# AGENTS.md — DocReview

## Editable operating rules

For `gpt-6-astra` and `fable-5.1`: use this contract, not model-specific rituals or generic checklists.

- Continuity lives in assignments, issues, PRs, commits and reproducible tests. Replaceable workers/models preserve valid evidence and improve outcomes through affected tests; a new model or conversation proves neither progress nor independent review.
- Deliver the smallest reliable approved diff. Preserve foreign staged, unstaged, untracked and ignored work; no unsolicited cleanup/refactoring.
- Inspect the named behavior, definitions, direct callers and relevant tests. Reopen sources/instructions only after changes or concrete uncertainty; avoid repeated repository/backlog scans.
- Reuse passing tester evidence while code/inputs/environment remain valid. Workflow stages do not justify reruns; review changed deltas and never hide failed gates.
- Resolve discoverable facts and routine choices autonomously; continue approved sequences. Ask only for material ambiguity, changed scope/risk or missing authority.
- Use one agent for coupled work; delegate bounded independent ownership when efficient. Routine staffing is authorized within runtime limits; one owner controls shared contracts/Git writes.
- Report only outcomes, meaningful changes, blockers or next actions; classify checks as passed/failed/blocked/not run. Omit unchanged updates.
- Keep queues, commit IDs and test counts in PRs/tasks. Instruction edits require a user request.
- Consult [DECISIONS.md](DECISIONS.md) at session start and on any requirement change; treat active entries as standing decisions. When new instructions conflict with an active entry, surface the conflict for the user's decision before proceeding. Record outcomes by appending entries; mark superseded entries rather than deleting them.

## Personal project records

For registered local DocReview work, read the Second Brain project hub, TODO and its linked plan (`Projects/docreview-rag/` in the local Vault) at task start, and compare them with the actual checkout. At normal completion, follow the second-brain skill's recording workflow for verified TODO, plan and log updates. Personal planning and progress belong there; code, product documentation, raw experiments, this repository's decision ledger and delivery evidence retain their existing owners and authorization rules.

## Project-specific contract — uneditable by default

**Edit boundary:** change this section only when the user explicitly requests the corresponding project-rule change. Ordinary implementation or instruction cleanup is not permission to weaken, relocate or relabel protected rules. Higher-priority instructions and explicit user directions still prevail.

### Authority and delivery

- Maintainers follow the user-authorized commit-it tracking/delivery flow (installed skill, currently 4.0.0). Reread its current source and references when another conversation may have updated it; these repository rules still override it. Scoped implementation authorization covers issue tracking, commit, ordinary push, PR, verified squash merge and checkout synchronization only for that maintainer role.
- For the maintainer's configured automation, code/configuration commits use `Sungyong Cho <dev@sungyongcho.com>` as both author and committer; development pushes and PR creation authenticate as `sungyongcho`.
- Preserve existing history. External contributors retain their own identities; do not switch global credentials or foreign worktrees.
- Destructive user-data actions, credentials, deployment, protection changes, meaningful paid work and rewriting published history require their own authorization.
- Communicate in Korean. Write code, comments, docstrings and GitHub messages in English; preserve required Korean UI text and paired Korean/English guides.

### Git and tracking

- `main` is stable/default. `v1` is a frozen parentless legacy archive: never modify it or merge it into main. `v2.0.0` identifies `61cb17b49b0b6bf0745b6fb7cfdd16b67d101731`.
- Branches: `<type>/<actual-issue-number>-<description>`. A directly requested, issue-free documentation PR may use `docs/<description>`; do not invent an issue. Use release tags, not product-version prefixes on ordinary branches.
- Commit/PR titles use English Conventional Commits: `<type>(<scope>): <outcome>`. Commit bodies contain Summary, Changes, Verification and applicable `Refs`. No internal assembly-stage labels, unsolicited breaking-change markers or attribution footers. Stage explicit paths and use files for multiline commit/PR text.
- Link every delivered issue. `Closes` means its full scope is complete; use `Refs` for partial delivery. Opening a PR is not permission to close an issue directly.
- Issues use Problem / outcome, Scope and observable Acceptance checks. Ordinary issue messages/images do not create Git assets, commits or evidence-only PRs.
- Keep `core.hooksPath=.githooks` in clones. Never bypass hooks or hide foreign changes with stash/reset. Fetch before integration/publication and inspect divergence.
- The maintainer's canonical local branches are main/v1. Legacy assemble/zero/new workflows and checkpoint stamping are retired.
- Living drafts #37 (`docs/29-project-ideas`, `ideas.md`) and #38 (`docs/30-development-log`, `docs/DEVELOPMENT_STORY_OUTLINE.md`) retain user wording and only their own file. Never merge them without a specific request; general merge requests exclude them. Do not overwrite their authors' active changes.
- Genuine Dependabot maintenance is authorized for maintainers: inspect exact author/head/diff and compatibility, pass relevant gates, then use the normal verified squash policy. Close only with a concrete reason; never bypass protection or suppress advisories.

### Engineering and verification

- Import from defining modules. Package `__init__.py` files do not re-export symbols except `app/retrieval`; do not add unnecessary package files or import compatibility shims.
- Mirror implementation tests: `app/X/y.py` → `tests/X/test_y.py`. Multi-module behavior uses `tests/X/test_NN_<behavior>.py`, numbered per directory. Share helpers through support modules, never import one test module from another.
- Document private/nested helpers too. Test docstrings are 1–3 lines without NumPyDoc sections. Reuse nearby fixtures; do not reproduce production logic inside tests.
- ORM models in `app/db/models.py` precede persistence users; schema contracts live in `tests/db/test_models.py`. Preserve source, chunk, citation and selection identity.
- Start with relevant behavioral checks and scoped Ruff/format, then affected type/build checks. Verify checker availability; do not repeat the retired claim that it is absent. Always review the diff and run `git diff --check` before delivery.
- SQL/schema/pgvector changes require actual isolated PostgreSQL verification with `-m live_postgres --require-live-postgres`. Mock or skipped checks are not live proof. Never use the user's database as a disposable fixture or run concurrent DB writers.
- Full clean-checkout/image gates require release impact or an explicit requirement. Run required checks once for the final relevant state; reuse valid results thereafter.

### Documentation and runtime

- Changed user flows update affected `docs/TUTORIAL/en/` and `docs/TUTORIAL/ko/`; update README/CLI guidance only when affected. If no tutorial impact, explain that in the PR.
- Preserve screenshot assets unless the user requests captures. For missing visual evidence, add `### SCREENSHOT NEEDED` and an adjacent HTML comment naming the feature, exact state, locale and expected evidence. Never present old/synthetic images as proof. Requested captures use actual states, light mode and both locales unless narrowed.
- Local Compose uses `docker/docker-compose.yml`; the dev/prod overlays set runtime and preview behavior. Deployment uses `deploy/gcp/docker-compose.deploy.yml`, separately authorized. `.env` does not choose Compose files. A changed public bundle mode needs a build.
- `MODE` selects the OpenAI key slot (development `OPENAI_API_KEY_LOCAL`, production `OPENAI_API_KEY_PROD`); production rejects local engines. `DOCREVIEW_ADMIN_MODE` controls backend authority; `NEXT_PUBLIC_ADMIN_MODE` controls the web bundle. Keep them distinct.
- Diagnose typed failures: workflow budget (`resource`, `limit`, `observed`, `blocked_node`), provider failure (`status`, `attempts`, `details`, optional numeric budget/source), or node error (`error_type`, `message`, `node`). Wall-clock seconds are not token counts; provider and workflow ceilings can differ. Never guess which resource failed.
- Jobs are queued/running or succeeded/failed/cancelled/interrupted. Interrupted work does not resume automatically; failed/interrupted jobs may expose an explicit retry.
