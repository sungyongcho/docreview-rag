# M3.4 Tutorial 7 — Running the evaluation and measuring the budget

Tutorial 5 defined the experiment arms and tutorial 6 defined the records one run leaves behind. What neither did is execute anything: not one query has been retrieved, not one clock has been read. The six functions in this document close that gap — they run retrieval, measure the time it takes, and store the result.

The failure this layer guards against is silent misattribution. An evaluator wired slightly wrong — a result stored under a configuration it did not actually run, an arm labelled with a ranker it never used — produces an artifact that looks exactly like a healthy one: every field filled, every number plausible, no error anywhere. Weeks later that artifact steers a chunking or ranker decision in the wrong direction, and nothing in the file can reveal the swap.

So the invariant of this document: **one run's artifact contains everything needed to re-derive its own aggregates and to attribute them to exactly one configuration.** Every function below either feeds that artifact or defends that attribution.

**Prerequisite:** The record layer of `retrieval_eval.py` from tutorial 6 is written. Its tests run together in tutorial 8.

### The budget is measured too

Measuring quality alone is half the job. Two performance gates exist.

- 300 seconds to **index one complete arm**
- **200** sequential retrieval queries in 90 seconds

Those gates are what make a trade like "recall rose 0.03 and indexing got 3× slower" visible. Tune on quality metrics alone and at some point you have an unusably slow system.

The thresholds are not hypothetical — the committed run behind this module measured both gates. On the author's machine, indexing the 500-char arm (20 documents, 12,984 chunks) used 38.5 of the allowed 300 seconds, the 1200-char arm (9,172 chunks) used 33.9, and 200 sequential hybrid queries against the 1200-char corpus used 29.79 of the allowed 90 seconds — mean 148.9 ms per query, p95 213.6 ms, worst 283.4 ms. Read the evidence directly:

```bash
python3 -c "import json; d = json.load(open('data/eval_runs/20260824T203336Z-budgets.json')); print(json.dumps({'indexing': d['indexing'], 'query_budget': d['query_budget']}, indent=2))"
```

Where that file comes from: it is written by the CLI that tutorial 8 assembles. At the end of a run, `_run_cli` serializes the two indexing measurements and the query-budget measurement into one `{timestamp}-budgets.json` beside the ten per-arm artifacts of the same run. The committed copy under `data/eval_runs` came from the default deterministic command on 2026-08-24; its `measurement_provenance` block records which embedding provider ran, which lexical ranker served the budget queries, that the corpus was an isolated temporary one, and that no paid API was called. Nothing ever updates this file — the next run writes a new timestamped file next to it, and the old one stays as history.

The budget JSON records **actual observations.** Tests never fill it with fakes. If the measuring instrument lies, every decision above it collapses.

One honest limit: `passed` is wall-clock truth about one machine, one provider, one isolated corpus. It proves the algorithmic cost fits the budget locally; it does not promise a hosted deployment's latency, and swapping the deterministic provider for a real embedding API would add a network round trip to every vector and hybrid query.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `evaluate_retriever` | **Implement** the run loop yourself | Where 28 run and 24 are scored |
| `write_evaluation_artifact` | **Define the structure, then inspect serialization** | Why an artifact must be stable |
| The two budget functions | **Implement** the measurement rules yourself | Where the clock gets read |
| `make_retriever` | **Implement** the strategy binding yourself | How three strategies share one interface |
| `persist_evaluation` | **Inspect call order** | Why the baseline is read before storing |

### 1. 28 run, 24 scored

#### Extend `app/evals/retrieval_eval.py` — running the evaluation

**Learning action — implement the run loop:** write the loop yourself. Trace what happens when `case.answers` is empty.

One recap before the code: the `retriever` argument is nothing more than an async callable of shape (question, k) → hits — the closure that `make_retriever` builds in section 4 around the M2 search functions. `evaluate_retriever` deliberately knows nothing else about it.

<!-- src: app/evals/retrieval_eval.py::evaluate_retriever -->
```python
async def evaluate_retriever(
    cases: Sequence[GoldenCase],
    retriever: Retriever,
    *,
    suite: str,
    config: Mapping[str, Any],
    k: int = 5,
    clock: Clock = time.perf_counter_ns,
    recorded_at: datetime | None = None,
) -> RetrievalEvaluation:
    """Evaluate every case once while scoring only source-bearing positives."""
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be nonblank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    ordered = tuple(sorted(cases, key=lambda case: case.id))
    if not ordered:
        raise ValueError("golden cases must not be empty")
    if len({case.id for case in ordered}) != len(ordered):
        raise ValueError("golden case ids must be unique")
    provenance = _golden_provenance(ordered)

    results: list[CaseEvaluation] = []
    scores: list[CaseScore] = []
    latencies: list[float] = []
    for case in ordered:
        started = clock()
        hits = tuple(await retriever(case.question, k))
        elapsed_ms = (clock() - started) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        case_score = score_case(case.id, case.answers, hits, k) if case.answers else None
        if case_score is not None:
            scores.append(case_score)
        results.append(
            CaseEvaluation(
                golden=case,
                latency_ms=elapsed_ms,
                hits=hits,
                score=case_score,
            )
        )

    return RetrievalEvaluation(
        suite=suite,
        recorded_at=recorded_at or datetime.now(UTC),
        config=_canonical_config(config),
        provenance=provenance,
        score=score_suite(scores),
        latency=_latency_summary(latencies),
        cases=tuple(results),
    )
```

**What to look for in the code**

- The single line `score_case(...) if case.answers else None` is the whole 28/24 distinction. An absent case **still runs retrieval and still records hits**, it just never enters the `scores` list.
- `clock` is injectable and defaults to `time.perf_counter_ns`. A monotonic counter rather than a wall clock means an NTP correction cannot make a latency negative.
- It still checks `elapsed_ms < 0`. An injected clock may not be monotonic, and a negative latency would make `_latency_summary` quietly report a nonsense percentile.
- `sorted(cases, key=...)` fixes case order. If the latency list ordering changed per run, p95 would move.
- `recorded_at or datetime.now(UTC)` allows injection so tests can pin time.

> **Concept — Why absent cases run but are never scored**
>
> Four of the 28 golden cases are absent cases: the correct answer is that the corpus contains nothing, so there is no gold span to compare hits against. Recall is undefined there — count an absent case as 0 and every retriever is punished for correct behavior; count it as 1 and the average inflates on no evidence. Excluding them from the score is the only honest arithmetic.
>
> The obvious simplification — skip them entirely — would quietly destroy two kinds of evidence. Their latency belongs in the budget picture, because absent questions are part of the real workload the gates claim to describe. And their recorded hits are exactly what the M4 absence-judgment layer will need: to decide how a system should say "not in the documents", one must first see what retrieval returns when the right answer is nothing.
>
> So the loop runs all 28, records hits and latency for all 28, and lets only the 24 source-bearing positives into the score list. The artifact keeps the split visible as provenance: 28 total, 24 scored, 4 unscored.

### 2. An artifact has to be stable

#### Extend `app/evals/retrieval_eval.py` — writing the artifact

**Learning action — define the structure, then inspect serialization:** note what each of the four `json.dumps` arguments guarantees.

<!-- src: app/evals/retrieval_eval.py::write_evaluation_artifact -->
```python
def write_evaluation_artifact(path: str | Path, evaluation: RetrievalEvaluation) -> Path:
    """Write one stable UTF-8 raw artifact and return its path."""
    artifact_path = Path(path)
    if artifact_path.suffix != ".json":
        raise ValueError("evaluation artifact path must end in .json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        evaluation.artifact_payload(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    artifact_path.write_text(payload + "\n", encoding="utf-8")
    return artifact_path
```

**What to look for in the code**

- `sort_keys=True` and `indent=2` make the same run produce the same bytes. Two artifacts can be compared with `diff` — without it, a differing dictionary order makes everything look changed.
- `allow_nan=False` keeps a `NaN` latency out of the file. It is outside the JSON standard, so other tools cannot read it.
- The `.json` suffix is enforced. Passing a directory or an extensionless path by mistake would quietly create something strange.
- `mkdir(parents=True, exist_ok=True)` creates the artifact directory. Finishing all the measurement and then failing at the write step because a directory is missing throws the whole run away.

Why keep a file at all when section 5 also stores the run in the database? Because the two records answer different questions. The database row keeps seven aggregate metric values and a `raw_artifact_path` pointer — enough to compare runs, useless for asking which case failed and what came back instead. The raw artifact keeps every case's hits and spans, so the aggregates can be re-derived from it at any time: the row cannot reconstruct the artifact, but the artifact can reconstruct the row. Losing the file loses the evidence, which is why it is written before persistence is even considered.

### 3. Where the clock gets read

#### Extend `app/evals/retrieval_eval.py` — budget measurement

**Learning action — implement the measurement rules:** follow how `previous` is updated in the `measure_query_budget` loop.

<!-- src: app/evals/retrieval_eval.py::measure_query_budget,assess_indexing_budget -->
```python
async def measure_query_budget(
    queries: Sequence[str],
    retriever: Retriever,
    *,
    k: int = 5,
    query_count: int = QUERY_BUDGET_COUNT,
    budget_seconds: float = QUERY_BUDGET_SECONDS,
    clock: Clock = time.perf_counter_ns,
) -> QueryBudgetMeasurement:
    """Repeat nonempty queries sequentially and assess the wall-clock budget."""
    if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("queries must contain nonblank strings")
    if isinstance(query_count, bool) or not isinstance(query_count, int) or query_count <= 0:
        raise ValueError("query_count must be a positive integer")
    if k <= 0:
        raise ValueError("k must be positive")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")

    previous = clock()
    latencies: list[float] = []
    for index in range(query_count):
        await retriever(queries[index % len(queries)], k)
        current = clock()
        elapsed_ms = (current - previous) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        previous = current

    summary = _latency_summary(latencies)
    total_seconds = summary.total_ms / 1_000
    return QueryBudgetMeasurement(
        query_count=query_count,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
        mean_ms=summary.mean_ms,
        p50_ms=summary.p50_ms,
        p95_ms=summary.p95_ms,
        max_ms=summary.max_ms,
    )


def assess_indexing_budget(
    *,
    target_text_chars: int,
    document_count: int,
    chunk_count: int,
    embedding_provider: str,
    total_seconds: float,
    budget_seconds: float = INDEXING_BUDGET_SECONDS,
) -> IndexingBudgetMeasurement:
    """Validate and assess one measured indexing duration."""
    if target_text_chars <= 0 or document_count <= 0 or chunk_count <= 0:
        raise ValueError("indexing counts and target_text_chars must be positive")
    if not embedding_provider.strip():
        raise ValueError("embedding_provider must be nonblank")
    if not math.isfinite(total_seconds) or total_seconds < 0:
        raise ValueError("total_seconds must be finite and nonnegative")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")
    return IndexingBudgetMeasurement(
        target_text_chars=target_text_chars,
        document_count=document_count,
        chunk_count=chunk_count,
        embedding_provider=embedding_provider,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
    )
```

**What to look for in the code**

- `previous = clock()` runs once **outside** the loop, then continues as `previous = current` inside. It measures **contiguous intervals** rather than gaps between queries, so the total equals real elapsed time.
- `queries[index % len(queries)]` cycles the queries. Repeating one query 200 times would let cache effects distort the measurement.
- `assess_indexing_budget` never reads a clock. It takes **already measured** seconds and only judges. Separating measurement from judgment lets tests verify the judging logic with fabricated times.
- Both functions compute `passed` into the record. Change the threshold later and the file still holds the verdict made at the time.

> **Concept — Why 200 queries when the suite has 28**
>
> A latency gate is a claim about a distribution, and the tail of a distribution is the last thing to stabilize. With only 28 samples, the p95 under this file's percentile rule is simply the second-slowest measurement — one garbage-collection pause or one cold cache decides the number. With 200 samples the p95 is the eleventh-slowest, so ten worse measurements sit above it and no single accident owns it.
>
> That is why the budget cycles the 28 golden questions roughly seven times instead of inventing new ones: the goal is a stable estimate over a realistic query mix, not more coverage. And the queries run sequentially on purpose — the gate is defined as sequential wall-clock so two runs stay comparable, while a concurrent run would measure the connection pool as much as the retrieval path.

### 4. Three strategies, one interface

#### Extend `app/evals/retrieval_eval.py` — binding a retriever

**Learning action — implement the strategy binding:** note what the closure captures and why a function is returned.

<!-- src: app/evals/retrieval_eval.py::make_retriever -->
```python
def make_retriever(
    session: AsyncSession,
    *,
    strategy: RetrievalStrategy,
    provider: EmbeddingProvider | None,
    lexical_ranker: LexicalRanker | None = None,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one explicit retrieval strategy and lexical ranker to a session.

    The ranker is required exactly when the strategy runs a lexical query, so an
    arm can never be measured under a ranker it did not use, and a vector arm can
    never be labelled with one it never touched.
    """
    if strategy not in {"lexical", "vector", "hybrid"}:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    if strategy == "vector":
        if lexical_ranker is not None:
            raise ValueError("vector retrieval must not name a lexical ranker")
    elif lexical_ranker not in {"ts_rank_cd", "bm25"}:
        raise ValueError(f"{strategy} retrieval requires an explicit lexical ranker")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if strategy in {"vector", "hybrid"} and provider is None:
        raise ValueError(f"{strategy} retrieval requires an embedding provider")

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        if candidate_k < k:
            raise ValueError("candidate_k must be at least k")
        if strategy == "lexical":
            if lexical_ranker == "bm25":
                return await bm25_search(session, query, k, filters)
            return await lexical_search(session, query, k, filters)
        assert provider is not None
        if strategy == "vector":
            query_vector = await provider.embed_query(query)
            return await vector_search(session, query_vector, k=k, filters=filters)
        result = await retrieve(
            session,
            query,
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
            lexical_ranker=lexical_ranker,
        )
        return result.hits

    return run
```

**What to look for in the code**

- The return type is `Retriever` — an interface of exactly `(query, k) -> hits`. `evaluate_retriever` never learns which strategy it is running.
- The strategy and provider checks run **before the closure is built**. Failing on query 100 of 200 with "vector retrieval requires an embedding provider" is unacceptable.
- `strategy in {"vector", "hybrid"} and provider is None` is rejected up front. Lexical needs no provider, so its absence is fine there.
- The `candidate_k < k` check lives **inside** the closure, because `k` arrives at call time.

The obvious alternative is no closure at all: pass a strategy string into `evaluate_retriever` and branch inside the loop. That would weld the measurement loop to every retrieval path — each new arm would edit the measured code itself, and the loop would grow provider and ranker parameters it mostly ignores. Worse, it would blur attribution: the docstring's promise that an arm can never be measured under a ranker it did not use is enforceable precisely because binding and validation happen here, once, before any measurement starts. With the closure, every arm runs through a byte-identical loop, so a latency difference between two arms can only come from the retrieval path itself.

### 5. The baseline is read before storing

#### Extend `app/evals/retrieval_eval.py` — persistence and comparison

**Learning action — inspect call order:** work out what breaks if the three calls are reordered.

<!-- src: app/evals/retrieval_eval.py::persist_evaluation -->
```python
async def persist_evaluation(
    session: AsyncSession,
    evaluation: RetrievalEvaluation,
    *,
    raw_artifact_path: str | Path,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> PersistedEvaluation:
    """Persist one run and compare it with the latest suite/config baseline."""
    baseline = await latest_comparable_baseline(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
    )
    comparison = (
        compare_against_baseline(
            baseline.metrics,
            evaluation.metric_values(),
            tolerances=tolerances,
        )
        if baseline is not None
        else None
    )
    result = await persist_eval_result(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
        metrics=evaluation.metric_values(),
        raw_artifact_path=raw_artifact_path,
        created_at=evaluation.recorded_at,
    )
    if result.id is None:
        raise RuntimeError("persisted evaluation did not receive an id")
    return PersistedEvaluation(
        result_id=result.id,
        baseline_id=baseline.id if baseline is not None else None,
        comparison=comparison,
    )
```

**What to look for in the code**

- `latest_comparable_baseline` comes **before** `persist_eval_result`. Reverse them and the run just stored becomes its own baseline, so regression reads zero forever.
- When `baseline is None`, `comparison` is `None` too. A first run never looks like it passed a "no regression" check.
- `created_at=evaluation.recorded_at` is passed through. The **measurement** time is recorded rather than the storage time, so baseline ordering follows real experiment order.
- `result.id is None` is checked. `persist_eval_result` flushes, so an id must exist; if it does not, this fails loudly rather than continuing.

> **Concept — Why storing results is opt-in**
>
> The CLI in tutorial 8 always writes the raw artifacts, but it writes database rows only when a flag asks for it. That asymmetry is deliberate. Tutorial 4's comparison rule picks, as baseline, the newest stored row with the same suite and a byte-identical configuration — which means every stored row becomes the yardstick for the next stored run of that configuration.
>
> If every exploratory execution stored itself, a debugging run against a half-broken corpus would silently become the baseline the next serious run is judged against, and "no regression" would come to mean "no worse than my broken experiment". Keeping persistence opt-in keeps the baseline table a set of deliberate nominations rather than a log of everything that ever executed. Measurement is free; becoming the yardstick requires an explicit decision.

In the tutorial-8 CLI that decision is the `--persist-results` flag, and its default is off.

### Run the focused test deferred from tutorial 5

`RetrievalEvaluation`, `evaluate_retriever`, and `write_evaluation_artifact` now all exist, so run the ablation-focused test from tutorial 5.

Why it had to wait until now: this test file is one place the skip machinery cannot protect. Its import block pulls `evaluate_retriever` straight from `retrieval_eval.py` with no `need()` guard, and `ablation.py` itself imports `RetrievalEvaluation` and `write_evaluation_artifact` at its own top. Before tutorial 6 and this document those names did not exist, so the file failed at collection with an ImportError instead of skipping — a red that means "not written yet", not "written wrong".

```bash
uv run pytest tests/evals/test_04_ablation.py -q
```

The complete `retrieval_eval.py` runner and budget tests run together in tutorial 8.

### What you should be able to explain now

- **Which single line makes 28 run while only 24 are scored?**
  - **Answer:** `case_score = score_case(...) if case.answers else None` records every retrieval but adds a score only for cases that have gold spans.
- **Why a monotonic counter rather than a wall clock?**
  - **Answer:** A monotonic counter cannot jump because of an NTP or system-clock correction, so elapsed latency cannot become negative.
- **What does `sort_keys=True` make possible for an artifact?**
  - **Answer:** It makes serialization byte-stable, so artifacts from two runs can be diffed and compared directly.
- **What gets distorted if one query is repeated for all 200 measurements?**
  - **Answer:** Cache effects make the query-budget latency unrepresentative, usually making repeated retrieval look faster than a varied workload.
- **What happens to regression if the baseline lookup moves after storing?**
  - **Answer:** The new run finds itself as the latest baseline, so every delta is zero and real regressions disappear.
- **Why do the four absent cases run at all if they are never scored?**
  - **Answer:** Their latency is part of the workload the budget describes, and their recorded hits are the evidence M4's absence judgment will be built on; only the score excludes them.
- **What would go wrong if every run persisted itself by default?**
  - **Answer:** Under the newest-comparable rule every stored row becomes the next run's baseline, so throwaway experiments would become yardsticks; `--persist-results` keeps that a deliberate decision.

---

[← Previous: Evaluation records](06-evaluation-records.md) · [Module overview](../03-build.md) · [Next: Isolated run and CLI →](08-evaluation-cli.md)
