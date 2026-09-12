# AGENTS.md — DocReview

## Editable operating rules

For `gpt-6-astra` and `fable-5.1`: use this contract, not model-specific rituals or generic checklists.

- Assigned implementers read [WORKER.md](WORKER.md) first for delivery, queues, staffing, integration and reviews.
- Explicitly user-designated live sessions read [INTERACTIVE.md](INTERACTIVE.md) first. INTERACTIVE is a peer of WORKER and MAINTAINER; its session-scoped delivery exception is defined below.
- User-designated intake coordinators read [MODERATOR.md](MODERATOR.md) for intake, sizing, evidence, drafts and owner notification.
- Continuity lives in assignments, issues, PRs, commits and reproducible tests. Replaceable workers/models preserve valid evidence and improve outcomes through affected tests; a new model or conversation proves neither progress nor independent review.
- Deliver the smallest reliable approved diff. Preserve foreign staged, unstaged, untracked and ignored work; no unsolicited cleanup/refactoring.
- Inspect the named behavior, definitions, direct callers and relevant tests. Reopen sources/instructions only after changes or concrete uncertainty; avoid repeated repository/backlog scans.
- Reuse passing tester evidence while code/inputs/environment remain valid. Workflow stages do not justify reruns; review changed deltas and never hide failed gates.
- Resolve discoverable facts and routine choices autonomously; continue approved sequences. Ask only for material ambiguity, changed scope/risk or missing authority.
- Use one agent for coupled work; delegate bounded independent ownership when efficient. Routine staffing is authorized within runtime limits; one owner controls shared contracts/Git writes.
- Report only outcomes, meaningful changes, blockers or next actions; classify checks as passed/failed/blocked/not run. Omit unchanged updates.
- Keep queues, commit IDs and test counts in PRs/tasks. Instruction edits require a user request.

## Project-specific contract — uneditable by default

**Edit boundary:** change this section only when the user explicitly requests the corresponding project-rule change. Ordinary implementation or instruction cleanup is not permission to weaken, relocate or relabel protected rules. Apply the same boundary to WORKER.md and MODERATOR.md. Higher-priority instructions and explicit user directions still prevail.

### Authority and delivery

- User-designated INTERACTIVE sessions use the latest explicit user requests as the final requirements, including changes that supersede older issues. Within the named scope, session authority covers iterative edits/tests, personal commits/pushes/PRs, disclosed `Self-review: LGTM`, verified squash merge and clean local-main fast-forward. No separate reviewer task or repeated ordinary approval is required. Active overlaps require checkpoint-preserving ownership coordination before writes; unrelated work survives.
- At each INTERACTIVE PR, record actual `Requirement changes` and complete/superseded/delta/retain dispositions. Close source issues only after verified merge; create residual issues first and preserve active ownership. Failed checks remain OCCUPIED; exact passing head/base evidence permits MERGE_READY. Use `opsctl interactive` with `merge_method: squash`. Dirty main is preserved, never stashed/reset automatically. Runtime/tool approvals, deployment, credentials and destructive data actions remain separate. These exceptions do not apply to ordinary WORKER delivery.

- Ordinary worker implementation ends with verified PR delivery at `REVIEW_READY`. This completes implementation; it does not start a review. The user may open a different task and request review of the named PR, or the implementing worker may record a request. Ordinary self-review still requires explicit user approval for that scope.
- Keep progress in the existing work-state record. At `REVIEW_READY`, consolidate the PR's completed outcomes, final verification and review notes in one reusable summary; no per-commit delivery comments. Preserve historical evidence and apply issue checklist changes only from verified acceptance results.
- An explicit user review request in a different task authorizes autonomous in-scope review, repair, verification, personal commits, ordinary pushes, guarded rebase/lease publication, and user-visible task/OPS coordination through `MERGE_READY` under WORKER.md. The reviewer may register the user-origin request while retaining original worker/task provenance. Do not require another implementer request or acknowledgement for a ready, paused scope; block actual overlapping writers. Declare repair scope/files and head/base, use Draft/OCCUPIED, and disclose reviewer contributions. Material intent or scope uncertainty requires a question. These standing permissions do not override higher-priority runtime/tool approval policies.
- Add `MERGE_READY` alongside `REVIEW_READY` only after eligible review and current passing checks for the matching head/base. User-requested separate reviews rebase onto the current base before final readiness. At a foreground checkpoint, changed base/head invalidates readiness: reconcile and renew affected evidence under that review's rebase authority. No scheduler is implied. Neither ready label grants merge, deployment, credential changes or local-main authority.
- An explicitly user-designated commit-error or conflict resolver may close assigned PRs, edit assigned issues and self-review only when those actions and targets are explicitly granted. A `conflict-resolver` may fix, verify and squash-merge only its separately authorized PR set through WORKER.md. Preserve authors/history; no global maintainer rights or merge authority follows from the role name or a label.
- Eligible successful reviews start exactly with `Self-review: LGTM` for explicit user-approved original-worker self-review or `Review: LGTM` for requested review in a different task, including disclosed bounded repairs. This repair-role exception does not let the original implementation worker waive its own self-review approval. Implementation verification alone must not publish an approval heading. Authorized conflict resolution uses `Conflict resolution: LGTM`, bound to head/base/tree and sequence revision/order. These are the only approval headings; preserve original authors and actual worker IDs. Conflict approval is not independent human review or authorization by itself.
- Non-worker maintainers follow the user-authorized commit-it tracking/delivery flow (installed skill, currently 4.0.0). Reread its current source and references when another conversation may have updated it; these repository rules still override it. Scoped implementation authorization covers issue tracking, commit, ordinary push, PR, verified squash merge and checkout synchronization only for that maintainer role.
- Creating/deleting issues, changing issue scope, assigning people, merging or synchronizing a checkout must never be inferred for an ordinary worker from the general maintainer workflow. Ordinary workers may maintain only their assigned ownership/status comments and their managed labels under WORKER.md; this exception does not authorize issue-body edits. Explicit user-approved takeover also authorizes recording that scoped ownership transfer without another approval or a reply from the previous worker.
- For the maintainer's configured automation, code/configuration commits use `Sungyong Cho <dev@sungyongcho.com>` as both author and committer; development pushes and PR creation authenticate as `sungyongcho`.
- `sungyongcho-ops` records authorized intake, ownership and handoffs, status, actual pushed commit SHAs and PR links, managed labels, and automated COMMENT reviews. Use the central OPS policy and guarded commands described in WORKER.md. DEV/OPS classify work purpose; OCCUPIED/REVIEW_READY mirror work state; MERGE_READY additionally records eligible review and current verification across issues and PRs. Preserve unrelated labels. Account separation does not expand worker authority.
- Public OPS records use a concise heading and canonical Markdown fields/nested lists, each datum once; never publish JSON fences, giant payload dumps or hidden JSON duplicates. Use strict parsing with no runtime legacy-JSON fallback. Explicit audited migration alone converts verified OPS-generated records in place across the authorized managed registry; preserve IDs/authors/head/base/evidence, exclude human/unmanaged content, and do not rewrite Git commits or history. WORKER.md defines marker and repair-record boundaries.
- Preserve existing history and active assignments. External contributors retain their own identities; do not switch global credentials or foreign worktrees.
- Destructive user-data actions, credentials, deployment, protection changes, meaningful paid work and rewriting published history require their own authorization.
- Communicate in Korean. Write code, comments, docstrings and GitHub messages in English; preserve required Korean UI text and paired Korean/English guides.

### Git and tracking

- `main` is stable/default. `v1` is a frozen parentless legacy archive: never modify it or merge it into main. `v2.0.0` identifies `61cb17b49b0b6bf0745b6fb7cfdd16b67d101731`.
- Branches: `<type>/<actual-issue-number>-<description>`. A directly requested, issue-free documentation PR may use `docs/<description>`; do not invent an issue. Use release tags, not product-version prefixes on ordinary branches.
- Commit/PR titles use English Conventional Commits: `<type>(<scope>): <outcome>`. Commit bodies contain Summary, Changes, Verification and applicable `Refs`. Conflict resolution commits and squash messages also preserve the sequence metadata in WORKER.md. No internal assembly-stage labels, unsolicited breaking-change markers or attribution footers. Stage explicit paths and use files for multiline commit/PR text.
- Link every delivered issue. `Closes` means its full scope is complete; use `Refs` for partial delivery. Opening a PR is not permission to close an issue directly.
- User-designated moderators have standing routine issue-management authority under MODERATOR.md, including direct image attachments and evidenced close/reopen actions without per-action reapproval. Use Problem / outcome, Scope and observable Acceptance checks. Ordinary issue messages/images do not create Git assets, commits or evidence-only PRs. Worker delivery and Git permissions remain separate.
- Keep `core.hooksPath=.githooks` in clones. Never bypass hooks or hide foreign changes with stash/reset. Fetch before integration/publication and inspect divergence.
- The maintainer's canonical local branches are main/v1; worker backup refs are retained under WORKER.md. Legacy assemble/zero/new workflows and checkpoint stamping are retired.
- Living drafts #37 (`docs/29-project-ideas`, `ideas.md`) and #38 (`docs/30-development-log`, `docs/DEVELOPMENT_STORY_OUTLINE.md`) retain user wording and only their own file. Never merge them without a specific request; general merge requests exclude them. Do not overwrite their authors' active changes.
- Genuine Dependabot maintenance is authorized for non-worker maintainers: inspect exact author/head/diff and compatibility, pass relevant gates, then use the normal verified squash policy. Close only with a concrete reason; never bypass protection or suppress advisories. Workers do not manage unrelated Dependabot PRs.

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

<!-- ops:project:AGENTS.md:v1 -->
# Shared operating defaults

Keep project-specific rules in this file; they take precedence over these defaults.
Use WORKER.md for assigned implementation/review, INTERACTIVE.md for explicitly
user-directed live iteration and delivery, and MODERATOR.md for assigned intake.
INTERACTIVE is a peer role to WORKER and MAINTAINER; its scoped standing delivery
authority does not extend to ordinary workers.
Inspect the requested scope, preserve foreign changes and verify affected behavior.
Record work in this project's GitHub issues/PRs, not a central project-data collection.
Use the installed commit-it skill for portable Git procedures. OPS provides execution
tools and these managed rules; it does not own product skill installation settings.
Consult the project's DECISIONS.md ledger at session start or intake and on any
requirement change; treat active entries as standing decisions. When new
instructions conflict with an active entry, surface the conflict for the user's
decision before proceeding. Record outcomes by appending entries; mark superseded
entries rather than deleting them.

For INTERACTIVE sessions, use the latest explicit user requirements and the declared
session delivery grant; consult INTERACTIVE.md before creating/revising the session PR.
Project-specific role dispatch must explicitly recognize this role during adoption.
<!-- /ops:project:AGENTS.md -->
