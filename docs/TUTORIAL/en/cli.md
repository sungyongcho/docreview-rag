# Local command reference {#local-command-reference}

> [!DEV]
> These commands are for the operator of a local checkout and its services. They are not actions available to visitors through the public interface.

`rag-alias.sh` registers commands for starting, stopping, and inspecting this checkout in Bash or Zsh.
For the twelve-step screen-led exercise, start with the [DocReview RAG overview](overview.md).
Use [environment setup](environment.md#step-1), [acquisition](acquisition.md#step-3), and
[indexing](indexing.md#step-5) alongside the commands below.

CLI and dashboard operations share results when they use the same local database, source directory, and
embedding configuration. Check completed CLI work in the dashboard instead of running it twice. A different
`DATABASE_URL` or remote server is a different environment.

## Register commands and open help {#register-commands-and-open-help}

Run from the repository root:

```bash
source ./rag-alias.sh
rag-help
```

`source ./rag-alias.sh` is the one-command installation and activation path in an interactive
Bash or Zsh terminal. Choose Y to persist the startup registration; the commands are available
after a login-shell restart. The restart banner says **remember to type rag-help**. No leaves startup unchanged and loads the commands for this session only. Re-sourcing compares the embedded version and registered definitions: [already installed] means identical; [update required] refreshes changed, missing or customized registrations.
Startup-file loading, verification, update reloads and noninteractive/redirected sourcing do not
prompt for installation. Registration does not install application dependencies.

<!-- details: shell-activation-details | Executed-script path and wordmark details -->

If you instead execute `./rag-alias.sh`, it installs/verifies registration and offers a new login
shell with an explicit default-No prompt in an interactive terminal. Consent replaces the installer
process with the detected Bash/Zsh login shell; it cannot replace the calling parent shell or inject
functions into it. Exiting the new shell returns to the original one. Login files control startup;
if a Bash login profile does not load `.bashrc`, use the printed source command. Declining or EOF
never starts a shell. Sourcing remains the reliable primary activation path.

The shell and Web share the same checked-in Small ASCII wordmark. An 80-column terminal displays the
full name; narrower terminals use the DR monogram or a plain product line. The wordmark remains plain; help adds color and bold only on a TTY when NO_COLOR is unset. Printing the banner needs no language runtime or network.

<!-- /details -->

The installer adds one source line to `.bashrc` or `${ZDOTDIR:-$HOME}/.zshrc`, preserving existing content and backing it up. New terminals load it automatically. For manual registration only, the equivalent line is:

```bash
# Replace this placeholder with your checkout's actual absolute path.
source /absolute/path/to/docreview-rag/rag-alias.sh >/dev/null
```

Registered `rag-*` commands target the checkout that registered them, even from another directory.
Run Python CLI, file inspection, and direct Docker commands from the **repository root**.

| Task | Command | Effect |
|---|---|---|
| Help | `rag-help` | Show commands, examples, and checkout path |
| Start development | `rag-dev start` | Start the dev stack and apply configuration |
| Rebuild and start | `rag-dev compose up --build -d` | Apply image/Python dependency changes |
| Start only DB | `rag-dev compose up -d db` | Prepare the DB before API/web work |
| Status | `rag-dev status` | Inspect containers and health |
| Recent API logs | `rag-dev logs --tail=80 app` | Inspect recent failures |
| Follow web logs | `rag-dev logs -f web` | Ctrl+C stops log viewing, not services |
| Restart web | `rag-dev restart web` | Refresh dependencies and prepared tutorial assets |
| Stop only API | `rag-dev stop app` | Keep the web status screen and database |
| Stop, preserving data | `rag-dev compose down` | Remove containers while retaining DB volume |
| Local public preview | `rag-prod start` | Switch to local prod UI and permissions |
| Model connectivity | `rag-dev doctor` | Diagnose the DocReview-to-model-server path |

### Mode commands {#mode-commands}

Use `rag-dev` or `rag-prod` followed by an explicit action:
`start`, `status`, `logs [service]`, `stop`, `restart`, `doctor`, or
`compose <arguments...>`. These commands manage this checkout locally; PROD is a
local visitor preview, not deployment. Start preserves existing data. A new database
starts empty, and server readiness does not mean the corpus is ready.

With no action, the mode command prints help without starting services.

Use `rag-dev corpus <operation>` for data preparation and
`rag-dev schema check|prepare|recover|recreate` for schema work.
Use `rag-dev help [command]` or `rag-prod help [command]` for details.
Raw Docker Compose operations require `compose`, for example
`rag-dev compose up --build -d`.

### Prepare a local PROD portfolio {#local-prod-data}

```bash
# Start and prepare, or reuse an already prepared local PROD database.
rag-prod start --local --ready --artifacts /path/to/public-bundle
# For an already running local PROD server:
rag-prod prepare --local --artifacts /path/to/public-bundle
# Inspect the bundle and current preparation state without changing either:
rag-prod prepare --local --check --artifacts /path/to/public-bundle
```

`prepare` requires an actual running local PROD server; it does not switch DEV to
PROD. `start --local --ready` starts and checks PROD before preparing its data.
Without `--ready`, `start` preserves data and starts a new database empty.
DEV has no `--ready`: use `rag-dev corpus` or the web preparation workflow.

<!-- details: prod-bundle-details | Bundle selection, restore scope, and verification -->

Bundle selection is `--artifacts PATH`, then `DOCREVIEW_PROD_ARTIFACT_DIR` from the
environment or `.env`, then the sole directory containing checksums under
`~/.local/share/docreview/prod-artifacts`. Missing or ambiguous bundles stop preparation
with an actionable message. No download or paid embedding generation is automatic.

Only the public 18-document deployment bundle is supported. Its checksums and
deployment format are validated; `database.private.dump` is never restored. PROD uses the
dedicated `prod_pg_data` volume, separate from DEV's `pg_data`, and restores files
under `data/local-prod/{corpus,eval-runs,runtime}`. DEV data and conversations remain
in DEV. The first restore requires empty targets; existing conflicting data is not
overwritten. An incomplete preparation receipt stops automatic retries and preserves
the partial state for inspection. If all data was restored but the final readiness check
failed, a later preparation revalidates the complete state and finishes the receipt
without importing data again. `--check` never updates the receipt.

Preparation verifies schema compatibility, document/chunk relationships, embedding
model and tokenizer, 384-dimensional vectors, evaluation snapshots, BM25 and runtime
readiness. A successful repeat revalidates and reuses the saved data without restoring
it again or calling providers. `--check` performs read-only validation and does not
create directories, restore data, or repair readiness. Restored vectors are not a
downloaded OpenAI answer model; actual questions still use the configured API.

<!-- /details -->

`rag-prod reset data --local` also stops with an explicit unsupported message:
PROD-only data reset is not connected yet. Preparing data never implies reset.

### Refresh an already-loaded helper {#refresh-an-already-loaded-helper}

```bash
rag-alias --check-updates
rag-alias update
# If the checkout moved, give its new directory or canonical helper file explicitly:
rag-alias update /new/path/to/docreview-rag/rag-alias.sh
```

<!-- details: helper-update-details | What the check and update actually change -->

The comparison reports the loaded path and installed SHA-256 alongside the checkout path and hash.
The check is read-only and succeeds whether or not an update is available. Update reloads changed
helper-owned commands in this shell, preserves customized functions, and repairs an existing owned
startup line in place. A moved/renamed registration or duplicate owned lines becomes one current
line; unrelated lines and their order remain. An unchanged valid line is not rewritten. If there
is no owned startup entry, update only refreshes this shell and reports that registration is absent.
Use the sourced installation path to persist it. No compatibility file is created.

<!-- /details -->

## Installation and configuration {#installation-and-configuration}

Requirements: uv, Docker Engine with Compose 2.24.4+, Node.js 24+, npm 11+, and Python 3.14+.
uv prepares the locked Python environment.

```bash
uv --version
docker compose version
node --version
npm --version
uv sync --locked
(cd web && npm ci)
if [ ! -f .env ]; then cp .env.example .env; fi
```

Edit `.env` locally. Replace the development-key placeholder with a real key, and leave unused keys empty.
Use your real name and reachable email for SEC access. Do not put secrets in terminal commands, screenshots, or Git.

```dotenv
SEC_USER_AGENT=Your Real Name your-real-contact@example.com
OPENAI_API_KEY_LOCAL=<replace-with-your-real-development-key>
OPENAI_API_KEY_PROD=
DART_API_KEY=
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
```

Do not leave the sample DART/prod placeholders in place. Check separately configured shell keys without
printing them. DEV uses only `OPENAI_API_KEY_LOCAL`; production uses only `OPENAI_API_KEY_PROD`.
Do not add MODE to `.env`. Python examples set `MODE=dev`; `rag-dev` selects it automatically.

The repository's model policy uses `text-embedding-3-large` at 384 dimensions, `gpt-5.6-terra` for answers,
and `gpt-5.6-luna` by default for translation. Verify key access and available credit. Do not substitute arbitrary
model names. Deterministic embeddings are for connectivity tests, not the semantic-quality path in this tutorial.

The host DB default is `postgresql+asyncpg://filing:filing@localhost:5432/filing`. Verify that any existing
DATABASE_URL points to this exercise's local DB. If DB_PORT changes, match the port in the host DATABASE_URL.
The Docker app uses the Compose service name `db` internally.

Installation and configuration do not make paid OpenAI requests. After starting services, System status
shows API/DB and model availability. Never upload `.env` or enter keys into the documentation page.

## Initial schema setup {#initial-schema-setup}

```bash
rag-dev start
```

Quick Start bootstraps Python, validates configuration, prepares an empty schema, and starts development services. It preserves existing compatible data. If the schema is incompatible, it stops; keep that database intact and choose an empty isolated or compatible database. Do not use a reset as installation recovery.

The image startup gate also runs for `rag-dev start` and prod/deploy Compose:
empty DB → initialize from ORM; compatible DB → preserve and start; drifted DB →
block API startup and print recovery commands. No automatic reset or migration occurs.
For an already-running app, document catalog requests check schema before querying;
missing tables/columns return a typed 503 instead of repeated invalid SQL.
Use `rag-dev logs --tail 80 app` when the gate blocks startup. `Check schema` and restart
alone never repair drift. Additive migrations remain deferred. In-place recreation is an explicit local DEV option below.

## Development and local prod preview {#development-and-local-prod-preview}

```bash
rag-dev start
rag-dev status
```

Both modes use [the local service](http://localhost:8000/docreview-rag/). Set APP_PORT in `.env`
and apply it with `rag-dev restart` if needed.

| Change | Apply with |
|---|---|
| Web/API source | Local automatic reload; API restarts can interrupt jobs |
| Web dependencies | `rag-dev restart web` |
| Tutorial Markdown or referenced image additions/replacements | Save to update the open Documentation automatically |
| Python dependencies/image | `rag-dev compose up --build -d` |
| Initial `.env` configuration or ports | `rag-dev start` |
| Saved Local LLM connection | Immediate; saved values override `.env` |

Local prod is a preview, not a deployment. DEV and PROD retain separate database volumes;
mode changes do not copy data. Use [local PROD preparation](#local-prod-data) to restore
the saved public portfolio into PROD. With OpenAI embedding configured,
prod API initialization also needs a real OPENAI_API_KEY_PROD. Preparing a key or viewing a page does not
itself generate an answer or incur answer-model usage.

```bash
rag-dev compose down
rag-prod start
# Return to development after checking the public UI.
rag-prod compose down
rag-dev start
```

**Live tutorial editing:** save Markdown under `docs/TUTORIAL/ko/` or `en/` in VS Code to update
an open development Documentation page automatically. New visual evidence starts as a
`SCREENSHOT NEEDED` heading with a short feature/state/locale comment; an approved capture later replaces
that markup with an image under `docs/TUTORIAL/assets/`. Invalid links or missing sources show an error
and recover after a valid save. Live updates apply to development; the static prod preview needs a
rebuilt bundle.

Prod blocks Local LLM and development write operations. If an existing dev conversation is incompatible,
start a new one. A visible web page does not prove that a keyless API is healthy. Normal shutdown uses `down`.
`rag-dev compose down -v` and `rag-prod compose down -v` are deliberately rejected to protect volumes.

## Optional review stream telemetry {#optional-review-stream-telemetry}

API clients can opt in to stage start/end events by sending the request header
`X-DocReview-Telemetry: stages` with the review stream request. These stage SSE events are additive;
clients that omit the header retain the existing default event stream. The UI uses recorded events
for execution progress and performance, without inventing missing timing values. Optional execution
metadata is stored in existing JSON payloads.

## Inspect status and logs {#inspect-status-and-logs}

```bash
rag-dev status
rag-dev logs --tail=80 app
rag-dev logs -f web
```

Inspect actual error locations in logs. Check for secrets or personal data before sharing logs.
Ctrl+C exits `logs -f` without stopping the service. System status and Jobs show related runtime state.

With a prepared DB/schema, inspect documents and index statistics without changing them:

```bash
rag-dev compose exec -T db psql -U filing -d filing -c 'SELECT doc_id FROM documents ORDER BY doc_id;'
rag-dev compose exec -T db psql -U filing -d filing -c 'SELECT count(*) AS chunks, count(embedding) AS embedded FROM chunks; SELECT count(*) AS bm25_stat_rows FROM bm25_corpus_stats;'
```

Counts do not validate embedding model identity; also inspect provider/pending state in the UI. Direct CLI
acquisition and ingestion can be absent from Jobs because they do not use the web task queue.

## Diagnose local-model connectivity {#diagnose-local-model-connectivity}

Ollama is installed separately from this project's Compose stack. The [macOS/Linux Ollama guide](ollama.md) owns installation, startup, listening-address changes, and model preparation. In **Settings → Local LLM**, keep the current connection or select **Default**; use **Add a server…** only for an alternate endpoint. **Run connection diagnostics** inspects the selected server without saving or running an answer.

```bash
rag-dev doctor
rag-dev doctor --details
rag-dev doctor --setup
rag-dev doctor --help
# Only when DocReview uses a different web address:
rag-dev doctor --web-url http://localhost:18080
```

| Option | Meaning |
| --- | --- |
| No option | Inspect the active/default server through the configured DocReview address; no URL is required |
| `--details` | Include advanced host/container and listening-address evidence |
| `--setup` | Print manual setup guidance without contacting or changing services |
| `--web-url` | Override the **DocReview frontend** address, not the Ollama address |

Diagnostics do not install, download/load models, start services, save settings, or generate answers. Read configuration, backend connectivity, and answer-model checks separately. An unavailable inventory is unconfirmed; an installed but unloaded model is normal standby.

For an older API without the shared diagnostic route, the command explicitly reports a legacy read-only fallback. `ollama list` and `ollama ps` independently show installed and currently loaded models. Continue with [server selection](settings.md#local-server), [connection recovery](ollama.md#diagnostics), or [answer configuration](answers.md#engines).

## Prepare one NVIDIA filing {#prepare-one-nvidia-filing}

```bash
rag-dev corpus acquire_edgar --identifier NVDA --year 2024
rag-dev corpus status
rag-dev corpus ingest_manifest --manifest manifest.json --selection sec-08b5f645cc174083 --expected-documents 1
rag-dev corpus status
```

Wait for each job to succeed. The acquisition result identifies an exact processing selection inside the common manifest; no catalog extraction or copied manifest is needed.

Ingestion only parses and stores chunks. It invalidates BM25 statistics without rebuilding
them. Run `rag-dev corpus backfill_embeddings`, wait for success, then run
`rag-dev corpus rebuild_bm25` and wait for success before hybrid retrieval. Repeat the BM25
operation after every parse/chunk run. Build step 4 offers **Compute BM25** initially
and **Recompute BM25** when statistics or a successful rebuild record exist; it also
permits recomputation while ready.

The direct runtime seed API retains its combined ingest-and-BM25 behavior for existing
API clients; isolated evaluation corpus arms likewise prepare their own statistics.
These are separate from the Build/CLI ingestion job.

## Python CLI reference {#python-cli-reference}

### Ingestion {#ingestion}

The Python CLI submits the same server job as the web interface:

```bash
uv run python -m app.cli ingest --manifest manifest.json --selection SELECTION_ID
```

Use the selection ID returned by acquisition. For a non-default development address, pass `--api-url`. Schema preparation belongs to `rag-dev start`; destructive reset belongs to `rag-dev reset data --local`.

### Embedding and retrieval {#embedding-and-retrieval}

```bash
rag-dev corpus backfill_embeddings --manifest manifest.json --selection SELECTION_ID
rag-dev corpus status
rag-dev corpus rebuild_bm25
rag-dev corpus status
uv run python -m app.cli retrieve --query 'NVIDIA revenue' --issuer NVDA --fiscal-year 2024
```

Embedding generation can incur provider usage. Retrieval tests the evidence; it does not submit an answer request. See [retrieval](retrieval.md) before the [first-answer guide](answers.md).

### DART acquisition {#dart-acquisition}

```bash
rag-dev corpus acquire_dart --identifier 005930 --year 2024
rag-dev corpus status
```

Use its returned selection ID for ingestion. SEC and DART share `manifest.json`.

### Option help {#option-help}

```bash
rag-dev corpus --help
uv run python -m app.cli ingest --help
uv run python -m app.cli retrieve --help
```

## Shutdown and selective cleanup {#shutdown-and-selective-cleanup}

### Stop and resume while preserving data {#stop-and-resume-while-preserving-data}

Normal shutdown preserves DB data, source files, saved configuration, and browser conversations:

```bash
rag-dev compose down
# In a later terminal, from the repository root:
source ./rag-alias.sh
rag-dev start
```

Check Documents and saved conversations after restarting. Reuse ready data instead of repeating paid backfill.

### Choose the deletion scope {#choose-the-deletion-scope}

Deletion is optional; choose the intended boundary.

| Scope | Removed | Preserved |
|---|---|---|
| Browser conversations | Conversations in this browser/origin | DB, source files, server connection |
| DB volume | Documents, chunks, vectors, BM25, run/trace, eval/snapshot, jobs and DB drafts | Host files, `.env`, browser storage |
| Downloaded source | Only the confirmed source file | DB, manifests, golden/profile sources, other files |
| Saved connection | Persisted Local LLM connection state | DB, sources, `.env`, conversation engine selection |

### Clear browser conversations {#clear-browser-conversations}

First save any answers/citations you need elsewhere; there is no undo. In Settings → Data & help, choose
Clear conversations and confirm. Reset conversation settings and Reset saved defaults are separate actions.
Afterwards the conversation list should be empty while Documents and Jobs remain. Other browsers/ports have
separate storage. Stop here if deleting conversations was your only goal.

### Delete the local DB volume {#delete-the-local-db-volume}

**Before deletion:** confirm the local checkout/project. Do not apply this to a differently named `-p` project.
`down -v` also removes this stack's web_node_modules and web_next cache volumes. Make and inspect a DB dump
if you want recovery; source files can rebuild retrieval data but cannot recover old run/evaluation/job history.

```bash
rag-dev status
mkdir -p /tmp/docreview-backups
docreview_backup=$(mktemp /tmp/docreview-backups/filing.XXXXXX.dump)
rag-dev compose exec -T db pg_dump -U filing -d filing -Fc > "$docreview_backup"
rag-dev compose exec -T db pg_restore --list < "$docreview_backup"
```

Continue only if both dump and listing succeed. Move the backup to a safe persistent location: `/tmp` may
be cleared. Recovery requires pg_restore into a compatible empty PostgreSQL/pgvector DB. Listing the dump
is not a restore test.

**Destructive — only after confirming the target and recovery requirements:**

```bash
rag-dev compose down
docker compose --project-directory . -f docker/docker-compose.yml down -v
rag-dev compose up -d db
rag-dev compose exec -T db psql -U filing -d filing -c '\dt'
```

The new DB should have no app tables. Host source files and `.env` remain. Use
[initial schema setup](#initial-schema-setup) and then web ingestion; re-embedding incurs cost again.
Old browser conversations may remain but can no longer resolve deleted DB evidence or run IDs.

### Delete only the downloaded source {#delete-only-the-downloaded-source}

Finish acquisition/ingestion/evaluation first. Confirm the exact file, back it up or verify it can be downloaded
again, and consider other exercises using it. Do not delete the whole corpus directory.

```bash
ls -l data/corpus/NVDA/2024-02-21_0001045810-24-000029.html
# Only after confirming this file and any needed backup:
rm -i -- data/corpus/NVDA/2024-02-21_0001045810-24-000029.html
test ! -e data/corpus/NVDA/2024-02-21_0001045810-24-000029.html && echo 'Source removed'
```

Verify that only the file disappeared; manifests, golden/profile sources, and DB remain. Source-based
validation or re-ingestion may fail until you re-download with the one-filing example. There is no individual
DB-document deletion button/API in this walkthrough.

### Reset local connection settings {#reset-local-connection-settings}

In Settings → Local LLM, **Disconnect** persists an explicit off state and prevents default reconnection.
**Use Default** checks the startup endpoint selected by process environment → `.env` → defaults
before switching to it. A failed check or save preserves the working connection; added servers remain
in the selector. Neither action removes OpenAI keys or conversations.

Only remove the connection file itself when necessary. Back up the default target
`data/local-settings/local-llm.json` or record its server catalog and address/protocol first. Removing it also removes the saved server list and an explicit
Disconnect state, so defaults may connect again next startup. Use Disconnect if you only want to turn it off.

```bash
rag-dev compose down
ls -l data/local-settings/local-llm.json
# Only after confirming the target and any needed backup:
rm -i -- data/local-settings/local-llm.json
test ! -e data/local-settings/local-llm.json && echo 'Saved connection file removed'
rag-dev start
```

Check the initial connection in Settings. To recover, stop the app, restore the backup at the original path,
and restart. `.env` and conversation-specific model selection remain separate.

## Troubleshooting {#troubleshooting}

For a blocked runtime reset, open Reset runtime data at the top left of Pipeline. Read Last checked
and Reset diagnosis before changing anything. The permission details identify the actual path and operator;
manual ACL suggestions are not applied automatically. Preserve existing application access and have the
owner review the requested permissions, then check availability again. Reset is optional, even when blocked.

Read the actual error location and message first:

```bash
rag-dev status
rag-dev logs --tail=80 app
rag-dev corpus readiness
```

An incompatible-schema diagnostic stops startup without changing existing data. If the web opens, inspect
System status, Jobs, and the answer's Run trace. If the web itself is unavailable, inspect web logs first.

| Symptom | Check | Action and completion |
|---|---|---|
| Web unavailable | web logs, APP_PORT, port owner | Inspect `rag-dev logs --tail=80 web`; use the correct URL |
| API/DB unavailable | service and DB health | Restore the connection; refresh and verify schema |
| schema_drift | Existing schema mismatch | Preserve this database and choose an empty isolated or compatible database |
| Missing/stale embeddings | provider, identity, pending | Correct configuration and run needed paid backfill after checking the manifest and explicit selection |
| BM25 not ready | Normal intermediate state after parsing/chunking | Run Compute/Recompute BM25 (step 4); hybrid/lexical wait, vector needs embeddings only |
| NOT_IN_DOCS | scope, company/year filters, evidence | Inspect Documents and candidates; ask something actually supported by the corpus |
| provider_failure | status, attempts, details, node | Fix key/access/connectivity/limits; schema recreation does not fix this |
| budget_exceeded | resource, limit, observed, blocked_node | Adjust the specific limit under Review settings → Run limits; retries can cost more |
| node_error | error_type, message, node | Fix the named non-model stage before retrying |
| interrupted job | app restart | It is not automatically resumed; inspect state and explicitly retry |

The default wall-clock limit is **120 seconds for the whole run**, not a token budget. Input tokens,
output tokens, and iterations also accumulate across calls and retries. Evidence size is a separate setting under **Review settings → Evidence**.
A local server can answer readiness checks while still being too slow for an actual model request.

Queued/running jobs are active; succeeded/failed/cancelled jobs are finished. Interrupted means the app
restarted mid-work. Failed and interrupted jobs offer Retry; cancelled jobs do not. Inspect completed work
and remaining scope before retrying paid embedding.

## Remove command registration {#remove-command-registration}

```bash
rag-alias remove
# If the registered command is unavailable:
./rag-alias.sh --delete
```

Confirm the shown startup file/checkout. The matching registration line is backed up and removed; other
projects, code, and DB data are preserved. The sourced command can also remove unchanged commands from
the current shell. A separately executed script cannot modify its parent shell, so follow its instructions.
Keep the backup path and verify a new terminal does not auto-load the registration. To restore it, follow
[registration instructions](#register-commands-and-open-help).

## Quick Start and data reset {#quick-start-and-data-reset}

Cloned the repository and unsure what to do? Run **`rag-dev start`**. It prepares
Python dependencies, creates `.env` only when missing, checks configuration, starts
DEV, prepares an empty schema, waits for readiness and prints the web Quick Start link.
Existing data is preserved. It makes no model, embedding or filing download request.

Every command accepts `--verbose` (`-vv`). Setup/build commands normally show step
status and elapsed time; verbose mode streams the underlying output. A failed step
prints its last 20 lines and the exact command to rerun. Colour and bold appear only
in a terminal with `NO_COLOR` unset; redirected output uses plain `[ OK ]` / `[FAIL]`.
`rag-help` groups Quick Start, stack, data and reset commands in aligned columns.

### Reset the local environment {#reset-the-local-environment}

```bash
rag-prod reset environment --local --all-modes --status
rag-prod reset environment --local --all-modes
# Start separately after reviewing the reset result:
rag-prod start
```

The DEV and PROD forms reset the same checkout environment; `--all-modes`
explicitly acknowledges that scope. The preview lists this project's containers,
volumes, dedicated images, generated data and runtime caches. Review the exact list
before confirming deletion. Other projects and shared Docker resources are excluded.

Preserve `.env`, Git history, source edits, external bundles, `data/golden/`, local
Ollama models and protected keep
paths. No tracked source is restored to HEAD. There is no extreme mode or
discard-tracked option. An environment reset always exits without starting services.
Inspect its status receipt after partial failure; do not hide a failed deletion by
starting another reset. Existing browser-reset behavior applies at the next DEV
connection, not during ordinary startup.

### Reset local data {#reset-local-data}

```bash
rag-dev reset data --local
rag-dev reset data --local --keep-sources
rag-dev reset data --local --sample
rag-dev reset data --local --status
```

Preview ORM-owned data and downloaded sources, then explicitly confirm the scope.
Preserve `.env`, model settings, evaluation exports, unrelated tables, images and
volumes. `--keep-sources` retains source files; `--sample` prepares the NVDA/AMD
FY2023–2024 selection without downloading. These flags are mutually exclusive.

Reset leaves services stopped. Inspect the result, then run `rag-dev start`
separately. It never rebuilds, imports data, or generates embeddings automatically.
Retain the source permission preflight and rollback journal. If DB work is uncertain,
preserve `data/.schema-recreate-journal/journal.json`, run `rag-dev schema check`,
and inspect completed stages before retrying.

### Configuration repair within the current step {#configuration-repair-within-the-current-step}

`rag-dev start` and `rag-dev reset data --local` report invalid keys' `.env` lines and effective
shell/file sources without exposing credentials. Choose `[f]` to ignore failing
shell exports for this invocation, `[e]` to write the two public embedding settings,
`[r]` to recheck a local edit, or `[q]` to cancel. Parent-shell exports are unchanged.
Startup failures offer diagnosed, confirmed recovery while preserving volumes.

## Recover an incompatible local schema {#recover-an-incompatible-local-schema}

A restart or schema check does not repair drift. Preserve the original database and
use a separate recovery environment when you need a usable empty runtime:

```bash
uv run python -m scripts.schema check
uv run python -m scripts.schema recover --return-stage index
# Optional: --parent /existing/directory (outside the original checkout)
```

<!-- details: schema-recovery-checkout | What the recovery checkout contains and how to use it -->

Recovery creates a private, uniquely named checkout under the selected parent (the
original checkout's parent by default). It clones the committed revision into a
separate Git repository with no push remote, copies `.env` privately, selects distinct
loopback DB/web/operator ports, and uses its own Compose project and volumes. Original
configuration, services, database and downloaded corpus remain unchanged. Uncommitted
source edits and downloaded/private corpus files are not copied. Host `DATABASE_URL`
and Compose overrides cannot redirect the new project's operations to the old DB.

The command installs locked dependencies, starts its DB, prepares only the empty
schema, starts DEV services, and checks both CLI schema status and the API through
the web origin. No filings or provider requests are submitted. Only after both checks
succeed does it print **Recovery ready** and a URL returning to the requested Build
step. Supported stages: filings, index, embeddings, lexical, ask, answer_model, evaluate.
This is a new empty environment; the original incompatible schema is not repaired.

Use the printed `cd` command and `source ./rag-alias.sh` in a separate terminal to
select that recovery environment's CLI. Its schema output includes the local DB
target. Re-check the destination in the web UI, then prepare missing data in order.
Do not run commands from the original directory expecting them to target recovery.

A failed installation/start/readiness check leaves the recovery directory intact and
prints retry commands. Inspect its logs and recheck; never treat a failed or unknown
check as completion. No reset, migration of the old DB, or automatic paid reprocessing
is performed. `rag-dev compose down` from the recovery checkout stops that project while
preserving its volumes.

<!-- /details -->

Evaluation errors now keep Retry/details alongside preparation navigation. Verified
missing artifacts lead to acquisition, missing chunks to indexing, pending embeddings
to embedding preparation, and a missing lexical index to BM25. Schema/unknown failures
and invalid source contracts lead to setup diagnosis. Opening navigation never starts
a job; refresh at the destination reads current state.

## Explicit local database recreation {#explicit-local-database-recreation}

`rag-dev start` prepares the Python environment and starts services. Startup prepares
only an empty DB; it never discards existing data. For first-time setup or users who
understand the consequences, the preparation notice also offers this dangerous option:

```bash
uv run python -m scripts.schema recreate
```

This deletes ORM-owned tables and all their rows in the verified local DEV database,
then recreates the schema from the current models. Review the exact target and table
counts and raw-file paths/counts. Default recreation also clears downloaded raw sources and manifest source entries. Type `Y` only if you accept the entire preview.
Enter, wrong text, EOF and noninteractive input do not authorize it; previews expire
after five minutes. The app is stopped only after confirmation. Other DB clients must
be closed; shared Docker volumes and nonlocal targets are refused.

Code, `.env`, evaluation exports, the DB volume, unrelated tables
and host Ollama stay. No backup is made. Unknown foreign-key dependencies cause the
transaction to roll back rather than using cascading deletion. On failure, the API may
remain stopped; inspect schema state before another attempt. On verified success,
run `rag-dev start`, re-check Build, then explicitly repeat parsing, embeddings and BM25.
Embedding work may cost money and is never started by recreation.

The DB warning modal keeps raw errors in a closed terminal-style box under
**Please review the error**. Expand it to inspect the original message; existing
status/navigation/dismiss buttons retain their behavior.

## Clean start scopes {#clean-start-scopes}

| Command | Cleared | Preserved / next step |
| --- | --- | --- |
| `uv run python -m scripts.schema recreate` | ORM tables/data and downloaded raw SEC/DART sources/manifest source entries | Code, `.env`, evaluation exports, unrelated tables, DB volume; empty Filings draft |
| Same command with `--sample` | Same clean start | Server-persisted NVDA/AMD FY2023–2024 draft; press Download yourself |
| Same command with `--keep-sources` | ORM tables/data only | All raw source files; confirm `Y` |
| `rag-dev reset data --local` | ORM/source scope; `--keep-sources` and `--sample` supported | Preserves settings/exports/volume; remains stopped until explicit start |
| `rag-prod reset environment --local --all-modes` | Previewed local containers, volumes, dedicated images, generated data and caches | Preserves .env/source edits; no restart |

The two options cannot be combined. CLI acquisition still requires explicit identifiers and years.

<!-- details: clean-start-journal | Source quarantine and recovery journal behavior -->

Source cleanup quarantines the exact previewed files under `data/.schema-recreate-journal` until the DB transaction commits. A DB failure attempts to restore all source bytes; inspect the schema before retrying because a lost connection can leave the DB outcome unconfirmed. Interrupted or incomplete cleanup retains `journal.json` with paths and phase and blocks another reset. Inspect that journal and preserve its backups; do not delete it or repeat recreation to hide the failure. If DB commit succeeded but file cleanup failed, the command returns failure and says so explicitly. The API remains stopped until you inspect state and run `rag-dev start`.

<!-- /details -->
