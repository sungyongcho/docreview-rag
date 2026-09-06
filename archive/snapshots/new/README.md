# DocReview RAG Agent

An evidence-first document-review system for SEC 10-K filings. It parses filing structure
and tables, preserves source hashes and character spans through retrieval, evaluates ranked
evidence, and exposes guarded review results through a CLI, FastAPI, and a Gradio portfolio
demo.

The central design rule is simple: an answer is useful only when its evidence identity and
failure state remain inspectable.

## What the repository demonstrates

- structure-aware ingestion from raw SEC HTML into section and table chunks;
- idempotent PostgreSQL persistence with exact `[start_char, end_char)` source spans;
- exact pgvector cosine search plus PostgreSQL full-text search with selectable `ts_rank_cd`/BM25 lexical ranking, fused by rank-only RRF, with an optional local cross-encoder rerank stage;
- source-bound golden cases, span-overlap scoring, regression baselines, and ablations;
- strict structured model output, citation allow-listing, cumulative budgets, and traces;
- typed CLI and HTTP boundaries that default to deterministic, offline-safe behavior; and
- a small Gradio surface that makes supported, unsupported, trace, and cost states visible.

## Measured evidence

| Evidence | Repository result | Honest interpretation |
|---|---:|---|
| Corpus manifest | 20 filings; 5 each for AMD, INTC, MU, and NVDA | A bounded portfolio corpus, not a general SEC index |
| 1200-character indexing arm | 9,172 chunks in 33.860 s | Passed the 300 s local budget, BM25 statistics included |
| 500-character indexing arm | 12,984 chunks in 38.453 s | More chunks, but no longer the quality leader under BM25 |
| Best measured Recall@5 | 0.521 for 1200-lexical-bm25 | Lexical BM25 leads every arm; fusing the weak deterministic vector ranking dilutes it |
| 200-query budget | 29.786 s total; 213.559 ms P95 | Passed the 90 s local budget under the relaxed `ts_rank_cd` hybrid |
| M6.1 demo acceptance | 6 passed; build and loopback launch/close at `127.0.0.1:7861` succeeded | Proves the local canned UI boundary, not runtime-backed corpus retrieval |
| M6 regression checkpoint | 697 passed, 1 skipped | Full offline suite after the real M5/M6 retrieval-shape join |
| M7 focused release checkpoint | 67 passed | Release, demo, and API guards without database/provider network calls |
| M7 regression checkpoint | 718 passed, 1 skipped | Full populated-repository offline suite; live OpenAI remains opt-in |

The committed ten-arm M3 run (`20260824T203336Z`) used deterministic token-hash embeddings
in isolated temporary PostgreSQL tables. It made no paid call and did not modify populated
corpus embeddings. The earlier six-arm run that measured zero lexical candidates remains
committed; it is what motivated the M2.4 lexical fix and the M2.9 BM25 arm. See
the [evaluation report](docs/en/eval-report.md) for the complete matrix and the
[failure analysis](docs/en/failure-analysis.md) for the tradeoffs behind it.

## Architecture

The system carries source identity from raw filing bytes to every public evidence card:

`SEC HTML -> sections/tables -> source-stable chunks -> PostgreSQL/pgvector -> hybrid ranks -> guarded workflow -> CLI/API/demo`

See [architecture.md](docs/en/architecture.md) for component boundaries, data flow, trust
decisions, and deliberate omissions.

## Quick start

Prerequisites: Python 3.14 or newer, [uv](https://docs.astral.sh/uv/), and Docker only for
the PostgreSQL-backed path.

Install the locked development environment and optional demo dependency:

```bash
uv sync --locked --extra demo
```

The equivalent Makefile command is:

```bash
make install
```

Launch the offline portfolio demo:

```bash
uv run --extra demo python -m app.demo
```

The equivalent shortcut is `make run`; use `make debug` for the verbose focused demo suite.

Open the local URL printed by Gradio. The current default uses `CannedDemoService`: its Acme
filing, citation, span, and hash are synthetic test fixtures for demonstrating UI behavior.
They are not measurements from the committed SEC corpus. The injectable runtime adapter is
regression-tested against the real M5 `RetrievalResult.hits` return type; the default launch
intentionally remains canned and must be labeled that way.

### Run the deployment-ready canned surface

The release entrypoint adds bounded single-process rate limiting, read-only public policy,
security headers, non-secret release metadata, and container health:

```bash
DOCREVIEW_MODE=canned uv run --extra demo uvicorn app.release.space:app --host 127.0.0.1 --port 7860 --workers 1 --log-level warning
```

From another terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:7860/health
curl --fail --silent --show-error http://127.0.0.1:7860/release
```

The Hugging Face Docker Space metadata is a local template under `deploy/huggingface/`.
No Space, external account resource, image push, or hosted deployment was created.

### Run the real local corpus path

Start PostgreSQL, create the schema, ingest the manifest, and backfill deterministic
embeddings before retrieval:

```bash
docker compose up -d db
uv run python -m app.cli ingest --manifest data/corpus/manifest.json --create-schema
uv run python -m app.cli retrieve --query "NVDA 2024 R&D" --provider deterministic --embed-missing -k 3
```

Run the HTTP surface in a separate terminal:

```bash
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli serve --host 127.0.0.1 --port 8000 --log-level warning
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/openapi.json
```

Retrieval uses deterministic embeddings by default in the runtime adapter. Review remains
fail-closed until an LLM provider and an explicit provider budget are injected together; an
ambient API key is not consent to make a paid request.

## Security boundary

The browser never accepts provider credentials. Public evidence and traces use strict typed
projections; expected database/provider failures become non-leaking resources; persisted
runs omit credential values; and a provider cannot activate from ambient credentials alone.
M7 adds canned-first release composition, bounded rolling limits for one worker, public
ingestion denial, security headers on success and early policy errors, server-only optional
operator secrets, and explicit token/cost caps. It is not distributed abuse protection or
a hosted threat-model proof; replicas require a shared limiter, and no external deployment
was authorized.

## Reproduce the evaluation

The default command is offline-safe but requires local PostgreSQL:

```bash
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

Raw evidence is under `data/eval_runs/`. Golden cases remain agent-curated and pending
author approval; machine validation is not human review.

## Verification

```bash
make docs
make demo-check
uv run pytest -o addopts="" tests/release tests/demo tests/api -q
scripts/verify_clean_checkout.sh
make test
```

The current full-suite result is `833 passed, 1 skipped`; the historical post-M7
checkpoint was `718 passed, 1 skipped`. The one skip is the explicitly opt-in live OpenAI
workflow test; ordinary verification made no paid provider call.

## Portfolio caveats

- Deterministic embeddings prove reproducibility and plumbing, not semantic quality.
- The first recorded experiment measured zero lexical candidates; after the M2.4 fix and
  the M2.9 BM25 arm, lexical retrieval leads and hybrid fusion trails it, because rank-only
  RRF cannot know that the deterministic vector component is weak.
- The 28-case golden suite has 24 positive and 4 absent cases, all pending author approval.
- The default Gradio demo is canned and zero-cost; it must not be presented as a live SEC or
  model-backed result.
- The in-process release limiter is suitable for one worker only; it is not distributed
  protection or authentication.

> **Screenshot placeholder — not measured evidence.** No screenshot is committed. This
> text preserves the honest absence of visual evidence; any future capture must name its
> canned or local-runtime mode and pass the release gate in the M6 tutorial.

## Documentation route

- [Unified documentation hub](docs/00-README.md) — current tutorials, module order,
  historical planning evidence, portfolio closeout, and deployment assets.

## Roadmap

- M2.9 through M2.11 are complete: BM25 and `ts_rank_cd` are selectable lexical rankers,
  local embedding and cross-encoder providers sit behind the existing boundaries, and the
  M3.4 matrix measures every ranker arm.
- M6 is complete: the demo adapter consumes the real M5 retrieval return shape, the local
  Gradio boundary is smoke-tested, and repository verification is recorded.
- M7 is complete locally: release guards, deployment assets, container smoke, and clean-
  archive proof are recorded without external publication.
- M8.1 through M8.4 are complete after parity, structural checks, and documentation gates.
