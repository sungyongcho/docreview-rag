# M3 Overview — Source-grounded retrieval evaluation

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

M3 turns the cited retrieval surface from M2 into a reproducible evaluation system. The milestone moves in one sortable path: **M3.1 golden → M3.2 scoring → M3.3 regression → M3.4 ablation/runner → M3.5 curation**. Each layer is written directly at its canonical path and has a cumulative test gate.

## Milestone contract

`raw-source golden spans -> deterministic metrics -> comparable baselines -> measured experiments`

The committed golden set is agent-curated and pending author approval. Machine validation does not make it human-verified. The committed experiment evidence uses the deterministic embedding provider in isolated temporary PostgreSQL tables; it made no paid API call and did not replace the populated corpus embeddings.

## Six-document reading order

1. [Overview](00-README.md) gives the sortable path and stop gates. 2. [Measured findings](01-findings.md) records only results backed by committed artifacts. 3. [Normative specification](02-spec.md) defines the stable contracts. 4. [Build guide](03-build.md) proceeds from concepts to code and cumulative tests. 5. [Bugs and design traps](04-bugs.md) records symptoms, causes, and regression guards. 6. [Verification](05-verify.md) gives acceptance commands and failure triage.

The portfolio-facing comparison is [the evaluation report](../eval-report.md). Raw evidence is under `data/eval_runs/`.

## Sortable M3 path

### M3.1 — Golden data

- **Prerequisites:** the immutable 20-document corpus and its manifest must be present.
- **Files:** `app/evals/types.py`, `app/evals/loader.py`, `app/evals/__init__.py`, `data/golden/retrieval.json`, and `tests/evals/test_01_contract.py` plus `tests/evals/test_02_loader.py`.
- **Exact command:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
```

- **Expected result:** `29 passed`; 28 cases load as 24 source-bearing positives and four absent cases.
- **Stop condition:** do not advance while any source hash, half-open span, uniqueness, distribution, or review-provenance check fails.

### M3.2 — Deterministic scoring

- **Prerequisites:** M3.1 passes and golden spans remain raw-source coordinates.
- **Files:** `app/evals/scoring.py` and `tests/evals/test_02_scoring.py`.
- **Exact command:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py -q
```

- **Expected result:** `55 passed`; Recall@k, Hit Rate@k, and MRR use deterministic top-k source-span relevance.
- **Stop condition:** do not advance if reordered chunk IDs change a score, repeated hits double-count a gold span, or absent cases enter retrieval-quality metrics.

### M3.3 — Regression baselines

- **Prerequisites:** M3.2 passes and every gated metric has an explicit direction and tolerance.
- **Files:** `app/db/models.py`, `app/evals/regression.py`, and `tests/evals/test_03_regression.py`.
- **Exact command:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py -q
```

- **Expected result:** `74 passed`; configs serialize canonically and only the newest row with the same suite and config is a comparable baseline.
- **Stop condition:** do not advance if latency is implicitly treated as higher-is-better, a tolerance boundary fails, or a different config can become the baseline.

### M3.4 — Ablation and runner

- **Prerequisites:** M3.3 passes, loopback PostgreSQL has pgvector, and the provider choice is explicit. The default command is offline and deterministic.
- **Files:** `app/evals/ablation.py`, `app/evals/retrieval_eval.py`, `app/evals/__main__.py`, and `tests/evals/test_04_ablation.py` through `tests/evals/test_06_postgres.py`.
- **Exact command:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py tests/evals/test_04_ablation.py tests/evals/test_05_runner.py tests/evals/test_06_postgres.py -q
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

- **Expected result:** `100 passed`; the runner writes ten per-arm artifacts plus one budget artifact, labels provider and review provenance, measures both chunking arms, and stays below 300 seconds per indexing arm and 90 seconds for 200 sequential queries.
- **Stop condition:** stop if PostgreSQL is not isolated to temporary experiment tables, provider identity is unknown, the populated embeddings would change, any provenance field is missing, any budget fails, or a metric lacks a raw artifact.

### M3.5 — Golden curation

- **Prerequisites:** M3.4 passes. Curation and the breakdown run offline; only the cumulative command's live test still wants loopback PostgreSQL.
- **Files:** `app/evals/curation.py`, `app/evals/breakdown.py`, `data/golden/candidates/r1.json`, and `tests/evals/test_07_curation.py`.
- **Exact command:**

```bash
uv run pytest -o addopts="" tests/evals -q
```

- **Expected result:** `113 passed`; committed candidates clear every machine gate and stay pending, promotion mints `m3c` ids only from explicit approvals while preserving pending-approval provenance, and taxonomy breakdowns enforce a strict case-to-score bijection.
- **Stop condition:** do not advance while a candidate bypasses a machine gate, an undecided candidate can promote, a promoted case claims verification, or a breakdown accepts partial scoring.

## Offline quick start

```bash
docker compose up -d db
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

The checked-in evidence sets are timestamped `20260812T200916Z` and `20260824T203336Z`, and the evaluation report reads the newer one. Their deterministic vectors are a reproducibility baseline, not a semantic-quality proxy and not evidence that the populated corpus uses the same provider.

## Paid-provider gate

No OpenAI call was made for the committed run. After the author explicitly approves cost, confirms a valid key and model access, and accepts creation of a separate artifact set, the opt-in command is:

```bash
OPENAI_API_KEY="your-key" uv run python -m app.evals --provider openai --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

The command still uses temporary tables and does not overwrite populated embeddings. See [verification](05-verify.md#manual-and-paid-provider-gates) for the current cost estimate and the gates that remain manual.
