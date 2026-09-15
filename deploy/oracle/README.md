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
| Installer | `apply_backend.sh` | same logic; app image verified with `docker image inspect` |

## Prerequisites

1. The instance is prepared by `gomoku/deploy/oracle/01_host_setup.sh` (Docker,
   swap, host firewall for 8080/8880, `/opt/docreview`, `~/build`).
2. The VCN security list admits `tcp/8880` from Cloudflare IPv4 ranges only.
3. Repo `.env` contains (see `.env.example`):

```sh
DEPLOY_ORACLE_HOST=<public IPv4>
DEPLOY_ORACLE_SSH_USER=ubuntu
# DEPLOY_ORACLE_SSH_KEY=~/.ssh/<key>
OPENAI_API_KEY_PROD=...
DEPLOY_POSTGRES_PASSWORD=...            # first-install only
DEPLOY_ARTIFACT_DIR=~/.local/share/docreview/prod-artifacts/<release>
```

The artifact directory is the same validated public bundle used for GCP
(`database.public.dump`, `originals.tar.gz`, allow-listed `eval_runs`). The
private dump is never transferred.

## First installation

```sh
bash deploy/oracle/deploy_backend.sh first-install
```

1. rsyncs the source tree (no `.git`, `.env`, `.venv`, local data) to `~/build/docreview-rag`.
2. `docker build` on the instance: Next.js static export + `uv sync --extra cpu`.
   `uv.lock` already pins `torch +cpu` `manylinux_2_28_aarch64` wheels. Expect 10-20 min the first time.
3. Stages `backend.env`, compose, Caddyfile, verifiers and artifacts in a private
   `/tmp/docreview-deploy.*`, then runs `apply_backend.sh` as root: restore, verify,
   start `db`, `app`, `caddy`.
4. Prints `/health` from the instance.

## Update / rollback

```sh
bash deploy/oracle/deploy_backend.sh update     # rebuild image from the current checkout, swap app only
bash deploy/oracle/deploy_backend.sh rollback   # previous image, no rebuild
DO_BUILD=false bash deploy/oracle/deploy_backend.sh update   # reuse the image already on the instance
```

Database, corpus, evaluations and the SQLite allowance survive updates exactly as on GCP.

## Cut over routing

```sh
bash deploy/oracle/print_origin.sh
```

Copy the three printed values into the **gomoku** `.env`, then run
`gomoku/deploy/03_deploy_cloudflare.sh`. The Firebase Hosting site is unchanged.

## Operations

```sh
ssh ubuntu@$DEPLOY_ORACLE_HOST 'cd /opt/docreview && sudo docker compose --env-file .env --env-file image.env ps'
ssh ubuntu@$DEPLOY_ORACLE_HOST 'sudo docker logs --tail 100 docreview-app-1'
```

Memory budget on the shared 12 GB host: Postgres is bounded by the compose
`shared_buffers=256MB`; the app with the CPU reranker uses 1.5-2.5 GB; minimax
is capped at 1 GB. Old app images accumulate on the instance; prune with
`sudo docker image prune -f` after a verified update (the rollback tag is kept).
