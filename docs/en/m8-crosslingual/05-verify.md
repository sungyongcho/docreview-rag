# M8 Verification

Run acceptance in dependency order. Stop at the first failure; a later table cannot repair a lower-layer contract.

## 1. Offline gates

```bash
uv run pytest tests/crosslingual/test_01_bilingual.py -q
uv run pytest tests/crosslingual/test_02_crosslingual.py -q
uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q
uv run pytest tests/crosslingual/test_05_parity.py -q
uv run pytest tests/crosslingual -q
```

| Test file | Checkpoint | Expected |
|---|---|---:|
| `tests/crosslingual/test_01_bilingual.py` | M8.1 | 13 passed |
| `tests/crosslingual/test_02_crosslingual.py` | M8.2 | 23 passed |
| `tests/crosslingual/test_03_language.py` | M8.3 | 15 passed |
| `tests/crosslingual/test_04_translate.py` | M8.3 | 7 passed |
| `tests/crosslingual/test_05_parity.py` | M8.4 | 11 passed |
| **`tests/crosslingual`** | M8.1–M8.4 | **69 passed** |

The whole directory is offline and deterministic: no PostgreSQL, no network, no API key. A skip in this suite means a canonical symbol is missing, not that an external service was unavailable.

The complete repository suite after M8 lands:

```bash
uv run pytest -q
```

Expected: `959 passed, 1 skipped`. The single skip is the live PostgreSQL test, which skips safely when the configured database is unavailable or non-loopback.

## 2. What the suite pins

- Twin identity: the two suites cover the same case ids and agree on category, facet, tags, answers, expected label, and reference answer; an untranslated copy is rejected before the Hangul rules run (`test_01`).
- Arm provenance: the arm name encodes provider, strategy, ranker, handling, and language, and the config dict carries everything `latest_comparable_baseline` must separate on (`test_02`).
- Diagnostics that measure rather than assume: twin alignment runs with no corpus and asserts near-zero rather than zero; lexical coverage counts empty results instead of asserting a rate (`test_02`).
- Detection and routing: three Unicode ranges, mixed-script questions classified as Korean, blank input rejected, and the lexical component skipped only for Korean and only when routing is on (`test_03`).
- Translation discipline: validated output, fail-closed on refusal, schema violation, or a still-Korean result, and no path to a network provider (`test_04`).
- Parity arithmetic: delta and ratio per gated metric, an inclusive floor, fail-closed at a zero English slice, rejection of non-comparable pairs, and a regression tolerance above single-case granularity (`test_05`).

## 3. The measured run

Measurement is a command-line run, never a test. It requires the seeded local PostgreSQL from M2 and builds its own corpus in temporary tables. One invocation embeds the corpus once and shares it across every arm inside that invocation, so the matrix is cheapest when each provider is asked for all of its arms at once.

```bash
docker compose up -d db
uv run python -m app.evals.crosslingual --provider deterministic --languages en ko --strategies lexical vector hybrid --handling direct --artifact-dir data/eval_runs
uv run python -m app.evals.crosslingual --provider sbert --languages en ko --strategies vector --handling direct --artifact-dir data/eval_runs --persist-results
uv run python -m app.evals.crosslingual --provider sbert-multi --languages en ko --strategies vector hybrid --handling direct routed --artifact-dir data/eval_runs --persist-results --gate
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies vector hybrid --handling direct routed translated --translator-model gpt-4.1-mini --artifact-dir data/eval_runs --persist-results --gate
```

Expected behaviour:

- build and discard one isolated temporary corpus per invocation;
- evaluate every requested arm on its own language slice through the unmodified M3 harness;
- record all 28 cases per run and score only the 24 positive cases;
- write one timestamped raw JSON artifact per arm;
- record the embedding provider and `paid_api_calls` honestly in every config; and
- leave the populated corpus embeddings unchanged.

The recorded run of 2026-08-27 wrote 22 artifacts from these four invocations over a corpus of 20 documents and 9,172 chunks. Indexing took 15.28 s for `deterministic`, 59.56 s for `openai`, 125.08 s for `sbert-multi`, and 136.64 s for `sbert`, all inside the 300 s budget. The two sentence-transformer timings differ by CPU scheduling, not by model size, and are not a model comparison.

Two case counts sit side by side on this page and are easy to confuse. Every quality metric below is over the 24 scored positives; the two diagnostics are over all 28 cases, because a question with no answer span still has a query vector and still hits the lexical index.

## 4. Before — the collapse, measured

Direct handling, chunk target 1200, `k=5`, `candidate_k=20`, `ts_rank_cd`, 24 scored positive cases per language. The `deterministic` provider is the structural before: its vectors are token hashes, so this table describes the query path rather than a semantic space.

| Arm | Strategy | Language | Cases | Recall@5 | Hit rate@5 | MRR | P95 ms |
|---|---|---|---:|---:|---:|---:|---:|
| `xling-deterministic-lexical-ts-rank-cd-en` | lexical | en | 24 | 0.270833 | 0.291667 | 0.171528 | 186.053 |
| `xling-deterministic-lexical-ts-rank-cd-ko` | lexical | ko | 24 | 0.000000 | 0.000000 | 0.000000 | 84.695 |
| `xling-deterministic-vector-en` | vector | en | 24 | 0.062500 | 0.083333 | 0.083333 | 27.184 |
| `xling-deterministic-vector-ko` | vector | ko | 24 | 0.000000 | 0.000000 | 0.000000 | 27.833 |
| `xling-deterministic-hybrid-ts-rank-cd-en` | hybrid | en | 24 | 0.104167 | 0.125000 | 0.097222 | 209.503 |
| `xling-deterministic-hybrid-ts-rank-cd-ko` | hybrid | ko | 24 | 0.000000 | 0.000000 | 0.000000 | 110.736 |

Every Korean row is exactly zero on every metric. The English rows are weak too, which is the point of F3: token-hash vectors are a noise floor, so the honest reading of this table is the Korean column, not the English one.

### Real embedding spaces, direct handling

The same direct arms in three spaces that actually encode meaning.

| Arm | Strategy | Language | Cases | Recall@5 | Hit rate@5 | MRR | P95 ms |
|---|---|---|---:|---:|---:|---:|---:|
| `xling-openai-vector-en` | vector | en | 24 | 0.375000 | 0.375000 | 0.300000 | 203.673 |
| `xling-openai-vector-ko` | vector | ko | 24 | 0.208333 | 0.208333 | 0.131944 | 182.466 |
| `xling-openai-hybrid-ts-rank-cd-en` | hybrid | en | 24 | 0.395833 | 0.416667 | 0.362500 | 346.982 |
| `xling-openai-hybrid-ts-rank-cd-ko` | hybrid | ko | 24 | 0.208333 | 0.208333 | 0.105556 | 292.065 |
| `xling-sbert-multi-vector-en` | vector | en | 24 | 0.125000 | 0.125000 | 0.097222 | 41.798 |
| `xling-sbert-multi-vector-ko` | vector | ko | 24 | 0.208333 | 0.208333 | 0.107639 | 43.888 |
| `xling-sbert-multi-hybrid-ts-rank-cd-en` | hybrid | en | 24 | 0.229167 | 0.250000 | 0.168056 | 227.325 |
| `xling-sbert-multi-hybrid-ts-rank-cd-ko` | hybrid | ko | 24 | 0.250000 | 0.250000 | 0.114583 | 129.579 |
| `xling-sbert-vector-en` | vector | en | 24 | 0.416667 | 0.416667 | 0.277778 | 37.023 |
| `xling-sbert-vector-ko` | vector | ko | 24 | 0.125000 | 0.125000 | 0.063889 | 39.815 |

Three things in this table are worth reading before any fix is discussed. The English-only `all-MiniLM-L6-v2` has the best English vector recall of any arm measured, 0.416667, above the OpenAI arm's 0.375000 — cross-lingual weakness is a property of a vector space, not a verdict on model quality. The multilingual sentence-transformer scores *higher* in Korean than in English on both of its arms, which already shows that a ko/en ratio is not a quality measure. And the OpenAI hybrid arm is the strongest English arm in the matrix while its Korean slice sits at half of it, which is the gap the rest of this page is about.

### Twin-query alignment

Mean, minimum, and maximum cosine between each Korean query vector and its English twin, over 28 pairs, with no corpus and no database.

| Provider | Model | Pairs | Mean cosine | Min cosine | Max cosine |
|---|---|---:|---:|---:|---:|
| `deterministic` | `token-hash-384` | 28 | 0.103210 | −0.048113 | 0.316228 |
| `sbert` | `all-MiniLM-L6-v2` | 28 | 0.339279 | −0.034543 | 0.750546 |
| `openai` | `text-embedding-3-small` at 384 | 28 | 0.568644 | 0.329923 | 0.861984 |
| `sbert-multi` | `paraphrase-multilingual-MiniLM-L12-v2` | 28 | 0.811329 | 0.634176 | 0.913633 |

This ordering is visible before a single chunk is indexed, and it predicts the ko/en ratio ordering of the vector arms above. The deterministic row needs its own reading: the maximum is exactly 0.316228, which is 1/√10, the signature of hash collisions across 384 dimensions rather than any shared meaning. It is a structural zero with collision noise on top, and 0.3162 must not be reported as a semantic signal.

### Lexical candidate coverage

How often the English `to_tsvector('english')` index returns nothing at `candidate_k=20`, per language, over all 28 cases. The numbers depend only on the question text and the English index, so they were identical in all four invocations.

| Language | Cases | Zero-candidate cases | Zero-candidate rate | Mean candidates |
|---|---:|---:|---:|---:|
| en | 28 | 0 | 0.000000 | 20.00 |
| ko | 28 | 4 | 0.142857 | 16.82 |

The Korean rate is a measurement, not the assumed 100%. Latin tokens inside Korean questions — tickers, process nodes, fiscal years — still match the English index. Only four Korean questions return nothing: `m3c-13` and `m3c-21` carry no Latin characters at all, `m3c-08` writes its year as `2019년` so the digits never become a bare lexeme, and `m3c-18` carries `CAC`, which does not occur in the corpus.

The other 24 Korean questions average 16.82 of 20 candidates, and Korean lexical recall@5 is still 0.000000. **That is the finding: for Korean the lexical component is not silent, it is confidently wrong.** A component that returns nothing is visible in `ComponentRankings.lexical`; a component that returns twenty irrelevant chunks looks exactly like a component that worked.

### Failure analysis by category

The OpenAI direct hybrid arm, sliced by golden category through the unmodified `breakdown_by_category` and joined at render time.

| Arm | Language | Category | Cases | Recall@5 | Hit rate@5 | MRR |
|---|---|---|---:|---:|---:|---:|
| `xling-openai-hybrid-ts-rank-cd-en` | en | `simple_lookup` | 13 | 0.653846 | 0.692308 | 0.630769 |
| `xling-openai-hybrid-ts-rank-cd-en` | en | `exact_number` | 5 | 0.000000 | 0.000000 | 0.000000 |
| `xling-openai-hybrid-ts-rank-cd-en` | en | `multi_hop` | 6 | 0.166667 | 0.166667 | 0.083333 |
| `xling-openai-hybrid-ts-rank-cd-ko` | ko | `simple_lookup` | 13 | 0.307692 | 0.307692 | 0.156410 |
| `xling-openai-hybrid-ts-rank-cd-ko` | ko | `exact_number` | 5 | 0.000000 | 0.000000 | 0.000000 |
| `xling-openai-hybrid-ts-rank-cd-ko` | ko | `multi_hop` | 6 | 0.166667 | 0.166667 | 0.083333 |

Category slices are reported, never gated. With five cases in `exact_number`, one flipped case moves the slice by 0.2.

The whole cross-lingual gap lives in `simple_lookup`: `multi_hop` already scores the same in both languages, and `exact_number` is 0.000000 in every arm, in both languages, and under every provider on this page. **`exact_number` is an English-side retrieval gap that this module measures but does not cause; attributing it to language would be a false cross-lingual finding.**

## 5. After — routing and translation

Hybrid strategy only, since routing and translation only mean something where both components run.

| Arm | Handling | Language | Cases | Recall@5 | Hit rate@5 | MRR | P95 ms |
|---|---|---|---:|---:|---:|---:|---:|
| `xling-openai-hybrid-ts-rank-cd-routed-en` | routed | en | 24 | 0.395833 | 0.416667 | 0.362500 | 349.120 |
| `xling-openai-hybrid-ts-rank-cd-routed-ko` | routed | ko | 24 | 0.208333 | 0.208333 | 0.131944 | 170.274 |
| `xling-openai-hybrid-ts-rank-cd-translated-en` | translated | en | 24 | 0.395833 | 0.416667 | 0.362500 | 4086.188 |
| `xling-openai-hybrid-ts-rank-cd-translated-ko` | translated | ko | 24 | 0.395833 | 0.416667 | 0.336806 | 2934.909 |
| `xling-sbert-multi-hybrid-ts-rank-cd-routed-en` | routed | en | 24 | 0.229167 | 0.250000 | 0.168056 | 223.994 |
| `xling-sbert-multi-hybrid-ts-rank-cd-routed-ko` | routed | ko | 24 | 0.208333 | 0.208333 | 0.107639 | 44.547 |

### Improvement cycle delta

The Korean slice of the OpenAI hybrid arm across the three query paths, with the change the cycle claims.

| Metric | KO direct | KO routed | KO translated | Best delta vs direct |
|---|---:|---:|---:|---:|
| `recall_at_k` | 0.208333 | 0.208333 | 0.395833 | +0.187500 |
| `hit_rate_at_k` | 0.208333 | 0.208333 | 0.416667 | +0.208333 |
| `mrr` | 0.105556 | 0.131944 | 0.336806 | +0.231250 |

**Routing did not fix Korean, and the design expected it to.** Under the OpenAI arm, routing flipped no case at all: Korean recall and hit rate are unchanged to six decimals, and only MRR moves, from 0.105556 to 0.131944, because dropping a wrong lexical list lets two already-found chunks rise (`m3c-11` from rank 2 to 1, `m3c-23` from rank 5 to 3). That is exactly what the coverage table predicts. Only 4 of 28 Korean questions had nothing to drop, so removing the lexical arm removes a ranking distortion, not a retrieval failure — the Korean weakness lives on the vector side, and translation is what moves it.

Translation reaches a recall and hit-rate ratio of exactly 1.000000, recovering the same five `simple_lookup` cases English gets and no others. The MRR ratio is 0.929119, not 1.0: the hit *set* is identical to English while the *ranks* differ (`m3c-08` moves from rank 1 to 4, `m3c-11` from 2 to 3, `m3c-13` from 5 to 2). Parity here means the same documents found, not the same ordering. The price is latency — P95 rises from 292 ms to 2,935 ms because every Korean query now waits on an LLM call.

The English slice must not move to pay for this, and it does not:

| Metric | EN direct | EN routed | EN translated | Movement |
|---|---:|---:|---:|---:|
| `recall_at_k` | 0.395833 | 0.395833 | 0.395833 | 0.000000 |
| `hit_rate_at_k` | 0.416667 | 0.416667 | 0.416667 | 0.000000 |
| `mrr` | 0.362500 | 0.362500 | 0.362500 | 0.000000 |

Routing fires only on Hangul, and the translator is a verified no-op on English: all 28 English queries came back byte-identical with `source_language` reported as English, which is why the translated English arm reproduces the direct one exactly. These runs were the first of `m8-crosslingual-v1` in this database, so every persisted row reports a null baseline and a null comparison — this run *is* the baseline, and the 0.05 per-metric regression tolerance starts guarding from the next run on.

## 6. Parity verdict

The gated metric is `recall_at_k` at a floor of 0.85, inclusive at the boundary, on hybrid arms with `routed` or `translated` handling. The `direct` row is printed for contrast and is not gated.

| Arm pair | Handling | Cases | Recall@5 EN | Recall@5 KO | Delta | Ratio | Gated | Verdict |
|---|---|---:|---:|---:|---:|---:|---|---|
| `xling-openai-hybrid-ts-rank-cd` | direct | 24 | 0.395833 | 0.208333 | 0.187500 | 0.526316 | no | before-measurement |
| `xling-openai-hybrid-ts-rank-cd-routed` | routed | 24 | 0.395833 | 0.208333 | 0.187500 | 0.526316 | yes | FAIL |
| `xling-openai-hybrid-ts-rank-cd-translated` | translated | 24 | 0.395833 | 0.395833 | 0.000000 | 1.000000 | yes | PASS |
| `xling-sbert-multi-hybrid-ts-rank-cd` | direct | 24 | 0.229167 | 0.250000 | −0.020833 | 1.090909 | no | before-measurement |
| `xling-sbert-multi-hybrid-ts-rank-cd-routed` | routed | 24 | 0.229167 | 0.208333 | 0.020833 | 0.909091 | yes | PASS |

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling routed translated --gate
echo "exit: $?"
```

The overall gate is the conjunction over the gated arms, so this command exits 1: the translated arm passes and the routed arm fails at ratio 0.526316. The `sbert-multi` run with only a routed arm exits 0.

A zero exit is the parity claim. A nonzero exit means either the ratio fell below the floor or the English slice scored zero and the ratio was undefined — both are failures, and neither is reportable as a pass. One further caution belongs next to a zero exit: `gate.passed` is also `true` when the payload lists no gated arm at all, because a conjunction over an empty list is vacuously true. Only `--gate`, which refuses to run without a gateable pair, makes the exit code mean anything.

**A ratio can be passed by getting worse.** The `sbert-multi` routed arm clears the 0.85 floor at 0.909091, and its English recall of 0.229167 is the weakest English hybrid number on this page — below the OpenAI arm's 0.395833 and below the English-only sentence-transformer's 0.416667. On its vector arm the ratio is 1.666667, Korean above English. Nothing in the ratio notices that both slices fell; that is why `language_regression` exists and why the two halves of the gate are not optional. Routing is also not free: the same `sbert-multi` routing that raised the ratio *lost* `m3c-16`, whose Korean question names `GDDR6` and `GDDR6X` in Latin script — real lexical signal, discarded wholesale by the route. Its hit set fell from 6 to 5 and recall from 0.250000 to 0.208333.

## 7. Cost and provenance

The free gate on this page is `--provider sbert-multi --handling routed`: it runs on CPU, performs no LLM call, and exits 0. It is also the arm the section above warns about, so a run that means to reproduce the shipping claim needs the paid paths:

```bash
OPENAI_API_KEY="your-key" uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies vector hybrid --handling direct routed
OPENAI_API_KEY="your-key" uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling translated --translator-model gpt-4.1-mini
```

The recorded OpenAI session cost about $0.05 in total, with $0.06 as the upper bound: one corpus embed of 9,172 chunks at roughly two million tokens for $0.038 to $0.044, 224 query embeddings for under $0.001, and 56 `gpt-4.1-mini` translation calls for about $0.008. Only one corpus embed was paid for, because all eight OpenAI arms shared a single temporary corpus session. The translator was run on both languages, 28 calls each, because the parity pair requires a translated English arm as well. Every translated query is recorded in the run payload — joined on the question text, since that payload carries no case id — so a reported translated number can be re-read case by case. Gate runs use deterministic paths; measured translation runs are reported, not baselined.

Korean golden review remains a separate manual gate. Machine validation of the twin contract does not make any case human-verified.

## 8. Failure triage

| Symptom | Likely boundary | First action |
|---|---|---|
| `GoldenDataError` about duplicate spans | M8.1 loading | load the two suites as two files, never as a directory |
| `TwinCaseError` naming a field | M8.1 twins | fix the Korean case to match the English one; never relax the invariant list |
| Parity raises "arms must differ only in query language" | M8.2 config | check `embedding.model` and `query.handling` in both configs |
| Korean zero-candidate rate below expectation | M8.2 diagnostics | read the matched lexemes; Latin tokens in Korean questions are expected |
| A routed arm hits a real session in a test | M8.3 handling | routed calls `retrieve` directly; fake `retrieve`, not `make_retriever` |
| `QueryTranslationError` on every case | M8.3 translation | check the provider budget and the schema; the arm must not fall back |
| Ratio reported as `undefined` | M8.4 parity | the English slice scored zero; fix the English arm before reading the Korean one |
| `--gate` raises instead of judging | M8.4 gate | the matrix has no `routed` or `translated` hybrid pair in both languages |
