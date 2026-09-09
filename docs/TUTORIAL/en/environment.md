# Environment setup

Cloned the repository and unsure what to do? Run `source ./rag-alias.sh`, then
`rag-start-quick`. Use `rag-start-fresh` only for a separately confirmed checkout cleanup;
`rag-reset` resets ORM data/sources while preserving configuration and volumes.
All commands accept `--verbose` (`-vv`); see [CLI setup/reset](cli.md).

This page is for people who clone DocReview RAG from GitHub and run it locally from scratch. Follow Part 1 below to reach a running service and open Build. If you only want to try an existing instance, use [Quick Start](quickstart.md).

## Part 1: Setup {#qs-setup}

### Prerequisites {#prerequisites}

Use Bash or Zsh with uv and Docker Engine / Compose 2.24.4+. Node and npm run in the
web container; this path does not require their installation on the host.

```bash
git clone https://github.com/sungyongcho/docreview-rag-agent.git
cd docreview-rag-agent
source ./rag-alias.sh
rag-help
rag-start-quick
```

Source is the one-command install and activation path. Choose Y to save startup registration and restart the login shell; its banner reminds you to type rag-help. N loads only this session. Re-sourcing reports [already installed] or [update required] by comparing the version and registered definitions.

The Helper is included in the clone. `rag-alias update` refreshes it when the checkout changes. Use `source` for shell registration.
See [helper installation and updates](cli.md) for moved paths and the optional default-No login-shell offer after executed installation.
The first run creates `.env` only if absent. Edit it locally and rerun `rag-start-quick`:

```dotenv
SEC_USER_AGENT=Your Real Name your-real-contact@example.org
DART_API_KEY=<your-own-dart-key>
OPENAI_API_KEY_LOCAL=<your-own-openai-development-key>
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
```

Replace every placeholder. DEV reads only `OPENAI_API_KEY_LOCAL`; production reads
only `OPENAI_API_KEY_PROD`. Never paste keys into this page or capture them in screenshots.
The repository uses 384 embedding dimensions. Deterministic embeddings do not satisfy
this tutorial. Downloading filings needs valid SEC contact details and a DART key;
generating embeddings incurs OpenAI usage. The first-run command does neither.

The command creates a schema only in an empty database, preserves a compatible
existing database, and reports schema drift without resetting it. Fix missing tools
or configuration and rerun the same command; do not use `rag-reset` to repair
installation. Open the printed URL, normally `http://localhost:8000/docreview-rag-agent/`.

The setup command reports five stages: prerequisites, local configuration, project
service state/startup, schema preparation, and DEV server readiness. It identifies
`db`, `app`, and `web` as stopped, starting, unhealthy, or running; a running container
without a health check is not proof of server readiness. Existing healthy services
are reported before Compose reconciles the development configuration.

If configuration blocks progress, each key shows its `.env` line, shell value and effective
source, with credentials hidden. Choose `[f]` to ignore failing exports for this invocation,
`[e]` to save the two public embedding settings, or edit the named file and choose `[r]` to resume
at the same step. `[q]` cancels. The parent shell is unchanged; use the printed `unset KEY` there
for future invocations. For startup/readiness failures, existing read-only diagnostics run and
the command offers one confirmed, volume-preserving down/build/start recovery.

### SCREENSHOT NEEDED
<!-- Feature: guided Quick Start configuration repair; locale=en; TTY color/bold or NO_COLOR plain text; show a redacted shell-versus-file embedding conflict and successful resume without reinstalling dependencies. Preserve existing assets. -->

## 1. Open and verify the environment {#step-1}

**Goal:** establish that the current environment is ready for document inspection and
the preparation operations you intend to use.

**Prerequisites:** complete the setup above, or reuse a running service with a compatible
database. No document acquisition, embedding, or answer request is needed for this check.

**Screen path:** sidebar **System → System status**. The page heading is **Runtime readiness**.
Read the mode indicator; use the development environment for the preparation tutorial.
Public mode can expose fewer controls because it has different permissions. Corpus counts are shown on both builds; only whether the corpus is writable is withheld.

**Inputs and meaning:** this is a read-only check; no question or company selection is
required. Confirm that the service address is the intended environment. A different
API/database address can refer to different data even when the interface looks familiar.

**Primary action:** click **Refresh** once and wait for **Checking…** to finish.

**What visibly changes:** the status facts refresh. Read the API condition shown in the
System navigation or connection warning, then inspect the Database and Schema facts.
Corpus counts and model policy describe separate aspects of the same environment.

| Fact | What to verify | What it does not prove |
|---|---|---|
| API condition | The service responds instead of remaining unavailable or checking. | That documents or model calls are ready. |
| Database | Connected to the intended database. | That the schema is compatible. |
| Schema | No missing-table or schema-drift condition. | That the catalog contains any documents. |
| Mode and permissions | Development preparation controls are available when needed. | That a public instance permits administrator writes. |
| Corpus | Counts and readiness are collected, including honest empty or partial states. | That all displayed vectors were produced by the intended model. |
| Model availability | The selected engine is available, or its missing prerequisite is explained. | That a model request has succeeded or that an answer will be supported. |

<!-- capture:01-system-status -->

![System status separates actual API/database/schema health, corpus readiness and model availability.](../assets/01-system-status.en.jpg)

*System status separates actual API/database/schema health, corpus readiness and model availability. This development corpus contains 30 filings; no preparation was rerun.*

### SCREENSHOT NEEDED

<!-- SCREENSHOT NEEDED: feature=system-status-dev-badges; locale=en; theme=light; capture=system-status-tab-showing-dev-badges-on-local-model-policy-and-local-runtime-panels; issue=79; preserve-existing-assets=true -->

**Screenshot pending for the DEV badges on the Local model policy and Local runtime panels. Existing screenshots remain unchanged.**

**Completion criteria:** the API responds, the DB is connected, and the schema is usable.
You know whether this environment allows document preparation. An empty corpus does not
invalidate those checks; identifying existing data is the next step. Unknown fields
remain unresolved and should not be counted as passed.

**Common failure and recovery:** if the page opens but API checks fail, inspect
`rag-dev ps` and `rag-dev logs --tail=80 app`. Follow [Troubleshooting](troubleshooting.md)
for the recorded symptom, apply the relevant fix, and repeat Refresh. For a fresh DB,
use the linked schema setup. A schema-drift error is not a reason to delete an existing DB.

**Next:** open Build and continue with the developer preparation guide below.

## Open Build and continue {#open-build}

Open the printed application URL and select **Build → Pipeline**. Confirm that you can inspect the preparation graph and the selected step. Opening Build does not download a filing or run a model.

**Service ready is not data ready.** Continue with [Quick Start — DEV ONLY](quickstart-dev.md#qs-web-1): choose CLI or Web to verify the environment, acquire the two example reports, parse and chunk them, prepare embeddings and BM25, and check readiness before asking. Reuse completed work. The existing [twelve-step learning path](overview.md#learning-path) then covers questions, settings, and evaluation.

### SCREENSHOT NEEDED
<!-- Feature: fresh-clone environment setup handoff; locale=en; light mode; show successful redacted service readiness and Build → Pipeline open before acquiring sources, with separate API/database/schema facts and the DEV Quick Start continuation. Preserve existing assets. -->

## Recover a blocked preparation step {#schema-recovery}

Build shows database schema status separately from source storage permissions. A schema mismatch does not mean `data/` is unwritable. Use **Check schema** to reload its reported state. When **Run in terminal** appears, copy its command, run it from this checkout, then return to the same step and select **Check updated status**. An unchanged blocker remains visible; clicking the button alone does not repair it.

```bash
uv run python -m scripts.schema check
```

Normal Compose startup now prepares an empty database automatically after DB health succeeds.
The image entrypoint inspects an existing database without schema changes and refuses to launch
the API on drift. This applies to dev, prod preview and the deployment Compose using this image.
The web container may still open while the API is blocked; inspect `rag-dev logs --tail 80 app`
for the schema diagnosis and local `check`/`recover` commands. Database-free canned images skip
the gate. Source acquisition and indexing remain separate prerequisites.

If you started only the DB, you can still prepare an empty local database manually:

```bash
uv run python -m scripts.schema prepare
```

Existing incompatible databases are preserved and preparation refuses to change them. Rebuilding images or restarting services does not repair an incompatible database layout. Select a compatible or empty local database before indexing. If you deliberately choose to discard the local DEV database, use the separately confirmed `scripts.schema recreate` path in the CLI guide; it is never automatic. Service and actual storage-permission blockers display their own terminal command and expected result.

### Local container file ownership

Local Compose keeps the image's non-root UID 10001 and uses `HOST_GID` as the app's primary group
(default 1000; `rag-dev` supplies the invoking host group). API startup applies `umask 0002` after
the unchanged database initialization gate. New source/download and evaluation directories are
group-writable; saved local-model settings are mode 0640, readable by the host group. The existing
image user and deployment Compose remain unchanged; this is a local bind-mount sharing policy.

The host's `data/` directory must permit that group to write. For direct Compose on a host whose
primary group is not 1000, set `HOST_GID` to `id -g`. Earlier container-owned files keep their existing
permissions: the reset preview prints the exact elevated repair for blocked source paths. If an old
`data/local-settings` or `data/eval_runs` path also needs host access, ask its owner to apply the same
scoped ACL repair to that directory. No ownership/ACL change is automatic. After updating this local
Compose policy, recreate the app with `rag-dev up -d`; an existing container does not acquire a new
primary group or command merely from a source reload. See [reset recovery](cli.md).

An error links to the relevant pipeline step through **Inspect this step**, or to setup guidance for a database/schema blocker. Follow that destination for the current diagnosis and terminal instructions; other error panels keep only the cause and navigation link.

### SCREENSHOT NEEDED

<!-- SCREENSHOT NEEDED: feature=schema-and-terminal-handoff-recheck; locale=en; theme=light; capture=blocked-and-resolved-states; issue=17; preserve-existing-assets=true -->

**Screenshot pending for the updated controls and resulting state. Existing screenshots are unchanged.**


For incompatible schemas, run `.venv/bin/python -m scripts.schema check`;
Quickstart ignores an external `DATABASE_URL` and uses the local `DB_PORT`. Safe target-selection
recovery is tracked in [#25](https://github.com/sungyongcho/docreview-rag-agent/issues/25).
Do not reset your database to resolve this setup stop.

## Keep the environment and work separate {#environment-boundaries}

Ollama is optional for local answers and is installed separately from this DocReview stack. In **Settings → Local LLM**, select **Default** and use **Run connection diagnostics** before making connection changes. Use **Add a server…** only for a different endpoint. The [macOS/Linux setup guide](ollama.md) covers installation and backend access; `rag-ollama-check` performs read-only diagnostics. A missing answer model does not by itself mean the API, database, or schema is broken.

The development stack supports source reload and live documentation updates. API
restarts can interrupt queued work; check Jobs before deciding that an interrupted
operation needs a retry. [Runtime](runtime.md) explains job and execution states.

> [!DEV]
> Production preview is a DEV-only inspection tool. It leaves the backend in DEV and does not grant production operator permissions.

In a running DEV environment, **Production preview** opens the same PROD interface against the current DEV backend. Public reads, bounded search and answers execute through the public request policy. Administrator actions and local engines stay unavailable. Finish an active DEV request before opening the preview; **Exit preview** restores the retained DEV tree.

Conversations, document scope, settings and browser-only experiments persist under a preview-specific localStorage namespace. They survive re-entry and reload without importing DEV conversations. Language and theme are shared. No preview database is created or copied: published source data is read from the DEV backend's database, and DEV reprocessing can change it.

Click the struck PROD badge to pin its explanation; Close, Escape or an outside click dismisses it. Hover and keyboard focus also expose the explanation. Model calls are real and can consume usage.

<!-- capture:28-production-preview -->

![The isolated public-interface preview is explicitly labeled as using a DEV backend.](../assets/28-production-preview.en.jpg)

*Earlier preview layout; the current preview supports public requests and persistent isolated storage as described above.*

### SCREENSHOT NEEDED
<!-- feature=interactive-production-preview; locale=en; theme=light; state=pinned-PROD-explanation-with-public-interface; preserve-existing-assets=true -->
The public bundle and production backend remain separate release checks; the preview does not change server credentials or deployment settings.

`rag-prod` opens a local public preview with different permissions; it does not publish
the site. A working local-model connection in development does not make Local LLM
available in public mode. See [CLI environment commands](cli.md#development-and-local-prod-preview)
for deliberate mode changes, and [Settings](settings.md) for saved connection settings.

Do not use a destructive reset to make a readiness indicator turn green. Refresh reads
state; it does not repair, ingest, index, or call an answer model.

## Production deployment (near-zero cost) {#production-deployment}

Everything above runs on your machine. The public site is a separate, deliberately
small target: one Always Free VM behind a Cloudflare Worker, and a static export on
Firebase Hosting. The scripts live in `deploy/gcp/` and `scripts/deploy/`; none of them
runs as part of the tutorial.

```text
visitor ──HTTPS──> sungyongcho.com/docreview-rag-agent/*
                          │  Cloudflare Worker (gomoku repo)
            ┌─────────────┴──────────────┐
   /docreview-rag-agent/*        /docreview-rag-agent/api/*
            │                              │  plain HTTP
            ▼                              ▼
   Firebase Hosting             GCP e2-micro (us-central1-a, ephemeral IP)
   static Next export           firewall: tcp:8000 from Cloudflare IPv4 only
                                  Caddy :80 → host 8000
                                    allow-list + X-DocReview-Public: true
                                      └─> FastAPI ──> pgvector Postgres
                                  operator: 127.0.0.1:8001 via SSH tunnel only
```

TLS ends at Cloudflare. The VM speaks plain HTTP on port `8000`, and the GCP firewall
admits only Cloudflare's published IPv4 ranges, so nothing else can reach it directly.
Caddy proxies only the public paths and adds `X-DocReview-Public: true`; that header is
what hides `/admin/*` and `/ingest`, so Caddy must stay in front of every externally
reachable port. The operator API is reachable only through
`deploy/gcp/operator_tunnel.sh`, which forwards the loopback-only port `8001`.

### Order of operations {#production-order}

1. Fill `.env` with `DEPLOY_GCP_PROJECT` (and optionally `DEPLOY_GCP_ZONE`,
   `DEPLOY_VM_NAME`, `DEPLOY_MACHINE_TYPE`) and copy `deploy/gcp/backend.env.example`
   to `deploy/gcp/backend.env` (gitignored). `deploy/gcp/deploy_env_config.sh` loads
   both and prints a masked summary.
2. `deploy/gcp/create_vm.sh` creates the e2-micro VM with a `pd-standard` 30 GB boot
   disk, an ephemeral external IP, and the Cloudflare-only firewall rule for `tcp:8000`.
   `deploy/gcp/startup.sh` installs Docker and a 2 GB swap file on first boot.
3. Copy the prepared corpus into `/var/lib/docreview/corpus` on the VM, then run
   `deploy/gcp/deploy_backend.sh`. It copies `docker-compose.deploy.yml`,
   `deploy/Caddyfile` and `backend.env` (as `/opt/docreview/.env`) and starts the stack.
4. `deploy/gcp/print_origin.sh` prints `DEPLOY_DOCREVIEW_ORIGIN=http://<ip>:8000` and
   `DEPLOY_DOCREVIEW_SITE_ORIGIN=https://<site>.web.app`.
5. Paste those lines into the gomoku repo's `.env` and run its
   `03_deploy_cloudflare.sh`; the Worker routes `/docreview-rag-agent/api/*` to the
   VM and everything else under `/docreview-rag-agent/*` to Firebase Hosting.
6. `FIREBASE_PROJECT_ID=<project-id> scripts/deploy/firebase.sh` builds the public
   bundle with `NEXT_PUBLIC_ADMIN_MODE` unset and deploys it.

The external IP is ephemeral: stopping and starting the VM changes it, so repeat
steps 4 and 5 afterwards. A reserved static IP avoids that at roughly $3/month.

### Monthly cost {#production-cost}

| Component | Detail | Cost |
|---|---|---|
| GCP e2-micro | Always Free in `us-central1`, `us-east1`, `us-west1`: 1 shared vCPU, 1 GB RAM, 30 GB `pd-standard`, 1 GB/month North America egress | $0 |
| External IP | Ephemeral; a reserved static IP would be about $3/month | $0 |
| Firebase Hosting | Free tier (static export) | $0 |
| Cloudflare Worker | Free tier, shared with the gomoku Worker | $0 |
| OpenAI | Capped per UTC day by `DOCREVIEW_PUBLIC_DAILY_COST_USD` (`1.00` in the compose file) | ≤ $1/day |

Trade-offs: visitors in Europe see roughly 100 ms of added latency because the VM sits
in North America. The database (about 430 MB today) fits the 30 GB disk with room for
Postgres, Docker images and swap. With 1 GB of RAM, Postgres runs with
`shared_buffers=128MB` and `work_mem=4MB`; the 2 GB swap file absorbs the occasional spike.
