# M9.5 Tutorial 5 — An improvement is a measured delta

Multi-hop questions — "how did X change between 2022 and 2023" — lose recall under a single embedded query, and the golden set has carried a `multi_hop` category since M3 waiting for this moment. This document splits the question, retrieves per part, fuses the rankings — and then submits the whole idea to the unmodified M3 harness, because **a retrieval improvement that is not a per-category delta in an artifact is an anecdote.**

**Prerequisite:** M9.4 is complete and `uv run pytest tests/agent/test_05_builtin_tools.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `QueryDecomposition` + `decompose_query` | **Implement** the fail-closed split | The fallback is the original question, never an error |
| `merge_ranked_lists` | **Implement** n-list RRF | Rank-only fusion, deterministic ties — M2's rule generalized |
| The retriever + comparison | **Implement, then run the measurement** | The M3 harness takes the new retriever unmodified |

### 1. Decomposition fails closed

#### Create `app/agent/decompose.py` — the split

**Learning action — implement the fail-closed split:** enumerate the failure modes and confirm every one lands on the same fallback.

<!-- src: app/agent/decompose.py::QueryDecomposition,decompose_query -->
```python
class QueryDecomposition(StrictAgentModel):
    """The structured decomposition contract returned by the LLM."""

    sub_questions: tuple[Annotated[StrictStr, Field(min_length=1)], ...]

    @model_validator(mode="after")
    def validate_sub_questions(self) -> Self:
        """Reject empty, oversized, blank, or duplicated decompositions."""
        if not 1 <= len(self.sub_questions) <= MAX_SUB_QUESTIONS:
            raise ValueError(f"decomposition requires 1 to {MAX_SUB_QUESTIONS} sub-questions")
        normalized = [" ".join(question.split()).casefold() for question in self.sub_questions]
        if any(not question for question in normalized):
            raise ValueError("sub-questions must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("sub-questions must be unique")
        return self


async def decompose_query(
    question: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> tuple[str, ...]:
    """Return validated sub-questions, falling back to the original on failure.

    The fallback is deliberate: decomposition is an optimization, and an
    unavailable or refusing provider must degrade to the measured single-query
    baseline instead of failing the retrieval request outright.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    prompt = Prompt(system=DECOMPOSE_SYSTEM_PROMPT, user=question)
    result = await llm_provider.complete(prompt, QueryDecomposition, provider_budget)
    if result.status != "ok" or result.parsed is None:
        return (question,)
    return result.parsed.sub_questions
```

**What to look for in the code**

- `QueryDecomposition` allows one to four sub-questions, normalized and unique. A model that "decomposes" into duplicates or an essay fails validation, and validation failure is just another road to the fallback.
- **Every failure — provider exception, malformed JSON, empty list — falls back to the original question, so decomposition can only ever add recall paths, never subtract the baseline.** A feature that can make retrieval worse when its LLM hiccups would be a liability, not an improvement.

### 2. Fusion is rank-only, again

#### Extend `app/agent/decompose.py` — n-list reciprocal-rank fusion

**Learning action — implement n-list RRF:** compare with M2's two-list fusion and identify what generalized and what did not.

<!-- src: app/agent/decompose.py::merge_ranked_lists -->
```python
def merge_ranked_lists(
    ranked_lists: tuple[tuple[ChunkHit, ...], ...],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> tuple[ChunkHit, ...]:
    """Fuse per-sub-question rankings with reciprocal-rank scores over n lists.

    This is the M2.5 fusion rule generalized from two fixed components to one
    list per sub-question: only ranks contribute, so sub-questions with
    incomparable native scores still merge deterministically.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    scores: dict[int, float] = {}
    first_seen: dict[int, ChunkHit] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            first_seen.setdefault(hit.chunk_id, hit)
    fused = sorted(
        first_seen.values(),
        key=lambda hit: (
            -scores[hit.chunk_id],
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
    return tuple(hit.model_copy(update={"score": scores[hit.chunk_id]}) for hit in fused[:k])
```

**What to look for in the code**

- Scores from different sub-questions are incomparable — same lesson as M2's dense-versus-lexical fusion, so the merge uses ranks only, with the same `rrf_k` damping.
- The tie-break is a full deterministic key, not dict order. Two runs over the same lists must produce the same fused ranking, or the evaluation in the next section measures noise.
- Fused hits are `model_copy` updates with the RRF score — the source hits stay frozen, per the M1 value-object rule.

### 3. The claim goes through the harness

#### Extend `app/agent/decompose.py` — a drop-in retriever

**Learning action — implement the retriever:** check its signature against M3's `Retriever` type before writing the body.

<!-- src: app/agent/decompose.py::make_decomposed_retriever -->
```python
def make_decomposed_retriever(
    session: AsyncSession,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
):
    """Return an M3-compatible ``Retriever`` that decomposes before retrieving.

    The callable signature matches ``evaluate_retriever``'s ``Retriever``
    contract exactly, so the decomposed strategy plugs into the existing
    evaluation harness without modifying any M3 file.
    """

    async def retrieve_decomposed(question: str, k: int) -> tuple[ChunkHit, ...]:
        sub_questions = await decompose_query(
            question,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        ranked_lists = []
        for sub_question in sub_questions:
            result = await retrieve(
                session,
                sub_question,
                provider=embedding_provider,
                k=k,
                candidate_k=candidate_k,
                filters=filters,
                rrf_k=rrf_k,
            )
            ranked_lists.append(result.hits)
        return merge_ranked_lists(tuple(ranked_lists), k, rrf_k=rrf_k)

    return retrieve_decomposed
```

#### Create `app/agent/eval.py` — per-category measurement

**Learning action — run the measurement:** the deliverable is two artifacts and a delta table, not a sentence saying it improved.

<!-- src: app/agent/eval.py::category_metrics,run_decomposition_comparison -->
```python
def category_metrics(evaluation: RetrievalEvaluation) -> dict[str, dict[str, float]]:
    """Return macro retrieval metrics per golden category, scored cases only.

    The suite-level score hides exactly the split this module exists to show:
    a decomposition change should move ``multi_hop`` without touching
    ``simple_lookup``. Absent cases stay excluded, mirroring M3's scoring rule.
    """
    grouped: dict[str, list[Any]] = {}
    for case in evaluation.cases:
        if case.score is None:
            continue
        grouped.setdefault(case.golden.category, []).append(case.score)
    metrics: dict[str, dict[str, float]] = {}
    for category in sorted(grouped):
        scores = grouped[category]
        count = len(scores)
        metrics[category] = {
            "scored_case_count": float(count),
            "recall_at_k": sum(score.recall_at_k for score in scores) / count,
            "hit_rate_at_k": sum(score.hit_at_k for score in scores) / count,
            "mrr": sum(score.reciprocal_rank for score in scores) / count,
        }
    return metrics


def _arm_payload(evaluation: RetrievalEvaluation) -> dict[str, Any]:
    return {
        "metrics": evaluation.metric_values(),
        "categories": category_metrics(evaluation),
    }


def _artifact_name(recorded_at: datetime, label: str) -> str:
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{label}.json"


async def run_decomposition_comparison(
    cases: Sequence[GoldenCase],
    *,
    baseline_retriever: Retriever,
    decomposed_retriever: Retriever,
    baseline_config: Mapping[str, Any],
    decomposed_config: Mapping[str, Any],
    suite: str,
    artifact_dir: str | Path,
    k: int = 5,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate both retrievers on one golden suite and write paired artifacts.

    Both arms run through the unmodified M3 harness, so their artifacts have
    the same schema as every other evaluation and remain comparable with the
    stored baselines. The returned payload adds the per-category split and the
    metric deltas the ablation narrative needs.
    """
    moment = recorded_at or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    baseline = await evaluate_retriever(
        cases,
        baseline_retriever,
        suite=suite,
        config=baseline_config,
        k=k,
        recorded_at=moment,
    )
    decomposed = await evaluate_retriever(
        cases,
        decomposed_retriever,
        suite=suite,
        config=decomposed_config,
        k=k,
        recorded_at=moment,
    )
    directory = Path(artifact_dir)
    baseline_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-baseline"),
        baseline,
    )
    decomposed_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-decomposed"),
        decomposed,
    )
    baseline_categories = category_metrics(baseline)
    decomposed_categories = category_metrics(decomposed)
    deltas = {
        category: {
            "recall_at_k": decomposed_categories[category]["recall_at_k"]
            - baseline_categories[category]["recall_at_k"],
            "mrr": decomposed_categories[category]["mrr"] - baseline_categories[category]["mrr"],
        }
        for category in sorted(set(baseline_categories) & set(decomposed_categories))
    }
    return {
        "suite": suite,
        "k": k,
        "baseline": _arm_payload(baseline),
        "decomposed": _arm_payload(decomposed),
        "category_deltas": deltas,
        "artifacts": {
            "baseline": str(baseline_path),
            "decomposed": str(decomposed_path),
        },
    }
```

**What to look for in the code**

- `make_decomposed_retriever` returns a plain callable matching M3's `Retriever` contract. **Not one line of `app/evals` changes: the harness was built to judge any retriever, and this is the payoff.**
- `category_metrics` slices per golden category and excludes unscored absent cases, exactly as the M3 aggregate does — a category average that quietly included unscored rows would be a different metric wearing the same name.
- `run_decomposition_comparison` runs baseline and decomposed retrievers over the same golden set and writes both artifacts plus per-category deltas. **The interesting number is the `multi_hop` delta against the flat overall delta — an improvement claim lives in that slice or nowhere.**

### Focused tests and the contract they keep

```bash
uv run pytest tests/agent/test_06_decompose.py -q
```

| What the test breaks | Contract it protects |
|---|---|
| A provider that raises mid-decomposition | The fallback returns the original question |
| Duplicate or empty sub-questions | The decomposition contract stays tight |
| Reordered input lists with tied ranks | Fusion is deterministic, rank-only |
| A category slice over unscored cases | Sliced metrics keep the M3 scoring rules |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why must decomposition failure return the original question?**
  - **Answer:** Fail-closed here means the baseline is the floor — the feature can add recall paths but can never do worse than not existing.
- **Why fuse with ranks instead of scores?**
  - **Answer:** Scores across differently-embedded sub-questions are incomparable, the same reason M2 refused to mix dense and lexical scores.
- **Why is "the M3 harness runs unmodified" the headline of this checkpoint?**
  - **Answer:** The claim is only credible because the judge predates the contestant; an evaluation adjusted to fit the feature proves nothing.

---

[← Previous: built-in tools](04-builtin-tools.md) · [Module overview](../03-build.md) · [Next: MCP and the CLI →](06-mcp-cli.md)
