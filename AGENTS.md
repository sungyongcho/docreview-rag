# AGENTS.md — DocReview

Edit this file only when the user asks for a rule change.

## Working rules

- Resolve discoverable facts and routine choices yourself and continue an approved sequence. Ask only for material ambiguity, changed scope or risk, or missing authority.
- Fix the kind of defect, not one instance of it, and do not mark a defect and leave it. Say that something works only after running it.
- Preserve work that is not yours: staged, unstaged, untracked and ignored files, other worktrees and other contributors' identities. Never hide it with stash or reset.
- Report outcomes, meaningful changes, blockers and next actions. Classify each check as passed, failed, blocked or not run, and never hide a failed one.
- [DECISIONS.md](DECISIONS.md) records standing decisions about the code. Read the entries for the area you change. A user instruction that contradicts an active entry replaces it: mark the entry superseded, append the new one and say so in the report.
- Personal planning and progress live in the Second Brain Vault (`Projects/docreview-rag/`). Read its TODO at task start and record verified outcomes there through the second-brain skill.
- Communicate in Korean. Write code, comments, docstrings and GitHub messages in English; preserve required Korean UI text and paired Korean/English guides.

## Authority and delivery

- Study and implementation happen on `mcp-and-langgraph`; study sessions run in the `gpt-6-astra` session through the docreview-study skill. When both are complete the branch lands on `main` by rebase merge. Until then `main` and the running service stay as they are.
- Commit locally. Push, pull requests and anything that reaches `main` wait for the user's request.
- Database writes and re-indexing, paid model calls, Auth0 tenant settings, external publication, deployment, credentials, branch-protection changes and rewriting published history each need the user's approval.
- Commits and pull requests follow the user-authorized commit-it tracking/delivery flow, using the latest installed version of the skill. Reread its current source and references when another conversation may have updated it; these repository rules still override it.
- Code and configuration commits use `Sungyong Cho <dev@sungyongcho.com>` as both author and committer; pushes and PR creation authenticate as `sungyongcho`. Do not switch global credentials.

## Git and tracking

- `main` is stable/default. `v1` is a frozen parentless legacy archive: never modify it or merge it into main. `v2.0.0` identifies `61cb17b49b0b6bf0745b6fb7cfdd16b67d101731`.
- Branches: `<type>/<actual-issue-number>-<description>`. A directly requested, issue-free documentation PR may use `docs/<description>`; do not invent an issue. Use release tags, not product-version prefixes on ordinary branches.
- Commit/PR titles use English Conventional Commits: `<type>(<scope>): <outcome>`. Commit bodies contain Summary, Changes, Verification and applicable `Refs`. No attribution footers, stage labels or unsolicited breaking-change markers. Stage explicit paths and use files for multiline commit/PR text.
- Link every delivered issue. `Closes` means its full scope is complete; use `Refs` for partial delivery. Opening a PR is not permission to close an issue directly.
- Issues use Problem / outcome, Scope and observable Acceptance checks. Ordinary issue messages/images do not create Git assets, commits or evidence-only PRs.
- Keep `core.hooksPath=.githooks` in clones and never bypass hooks. Fetch before integration/publication and inspect divergence.
- Dependabot PRs: inspect exact author/head/diff and compatibility and pass the relevant gates before merging. Close only with a concrete reason; never bypass protection or suppress advisories.

## Engineering and verification

- Import from defining modules. Package `__init__.py` files do not re-export symbols except `app/retrieval`; do not add unnecessary package files or import compatibility shims.
- Mirror implementation tests: `app/X/y.py` → `tests/X/test_y.py`; a module that needs several test files gets `tests/X/y/test_NN_<feature>.py`. Multi-module behavior uses `tests/X/test_NN_<behavior>.py`, numbered per directory. Share helpers through `conftest.py` and support modules, never import one test module from another.
- Document private/nested helpers too. Test docstrings are 1–3 lines without NumPyDoc sections. Reuse nearby fixtures; do not reproduce production logic inside tests.
- ORM models in `app/db/models.py` precede persistence users; schema contracts live in `tests/db/test_models.py`. Preserve source, chunk, citation and selection identity.
- Start with relevant behavioral checks and scoped Ruff/format, then affected type/build checks. Always review the diff and run `git diff --check` before delivery.
- SQL/schema/pgvector changes require actual isolated PostgreSQL verification with `-m live_postgres --require-live-postgres`. Mock or skipped checks are not live proof. Never use the user's database as a disposable fixture or run concurrent DB writers.
- Full clean-checkout/image gates require release impact or an explicit requirement. Run required checks once for the final relevant state; reuse valid results thereafter.

## Documentation and runtime

- Changed user flows update affected `docs/TUTORIAL/en/` and `docs/TUTORIAL/ko/`; update README/CLI guidance only when affected. If no tutorial impact, explain that in the PR.
- Preserve screenshot assets unless the user requests captures. For missing visual evidence, add `### SCREENSHOT NEEDED` and an adjacent HTML comment naming the feature, exact state, locale and expected evidence. Never present old/synthetic images as proof. Requested captures use actual states, light mode and both locales unless narrowed.
- Local Compose uses `docker/docker-compose.yml`; the dev/prod overlays set runtime and preview behavior. Deployment uses `deploy/gcp/docker-compose.deploy.yml`. `.env` does not choose Compose files. A changed public bundle mode needs a build.
- `MODE` selects the OpenAI key slot (development `OPENAI_API_KEY_LOCAL`, production `OPENAI_API_KEY_PROD`); production rejects local engines. `DOCREVIEW_ADMIN_MODE` controls backend authority; `NEXT_PUBLIC_ADMIN_MODE` controls the web bundle. Keep them distinct.
- Diagnose typed failures: workflow budget (`resource`, `limit`, `observed`, `blocked_node`), provider failure (`status`, `attempts`, `details`, optional numeric budget/source), or node error (`error_type`, `message`, `node`). Wall-clock seconds are not token counts; provider and workflow ceilings can differ. Never guess which resource failed.
- Jobs are queued/running or succeeded/failed/cancelled/interrupted. Interrupted work does not resume automatically; failed/interrupted jobs may expose an explicit retry.
