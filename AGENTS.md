# AGENTS.md — DocReview

DocReview answers questions over SEC 10-K and DART filings with citations, and it is the owner's study project. Five purposes are fixed: the RAG service itself, MCP, the Lang series (LangChain, LangGraph, LangSmith), Auth0 authorization and a web Agent. Everything else (module layout, code paths, tests, documents) is restructured whenever that makes the code right and easier to learn from.

## Working rules

- When something is wrong, find the structure that produced it and redesign that structure. Do not patch instances one by one, and do not choose a design because it is easy to implement.
- Resolve discoverable facts and routine choices yourself. Ask only for material ambiguity, missing authority or the approvals below.
- Say that something works only after running it. Report each check as passed, failed, blocked or not run, and never hide a failed one.
- Preserve ignored files, other worktrees and other contributors' identities as well.
- The study plan and its progress live in the Second Brain owner `Projects/docreview-rag`; read its TODO at task start and record verified outcomes there.
- Preserve required Korean UI text and the paired Korean/English guides.

## Approval

- Work happens on `mcp-and-langgraph`. `main` and the running service stay as they are until the whole branch is ready to deploy; then the branch lands on `main` by rebase merge. `v1` is a frozen archive: never modify it or merge it.
- Pull requests and anything that reaches `main` wait for the user's request.
- Each of these also needs the user's approval: database writes and re-indexing, paid model calls, Auth0 tenant settings, branch-protection changes and rewriting published history.
- Commits use `Sungyong Cho <dev@sungyongcho.com>` as both author and committer; pushes authenticate as `sungyongcho`. Do not switch global credentials.

## Commits

- Titles are English Conventional Commits: `<type>(<scope>): <outcome>`. Bodies contain Summary, Changes and Verification, and `Refs` when an issue applies. Stage explicit paths and pass multiline messages from a file.
- Keep `core.hooksPath=.githooks` and never bypass hooks.

## Verification

- Run the checks that cover what changed: the affected tests, `ruff check`, `ruff format --check`, `basedpyright` and `git diff --check`.
- SQL, schema and pgvector changes are verified on an isolated PostgreSQL with `-m live_postgres --require-live-postgres`. A mocked or skipped check is not live proof. Never use the user's database as a disposable fixture and never run concurrent database writers.
- A changed user flow updates `docs/TUTORIAL/en/` and `docs/TUTORIAL/ko/`.

## Runtime facts

- Local Compose uses `docker/docker-compose.yml`; the dev and prod overlays set runtime and preview behavior. Deployment uses `deploy/gcp/docker-compose.deploy.yml`, shared by the Oracle path in production and the alternate GCP path. `.env` does not choose Compose files. A changed public bundle mode needs a build.
- `MODE` selects the OpenAI key slot (development `OPENAI_API_KEY_LOCAL`, production `OPENAI_API_KEY_PROD`); production rejects local engines. `DOCREVIEW_ADMIN_MODE` controls backend authority and `NEXT_PUBLIC_ADMIN_MODE` controls the web bundle; they are distinct.
- Failures are typed: workflow budget (`resource`, `limit`, `observed`, `blocked_node`), provider failure (`status`, `attempts`, `details`, optional numeric budget or source) or node error (`error_type`, `message`, `node`). Wall-clock seconds are not token counts, and provider and workflow ceilings can differ.
- Jobs are queued or running, then succeeded, failed, cancelled or interrupted. Interrupted work does not resume automatically; failed and interrupted jobs may expose an explicit retry.
