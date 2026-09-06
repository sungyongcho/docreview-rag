# M3 Spec

## 1. Scope

This specification defines the complete M3 path: strict golden data, deterministic scoring, typed regression comparison, evaluation-result persistence, configurable retrieval ablations, raw per-case artifacts, and measured latency budgets. The layers must be built in order: M3.1 golden, M3.2 scoring, M3.3 regression, then M3.4 ablation and runner.

The canonical dataset is `data/golden/retrieval.json`. It contains 28 agent-curated candidates pending author approval. No committed case is human-verified.

## 2. Stable source contract

A positive answer is a half-open raw-source interval `[start_char, end_char)` in the exact UTF-8 filing identified by `doc_id` and `source_sha256`. The offsets address decoded Unicode characters, not bytes, rendered text, parser blocks, chunk bodies, or database chunk IDs.

Golden answers must remain independent of a particular chunking configuration. The current dataset therefore cites only answer-bearing source sentences, fragments, or table rows. A retrieved chunk may change under ablation while the raw answer interval remains stable.

Every positive span must satisfy all of the following:

1. its document exists in `data/corpus/manifest.json`; 2. its SHA-256 equals the exact source-file byte hash; 3. `0 <= start_char < end_char <= len(decoded_source)`; 4. the cited interval contains visible source evidence; and 5. its identity is not duplicated within the case or committed suite.

## 3. JSON schema

The file root is a JSON array. Unknown fields, duplicate JSON object keys, duplicate case IDs, normalized duplicate questions, invalid enums, scalar coercion, empty text fields, duplicate tags, malformed hashes, and invalid spans are errors.

Each case has this shape:

```json
{
  "id": "m3c-07",
  "question": "What was AMD's research and development expense in fiscal 2023?",
  "category": "exact_number",
  "facet": "numeric",
  "tags": ["demo-hero"],
  "answers": [
    {
      "doc_id": "AMD-FY2023",
      "source_sha256": "0e9d83bd98b81b70050a88635171e721488f783eada9686fe21d6919ee1b668e",
      "start_char": 756006,
      "end_char": 756419
    }
  ],
  "expected_label": "SUPPORTED",
  "reference_answer": "$5.872 billion.",
  "note": "Exact-number retrieval from a multi-year financial statement table.",
  "curation_status": "agent-curated",
  "approval_status": "pending-author-approval",
  "human_verified": false
}
```

### Categories and facets

`category` is the normative M3 evaluation category:

- `simple_lookup`
- `exact_number`
- `multi_hop`
- `absent`

`facet` is a separate required semantic-review dimension:

- `factual`
- `comparison`
- `risk`
- `policy`
- `numeric`

The two dimensions must not be collapsed. The current set deliberately records exact distributions instead of claiming artificial equality: categories are 13 simple lookups, five exact-number cases, six multi-hop cases, and four absent cases; facets are six factual, six comparison, six risk, five policy, and five numeric cases.

### Positive and absent invariants

A non-absent case must contain at least one validated answer span, expect `SUPPORTED`, and provide a supported reference answer. An absent case must contain zero spans, expect `NOT_IN_DOCS`, and use `NOT_IN_DOCS` as its reference answer.

All cases must use `curation_status="agent-curated"`, `approval_status="pending-author-approval"`, and the literal JSON boolean `human_verified=false` until an author performs and records a separate review. Machine validation must never be represented as human verification.

## 4. Dataset composition

The committed set contains 24 positives and four absent cases. The positives cite all 20 filings and are balanced at six cases per ticker. Eight positive `demo-hero` cases are balanced at two per ticker.

Four redundant non-hero positive candidates were replaced with negative guardrail cases so the normative category dimension includes honest absence behavior. Negative cases are claims about the complete immutable corpus, not citations to a source span, and remain pending author confirmation.

## 5. Loader behavior

`load_golden_cases()` accepts one JSON file or a directory whose `*.json` files are merged in filename order. It returns `list[GoldenCase]` only after schema, cross-case uniqueness, corpus manifest, source hash, bounds, and visible-evidence validation succeeds. Any violation raises `GoldenDataError`; the loader does not skip, repair, normalize, or silently discard invalid cases.

`validate_golden_sources()` exposes the corpus-binding check independently for callers that already hold typed cases. Source files are read as bytes, decoded as UTF-8 without universal newline translation, hashed from the original bytes, and indexed by decoded character offset.

## 6. Direct implementation path

`tests/evals` loads the canonical `app.evals` package. Missing symbols skip dependent tests so the suite acts as a progress board, while implemented symbols remain subject to the same strict tests.

```bash
uv run pytest tests/evals
uv run pytest tests/evals -v
```

## 7. Review and completion gate

The machine gate requires the focused tests, Ruff, and documentation synchronization to pass. Human approval is a separate gate described in `data/golden/REVIEW.md`; passing tests does not satisfy it. Until the author completes that review, every case remains an agent-curated candidate and no human-verification claim is permitted.

## 8. Deterministic retrieval scoring

`app.evals.scoring` evaluates positive golden cases only. Absent cases have no retrieval span and are reserved for later label-accuracy scoring; passing an empty gold-span list to `score_case()` is an error.

### Half-open span relevance

The single relevance threshold is `IOU_THRESHOLD=0.05`. A golden span `a` and retrieved chunk `b` are comparable only when both `doc_id` and `source_sha256` match. For comparable spans:

```text
overlap = max(0, min(a.end_char, b.end_char) - max(a.start_char, b.start_char))
union = (a.end_char - a.start_char) + (b.end_char - b.start_char) - overlap
IoU = overlap / union
relevant = IoU >= IOU_THRESHOLD
```

Half-open intervals that only touch have zero overlap. The deliberately low threshold lets different chunking configurations cover the same narrow raw answer without requiring equal chunk boundaries. Snapshot-hash matching prevents stale offsets from receiving credit.

### Per-case matching

Only the first `k` hits are considered, and `k` must be a positive integer. Recall counts unique gold spans covered by at least one relevant hit. Repeated hits covering the same gold span never increase recall; one broad hit may cover multiple distinct gold spans when its IoU independently reaches the threshold for each.

`CaseScore` records the gold and matched counts, `recall_at_k`, binary `hit_at_k`, the first relevant one-based rank, and its reciprocal. A case with no relevant top-k hit receives zero for all three metric values and has no first relevant rank.

### Suite metrics

`recall_at_k()` is macro recall: the arithmetic mean of per-case recall, so each question has equal weight even when cases contain different numbers of gold spans. `hit_rate_at_k()` is the fraction of cases with any relevant top-k hit. MRR is the arithmetic mean of each case's first relevant reciprocal rank and is exposed as both `mrr()` and `mean_reciprocal_rank()`. A suite must be nonempty, use unique case IDs, and use one common `k`.

`score_suite()` returns those three metrics with per-case results sorted by case ID. Matching depends only on immutable source identity and half-open coordinates, never on database chunk IDs or parser ordinals, so re-chunking and reordered chunk identities cannot alter a result when the ranked source coverage is equivalent.

Run the canonical scoring test directly:

```bash
uv run pytest tests/evals/test_02_scoring.py -v
```

## 9. Regression comparison and persistence

Regression gates apply only to the explicit higher-is-better metrics `recall_at_k`, `hit_rate_at_k`, and `mrr`, in that stable order. Each metric has a configurable maximum absolute drop. A drop equal to the tolerance passes; a larger drop fails. Extra values such as latency are stored but never receive an implicit direction.

Experiment configs must be finite JSON objects with string keys. Canonical serialization uses sorted keys, compact separators, UTF-8 characters, and no NaN or infinity. Two configs are comparable only when their canonical JSON values and suite names match.

`EvalResult` persists one suite, canonical config, metrics object, raw artifact path, and timezone-aware timestamp. `latest_comparable_baseline()` orders matching rows by timestamp and then ID, newest first. Persistence flushes without committing; transaction ownership belongs to the caller.

Run the canonical regression test directly:

```bash
uv run pytest tests/evals/test_03_regression.py -v
```

## 10. Ablation matrix

An `ExperimentConfig` must name every variable that affects comparability:

- structure-aware chunking target and the raw-span golden identity;
- lexical, vector, or hybrid retrieval strategy;
- the lexical ranking function, which is `ts_rank_cd` or hand-written BM25 with explicit `k1`, `b`, and IDF variant;
- `k`, component candidate depth, and RRF constant;
- embedding provider and dimensions, including whether it is hosted or local;
- no reranker in this deterministic M3 baseline; a cross-encoder belongs to a separately approved follow-up experiment that records its candidate depth; and
- isolated environment, paid-call flag, and populated-embedding mutation flag.

The default matrix crosses chunk targets 500 and 1200 with lexical, vector, and hybrid retrieval, and expands every strategy that issues a lexical query over both lexical ranking functions. Vector retrieval issues none, so it contributes one arm per chunk target rather than one per ranking function, and the default matrix is ten arms rather than twelve. Every arm shall record its ranking function in its config name, its artifact filename, and its config provenance, so that two runs differing only in ranking function can neither overwrite each other nor be confused afterwards. BM25 statistics are properties of one particular chunking, so each temporary corpus arm shall rebuild them exactly once, during indexing and before any experiment runs; a rebuild shared across chunk targets would describe neither. The query budget shall name the ranking function it measured. The M2.11 cross-encoder is not added automatically to the current ten-arm baseline; its quality, latency, and candidate depth belong to a separately approved follow-up experiment. Config names are unique lowercase kebab-case and outcomes are sorted by chunk target, strategy order, lexical ranking function, and name. Re-chunking must never edit golden spans.

Run the canonical ablation test directly:

```bash
uv run pytest tests/evals/test_04_ablation.py -v
```

## 11. Runner and raw artifacts

The runner evaluates all 28 cases in case-ID order. It records raw hits and latency for every case but computes retrieval-quality metrics only for the 24 cases that contain source spans. The four absent cases require a future label-accuracy contract and must have `score=null` in M3 raw artifacts.

Every experiment artifact contains:

- schema version, suite, UTC timestamp, and complete experiment config;
- total, scored-positive, and unscored-absent counts;
- the literal golden review provenance;
- Recall@k, Hit Rate@k, MRR, and latency summary; and
- each complete golden case, raw ranked hit list, latency, and optional positive-case score.

Artifact JSON must be stable, UTF-8, sorted-key, finite JSON. The filename is the UTC run timestamp followed by the unique config name. Metrics without their raw artifact are not acceptable evidence.

Run the canonical runner test directly:

```bash
uv run pytest tests/evals/test_05_runner.py -v
```

## 12. Isolation and budgets

Each chunking arm is built in temporary PostgreSQL tables on a dedicated connection. The timer begins before manifest loading, parsing, and chunk construction and ends after temporary persistence, GIN construction, and embedding backfill. Closing the connection discards the experiment corpus. The runner must not read provider identity from existing vectors, overwrite populated embeddings, or mix provider spaces.

The acceptance budgets are:

- at most 300 wall-clock seconds for each complete 20-document indexing arm; and
- at most 90 wall-clock seconds for 200 sequential retrieval queries.

The budget artifact must store counts, provider identity, observed durations, thresholds, pass states, environment identity, paid-call state, and populated-corpus mutation state. These are measured results; fallback or fabricated values are prohibited.

## 13. Provider and review provenance

The default acceptance path uses `provider=deterministic`. Its token-hash vectors provide a stable offline baseline but are not a semantic-quality substitute. An OpenAI run is an explicit opt-in requiring author cost approval, a valid credential, and model access. It must write a separate artifact set and must still use temporary corpus tables.

Golden review and embedding-provider provenance are independent. A deterministic run does not establish which provider produced existing vectors, and machine-tested golden data remains agent-curated and pending author approval.

## 14. Complete acceptance gate

M3 is machine-complete when all 113 eval tests, Ruff, formatting, documentation sync, and raw-artifact validation pass. The safe live PostgreSQL test may skip only when the configured database is non-loopback or unavailable. Author approval of golden cases and any paid provider run remain separate manual gates.

```bash
uv run pytest -o addopts="" tests/evals -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_doc_code.py
```
