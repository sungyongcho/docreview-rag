# M7.2 Tutorial 3 — Carry the Python promises into the image

M7.1 built every code-level guard. All of it becomes meaningless if the container ends up like this.

- **runs as root** — a container escape does far more damage
- **starts multiple workers** — `InProcessRateLimiter` counts within one process, so four workers means four times the intended limit
- **packages secrets** — a `.env` swept into the build context lets anyone with the image read the key
- **exposes the wrong port**

The second is the subtle one. If whoever writes the Dockerfile does not know the rate limit rests on a **single-process assumption**, raising the worker count for performance quietly dismantles it.

So the deployment artifact has to preserve the same assumptions. **A boundary does not end at the code.**

**Prerequisite:** The `tests/release` app suite from tutorial 2 passes.

### Metadata is configuration, not proof

`deploy/huggingface/README.md` explains how to deploy. That is **not evidence that deployment happened.**

Likewise, a health check says only **the process is ready**, and the local UI smoke test verifies only **the canned Gradio boundary**. What each one proves and does not prove is written down.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `.dockerignore` | **Write the configuration, then confirm the responsibility** | What must leave the build context |
| `Dockerfile` | **Define the structure, then review the design decision** | Non-root, single worker, health check |
| `docker-compose.yml` | **Define the structure** | The local API and database route |
| The HF `Dockerfile` | **Inspect the boundary conversion** | Where Space's requirements meet our assumptions |
| `space.env.example` | **Write the configuration** | Defaults that may be public |

### 1. What must leave the build context

#### Create `.dockerignore` — build context exclusions

**Learning action — write the configuration, then confirm the responsibility:** note which leak or bloat each line prevents.

<!-- file: .dockerignore -->
```text
.git
.venv
.env
.env.*
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.mypy_cache
htmlcov
old
42_curriculum
data/corpus/**/*.html
data/eval_runs
```

**What to look for in the code**

- `.env` is there. Without it, **the key stays permanently in an image layer** — deleting it later still leaves it in layer history.
- `data/` is there. The corpus is 2 MB × 20 and would bloat the image needlessly. The root `Dockerfile` `COPY`s `data` explicitly, and the Space image never includes it.

### 2. Non-root, single worker, health check

#### Create `Dockerfile` — the local API image

**Learning action — define the structure, then review the design decision:** note where `USER appuser` sits and why `--workers 1` is present.

<!-- file: Dockerfile -->
```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "python", "-m", "app.cli", "serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**What to look for in the code**

- `useradd` creates a uid 10001 user and `USER appuser` switches to it. Everything after runs non-root.
- `COPY --chown=appuser:appuser` moves ownership, avoiding a non-root process unable to read root-owned files.
- `--workers 1` is explicit. **M7.1's in-process rate limit depends on that number.**
- Dependency installation comes **before** the code `COPY`. Changing code keeps the dependency layer cached.
- `HEALTHCHECK` hits `/health` — the endpoint M5.2 kept away from the database.

#### Create `docker-compose.yml` — the local stack

**Learning action — define the structure:** note the dependency between the database and API services.

<!-- file: docker-compose.yml -->
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: filing
      POSTGRES_USER: filing
      POSTGRES_PASSWORD: filing
    ports: ["${DB_PORT:-5432}:5432"]
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U filing -d filing"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      CORPUS_DIR: /app/data/corpus
      DATABASE_URL: postgresql+asyncpg://filing:filing@db:5432/filing
      EMBEDDING_PROVIDER: deterministic
    depends_on:
      db:
        condition: service_healthy
    ports: ["${APP_PORT:-8000}:8000"]
    init: true
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()",
        ]
      interval: 10s
      timeout: 3s
      start_period: 10s
      retries: 5

volumes:
  pg_data:
```

**What to look for in the code**

- It uses a pgvector image. M1.4's `CREATE EXTENSION` only succeeds on an image that has the extension.
- The API's `depends_on` carries a healthcheck condition, so seeding never runs before the database is up.

### 3. Where Space's requirements meet our assumptions

#### Create `deploy/huggingface/Dockerfile` — the Space image

**Learning action — inspect the boundary conversion:** put it beside the root `Dockerfile` and find every difference.

<!-- file: deploy/huggingface/Dockerfile -->
```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DOCREVIEW_MODE=canned \
    DOCREVIEW_PORT=7860

RUN useradd --create-home --uid 1000 user \
    && mkdir --parents /home/user/app \
    && chown user:user /home/user/app
WORKDIR /home/user/app

COPY --from=uv /uv /uvx /bin/
COPY --chown=user:user pyproject.toml uv.lock README.md ./

USER user
RUN uv sync --locked --no-dev --extra demo --no-install-project

COPY --chown=user:user app ./app

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "uvicorn", "app.release.space:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--log-level", "warning"]
```

**What to look for in the code**

- The uid is **1000**. Hugging Face Spaces requires it — a platform constraint, not our choice.
- The port is 7860. Also a Space convention.
- `DOCREVIEW_MODE=canned` is **baked into the image.** With no environment variable set it still comes up canned — M7.1's default pinned once more at the image layer.
- `data` is not copied. The Space runs canned only, without a corpus.
- `--extra demo` installs Gradio, a dependency the local image does not have.

#### Create `deploy/huggingface/space.env.example` — public default example

**Learning action — write the configuration:** note that this file contains no real key.

<!-- file: deploy/huggingface/space.env.example -->
```bash
# Public Spaces should remain canned unless runtime dependencies are explicitly provisioned.
DOCREVIEW_MODE=canned
DOCREVIEW_RATE_LIMIT_PER_MINUTE=10
DOCREVIEW_RATE_LIMIT_PER_DAY=100
DOCREVIEW_RATE_LIMIT_MAX_CLIENTS=1024
DOCREVIEW_TRUST_PROXY_HEADERS=false
DOCREVIEW_ALLOW_INGEST=false

# Runtime review is opt-in and still bounded by all three caps.
DOCREVIEW_OPENAI_MODEL=gpt-4.1-mini
DOCREVIEW_OPENAI_MAX_INPUT_TOKENS=12000
DOCREVIEW_OPENAI_MAX_OUTPUT_TOKENS=600
DOCREVIEW_OPENAI_MAX_COST_USD=0.01
DOCREVIEW_OPENAI_INPUT_PER_MILLION_USD=0.40
DOCREVIEW_OPENAI_OUTPUT_PER_MILLION_USD=1.60

# Configure OPENAI_API_KEY only as a server-side Space secret, never as a public variable.
```

**What to look for in the code**

- The `.example` suffix plus `.dockerignore` blocking `.env` means that even accidentally creating the real file keeps it out of the image.
- Real secrets go into the Space settings screen, never into the repository.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/release/test_05_assets.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| An image running as root | The container runs non-root. |
| A worker count other than 1 | The in-process rate-limit assumption holds. |
| `.env` missing from `.dockerignore` | No secret remains in an image layer. |
| A port or uid unlike Space's convention | Platform constraints are satisfied. |
| An image defaulting to runtime | A deployment never spends money by default. |

### What you should be able to explain now

- **What of M7.1 is quietly dismantled by raising the worker count?**
  - **Answer:** `InProcessRateLimiter` counts independently inside each process. Two workers therefore permit roughly twice the configured traffic, breaking the single-process rate-limit boundary without raising an error.
- **Why is deleting a `.env` too late once it entered an image?**
  - **Answer:** Container images retain the contents of earlier layers. Deleting the file in a later layer hides it from the final filesystem view but leaves the secret recoverable from layer history.
- **Why do the root image and the Space image use different uids?**
  - **Answer:** The root image chooses uid 10001 simply to run as a non-root application user. Hugging Face Spaces requires uid 1000, so the Space image follows that platform constraint while preserving the same non-root guarantee.
- **Why bake `DOCREVIEW_MODE=canned` into the image?**
  - **Answer:** It pins the zero-cost default at the image layer as well as in application settings. A deployment with no environment configuration therefore cannot start making provider calls accidentally.
- **Why is a README not evidence of deployment?**
  - **Answer:** A README records configuration and instructions; it does not show that a remote service was created, started, and answered a request. Publication requires evidence from an actual running deployment.

---

[← Previous: Release app assembly](02-release-app.md) · [Module overview](../03-build.md) · [Next: Clean-checkout verification →](04-clean-checkout.md)
