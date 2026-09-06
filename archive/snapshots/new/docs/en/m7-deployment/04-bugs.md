# M7 Bugs

These failures are narrow release regressions with executable checks.

## B01 — Ambient key silently activates paid mode

**Symptom:** setting `OPENAI_API_KEY` changes a canned launch into a provider-backed run.

**Root cause:** provider selection treats credential presence as consent.

**Fix:** require both `DOCREVIEW_MODE=runtime` and a server-side key; canned mode wins by default.

```bash
uv run pytest -o addopts="" tests/release/test_01_config.py -k "operator_key" -q
```

## B02 — The public browser becomes a secret form

**Symptom:** a password textbox sends visitor keys through Gradio state.

**Root cause:** "BYO key" is interpreted as a browser feature rather than operator-owned server configuration.

**Fix:** expose no key component. Configure an optional Space secret or ephemeral local environment value only after explicit authorization.

```bash
rg -n "api.?key|password|secret" app/demo.py app/release deploy/huggingface
```

## B03 — One in-process limiter is described as distributed protection

**Symptom:** a multi-worker deployment admits the configured limit once per worker.

**Root cause:** process-local counters have no shared state.

**Fix:** pin one worker and describe the LRU limiter as single-instance protection. Add an external shared limiter before replicas.

```bash
rg -n -- "--workers|single_process|single-instance" deploy/huggingface app/release docs/en/m7-deployment docs/ko/m7-deployment
```

## B04 — Forwarded addresses are trusted by default

**Symptom:** a caller rotates `X-Forwarded-For` values to evade a per-client limit.

**Root cause:** proxy headers are accepted without a trusted reverse-proxy boundary.

**Fix:** use the direct peer by default and enable forwarded parsing only in an explicitly trusted environment.

```bash
uv run pytest -o addopts="" tests/release/test_03_guards.py -k "forwarded" -q
```

## B05 — Guard responses bypass security headers

**Symptom:** successful API responses have security headers but read-only 403 or rate-limit 429 responses do not.

**Root cause:** the header middleware is registered inside the guard that returns early.

**Fix:** register the header layer last so it wraps the guard, and assert both early paths.

```bash
uv run pytest -o addopts="" tests/release/test_03_guards.py -k "headers or ingestion" -q
```

## B06 — A server key reaches logs or persisted traces

**Symptom:** exception text, Uvicorn output, or a run row contains a credential value.

**Root cause:** the key is passed beyond provider construction without redaction context.

**Fix:** keep it as `SecretStr`, pass its value only to the provider plus persistence/log redaction, keep provider remote storage off, and expose only a boolean publicly.

```bash
uv run pytest -o addopts="" tests/release -k "secret or redacted or runtime_composition" -q
```

## B07 — Public ingestion mutates the release database

**Symptom:** anonymous traffic can call `/ingest`.

**Root cause:** the local full-system API is exposed without a deployment policy layer.

**Fix:** return a typed read-only 403 before service execution unless an operator explicitly enables ingestion in a controlled environment.

```bash
uv run pytest -o addopts="" tests/release -k "ingest" -q
```

## B08 — Space metadata is mistaken for publication

**Symptom:** portfolio wording says "deployed" because a valid YAML template exists.

**Root cause:** configuration readiness and an external account mutation are conflated.

**Fix:** say "deployment-ready" and record that no Space, push, or external resource was created.

```bash
rg -n "deployment-ready|not published|external" README.md docs/en/m7-deployment docs/ko/m7-deployment deploy/huggingface
```

## B09 — A clean archive secretly copies local corpus or credentials

**Symptom:** clean verification succeeds only because `.env`, `.venv`, or ignored SEC HTML was copied.

**Root cause:** a recursive filesystem copy is used instead of Git-derived source selection.

**Fix:** build a null-delimited list from tracked and intentional untracked source, honor ignore rules, and run only self-contained suites in the clean archive.

```bash
scripts/verify_clean_checkout.sh
```

## B10 — The nonroot Space user cannot create the virtual environment

**Symptom:** the image fails at locked sync with `Permission denied` for `/home/user/app/.venv`.

**Root cause:** `WORKDIR` exists but remains owned by root when the build switches to UID 1000.

**Fix:** create and chown the exact application directory before `USER user`, then perform the locked sync as that user.

```bash
docker build --file deploy/huggingface/Dockerfile --tag docreview-m7-space:local .
```
