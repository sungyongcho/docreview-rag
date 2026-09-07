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
in the same source call. No leaves startup unchanged and loads the commands for this session only.
Startup-file loading, verification, update reloads and noninteractive/redirected sourcing do not
prompt for installation. Registration does not install application dependencies.

If you instead execute `./rag-alias.sh`, it installs/verifies registration and offers a new login
shell with an explicit default-No prompt in an interactive terminal. Consent replaces the installer
process with the detected Bash/Zsh login shell; it cannot replace the calling parent shell or inject
functions into it. Exiting the new shell returns to the original one. Login files control startup;
if a Bash login profile does not load `.bashrc`, use the printed source command. Declining or EOF
never starts a shell. Sourcing remains the reliable primary activation path.

The shell and Web share the same checked-in Small ASCII wordmark. An 80-column terminal displays the
full name; narrower terminals use the DR monogram or a plain product line. All terminals and redirected output remain free of color escapes. Printing the banner needs no language runtime or network.

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
`rag-help` starts with one Quick Start command and its printed-URL hand-off. Reset and recovery
commands have their own `[RESET]` block. The compact menu uses aligned columns and no ANSI
colors or escapes, including in a color-capable terminal; every command accepts
`--help`. Use `rag-corpus --help` for operation details and `rag-schema --help` for schema options.

### Command consolidation

Use `rag-alias update` for an already-loaded helper, or `source ./rag-alias.sh` for first activation. If this checkout still has a registration for the previous
underscore-named helper, the installer shows its exact path and offers to back up and replace that
one registration. Declining preserves it; no compatibility file or symlink is created. Explicit
uninstall also removes a detected old registration for this checkout. Reload the new helper in a
fresh shell after migration. These obsolete shortcuts are no longer registered;
use the replacement commands below. Existing shell definitions last until that shell exits.

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

### SCREENSHOT NEEDED
<!-- Feature: sourced helper installation, loaded/check-out hash update and default-No login offer; locale=en; plain terminal; show isolated startup registration and unchanged/moved update, without credentials. Preserve historical installer assets. -->

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
rag-quickstart
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
an open development Documentation page automatically. Store shared images in `docs/TUTORIAL/assets/`
and reference them as below; VS Code Markdown preview and the website use the same original.

```markdown
![Alternative text describing what to inspect](../assets/02-pipeline.en.jpg)
```

New referenced images and replacements at the same filename update automatically. Click a screenshot
on the website to open the original. Invalid links or missing sources show an error and recover after
a valid save. Live updates apply to development; the static prod preview needs a rebuilt bundle.

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

## Python CLI reference

### Ingestion

The Python CLI submits the same server job as the web interface:

```bash
uv run python -m app.cli ingest --manifest manifest.json --selection SELECTION_ID
```

Use the selection ID returned by acquisition. For a non-default development address, pass `--api-url`. Schema preparation belongs to `rag-quickstart`; destructive reset belongs to `rag-fresh-start`.

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

## Reset local connection settings

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
| BM25 not ready | missing/invalidated statistics | Rebuild BM25 and verify job success plus readiness |
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

<!-- capture:16-run-trace -->

![The saved successful run records its original ID, four iterations, two provider requests, token counts and about 119.6 seconds elapsed.](../assets/16-run-trace.en.jpg)

*The saved successful run records its original ID, four iterations, two provider requests, token counts and about 119.6 seconds elapsed. These are historical recorded values, not a new measurement.*

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


## Ordinary and extreme runtime reset

`rag-fresh-start` is a guided host-side clean start. It checks prerequisites and configuration,
starts the checkout's DB, previews ORM data and downloaded sources, then requires the exact typed
phrase before resetting. A running web/operator service is not required for this ordinary path.
The five numbered ASCII steps contain no color escapes.

```bash
rag-fresh-start
rag-fresh-start --keep-sources
rag-fresh-start --sample
```

The default and sample modes require `RECREATE <checkout-name> AND SOURCES`; keeping sources
requires `RECREATE <checkout-name>`. The preview expires after five minutes and is rechecked before
execution. Cancellation never starts the application. A verified reset preserves code, `.env`,
evaluation exports, saved model settings, unrelated tables, the DB volume and host Ollama.
`--keep-sources` also preserves downloaded files; `--sample` presets NVDA/AMD FY2023–2024 without
performing downloads. The two options are mutually exclusive.

Before the typed confirmation or API stop, the host path checks source readability and write/search
access to source parent directories, `data/corpus` and the journal destination under `data`.
Readable container-owned directories can still prevent a rename. The preview lists every blocked
directory and prints a quoted `sudo setfacl -R -m u:<host-uid>:rwX -- <paths>` repair. Review the
exact paths, apply the repair, then choose the single inspection retry. The CLI never applies ACLs
or retries deletion automatically. `--keep-sources` does not require source-directory write access.

If failure occurs after an API stop, the command reports whether the database and sources are
unchanged/restored or whether recovery is uncertain, and prints `rag-dev up -d` to restore the API
without requesting a build. It does not print a raw container ID. If a journal remains or the DB
outcome is uncertain, preserve `data/.schema-recreate-journal/journal.json`, run `rag-schema check`
and inspect the stated boundary before another reset; a committed DB reset is never called unchanged.


### SCREENSHOT NEEDED
<!-- Feature: fresh-start host write-permission preflight before confirmation, exact sudo repair paths, and post-stop rollback/restart guidance; locale=en; theme=light; preserve existing screenshot assets. -->

After successful reset, the command runs `rag-dev up --build -d`, waits for confirmed readiness,
and prints the application URL and [Web Quick Start step 1](quickstart.md#qs-web-1) in both languages.
A failed build or readiness check reuses `rag-ollama-check` diagnostics and offers one confirmed
`rag-dev down` → `rag-dev up --build -d` recovery, preserving volumes. An incomplete reset never
reaches that restart. Browser conversations are not deleted by ordinary clean start.

### Configuration repair within the current step

Both `rag-quickstart` and ordinary `rag-fresh-start` identify each invalid key's `.env` line, shell
value and effective source. Credential/contact values stay hidden. For the reported embedding
conflict, `[f]` ignores failing shell exports for this invocation, `[e]` writes the two required
public embedding settings, `[r]` rechecks after a local file edit, and `[q]` cancels. The command
resumes at configuration instead of reinstalling dependencies. Parent-shell exports are unchanged;
use the printed `unset KEY` command there for future invocations. No option writes credentials or
makes an embedding/model request. Noninteractive blockers return failure with the same repair hints.

### SCREENSHOT NEEDED
<!-- Feature: guided terminal clean start and source-aware configuration repair; locale=en; plain ASCII/no-color; show redacted file/shell conflict, exact reset preview and successful readiness URL to qs-web-1 using disposable data. Preserve existing screenshots. -->

### Extreme reset

Only `rag-fresh-start --extreme` requires the existing DEV operator (`rag-dev up -d`). Its broader
web/operator deletion protocol and browser acknowledgement remain separate:

```bash
rag-fresh-start --extreme
```

Extreme mode shows the exact deletion inventory before two independent gates:
confirm that `.env`, conversations and custom corpus have been backed up, then type
`EXTREME <checkout-name>` to accept irreversible deletion. Enter, No, EOF, or
noninteractive input cannot authorize deletion. A changed or expired preview stops
execution. No backup is created and the application cannot restore deleted data.

The explicit fresh-clone **runtime-content** boundary is:

- Remove untracked files under `data/corpus` (including custom PDFs/JSON),
  `data/eval_runs`, `data/local-settings`, `build`, `dist`, `web/.next`, `web/out`,
  `web/.tutorial`, `web/public/tutorial-assets`, `.pytest_cache`, and `.ruff_cache`;
  remove untracked root `.env*` files. Empty directories may remain.
- Remove only verified checkout-owned `db`, `app`, `web` containers and local
  `pg_data`, `web_next`, `web_node_modules` Compose volumes. Shared/external volumes,
  unexpected containers and symbolic links block the operation.
- Preserve tracked files and local edits, Git history, host `.venv`/`node_modules`,
  unrelated untracked/ignored files, other Docker projects, host Ollama, external
  credentials, and the reset audit record. This is not `git clean` or a host reset.

After both terminal gates, close other DocReview tabs and open the printed
`/reset-local/#<operation-id>` URL in the browser holding the conversations.
The page clears and checks this origin's DocReview local/session storage, then sends
an authenticated acknowledgement for that operation. Only then can local deletion
proceed. The CLI reports browser deletion only with that acknowledgement, scoped to
that browser and origin; other profiles, devices, ports and localhost/127.0.0.1
origins are separate. Do not reopen old tabs that could save in-memory conversations.
If acknowledgement times out, local deletion does not start; browser deletion may
already have occurred, so inspect status before another attempt.

After verified extreme success, services stay stopped. Run `rag-quickstart`, fill the
new `.env` locally, and follow Quick Start to prepare data again. On partial failure,
review completed stages; no automatic restart or deletion retry occurs.

### SCREENSHOT NEEDED
<!-- Feature: extreme CLI browser acknowledgement. State: matching waiting operation on reset-local, then acknowledged deletion. Capture en and ko in light mode using disposable data only; no credentials. -->
The browser acknowledgement page has no new screenshot evidence yet.


Use `rag-fresh-start --status` to read the last extreme/web reset even when extreme deletion
removed `.env` or stopped the web container. This command uses the existing local
operator connection and never resubmits deletion. After updating the code, restart
the local operator with `rag-dev down` followed by `rag-dev up -d` before using the
new reset options; these commands preserve data volumes.


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

### SCREENSHOT NEEDED
<!-- Feature: schema recovery and evaluation preparation navigation. Capture light-mode en/ko evaluation error links, setup recovery command, and verified empty recovery destination; no credentials. -->
New screenshot evidence is pending; existing images are unchanged.


## Explicit local database recreation

`rag-up` is a shortcut for `rag-dev up --build -d`; it uses the Python environment
prepared by `rag-quickstart` or `uv sync --locked`. Its automatic startup prepares
only an empty DB; it never discards existing data. For first-time setup or users who
understand the consequences, the preparation notice also offers this dangerous option:

```bash
uv run python -m scripts.schema recreate
```

This deletes ORM-owned tables and all their rows in the verified local DEV database,
then recreates the schema from the current models. Review the exact target and table
counts and raw-file paths/counts. Default recreation also clears downloaded raw sources and manifest source entries. Type `RECREATE <checkout-name> AND SOURCES` only if you accept the entire preview.
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


### SCREENSHOT NEEDED
<!-- Feature: DB warning terminal disclosure and explicit recreation handoff; locale=en; light mode; show closed/open error box and danger warning with no credentials. Preserve existing assets. -->

## Clean start scopes

| Command | Cleared | Preserved / next step |
| --- | --- | --- |
| `uv run python -m scripts.schema recreate` | ORM tables/data and downloaded raw SEC/DART sources/manifest source entries | Code, `.env`, evaluation exports, unrelated tables, DB volume; empty Filings draft |
| Same command with `--sample` | Same clean start | Server-persisted NVDA/AMD FY2023–2024 draft; press Download yourself |
| Same command with `--keep-sources` | ORM tables/data only | All raw source files; confirm `RECREATE <checkout-name>` |
| `rag-fresh-start` | Same ORM/source scope as schema recreation; `--keep-sources` and `--sample` supported | Preserves settings/exports/volume; starts DEV, verifies readiness, prints the web hand-off links |
| `rag-fresh-start --extreme` | Previewed config, runtime files/caches and volumes | Two reset gates and browser acknowledgement; no automatic restart |

The two options cannot be combined. CLI acquisition still requires explicit identifiers and years. Source cleanup quarantines the exact previewed files under `data/.schema-recreate-journal` until the DB transaction commits. A DB failure attempts to restore all source bytes; inspect the schema before retrying because a lost connection can leave the DB outcome unconfirmed. Interrupted or incomplete cleanup retains `journal.json` with paths and phase and blocks another reset. Inspect that journal and preserve its backups; do not delete it or repeat recreation to hide the failure. If DB commit succeeded but file cleanup failed, the command returns failure and says so explicitly. The API remains stopped until you inspect state and run `rag-up`.
