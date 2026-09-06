# M3 Verification

Run acceptance in dependency order. Stop at the first failure; later output cannot repair a lower-layer contract.

## 1. Cumulative layer tests

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py -q
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py -q
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py tests/evals/test_04_ablation.py tests/evals/test_05_runner.py tests/evals/test_06_postgres.py -q
uv run pytest -o addopts="" tests/evals -q
```

Expected cumulative results:

| Layer | Expected |
|---|---:|
| M3.1 golden | 29 passed |
| M3.2 scoring | 55 passed |
| M3.3 regression | 74 passed |
| M3.4 ablation/runner | 100 passed |
| M3.5 curation/breakdown | 113 passed |

The live tests require a loopback database. They skip safely when PostgreSQL is unavailable or the configured host is not loopback; a release-quality local acceptance run should have PostgreSQL available and report no skip.

## 2. Canonical incremental gates

Run each canonical layer test while implementation is in progress:

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
uv run pytest -o addopts="" tests/evals/test_02_scoring.py -q
uv run pytest -o addopts="" tests/evals/test_03_regression.py -q
uv run pytest -o addopts="" tests/evals/test_04_ablation.py -q
uv run pytest -o addopts="" tests/evals/test_05_runner.py -q
```

Missing symbols may produce progress skips, not acceptance evidence. Every command above must pass without skips caused by missing implementation.

## 3. Deterministic offline experiment

```bash
docker compose up -d db
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

Expected behavior:

- build and discard two isolated temporary corpora;
- evaluate lexical, vector, and hybrid retrieval for each chunk target;
- record all 28 cases and score only the 24 positive cases;
- write six timestamped raw JSON artifacts and one budget JSON artifact;
- label the embedding provider `deterministic` and paid API calls `false`; and
- leave the populated corpus embeddings unchanged.

The committed corrected set is:

```text
data/eval_runs/20260812T200916Z-structure-500-lexical.json
data/eval_runs/20260812T200916Z-structure-500-vector.json
data/eval_runs/20260812T200916Z-structure-500-hybrid.json
data/eval_runs/20260812T200916Z-structure-1200-lexical.json
data/eval_runs/20260812T200916Z-structure-1200-vector.json
data/eval_runs/20260812T200916Z-structure-1200-hybrid.json
data/eval_runs/20260812T200916Z-budgets.json
```

No superseded partial-timing set may remain because its indexing timer excluded parse/chunk work.

## 4. Raw artifact checks

```bash
test "$(find data/eval_runs -maxdepth 1 -type f -name '20260812T200916Z-*.json' | wc -l)" -eq 7
uv run python - <<'PY'
import json
from pathlib import Path

root = Path("data/eval_runs")
arms = sorted(root.glob("20260812T200916Z-structure-*.json"))
assert len(arms) == 6
for path in arms:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["cases"]) == 28
    assert payload["config"]["embedding"]["provider"] == "deterministic"
    assert payload["config"]["measurement"]["paid_api_calls"] is False
    assert payload["config"]["measurement"]["populated_corpus_embeddings_modified"] is False
    assert payload["golden_provenance"]["human_verified"] is False
    assert payload["golden_provenance"]["approval_status"] == "pending-author-approval"

budget = json.loads((root / "20260812T200916Z-budgets.json").read_text(encoding="utf-8"))
assert all(item["passed"] for item in budget["indexing"])
assert budget["query_budget"]["query_count"] == 200
assert budget["query_budget"]["passed"] is True
print("validated six raw arms and one budget artifact")
PY
```

Measured budget expectations from the committed run:

```text
500 indexing:  75.157933840 s / 300 s, pass
1200 indexing: 63.880582629 s / 300 s, pass
200 queries:   12.993961915 s / 90 s, pass
query P95:     71.480470 ms
```

## 5. Quality, style, and documentation

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_doc_code.py
git diff --check
```

The documentation checker validates source-anchored blocks, prose constants, and relative links. A missing raw artifact link is a documentation failure even when unit tests pass.

## Manual and paid-provider gates

No paid OpenAI call was made. The OpenAI path remains opt-in:

```bash
OPENAI_API_KEY="your-key" uv run python -m app.evals --provider openai --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

Before running it, the author must:

1. approve paid use and a separate OpenAI artifact set; 2. provide a valid project credential with billing and `text-embedding-3-small` access; 3. confirm current pricing and sufficient rate limits; and 4. keep the temporary-table isolation and verify populated counts afterward.

The two chunking arms contain 15,392,912 indexed characters, and the vector/hybrid query passes add 28,533 question characters. Using the planning approximation of four characters per token gives about 3.855 million input tokens. At the current official [`text-embedding-3-small` price of $0.02 per million tokens](https://developers.openai.com/api/docs/models/text-embedding-3-small), the expected embedding charge is approximately **$0.08** and should be budgeted below **$0.10**. This is an estimate, not a measured bill; actual tokenization, retries, and pricing at execution time control the final amount.

Golden review is a separate manual gate. The author must inspect every cited span and every absent claim before changing `approval_status` or `human_verified`.

## Failure triage

| Symptom | Likely boundary | First action |
|---|---|---|
| Hash or bounds error | M3.1 golden/source snapshot | restore the exact corpus snapshot; never shift spans to fit chunks |
| Different score after reordering | M3.2 scoring | inspect source identity, unique-span matching, and stable case sorting |
| Missing or wrong baseline | M3.3 regression | compare suite plus canonical full config and timestamp/ID order |
| Empty lexical candidates | M3.4 retrieval | inspect the relaxed `to_tsquery` rewrite of `websearch_to_tsquery`; do not alter scoring |
| Provider mismatch | M3.4 provenance | stop, create a fresh isolated corpus, and declare one provider explicitly |
| Index budget unexpectedly low | M3.4 timing | verify the timer starts before manifest loading, parsing, and chunking |
| Public embedding count changed | isolation breach | stop; do not publish the run until the mutation is explained and repaired |
| Artifact/doc mismatch | evidence synchronization | validate the corrected timestamped JSON and rerun the doc checker |
