# M8.2 Tutorial 2 — Measure the failure before you own it

There is a fix waiting at the end of this module, and taking it now would be the mistake. **An improvement with no before-table is an anecdote, and a multilingual claim with no numbers is a rumor.** This document builds the arm that carries its own provenance into the M3 harness, plus two diagnostics that answer "does this system recognize Korean at all" cheaply enough to run before anything has been changed.

**Prerequisite:** M8.1 is complete and `uv run pytest tests/crosslingual/test_01_bilingual.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `CrosslingualArm` | **Implement** the arm and its config | The config dict carries every regression number |
| `twin_query_alignment` | **Implement** the corpus-free diagnostic | Near-zero is a claim; exact zero is a lie |
| `lexical_candidate_coverage` | **Implement** the collapse counter | The rate is measured, never assumed |
| The render helpers | **Write the joins** | Language is a second run, not a new dimension |

### 1. An arm has to say what it is

The M3 harness compares runs by their canonical config dict: `latest_comparable_baseline` matches on the serialized config, so two runs with the same config are treated as measurements of the same thing. That is a gift and a trap. Omit `query.language` and a Korean run silently inherits an English baseline; omit `embedding.model` and a multilingual arm is compared against a token-hash arm. **The config contract carries the full weight of every regression number in this module.**

#### Create `app/evals/crosslingual.py` — the arm

**Learning action — implement the arm:** write the validation first, and for each rule state which number it protects.

<!-- src: app/evals/crosslingual.py::CrosslingualArm -->
```python
@dataclass(frozen=True, slots=True)
class CrosslingualArm:
    """One measured cross-lingual retrieval arm and its canonical provenance."""

    embedding_provider: ProviderChoice
    embedding_model: str
    strategy: RetrievalStrategy
    language: QueryLanguage
    handling: QueryHandling = "direct"
    lexical_ranker: LexicalRanker | None = None
    translator_model: str | None = None
    dimensions: int = 384
    target_text_chars: int = CROSSLINGUAL_TARGET_TEXT_CHARS
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        """Reject arm shapes whose measured numbers could not be attributed."""
        if self.embedding_provider not in PROVIDER_CHOICES:
            raise ValueError(f"unsupported embedding provider: {self.embedding_provider}")
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must be nonblank")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if self.language not in LANGUAGE_ORDER:
            raise ValueError(f"unsupported query language: {self.language}")
        if self.handling not in HANDLING_ORDER:
            raise ValueError(f"unsupported query handling: {self.handling}")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in RANKER_SLUG:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")
        # Routing decides whether to ask the lexical component at all, so it only
        # means something where both components run. A "routed" vector arm would be
        # the direct vector arm under a label claiming a route it never took.
        if self.handling != "direct" and self.strategy != "hybrid":
            raise ValueError(f"{self.handling} handling requires the hybrid strategy")
        if (self.handling == "translated") != (self.translator_model is not None):
            raise ValueError("a translator model is required exactly for translated handling")
        if self.dimensions <= 0 or self.target_text_chars <= 0:
            raise ValueError("dimensions and target_text_chars must be positive")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if ARM_NAME.fullmatch(self.name) is None:
            raise ValueError("arm name must be lowercase kebab-case")

    @property
    def name(self) -> str:
        """Return the kebab arm name, which must survive being used as a filename."""
        parts = ["xling", self.embedding_provider, self.strategy]
        if self.lexical_ranker is not None:
            parts.append(RANKER_SLUG[self.lexical_ranker])
        if self.handling != "direct":
            parts.append(self.handling)
        parts.append(self.language)
        return "-".join(parts)

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Order arms by retrieval path, then handling, then language."""
        return (
            STRATEGY_ORDER[self.strategy],
            HANDLING_ORDER[self.handling],
            LANGUAGE_ORDER[self.language],
            self.name,
        )

    def paired_with(self, language: QueryLanguage) -> CrosslingualArm:
        """Return the same arm measured in the other query language."""
        return CrosslingualArm(**{**asdict(self), "language": language})

    def to_config(self) -> dict[str, Any]:
        """Return the canonical config dict consumed by artifacts and baselines.

        ``embedding.model`` and ``query.language`` carry the whole weight of every
        regression number in this module: ``latest_comparable_baseline`` matches on
        the serialized config, so an arm that omitted either would be compared
        against a run in a different vector space or a different language and the
        comparison would look valid.

        ``retrieval.reranker`` is recorded as null rather than left out. The M2.6
        cross-encoder is an English-trained model, so it stays off in every arm here;
        writing that down makes a future run that switches it on visibly incomparable
        instead of quietly contaminating the Korean slice.
        """
        translator = (
            None
            if self.translator_model is None
            else {"provider": "openai", "model": self.translator_model}
        )
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": {
                "strategy": self.strategy,
                "lexical_ranker": self.lexical_ranker,
                "reranker": None,
                "k": self.k,
                "candidate_k": self.candidate_k,
                "rrf_k": self.rrf_k,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "model": self.embedding_model,
                "dimensions": self.dimensions,
            },
            "query": {
                "language": self.language,
                "handling": self.handling,
                "translator": translator,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider == "openai"
                or self.handling == "translated",
                "populated_corpus_embeddings_modified": False,
            },
        }
```

**What to look for in the code**

- Every rejection in `__post_init__` protects an attribution, not a type. A `routed` vector arm would be the direct vector arm wearing a label that claims a route it never took — the value would be real and the name would be a lie.
- `retrieval.reranker` is written as `null` rather than omitted. **A recorded null makes a future run that enables the English-trained cross-encoder visibly incomparable, where an omitted key would let it merge into the same baseline.**
- The name is built from the same fields the config records, so an artifact filename and its config can never disagree about what ran.
- `paired_with` is how the parity step gets the other language: one field changes, and `__post_init__` re-validates the whole shape.

The arm feeds `evaluate_retriever` directly rather than going through `run_ablation`. `ExperimentConfig` has no place to record a query language or a handling mode, and its config-equality check would force that shape. Everything else — scoring, provenance, latency, artifact schema — is the M3 harness untouched.

### 2. The cheapest honest diagnostic

Before any corpus exists, one question can already be answered: does this embedding space put a Korean question anywhere near its English twin? Twenty-eight pairs, two `embed_documents` calls, no database.

#### Extend `app/evals/crosslingual.py` — twin alignment

**Learning action — implement the corpus-free diagnostic:** predict the deterministic provider's number before you run it, then check whether you were right about *exactly* zero.

<!-- src: app/evals/crosslingual.py::twin_query_alignment -->
```python
async def twin_query_alignment(
    provider: EmbeddingProvider,
    suite: BilingualSuite,
    *,
    provider_name: str = "unknown",
) -> TwinAlignment:
    """Measure how near each Korean query sits to its English twin, before any corpus.

    This is the cheapest honest answer to "does this embedding space recognize both
    languages at all": no database, no chunks, no retrieval. A token-hashing provider
    shares almost no tokens across the pair and lands near zero — near, not at, since
    384 hashed dimensions collide. A multilingual model places the twins close, and
    that difference is visible before a single arm is indexed.
    """
    pairs = suite.pairs()
    if not pairs:
        raise ValueError("twin alignment requires at least one pair")
    en_vectors = await provider.embed_documents([english.question for english, _ in pairs])
    ko_vectors = await provider.embed_documents([korean.question for _, korean in pairs])
    measured = tuple(
        TwinCosine(case_id=english.id, cosine=_cosine(en_vector, ko_vector))
        for (english, _), en_vector, ko_vector in zip(pairs, en_vectors, ko_vectors, strict=True)
    )
    cosines = [item.cosine for item in measured]
    return TwinAlignment(
        provider=provider_name,
        pair_count=len(measured),
        mean_cosine=sum(cosines) / len(cosines),
        min_cosine=min(cosines),
        max_cosine=max(cosines),
        pairs=measured,
    )
```

**What to look for in the code**

- The deterministic provider hashes tokens into 384 buckets and keeps Hangul eojeols as tokens, so a Korean vector is not empty and unrelated tokens collide into shared dimensions. **The honest assertion is a small bound, never `== 0.0`** — an exact-zero test fails on the first collision and teaches you nothing.
- `min_cosine` and `max_cosine` are reported alongside the mean, because a mean over 28 pairs hides the pair that fell apart.
- Per-pair cosines are kept, so a bad twin can be found by case id rather than by re-running the diagnostic.

### 3. Count the collapse, do not assume it

#### Extend `app/evals/crosslingual.py` — lexical coverage

**Learning action — implement the collapse counter:** write down the rate you expect for Korean, then read the docstring and revise it.

<!-- src: app/evals/crosslingual.py::lexical_candidate_coverage -->
```python
async def lexical_candidate_coverage(
    retriever: Retriever,
    cases: Sequence[GoldenCase],
    *,
    language: QueryLanguage,
    candidate_k: int = 20,
) -> LexicalCoverage:
    """Count how many questions the lexical arm answers with nothing at all.

    The retriever is injected rather than built from a session here, so the
    diagnostic is exercised offline against a scripted lexical arm and used in the
    measured run against ``make_retriever(session, strategy="lexical", ...)``.

    The rate is measured, not assumed. Korean questions about this corpus still carry
    Latin tokens — tickers, ``7nm``, ``G4ad`` — and the English tsquery can match
    those, so the collapse is partial in a way only the number shows.
    """
    if not cases:
        raise ValueError("lexical coverage requires at least one case")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    empty: list[str] = []
    total = 0
    for case in sorted(cases, key=lambda item: item.id):
        hits = await retriever(case.question, candidate_k)
        total += len(hits)
        if not hits:
            empty.append(case.id)
    return LexicalCoverage(
        language=language,
        case_count=len(cases),
        zero_candidate_cases=len(empty),
        zero_candidate_rate=len(empty) / len(cases),
        mean_candidate_count=total / len(cases),
        zero_candidate_case_ids=tuple(empty),
    )
```

**What to look for in the code**

- The parameter is a `Retriever`, not a session. That is what makes the diagnostic testable offline against a scripted arm while the measured run passes `make_retriever(session, strategy="lexical", ...)` — the same callable contract M3 already defined.
- **The Korean rate is a number the corpus produces, not the 100% the story wants.** A Korean question about a semiconductor filing carries tickers and process nodes in Latin script, and the English index matches those lexemes happily.
- `zero_candidate_case_ids` is returned so the failure analysis in chapter 4 can start from the cases that actually collapsed.

### 4. Language is a second run, not a new dimension

#### Extend `app/evals/crosslingual.py` — the joins

**Learning action — write the joins:** notice which module you did *not* have to edit.

<!-- src: app/evals/crosslingual.py::category_breakdown,arm_comparison_markdown,language_category_markdown -->
```python
def category_breakdown(evaluation: RetrievalEvaluation) -> tuple[GroupScore, ...]:
    """Slice one evaluation by golden category through the unmodified breakdown."""
    cases = [case.golden for case in evaluation.cases]
    scores = [case.score for case in evaluation.cases if case.score is not None]
    return breakdown_by_category(cases, scores)


def arm_comparison_markdown(runs: Sequence[LanguageRun]) -> str:
    """Render one row per measured arm in deterministic arm order."""
    if not runs:
        raise ValueError("comparison requires at least one run")
    lines = [
        "| Arm | Strategy | Handling | Language | Cases | Recall@k | Hit rate@k | MRR | P95 ms |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        score = run.evaluation.score
        lines.append(
            f"| {run.arm.name} | {run.arm.strategy} | {run.arm.handling} | "
            f"{run.arm.language} | {score.case_count} | {score.recall_at_k:.6f} | "
            f"{score.hit_rate_at_k:.6f} | {score.mrr:.6f} | "
            f"{run.evaluation.latency.p95_ms:.3f} |"
        )
    return "\n".join(lines)


def language_category_markdown(runs: Sequence[LanguageRun]) -> str:
    """Join the per-category slices of every run into one language-aware table.

    Language is not a breakdown dimension inside ``breakdown.py``; each language is a
    separate run of the unmodified harness, and the two are joined here at render
    time. That keeps ``GroupScore`` and the loader's span-identity rule untouched, and
    it is the same move M9.5 made when it sliced decomposition by category.
    """
    if not runs:
        raise ValueError("category table requires at least one run")
    lines = [
        "| Arm | Language | Category | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        for group in run.categories:
            lines.append(
                f"| {run.arm.name} | {run.arm.language} | {group.group} | "
                f"{group.case_count} | {group.recall_at_k:.6f} | "
                f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
            )
    return "\n".join(lines)
```

**What to look for in the code**

- `breakdown_by_category` is called unmodified. **Adding a language dimension inside `GroupScore` would have meant editing a scorer that predates this module — the join belongs at render time, where being wrong is cheap.**
- Rows come out in `sort_key` order, so two runs of the same matrix produce byte-comparable tables.
- The comparison table prints the case count next to every metric. With 24 scored positives per language, one flipped case is about 0.042, and a reader who cannot see `n` cannot see that.

One dependency lives outside this file. `crosslingual.py` imports `MULTILINGUAL_SBERT_MODEL` at module top, and `tests/crosslingual/test_02_crosslingual.py` does the same — until the constant exists, the M8.2 command dies at collection with an `ImportError`, not a failing assertion. Add the one line to `app/retrieval/sbert.py` before running anything:

<!-- src: app/retrieval/sbert.py::MULTILINGUAL_SBERT_MODEL -->
```python
MULTILINGUAL_SBERT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

### 5. The measured run

Measurement is a command-line run, never a test:

```bash
docker compose up -d db
uv run python -m app.evals.crosslingual --provider sbert-multi --languages en ko --strategies lexical vector hybrid
```

`--provider sbert-multi` is not a new provider literal. It is the existing `sbert` provider pointed at `paraphrase-multilingual-MiniLM-L12-v2`, which is natively 384 dimensions, so the arm changes the vector space without touching `embed_dim`, the `Vector(384)` column, or any migration. Record what comes back in [verification](../05-verify.md) before continuing — that table is the "before" the next two chapters are measured against.

### Focused tests and the contract they keep

```bash
uv run pytest tests/crosslingual/test_02_crosslingual.py -q
```

Expected: `23 passed`, with no database and no network.

| What the test breaks | Contract it protects |
|---|---|
| An arm whose config omits language or model | Baselines separate per language and per vector space |
| A `routed` arm on a non-hybrid strategy | An arm name may not claim a route it never took |
| An exact-zero cross-lingual cosine assertion | Near-orthogonality is the claim; hash collisions are real |
| A hard-coded Korean zero-candidate rate | The collapse is a measurement, not an assumption |
| A category table built inside `breakdown.py` | The M3 breakdown stays unmodified |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why does the config dict carry `embedding.model` and `query.language` explicitly?**
  - **Answer:** `latest_comparable_baseline` matches on the serialized config, so an omitted field silently compares a Korean run against an English baseline, or a multilingual arm against a token-hash arm.
- **Why assert near-zero rather than zero for deterministic twin cosines?**
  - **Answer:** 384 hash buckets collide, so unrelated tokens share dimensions; the structural claim is "this space does not relate the languages", and a small bound is its honest test.
- **Why measure the lexical zero-candidate rate instead of asserting 100%?**
  - **Answer:** Korean questions carry Latin tickers and process nodes that the English index matches, so the collapse is partial and only the number says how partial.

---

[← Previous: the bilingual golden suite](01-bilingual-golden.md) · [Module overview](../03-build.md) · [Next: routing and translation →](03-routing-and-translation.md)
