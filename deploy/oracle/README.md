# Oracle Cloud origin (Always Free A1)

Runs the production stack (`pgvector` Postgres, FastAPI app, Caddy) on the Oracle
Cloud Always Free instance shared with the gomoku minimax engine. The GCP path in
`deploy/gcp` is unchanged; this directory reuses its compose file, Caddyfile and
artifact verifiers so the runtime layout on the instance is identical:

| | GCP (`deploy/gcp`) | Oracle (`deploy/oracle`) |
| --- | --- | --- |
| Machine | e2-medium, 4 GB, x86_64 | A1.Flex 2 OCPU, 12 GB, aarch64 |
| Image | built locally, pushed to Artifact Registry | built **on the instance** (`docker build`), no registry |
| Transport | `gcloud compute ssh` via IAP | plain `ssh`/`rsync`/`scp` |
| Caddy port | 8000 or 8080 | **8880** (8080 belongs to minimax) |
| Runtime layout | `/opt/docreview`, `/var/lib/docreview` | same |
| Installer | `apply_backend.sh` | app/Caddy update and rollback; app image verified with `docker image inspect` |

## Prerequisites

1. The shared instance is prepared by `gomoku/deploy/oracle/01_host_setup.sh`
   (Docker, swap, host firewall for 8080/8880, `/opt/docreview`, `~/build`). Host
   provisioning and the game remain in gomoku; do not copy or rerun those
   provisioners for a DocReview application update.
2. Inspect the security lists actually attached to the instance's subnet, all
   attached network security groups, and the host firewall. Their effective rules
   must restrict `tcp/8880` to the intended Cloudflare IPv4 ranges. A correctly
   named but unattached security list is not evidence. Verify Caddy's observed
   peer address on the actual Worker route and hold deployment if the premise
   differs; the peer is a shared rate-limit key, not Worker authentication.
3. Repo `.env` contains (see `.env.example`):

```sh
DEPLOY_ORACLE_HOST=<public IPv4>
DEPLOY_ORACLE_SSH_USER=ubuntu
# DEPLOY_ORACLE_SSH_KEY=~/.ssh/<key>
# DEPLOY_ORACLE_SSH_CONFIG=/path/to/ssh-config
DEPLOY_DOCREVIEW_ORIGIN=http://docreview-api.sungyongcho.com:8880
DEPLOY_DOCREVIEW_SITE_ORIGIN=https://docreview-rag.web.app
OPENAI_API_KEY_PROD=...
DEPLOY_POSTGRES_PASSWORD=...            # first-install only
DEPLOY_ARTIFACT_DIR=~/.local/share/docreview/prod-artifacts/<release>
```

The artifact directory is the same validated public bundle used for GCP
(`database.public.dump`, `originals.tar.gz`, allow-listed `eval_runs`). The
private dump is never transferred.

SSH, SCP, and rsync use strict host-key checking. Verify the host key and have it
available in the selected SSH configuration's known-hosts file before deployment;
`DEPLOY_ORACLE_SSH_CONFIG` supplies `-F` consistently to all three transports.

Keep host, SSH user/key path, and origin configuration in DocReview's own `.env`.
Use the existing credential source or exported environment for Cloudflare
deployment credentials; migrating routing does not require copying tokens into
this repository. Existing DNS for `docreview-api.sungyongcho.com` must point to the
intended Oracle origin. These deployment scripts do not change DNS.

## First installation

```sh
bash deploy/oracle/deploy_backend.sh first-install
```

1. Creates an isolated remote `mktemp` build context and rsyncs the source tree
   into it (no `.git`, `.env`, `.venv`, or local data). It does not use `--delete`
   against an existing shared checkout. `DEPLOY_ORACLE_BUILD_DIR` is the parent
   directory; each `build.XXXXXXXX` context is retained after success or failure
   until separately authorized cleanup.
2. `docker build` on the instance: Next.js static export + `uv sync --extra cpu`.
   `uv.lock` already pins `torch +cpu` `manylinux_2_28_aarch64` wheels. Expect 10-20 min the first time.
3. Stages `backend.env`, compose, Caddyfile, verifiers and artifacts in a private
   `/tmp/docreview-deploy.*`, then runs `apply_backend.sh` as root: restore, verify,
   start `db`, `app`, `caddy`.
4. Prints `/health` from the instance.

## Update / rollback

```sh
bash deploy/oracle/deploy_backend.sh update     # rebuild image, update app and Caddy together
bash deploy/oracle/deploy_backend.sh rollback   # restore previous app image and Caddy, no rebuild
DO_BUILD=false bash deploy/oracle/deploy_backend.sh update   # reuse the image already on the instance
```

The previous application image and Caddy configuration form one rollback pair.
Updates and rollbacks preserve the database, corpus, evaluations, and the existing
SQLite request/cost ledger. Do not use first-install to update a populated origin.
The current Caddy container must be running: the installer validates the proposed
configuration through it before changing the app, then reloads Caddy. A failed
update retains its staging directory and any recorded in-progress marker and
rollback pair for inspection and recovery; do not overwrite an interrupted update.

## Cut over routing

```sh
bash deploy/oracle/print_origin.sh
```

Keep the printed origin values in DocReview's `.env` when overriding the
dedicated Worker's defaults. The IP diagnostic is for verifying the existing DNS
record, not for changing DNS. The Worker code and deployment live in
[`deploy/cloudflare`](../cloudflare/README.md):

```sh
npm --prefix deploy/cloudflare ci
npm --prefix deploy/cloudflare test
npm --prefix deploy/cloudflare run deploy:dry-run -- --bootstrap
npm --prefix deploy/cloudflare run deploy -- --bootstrap
```

Bootstrap publishes `docreview-router` without routes or workers.dev/preview URLs.
Use it only before the initial route transfer: repeating it after the cutover
would remove the dedicated Worker's routes. The one-time cutover then updates
the existing route IDs for only `sungyongcho.com/docreview-rag` and
`sungyongcho.com/docreview-rag/*` from the shared gomoku Worker to `docreview-router`.
Keep the shared Worker's other routes intact. After route transfer and verification,
routine releases use `npm --prefix deploy/cloudflare run deploy:dry-run` and
`npm --prefix deploy/cloudflare run deploy` from this repository without publishing
gomoku. Static requests preserve the
`/docreview-rag` prefix on the existing Firebase Hosting site; API requests strip
`/docreview-rag/api` before reaching `http://docreview-api.sungyongcho.com:8880`.
Publish the public static bundle separately with
`FIREBASE_PROJECT_ID=<project-id> scripts/deploy/firebase.sh`.

Verify the dedicated routes, origin health, static UI, and SSE after an authorized
cutover. Local tests and successful deployment commands alone do not prove live
request/cost protection; keep those validation results distinct.

## Operations

```sh
ssh ubuntu@$DEPLOY_ORACLE_HOST 'cd /opt/docreview && sudo docker compose --env-file .env --env-file image.env ps'
ssh ubuntu@$DEPLOY_ORACLE_HOST 'sudo docker logs --tail 100 docreview-app-1'
```

Memory budget on the shared 12 GB host: Postgres is bounded by the compose
`shared_buffers=256MB`; the app with the CPU reranker uses 1.5-2.5 GB; minimax
is capped at 1 GB. Old images and retained build contexts accumulate on the shared
instance. Inspect their owners and rollback requirements before separately
authorized cleanup.
