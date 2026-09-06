# M8 Spec — Twins, arms, and the parity gate

## 1. Scope

This specification defines the complete M8 path: a Korean twin golden suite bound to the same immutable answer spans as the English one, a cross-lingual arm matrix with canonical provenance, two query-path diagnostics, language-aware query handling in the retrieval service, and a ko/en parity definition with a gate. The layers are built in order: M8.1 twins, M8.2 measurement, M8.3 query handling, M8.4 parity.

M8 changes no evaluation contract. `app/evals/scoring.py`, `app/evals/breakdown.py`, `app/evals/regression.py`, and the artifact schema are used exactly as M3 left them. Language enters as a second run of the same harness, never as a new axis inside the scorer.

## 2. Twin-suite contract

The Korean suite is a separate file, `data/golden/retrieval_ko.json`, holding twenty-eight cases with the same `m3c-NN` ids as `data/golden/retrieval.json`. `data/golden/retrieval.json` is not edited by this module.

Separate files are forced, not preferred. `load_golden_cases` rejects duplicate answer-span identities across cases within one loaded batch, and twins share every span by design; two `load_golden_cases` calls give each file the loader's full manifest, SHA-256, bounds, and visible-evidence verification independently.

`validate_twin_cases(en_cases, ko_cases)` enforces the contract and returns the ordered pairs. It requires:

1. both suites nonempty, with no repeated case id inside either; 2. identical id sets across the two suites; 3. per pair, identical values for every field in `TWIN_INVARIANT_FIELDS` — `category`, `facet`, `tags`, `answers`, `expected_label`, `reference_answer`; 4. per pair, questions that differ after case-folded whitespace normalization; 5. no Hangul in the English question; and 6. at least one Hangul character in the Korean question.

Rule 4 is checked before rules 5 and 6. A question copied across untranslated is the likely authoring slip, and reporting it as "contains no Hangul" would name the symptom rather than the cause.

`reference_answer` stays English on both sides. Retrieval scoring never reads it, and requiring identity makes the invariant checkable instead of approximate. The Hangul scan in `app/evals/bilingual.py` is local to that module rather than imported from `app/retrieval/language.py`: the suite contract must hold before any query-path code exists, and sharing the helper would make the first checkpoint depend on the third.

Absent cases stay absent in both languages: four Korean questions with zero answer spans, `expected_label="NOT_IN_DOCS"`, and `reference_answer="NOT_IN_DOCS"`. Every case keeps `curation_status="agent-curated"`, `approval_status="pending-author-approval"`, and `human_verified=false`. Twins are translations of already-curated English cases; the validator is their machine gate and does not replace author review.

## 3. Arm grammar

An arm name is lowercase kebab-case and must survive being used as a filename:

```text
xling-<provider>-<strategy>[-<ranker-slug>][-<handling>]-<lang>
```

- `<provider>` is one of `deterministic`, `openai`, `sbert`, `sbert-multi`.
- `<strategy>` is `lexical`, `vector`, or `hybrid`.
- `<ranker-slug>` is `ts-rank-cd` or `bm25`, present for every strategy that issues a lexical query and absent for `vector`.
- `<handling>` is `routed` or `translated`, and is omitted entirely when handling is `direct`.
- `<lang>` is `en` or `ko`.

Examples: `xling-deterministic-vector-en`, `xling-deterministic-hybrid-ts-rank-cd-en`, `xling-sbert-multi-hybrid-ts-rank-cd-routed-ko`.

The arm constructor rejects shapes whose numbers could not be attributed: a `vector` arm that names a lexical ranker, a lexical or hybrid arm that omits one, a `routed` or `translated` arm on any strategy other than `hybrid`, a `translated` arm without a translator model or a non-translated arm with one, and inconsistent `k`, `candidate_k`, and `rrf_k`. Chunking is held fixed at the M3 winning target of 1200 characters so the only axes in the matrix are embedding space, retrieval strategy, query language, and query handling.

## 4. Canonical config dict

Every arm emits the config dict that `evaluate_retriever` records and `latest_comparable_baseline` matches on:

```json
{
  "name": "xling-sbert-multi-hybrid-ts-rank-cd-routed-ko",
  "chunking": {
    "strategy": "structure-aware",
    "target_text_chars": 1200,
    "golden_identity": "source-sha256-and-half-open-span"
  },
  "retrieval": {
    "strategy": "hybrid",
    "lexical_ranker": "ts_rank_cd",
    "reranker": null,
    "k": 5,
    "candidate_k": 20,
    "rrf_k": 60
  },
  "embedding": {
    "provider": "sbert-multi",
    "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "dimensions": 384
  },
  "query": {
    "language": "ko",
    "handling": "routed",
    "translator": null
  },
  "measurement": {
    "environment": "isolated-temporary-postgresql",
    "paid_api_calls": false,
    "populated_corpus_embeddings_modified": false
  }
}
```

`embedding.model` and `query.language` carry the weight of every regression number in this module. `latest_comparable_baseline` matches on the serialized config, so an arm that omitted either would be compared against a run in a different vector space or a different language, and the comparison would look valid while measuring the wrong difference.

`retrieval.reranker` is recorded as `null` in every M8 arm rather than left out, and the M2.6 cross-encoder stays off in every arm. That model is trained on English query-passage pairs, so enabling it would reorder the Korean slice under a scorer that has never been measured on Korean input. Writing the null down makes a future run that switches the reranker on visibly incomparable instead of quietly contaminating the Korean numbers.

`measurement.paid_api_calls` is true exactly when the embedding provider is `openai` or the handling is `translated`. The eval runner builds its own corpus in temporary tables through `temporary_corpus_session`, so no arm modifies the populated corpus embeddings.

## 5. Query handling

Three handling values, all built as wrappers over the unmodified M3 retriever factory, so the comparison is between query paths and never between evaluation code paths:

| Handling | Korean query path | English query path | Cost |
|---|---|---|---|
| `direct` | full hybrid, lexical component included | full hybrid | none |
| `routed` | lexical component skipped, ranking is vector-only | full hybrid | none |
| `translated` | translated to English, then full hybrid | full hybrid | one LLM call per query |

`detect_query_language(query)` classifies one nonblank query by scanning three Unicode ranges — precomposed syllables `U+AC00`–`U+D7A3`, conjoining jamo `U+1100`–`U+11FF`, and compatibility jamo `U+3130`–`U+318F`. Any Hangul makes the query Korean. The rule is presence, not proportion: Korean questions about this corpus carry tickers, process nodes, and fiscal years in Latin script, so a majority-script rule would misroute exactly the queries this module exists to route. A blank query raises rather than defaulting to English.

`retrieve()` gains one parameter, `route_by_language: bool | None = None`, in the same style as the M2.6 `reranker` parameter. `None` resolves from `Settings`. With routing on and a Korean query, the lexical component returns an empty list, which makes the taken route readable from `ComponentRankings.lexical` instead of inferred from configuration.

`app/config.py` gains exactly one field, `query_language_routing: bool = False`. It ships off: M8 measures the collapse before changing the shipped query path.

Translation is explicit injection only and is deliberately not a `Settings` mode. `translate_query(query, *, llm_provider, provider_budget)` requires the caller to hold a provider and a budget, so no configuration flag can put a paid network call into a request that never asked for one. It raises `QueryTranslationError` when the provider refuses, exhausts its budget, fails schema validation, or returns a query that still contains Hangul. Unlike `decompose_query`, it does not fall back to the input: a failed translation would leave the Korean query to be scored as if it had been translated, and the measured number would then describe an arm that never ran.

## 6. Parity definition

For one arm pair differing only in `query.language`, and for each higher-is-better metric `m` in `recall_at_k`, `hit_rate_at_k`, `mrr`:

```text
delta_m = m_en - m_ko
ratio_m = m_ko / m_en
```

`assess_parity(en_eval, ko_eval, *, min_recall_ratio=0.85)` returns all three pairs, and rejects inputs that are not comparable: a different suite, a different `k`, different case-id sets, different scored-case sets, or configs that disagree about anything other than `query.language` and the arm `name` that encodes it.

The ratio is undefined when the English slice scores zero, and that case **fails closed**. An arm whose English slice retrieves nothing has no parity to claim, and the quotient `0/0` would read as perfect agreement while describing two dead arms.

The gate is `ratio` on `recall_at_k` at a floor of `0.85`, inclusive at the boundary. It applies only to hybrid arms whose handling is `routed` or `translated`. The `direct` hybrid arm is the before-measurement and is expected to fail: gating it would make the gate report the very failure the module was built to expose, while passing it would mean the routing change had never been measured. `--gate` with no such arm pair raises rather than passing vacuously.

The standing per-language regression tolerance is `0.05` per metric, applied through the existing `compare_against_baseline`. Twenty-four positive cases per language means one flipped case moves a macro metric by about `0.042`, so a tolerance at or below single-case granularity would let the gate flap on noise. Every reported table prints its case count next to the metrics for the same reason. Per-category slices are reported but never gated: `exact_number` holds five cases, where one case is a fifth of the slice.

Parity is a ratio between two arms measured together, so it is only half the gate. `language_regression(baseline, current)` runs per language against its own stored baseline, because raising the Korean slice while quietly dropping the English one would improve the ratio.

## 7. Cost

Vectors from different models share no space, so every provider arm re-embeds the corpus. One arm indexes 9,172 chunks, roughly 2.7 to 3 million tokens under the planning approximation of four characters per token:

| Provider | Per-arm re-embedding | Wall clock | Note |
|---|---|---|---|
| `deterministic` | none | instant | token hashes, offline, no semantic claim |
| `sbert`, `sbert-multi` | none | minutes on CPU | `sentence-transformers` is already an installed extra |
| `openai` | about $0.06 per run | minutes | `text-embedding-3-small` at $0.02 per million tokens |

Query-side cost is negligible: fifty-six query embeddings, plus about twenty-four `gpt-4.1-mini` translations for a translated arm, together under $0.01. Switching the *production* corpus provider is a separate operation with the same embedding cost — clear `chunks.embedding` and re-run `embed_missing_chunks` — and is not part of any M8 run.

## 8. Out of scope

- **Korean-language answers.** "Korean question, Korean review answer, English citations" is one prompt line in the M4 workflow and has no deterministic metric here: this repository has no LLM-as-judge, so answer-language fidelity could only be asserted. Shipping it would break the module's own thesis that every claim is a measured number. It is second-round headroom.
- **A DART or 20-F corpus.** A Korean-language source adapter, a per-document language tag, and a Korean text-search configuration for the lexical column are a second-round extension. The parity gate built here is what would accept that corpus.
- **Enabling the M2.6 cross-encoder.** English-trained, off in every arm, recorded as `null` so the exclusion is a fact in the artifact.
- **A production routing default.** `query_language_routing` ships `false`, and the measured tables do not ask for it to change: routing flipped no Korean case on the OpenAI arm and cost one on the multilingual arm. Turning it on is a decision the tables would have to support, not one this module makes.

## 9. Acceptance gate

```bash
uv run pytest tests/crosslingual -q
uv run ruff check app/evals app/retrieval tests/crosslingual
uv run ruff format --check app/evals app/retrieval tests/crosslingual
uv run python scripts/check_doc_code.py docs/en/m8-crosslingual
```

M8 is machine-complete when the sixty-nine offline tests pass with no network, no database, and no key, and when the measured run in [verification](05-verify.md) has recorded its before and after tables with a parity verdict. Author approval of the Korean golden cases remains a separate manual gate, exactly as it is for the English suite.
