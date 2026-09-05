# Local command reference

`rag_alias.sh` registers commands for starting, stopping, and inspecting this checkout in Bash or Zsh.
For the twelve-step screen-led exercise, start with the [DocReview RAG v2 overview](overview.md).
Use [environment setup](environment.md#step-1), [acquisition](acquisition.md#step-3), and
[indexing](indexing.md#step-5) alongside the commands below.

CLI and dashboard operations share results when they use the same local database, source directory, and
embedding configuration. Check completed CLI work in the dashboard instead of running it twice. A different
`DATABASE_URL` or remote server is a different environment.

## Register commands and open help

Run from the repository root:

```bash
source ./rag_alias.sh
rag-help
```

`source` registers functions and aliases in the current shell. Executing `./rag_alias.sh` only displays setup
instructions; it cannot modify its parent shell. Registration does not install dependencies.

The shell and Web share the same checked-in Small ASCII wordmark. An 80-column terminal displays the
full name; narrower terminals use the DR monogram or a plain product line. `NO_COLOR`, dumb terminals,
and redirected output remain free of color escapes. Printing the banner needs no language runtime or network.

Load the file again in each new terminal, or add one source line with this checkout's real absolute path to
`.bashrc` or `.zshrc`. Do not add duplicates.

```bash
# Replace this placeholder with your checkout's actual absolute path.
source /absolute/path/to/docreview-rag-agent/rag_alias.sh >/dev/null
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

With no arguments, `rag-dev` and `rag-prod` use `up -d`. The `rag-dev-up/down` and `rag-prod-up/down`
aliases are shortcuts. Without registration, use `bash scripts/run_local.sh dev up -d`.

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
OPENAI_API_KEY=
OPENAI_API_KEY_LOCAL=<replace-with-your-real-development-key>
OPENAI_API_KEY_PROD=
DART_API_KEY=
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
```

Do not leave the sample DART/prod placeholders in place. Check separately configured shell keys without
printing them. A nonempty `OPENAI_API_KEY` overrides mode-specific slots; clear it to use the development slot.
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

Create tables so the **first document can be ingested in the web UI**. This does not ingest documents or
create embeddings. Complete installation first and reuse an existing compatible schema.

```bash
rag-dev up -d db
rag-dev ps db
rag-dev exec -T db psql -U filing -d filing -c '\dt'
```

For an empty DB, create missing schema objects. Existing model tables are not dropped or recreated.
If schema drift is reported, use troubleshooting rather than deleting data.

```bash
MODE=dev uv run python - <<'PY'
import asyncio
from app.db.bootstrap import bootstrap_schema
from app.db.session import engine

async def prepare():
    """Create missing schema objects and release the database connection."""
    try:
        await bootstrap_schema(engine)
    finally:
        await engine.dispose()

asyncio.run(prepare())
print("Schema ready")
PY
rag-dev exec -T db psql -U filing -d filing -c 'SELECT count(*) AS documents FROM documents;'
```

A fresh database has zero documents. Continue with [web acquisition and ingestion](walkthrough.md#3-download-nvidia-filings).
No paid model is called by schema preparation.

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
![Alternative text describing what to inspect](../assets/02-pipeline.jpg)
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
metadata is stored in existing JSON payloads; these fields do not require a schema migration.

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

`rag-diagnose` runs the same diagnostic. These commands do not install, download/load models, start services, save settings, or generate answers. Read configuration, backend connectivity, and answer-model checks separately. An unavailable inventory is unconfirmed; an installed but unloaded model is normal standby.

For an older API without the shared diagnostic route, the command explicitly reports a legacy read-only fallback. `ollama list` and `ollama ps` independently show installed and currently loaded models. Continue with [server selection](settings.md#local-server), [connection recovery](ollama.md#diagnostics), or [answer configuration](answers.md#engines).

## Prepare one NVIDIA filing

This block creates a one-filing manifest for the guided exercise while preserving the main manifest.
It checks an existing tutorial manifest rather than overwriting it. It does not download, ingest, or call a model.

```bash
uv run python - <<'PY'
import json
from pathlib import Path

source = Path("data/corpus/manifest.json")
target = Path("data/corpus/tutorial-manifest.json")
accession = "0001045810-24-000029"
entries = [row for row in json.loads(source.read_text())
           if row["ticker"] == "NVDA" and row["accession"] == accession]
assert len(entries) == 1, "NVIDIA FY2024 must exist exactly once"
if target.exists():
    saved = json.loads(target.read_text())
    assert len(saved) == 1 and saved[0]["accession"] == accession, "Inspect existing tutorial manifest"
else:
    target.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
print(target)
print(entries[0]["file"], "present:", Path(entries[0]["file"]).is_file())
PY
```

**Only when the source is missing**, download it using a real SEC contact. Existing source files are reused;
`--force` is unnecessary.

```bash
MODE=dev uv run python -m app.ingestion.edgar_api --manifest data/corpus/tutorial-manifest.json
test -s data/corpus/NVDA/2024-02-21_0001045810-24-000029.html && echo 'NVIDIA source ready'
```

If acquired through the web already, skip downloading and return to [manifest ingestion](walkthrough.md#4-ingest-the-source-into-documents-and-chunks).

## Python CLI reference

Use these instead of the corresponding web operation, not in addition to completed work.

### Ingestion

```bash
MODE=dev uv run python -m app.cli ingest \
  --manifest data/corpus/tutorial-manifest.json --expected-documents 1 --create-schema
```

Parse, chunk, upsert, and recalculate BM25 for the selected manifest. `--create-schema` creates missing
objects without altering/dropping existing tables. Expect `status: ok`, one document, and a positive chunk count.

### Embedding and retrieval

**Paid OpenAI operation:** backfill missing/mismatched embeddings across the DB and then embed the query.
The `--doc-id` filter restricts retrieval results, not the backfill scope.

```bash
MODE=dev uv run python -m app.cli retrieve \
  --query "What drove NVIDIA data center revenue growth in fiscal 2024?" \
  --doc-id NVDA-FY2024 --provider openai --embed-missing -k 5
```

Omit `--embed-missing` when vectors are ready. Query embedding still incurs cost. This returns evidence,
not a generated answer.

### DART acquisition

Set a real DART_API_KEY. Before ingesting an existing manifest, verify sources for all its entries.

```bash
MODE=dev uv run python -m app.ingestion.dart_api --stock-codes 005930 --fiscal-year 2024
MODE=dev uv run python -m app.cli ingest --manifest data/corpus/dart-manifest.json
```

Embedding is a separate step. Confirm new records in Documents.

### Option help

```bash
uv run python -m app.cli ingest --help
uv run python -m app.cli retrieve --help
uv run python -m app.ingestion.edgar_api --help
uv run python -m app.ingestion.dart_api --help
```

## Shutdown and selective cleanup

### Stop and resume while preserving data

Normal shutdown preserves DB data, source files, saved configuration, and browser conversations:

```bash
rag-dev down
# In a later terminal, from the repository root:
source ./rag_alias.sh
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

`--recreate-schema` is a separate destructive option that drops model tables, recreates them, and ingests
into the currently connected DB. It is not the same as volume deletion or non-destructive `--create-schema`.
It is not required for this walkthrough.

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
MODE=dev uv run python -m app.db.migrate --plan
```

The migration plan is for schema problems, not arbitrary connectivity failures. If the web opens, inspect
System status, Jobs, and the answer's Run trace. If the web itself is unavailable, inspect web logs first.

| Symptom | Check | Action and completion |
|---|---|---|
| Web unavailable | web logs, APP_PORT, port owner | Inspect `rag-dev logs --tail=80 web`; use the correct URL |
| API/DB unavailable | service and DB health | Restore the connection; refresh and verify schema |
| schema_drift | existing schema versus current models | Read the migration plan, back up, apply applicable preserving migrations with `MODE=dev uv run python -m app.db.migrate --apply`, then verify compatibility |
| Missing/stale embeddings | provider, identity, pending | Correct configuration and run needed paid backfill after reviewing its DB-wide scope |
| BM25 not ready | missing/invalidated statistics | Rebuild BM25 and verify job success plus readiness |
| NOT_IN_DOCS | scope, company/year filters, evidence | Inspect Documents and candidates; ask something actually supported by the corpus |
| provider_failure | status, attempts, details, node | Fix key/access/connectivity/limits; schema recreation does not fix this |
| budget_exceeded | resource, limit, observed, blocked_node | Adjust the specific run limit; retries can cost more |
| node_error | error_type, message, node | Fix the named non-model stage before retrying |
| interrupted job | app restart | It is not automatically resumed; inspect state and explicitly retry |

The default wall-clock limit is **120 seconds for the whole run**, not a token budget. Input tokens,
output tokens, and iterations also accumulate across calls and retries. Evidence size is a separate setting.
A local server can answer readiness checks while still being too slow for an actual model request.

Queued/running jobs are active; succeeded/failed/cancelled jobs are finished. Interrupted means the app
restarted mid-work. Failed and interrupted jobs offer Retry; cancelled jobs do not. Inspect completed work
and remaining scope before retrying paid embedding.

![Localized trace and usage of a saved successful run](../assets/16-run-trace.jpg)

*This trace belongs to a saved successful run. Usage and the node path retain their recorded values, and unperformed phases remain gray. Inspect status and error details in the same place when diagnosing a failure. No new model call was made for capture.*

## Remove command registration

```bash
rag-alias-delete
# If the registered command is unavailable:
./rag_alias.sh --uninstall
```

Confirm the shown startup file/checkout. The matching registration line is backed up and removed; other
projects, code, and DB data are preserved. The sourced command can also remove unchanged commands from
the current shell. A separately executed script cannot modify its parent shell, so follow its instructions.
Keep the backup path and verify a new terminal does not auto-load the registration. To restore it, follow
[registration instructions](#register-commands-and-open-help).
