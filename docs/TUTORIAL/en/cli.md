# Local command reference

> [!DEV]
> These commands are for the operator of a local checkout and its services. They are not actions available to visitors through the public interface.

`rag-alias.sh` registers commands for starting, stopping, and inspecting this checkout in Bash or Zsh.
For the twelve-step screen-led exercise, start with the [DocReview RAG v2 overview](overview.md).
Use [environment setup](environment.md#step-1), [acquisition](acquisition.md#step-3), and
[indexing](indexing.md#step-5) alongside the commands below.

CLI and dashboard operations share results when they use the same local database, source directory, and
embedding configuration. Check completed CLI work in the dashboard instead of running it twice. A different
`DATABASE_URL` or remote server is a different environment.

## Register commands and open help

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

If you instead execute `./rag-alias.sh`, it installs/verifies registration and offers a new login
shell with an explicit default-No prompt in an interactive terminal. Consent replaces the installer
process with the detected Bash/Zsh login shell; it cannot replace the calling parent shell or inject
functions into it. Exiting the new shell returns to the original one. Login files control startup;
if a Bash login profile does not load `.bashrc`, use the printed source command. Declining or EOF
never starts a shell. Sourcing remains the reliable primary activation path.

The shell and Web share the same checked-in Small ASCII wordmark. An 80-column terminal displays the
full name; narrower terminals use the DR monogram or a plain product line. The wordmark remains plain; help adds color and bold only on a TTY when NO_COLOR is unset. Printing the banner needs no language runtime or network.

The installer adds one source line to `.bashrc` or `${ZDOTDIR:-$HOME}/.zshrc`, preserving existing content and backing it up. New terminals load it automatically. For manual registration only, the equivalent line is:

```bash
# Replace this placeholder with your checkout's actual absolute path.
source /absolute/path/to/docreview-rag-agent/rag-alias.sh >/dev/null
```

Registered `rag-*` commands target the checkout that registered them, even from another directory.
Run Python CLI, file inspection, and direct Docker commands from the **repository root**.

| Task | Command | Effect |
|---|---|---|
| Help | `rag-help` | Show commands, examples, and checkout path |
| Start development | `rag-dev up -d` | Start the dev stack and apply configuration |
| Rebuild and start | `rag-dev up --build -d` | Apply image/Python dependency changes |
| Start only DB | `rag-dev up -d db` | Prepare the DB before API/web work |
| Status | `rag-dev ps` | Inspect containers and health |
| Recent API logs | `rag-dev logs --tail=80 app` | Inspect recent failures |
| Follow web logs | `rag-dev logs -f web` | Ctrl+C stops log viewing, not services |
| Restart web | `rag-dev restart web` | Refresh dependencies and prepared tutorial assets |
| Stop only API | `rag-dev stop app` | Keep the web status screen and database |
| Stop, preserving data | `rag-dev down` | Remove containers while retaining DB volume |
| Local public preview | `rag-prod up -d` | Switch to local prod UI and permissions |
| Model connectivity | `rag-ollama-check` | Diagnose the DocReview-to-model-server path |

With no arguments, `rag-dev` and `rag-prod` use `up -d`. Without registration, run
`.venv/bin/python -m scripts.stack dev up -d` from the repository root.
`rag-help` lists quick setup before fresh cleanup under Quick Start; data reset has its own
`[RESET]` block. Command names are bold, sections colored, secondary notes dim and warnings
yellow. NO_COLOR or redirected output stays plain. Every command accepts `--help` and
`--verbose` (`-vv`). Use `rag-corpus --help` for operation details and `rag-schema --help` for schema options.

### Command consolidation

Use `rag-alias update` for an already-loaded helper, or `source ./rag-alias.sh` for first activation. If this checkout still has a registration for the previous
underscore-named helper, the installer shows its exact path and offers to back up and replace that
one registration. Declining preserves it; no compatibility file or symlink is created. Explicit
uninstall also removes a detected old registration for this checkout. Reload the new helper in a
fresh shell after migration. These obsolete shortcuts are no longer registered;
use the replacement commands below. Re-sourcing retires removed definitions only when they still match the previously owned command.

| Removed shortcut | Replacement |
|---|---|
| `rag-dev-up` | `rag-dev up -d` |
| `rag-dev-down` | `rag-dev down` |
| `rag-prod-up` | `rag-prod up -d` |
| `rag-prod-down` | `rag-prod down` |
| `rag-diagnose` | `rag-ollama-check` |

Use `rag-up` to rebuild/start DEV and `rag-schema check|prepare|recover|recreate` for schema work.
Without helper registration, use `uv run python -m scripts.schema <action>`.
The compact menu retains separate ordinary, extreme, and schema-reset warnings. Read the full reset
preview and command help before confirming deletion.

### Refresh an already-loaded helper

```bash
rag-alias --check-updates
rag-alias update
# If the checkout moved, give its new directory or canonical helper file explicitly:
rag-alias update /new/path/to/docreview-rag-agent/rag-alias.sh
```

The comparison reports the loaded path and installed SHA-256 alongside the checkout path and hash.
The check is read-only and succeeds whether or not an update is available. Update reloads changed
helper-owned commands in this shell, preserves customized functions, and repairs an existing owned
startup line in place. A moved/renamed registration or duplicate owned lines becomes one current
line; unrelated lines and their order remain. An unchanged valid line is not rewritten. If there
is no owned startup entry, update only refreshes this shell and reports that registration is absent.
Use the sourced installation path to persist it. No compatibility file is created.

## Installation and configuration

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

## Initial schema setup

```bash
rag-start-quick
```

Quick Start bootstraps Python, validates configuration, prepares an empty schema, and starts development services. It preserves existing compatible data. If the schema is incompatible, it stops; keep that database intact and choose an empty isolated or compatible database. Do not use a reset as installation recovery.

The image startup gate also runs for `rag-dev up --build -d` and prod/deploy Compose:
empty DB → initialize from ORM; compatible DB → preserve and start; drifted DB →
block API startup and print recovery commands. No automatic reset or migration occurs.
For an already-running app, document catalog requests check schema before querying;
missing tables/columns return a typed 503 instead of repeated invalid SQL.
Use `rag-dev logs --tail 80 app` when the gate blocks startup. `Check schema` and restart
alone never repair drift. Additive migrations remain deferred. In-place recreation is an explicit local DEV option below.

## Development and local prod preview

```bash
rag-dev up --build -d
rag-dev ps
```

Both modes use [the local service](http://localhost:8000/docreview-rag-agent/). Set APP_PORT in `.env`
and apply it with `up -d` if needed.

| Change | Apply with |
|---|---|
| Web/API source | Local automatic reload; API restarts can interrupt jobs |
| Web dependencies | `rag-dev restart web` |
| Tutorial Markdown or referenced image additions/replacements | Save to update the open Documentation automatically |
| Python dependencies/image | `rag-dev up --build -d` |
| Initial `.env` configuration or ports | `rag-dev up -d` |
| Saved Local LLM connection | Immediate; saved values override `.env` |

Local prod is a preview, not a deployment. It retains the same data volume. With OpenAI embedding configured,
prod API initialization also needs a real OPENAI_API_KEY_PROD. Preparing a key or viewing a page does not
itself generate an answer or incur answer-model usage.

```bash
rag-dev down
rag-prod up -d
# Return to development after checking the public UI.
rag-prod down
rag-dev up -d
```

**Live tutorial editing:** save Markdown under `docs/TUTORIAL/ko/` or `en/` in VS Code to update
an open development Documentation page automatically. New visual evidence starts as a
`SCREENSHOT NEEDED` heading with a short feature/state/locale comment; an approved capture later replaces
that markup with an image under `docs/TUTORIAL/assets/`. Invalid links or missing sources show an error
and recover after a valid save. Live updates apply to development; the static prod preview needs a
rebuilt bundle.

Prod blocks Local LLM and development write operations. If an existing dev conversation is incompatible,
start a new one. A visible web page does not prove that a keyless API is healthy. Normal shutdown uses `down`.
`rag-dev down -v` and `rag-prod down -v` are deliberately rejected to protect volumes.

## Optional review stream telemetry

API clients can opt in to stage start/end events by sending the request header
`X-DocReview-Telemetry: stages` with the review stream request. These stage SSE events are additive;
clients that omit the header retain the existing default event stream. The UI uses recorded events
for execution progress and performance, without inventing missing timing values. Optional execution
metadata is stored in existing JSON payloads.

## Inspect status and logs

```bash
rag-dev ps
rag-dev logs --tail=80 app
rag-dev logs -f web
```

Inspect actual error locations in logs. Check for secrets or personal data before sharing logs.
Ctrl+C exits `logs -f` without stopping the service. System status and Jobs show related runtime state.

With a prepared DB/schema, inspect documents and index statistics without changing them:

```bash
rag-dev exec -T db psql -U filing -d filing -c 'SELECT doc_id FROM documents ORDER BY doc_id;'
rag-dev exec -T db psql -U filing -d filing -c 'SELECT count(*) AS chunks, count(embedding) AS embedded FROM chunks; SELECT count(*) AS bm25_stat_rows FROM bm25_corpus_stats;'
```

Counts do not validate embedding model identity; also inspect provider/pending state in the UI. Direct CLI
acquisition and ingestion can be absent from Jobs because they do not use the web task queue.

## Diagnose local-model connectivity

Ollama is installed separately from this project's Compose stack. The [macOS/Linux Ollama guide](ollama.md) owns installation, startup, listening-address changes, and model preparation. In **Settings → Local LLM**, keep the current connection or select **Default**; use **Add a server…** only for an alternate endpoint. **Run connection diagnostics** inspects the selected server without saving or running an answer.

```bash
rag-ollama-check
rag-ollama-check --details
rag-ollama-check --setup
rag-ollama-check --help
# Only when DocReview uses a different web address:
rag-ollama-check --web-url http://localhost:18080
```

| Option | Meaning |
| --- | --- |
| No option | Inspect the active/default server through the configured DocReview address; no URL is required |
| `--details` | Include advanced host/container and listening-address evidence |
| `--setup` | Print manual setup guidance without contacting or changing services |
| `--web-url` | Override the **DocReview frontend** address, not the Ollama address |

Diagnostics do not install, download/load models, start services, save settings, or generate answers. Read configuration, backend connectivity, and answer-model checks separately. An unavailable inventory is unconfirmed; an installed but unloaded model is normal standby.

For an older API without the shared diagnostic route, the command explicitly reports a legacy read-only fallback. `ollama list` and `ollama ps` independently show installed and currently loaded models. Continue with [server selection](settings.md#local-server), [connection recovery](ollama.md#diagnostics), or [answer configuration](answers.md#engines).

## Prepare one NVIDIA filing

```bash
rag-corpus acquire_edgar --identifier NVDA --year 2024
rag-corpus status
rag-corpus ingest_manifest --manifest manifest.json --selection sec-08b5f645cc174083 --expected-documents 1
rag-corpus status
```

Wait for each job to succeed. The acquisition result identifies an exact processing selection inside the common manifest; no catalog extraction or copied manifest is needed.

Ingestion only parses and stores chunks. It invalidates BM25 statistics without rebuilding
them. Run `rag-corpus backfill_embeddings`, wait for success, then run
`rag-corpus rebuild_bm25` and wait for success before hybrid retrieval. Repeat the BM25
operation after every parse/chunk run. Build step 4 offers **Compute BM25** initially
and **Recompute BM25** when statistics or a successful rebuild record exist; it also
permits recomputation while ready.

The direct runtime seed API retains its combined ingest-and-BM25 behavior for existing
API clients; isolated evaluation corpus arms likewise prepare their own statistics.
These are separate from the Build/CLI ingestion job.

## Python CLI reference

### Ingestion

The Python CLI submits the same server job as the web interface:

```bash
uv run python -m app.cli ingest --manifest manifest.json --selection SELECTION_ID
```

Use the selection ID returned by acquisition. For a non-default development address, pass `--api-url`. Schema preparation belongs to `rag-start-quick`; destructive reset belongs to `rag-reset`.

### Embedding and retrieval

```bash
rag-corpus backfill_embeddings --manifest manifest.json --selection SELECTION_ID
rag-corpus status
rag-corpus rebuild_bm25
rag-corpus status
uv run python -m app.cli retrieve --query 'NVIDIA revenue' --issuer NVDA --fiscal-year 2024
```

Embedding generation can incur provider usage. Retrieval tests the evidence; it does not submit an answer request. See [retrieval](retrieval.md) before the [first-answer guide](answers.md).

### DART acquisition

```bash
rag-corpus acquire_dart --identifier 005930 --year 2024
rag-corpus status
```

Use its returned selection ID for ingestion. SEC and DART share `manifest.json`.

### Option help

```bash
rag-corpus --help
uv run python -m app.cli ingest --help
uv run python -m app.cli retrieve --help
```

## Shutdown and selective cleanup

### Stop and resume while preserving data

Normal shutdown preserves DB data, source files, saved configuration, and browser conversations:

```bash
rag-dev down
# In a later terminal, from the repository root:
source ./rag-alias.sh
rag-dev up -d
```

Check Documents and saved conversations after restarting. Reuse ready data instead of repeating paid backfill.

### Choose the deletion scope

Deletion is optional; choose the intended boundary.

| Scope | Removed | Preserved |
|---|---|---|
| Browser conversations | Conversations in this browser/origin | DB, source files, server connection |
| DB volume | Documents, chunks, vectors, BM25, run/trace, eval/snapshot, jobs and DB drafts | Host files, `.env`, browser storage |
| Downloaded source | Only the confirmed source file | DB, manifests, golden/profile sources, other files |
| Saved connection | Persisted Local LLM connection state | DB, sources, `.env`, conversation engine selection |

### Clear browser conversations

First save any answers/citations you need elsewhere; there is no undo. In Settings → Data & help, choose
Clear conversations and confirm. Reset conversation settings and Reset saved defaults are separate actions.
Afterwards the conversation list should be empty while Documents and Jobs remain. Other browsers/ports have
separate storage. Stop here if deleting conversations was your only goal.

### Delete the local DB volume

**Before deletion:** confirm the local checkout/project. Do not apply this to a differently named `-p` project.
`down -v` also removes this stack's web_node_modules and web_next cache volumes. Make and inspect a DB dump
if you want recovery; source files can rebuild retrieval data but cannot recover old run/evaluation/job history.

```bash
rag-dev ps
mkdir -p /tmp/docreview-backups
docreview_backup=$(mktemp /tmp/docreview-backups/filing.XXXXXX.dump)
rag-dev exec -T db pg_dump -U filing -d filing -Fc > "$docreview_backup"
rag-dev exec -T db pg_restore --list < "$docreview_backup"
```

Continue only if both dump and listing succeed. Move the backup to a safe persistent location: `/tmp` may
be cleared. Recovery requires pg_restore into a compatible empty PostgreSQL/pgvector DB. Listing the dump
is not a restore test.

**Destructive — only after confirming the target and recovery requirements:**

```bash
rag-dev down
docker compose --project-directory . -f docker/docker-compose.yml down -v
rag-dev up -d db
rag-dev exec -T db psql -U filing -d filing -c '\dt'
```

The new DB should have no app tables. Host source files and `.env` remain. Use
[initial schema setup](#initial-schema-setup) and then web ingestion; re-embedding incurs cost again.
Old browser conversations may remain but can no longer resolve deleted DB evidence or run IDs.

### Delete only the downloaded source

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

### Reset local connection settings

In Settings → Local LLM, **Disconnect** persists an explicit off state and prevents default reconnection.
**Use Default** checks the startup endpoint selected by process environment → `.env` → defaults
before switching to it. A failed check or save preserves the working connection; added servers remain
in the selector. Neither action removes OpenAI keys or conversations.

Only remove the connection file itself when necessary. Back up the default target
`data/local-settings/local-llm.json` or record its server catalog and address/protocol first. Removing it also removes the saved server list and an explicit
Disconnect state, so defaults may connect again next startup. Use Disconnect if you only want to turn it off.

```bash
rag-dev down
ls -l data/local-settings/local-llm.json
# Only after confirming the target and any needed backup:
rm -i -- data/local-settings/local-llm.json
test ! -e data/local-settings/local-llm.json && echo 'Saved connection file removed'
rag-dev up -d
```

Check the initial connection in Settings. To recover, stop the app, restore the backup at the original path,
and restart. `.env` and conversation-specific model selection remain separate.

## Troubleshooting

For a blocked runtime reset, open Reset runtime data at the top left of Pipeline. Read Last checked
and Reset diagnosis before changing anything. The permission details identify the actual path and operator;
manual ACL suggestions are not applied automatically. Preserve existing application access and have the
owner review the requested permissions, then check availability again. Reset is optional, even when blocked.

Read the actual error location and message first:

```bash
rag-dev ps
rag-dev logs --tail=80 app
rag-corpus readiness
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

## Remove command registration

```bash
rag-alias-delete
# If the registered command is unavailable:
./rag-alias.sh --delete
```

Confirm the shown startup file/checkout. The matching registration line is backed up and removed; other
projects, code, and DB data are preserved. The sourced command can also remove unchanged commands from
the current shell. A separately executed script cannot modify its parent shell, so follow its instructions.
Keep the backup path and verify a new terminal does not auto-load the registration. To restore it, follow
[registration instructions](#register-commands-and-open-help).

## Quick Start and data reset

Cloned the repository and unsure what to do? Run **`rag-start-quick`**. It prepares
Python dependencies, creates `.env` only when missing, checks configuration, starts
DEV, prepares an empty schema, waits for readiness and prints the web Quick Start link.
Existing data is preserved. It makes no model, embedding or filing download request.

Every command accepts `--verbose` (`-vv`). Setup/build commands normally show step
status and elapsed time; verbose mode streams the underlying output. A failed step
prints its last 20 lines and the exact command to rerun. Colour and bold appear only
in a terminal with `NO_COLOR` unset; redirected output uses plain `[ OK ]` / `[FAIL]`.
`rag-help` groups Quick Start, stack, data and reset commands in aligned columns.

### Fresh checkout

```bash
rag-start-fresh
rag-start-fresh --no-start
rag-start-fresh --extreme
rag-start-fresh --status
```

Before changing anything, a numbered preview groups untracked/ignored files by
top-level path with file counts and sizes, lists tracked files to restore, and lists
this checkout's containers, named volumes and locally built images. This includes
sources and exports under `data/`, `.venv`, `web/node_modules`, `.next` and other caches.
Tracked changes under `data/` return to HEAD; tracked changes elsewhere block cleanup
unless you explicitly choose `--discard-tracked`. No backup is created.

Preserved: Git metadata/history, `.env*`, `.claude/`, `.agents/`, `.codex/`, `.vscode/`,
`.idea/`, `.freshstart-keep` and paths listed there, plus the Ollama models volume.
The keep file accepts one literal checkout-relative path per line; empty lines and
`#` comments are ignored. Absolute paths and `..` are rejected. Linked source paths
or nested Git repositories block cleanup. Other Docker projects and shared resources
are never deleted; no builder-cache pruning occurs. Tracked `.env.example` remains
available as the setup template even in extreme mode.

Every destructive prompt displays `(Y/n)` but **only the single uppercase `Y`**
accepts. `y`, `yes`, Enter, spaces and EOF cancel with “nothing changed”. Previews
expire after five minutes and changed inventories require a new preview. Extreme
mode asks a second time, naming `.env*`; it additionally deletes private `.env*`
files and this project's Ollama models volume. It never restarts automatically.

The cleaner attempts removals first. If permissions actually prevent deletion, it
lists only those failed paths, prints a scoped
`sudo chown -R "$(id -u):$(id -g)" -- <paths>` repair, and offers one retry after you
apply it. It never invokes sudo. A failure after deletion starts leaves a partial
receipt; inspect `rag-start-fresh --status` before requesting another preview.

Ordinary cleanup then runs `rag-start-quick`, including reinstalling dependencies.
`--no-start` stops after cleanup. Extreme mode ends with the instruction to run
`rag-start-quick`, which creates a new `.env` for local editing. Successful cleanup records
a reset ID. On its next DEV connection, the web interface restores DocReview conversations,
settings, and the company basket to defaults; other applications' storage is preserved.
Ordinary restarts, `rag-start-quick`, and `rag-reset` do not schedule this browser reset.
`--no-start` and extreme mode also apply it on the next DEV connection. The existing web
wipe endpoint remains available.

### Narrow data reset

```bash
rag-reset
rag-reset --keep-sources
rag-reset --sample
rag-reset --status
```

`rag-reset` previews ORM-owned database data and downloaded sources, asks for `Y`,
resets that scope, rebuilds DEV and waits for readiness. It preserves `.env`, saved
model settings, evaluation exports, unrelated tables, images and data volumes.
`--keep-sources` preserves downloaded files; `--sample` presets NVDA/AMD FY2023–2024
without downloading. These flags are mutually exclusive. It does not support
`--extreme`; use the separate fresh-checkout command for that purpose.

The existing source permission preflight and rollback journal remain in this narrow
reset. Follow its exact repair instructions if blocked. After uncertain DB work,
preserve `data/.schema-recreate-journal/journal.json`, run `rag-schema check`, and
inspect completed stages before another reset. A failed reset never starts a rebuild.
After a successful reset the command prints the application URL and bilingual
[Quick Start — DEV ONLY, Web step 1](quickstart-dev.md#qs-web-1) links.

Each setup/reset command keeps its own receipt under the checkout's Git metadata:
`rag-start-quick --status`, `rag-start-fresh --status`, and `rag-reset --status` read
those records. The reset status command also reads previous web/extreme evidence
when the existing operator is reachable; it never resubmits deletion.

### Configuration repair within the current step

`rag-start-quick` and `rag-reset` report invalid keys' `.env` lines and effective
shell/file sources without exposing credentials. Choose `[f]` to ignore failing
shell exports for this invocation, `[e]` to write the two public embedding settings,
`[r]` to recheck a local edit, or `[q]` to cancel. Parent-shell exports are unchanged.
Startup failures offer diagnosed, confirmed recovery while preserving volumes.

## Recover an incompatible local schema

A restart or schema check does not repair drift. Preserve the original database and
use a separate recovery environment when you need a usable empty runtime:

```bash
uv run python -m scripts.schema check
uv run python -m scripts.schema recover --return-stage index
# Optional: --parent /existing/directory (outside the original checkout)
```

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
is performed. `rag-dev down` from the recovery checkout stops that project while
preserving its volumes.

Evaluation errors now keep Retry/details alongside preparation navigation. Verified
missing artifacts lead to acquisition, missing chunks to indexing, pending embeddings
to embedding preparation, and a missing lexical index to BM25. Schema/unknown failures
and invalid source contracts lead to setup diagnosis. Opening navigation never starts
a job; refresh at the destination reads current state.

## Explicit local database recreation

`rag-up` is a shortcut for `rag-dev up --build -d`; it uses the Python environment
prepared by `rag-start-quick` or `uv sync --locked`. Its automatic startup prepares
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
run `rag-up`, re-check Build, then explicitly repeat parsing, embeddings and BM25.
Embedding work may cost money and is never started by recreation.

The DB warning modal keeps raw errors in a closed terminal-style box under
**Please review the error**. Expand it to inspect the original message; existing
status/navigation/dismiss buttons retain their behavior.

## Clean start scopes

| Command | Cleared | Preserved / next step |
| --- | --- | --- |
| `uv run python -m scripts.schema recreate` | ORM tables/data and downloaded raw SEC/DART sources/manifest source entries | Code, `.env`, evaluation exports, unrelated tables, DB volume; empty Filings draft |
| Same command with `--sample` | Same clean start | Server-persisted NVDA/AMD FY2023–2024 draft; press Download yourself |
| Same command with `--keep-sources` | ORM tables/data only | All raw source files; confirm `Y` |
| `rag-reset` | Same ORM/source scope as schema recreation; `--keep-sources` and `--sample` supported | Preserves settings/exports/volume; starts DEV, verifies readiness, prints the web hand-off links |
| `rag-start-fresh --extreme` | Previewed config, runtime files/caches and volumes | Two uppercase Y gates; DocReview browser defaults reset on next DEV connection; no restart |

The two options cannot be combined. CLI acquisition still requires explicit identifiers and years. Source cleanup quarantines the exact previewed files under `data/.schema-recreate-journal` until the DB transaction commits. A DB failure attempts to restore all source bytes; inspect the schema before retrying because a lost connection can leave the DB outcome unconfirmed. Interrupted or incomplete cleanup retains `journal.json` with paths and phase and blocks another reset. Inspect that journal and preserve its backups; do not delete it or repeat recreation to hide the failure. If DB commit succeeded but file cleanup failed, the command returns failure and says so explicitly. The API remains stopped until you inspect state and run `rag-up`.
