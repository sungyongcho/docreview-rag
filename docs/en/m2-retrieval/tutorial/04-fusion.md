# M2.5–M2.6 Tutorial 4 — Rank fusion and optional reranking

**Prerequisite:** Tutorial 3's `uv run pytest tests/retrieval/test_04_lexical.py -q` passes. Both retrieval paths must exist before their ranks can be fused.

## M2.5 — Fuse ranks, not scores

It is time to combine the two result sets. The first idea that comes to mind is a weighted average of the scores.

#### No file changes — why a weighted score sum is wrong

```python
final = 0.7 * vector_score + 0.3 * lexical_score   # ❌
```

Why that is wrong is the heart of this step.

### The two scores were never in the same unit

| | Vector score | Lexical score |
|---|---|---|
| What it is | `1 - cosine distance` | `ts_rank_cd` cover density |
| Range | roughly 0–1 | unbounded above |
| Meaning | semantic similarity | how densely the query terms cluster in the document |
| Distribution | mostly bunched in 0.6–0.9 | scale varies per query |

These are not values you can place side by side and add. `0.7 * 0.85 + 0.3 * 4.2` produces a number and means nothing.

Would normalizing help? Min-max normalization makes **the same document's score depend on the result set for that query.** A ranking flips because one more document happened to match.

### RRF discards the scores entirely

Reciprocal Rank Fusion ignores scores and uses **rank only**.

#### No file changes — reading the RRF formula

```
chunk's final score = Σ  1 / (rrf_k + its rank in each list)
```

A chunk ranked 1st by vector and 3rd by lexical scores `1/(60+1) + 1/(60+3)`.

A rank means the same thing regardless of which retriever produced it. "First" is what that retriever judged best, and whatever internal unit backs that judgment is irrelevant. **Only comparable things get compared.**

The effect is intuitive too. **A chunk high in both lists wins.** The judgment that something ranked 3rd by both is more trustworthy than something ranked 1st by only one gets baked into the formula.

`rrf_k` (default 60) is the constant that softens the influence of the top of each list. A smaller value widens the gap between 1st and 2nd; a larger one flattens it. It, too, is subject to M3's experiments.

### What to define, what to implement, and what to inspect

M2.5 builds `app/retrieval/hybrid.py` in four steps. Note that this file imports no SQLAlchemy: fusion is pure computation over two lists.

| Area | Learning action | What to take away |
|---|---|---|
| Module header | **Define the structure** | Why the search functions arrive as a type, not an import |
| `_FusedHit` and `_unique_ranked_hits` | **Implement** the deduplication yourself | Why one list may contribute one rank per chunk |
| `rrf_fuse` | **Implement** the fusion loop yourself | Where the rank replaces the score |
| `hybrid_search` | **Write the structure, then inspect the call order** | Why the two searches are awaited sequentially |

### 1. Module header

#### Create `app/retrieval/hybrid.py` — module header

**Learning action — define the structure:** the import list is the point. Nothing here knows about a database.

```python
"""Rank-only reciprocal rank fusion and thin hybrid orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.retrieval.types import ChunkHit, RetrievalFilters, sort_hits

DEFAULT_RRF_K = 60

SearchCallable = Callable[[str, int, RetrievalFilters], Awaitable[list[ChunkHit]]]
```

**What to look for in the code**

- Neither `vector_search` nor `lexical_search` is imported. `SearchCallable` describes their shape instead, so fusion can be tested with two plain lists and no database.
- `DEFAULT_RRF_K = 60` is a named constant, not a literal buried in the formula. M3 will vary it, and a value that has to be tuned needs a name.

### 2. One list contributes one rank per chunk

Deduplication sounds like defensive tidying. It is load-bearing.

Follow what happens without it. Suppose a component list contains chunk 500 twice — a lexical query that matched it through two different code paths, or a bug upstream that nobody has noticed yet. Ranks are assigned by position, so that chunk collects `1/(60+2)` *and* `1/(60+7)`. It now scores higher than a chunk genuinely ranked 1st by the other retriever.

A duplicate has outvoted a real result, and the fused ranking is wrong in a way that looks entirely reasonable from the outside.

#### Extend `app/retrieval/hybrid.py` — the fusion accumulator

**Learning action — implement the deduplication:** write `_unique_ranked_hits` yourself and work out what breaks without it.

<!-- src: app/retrieval/hybrid.py::_FusedHit,_unique_ranked_hits -->
```python
@dataclass(slots=True)
class _FusedHit:
    hit: ChunkHit
    score: float = 0.0


def _unique_ranked_hits(hits: Sequence[ChunkHit]) -> list[ChunkHit]:
    """Keep the first occurrence of each chunk so one list contributes one rank."""
    seen: set[int] = set()
    unique: list[ChunkHit] = []
    for hit in hits:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            unique.append(hit)
    return unique
```

- `_FusedHit` is deliberately **not** frozen, unlike every other record in this project. It is a short-lived accumulator whose `score` is added to in a loop.
- Deduplication happens **before** ranks are assigned. A duplicate inside one component list would otherwise take two rank positions and contribute twice, letting an accidental repeat outvote a genuinely well-ranked chunk.
- The first occurrence wins, which preserves the component retriever's ordering.

### 3. The fusion, where rank replaces score

#### Extend `app/retrieval/hybrid.py` — reciprocal rank fusion

**Learning action — implement the fusion loop:** write the accumulation yourself. Check that no incoming `score` is ever read.

<!-- src: app/retrieval/hybrid.py::rrf_fuse -->
```python
def rrf_fuse(
    vector_hits: Sequence[ChunkHit],
    lexical_hits: Sequence[ChunkHit],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Fuse ranked lists by reciprocal rank, keyed by database ``chunk_id``.

    Source scores are intentionally ignored because vector similarity and PostgreSQL
    FTS cover-density scores have unrelated scales. Each list contributes
    ``1 / (rrf_k + rank)`` once per chunk, where rank is one-based.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused: dict[int, _FusedHit] = {}
    for ranking in (vector_hits, lexical_hits):
        for rank, hit in enumerate(_unique_ranked_hits(ranking), start=1):
            contribution = 1.0 / (rrf_k + rank)
            entry = fused.get(hit.chunk_id)
            if entry is None:
                fused[hit.chunk_id] = _FusedHit(hit=hit, score=contribution)
            else:
                entry.score += contribution

    hits = [entry.hit.model_copy(update={"score": entry.score}) for entry in fused.values()]
    return sort_hits(hits)[:k]
```

**What to look for in the code**

- The incoming `hit.score` is never read. Only the position from `enumerate` matters, and that is the entire argument of this step expressed as code.
- `start=1` makes ranks one-based. With zero-based ranks the top hit would contribute `1/rrf_k` and the formula would no longer match the published definition.
- The accumulator is keyed by `chunk_id`, not by object identity. The same chunk arrives as two separate `ChunkHit` instances from the two paths.
- `model_copy(update={"score": ...})` replaces the score on a frozen model without mutating it. The rest of the evidence is carried through untouched.
- `sort_hits` runs only after every contribution is summed, and it brings M2.1's tie-breakers along, so equal RRF sums still order deterministically.
- Truncation to `[:k]` happens last. Cutting earlier would drop a chunk that a second list's contribution would have lifted into the top k.

### 4. Orchestration thin enough to test

The last function in this file does almost nothing, and that is deliberate.

It takes two callables, awaits them, and hands the results to `rrf_fuse`. It does not know what a session is, what an embedder is, or how a vector query gets prepared. All of that lives in M2.7's adapters, which close over whatever they need.

The payoff is that the fusion logic — the part with an actual algorithm in it — can be tested by passing two plain lists. No database, no fixtures, no mocks of an ORM. When a ranking comes out wrong, the test that fails points at arithmetic rather than at infrastructure.

#### Complete `app/retrieval/hybrid.py` — hybrid orchestration

**Learning action — write the structure, then inspect the call order:** the guards are mechanical. The two `await` lines carry the decision.

<!-- src: app/retrieval/hybrid.py::hybrid_search -->
```python
async def hybrid_search(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    vector_search: SearchCallable,
    lexical_search: SearchCallable,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Retrieve two candidate lists and combine them with rank-only RRF.

    Injected callables let the production adapter close over its session, embedder,
    and vector query preparation. Calls are awaited sequentially so both adapters may
    safely share one SQLAlchemy ``AsyncSession``.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    limit = candidate_k if candidate_k is not None else k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    active_filters = filters or RetrievalFilters()

    vector_hits = await vector_search(query, limit, active_filters)
    lexical_hits = await lexical_search(query, limit, active_filters)
    return rrf_fuse(vector_hits, lexical_hits, k, rrf_k=rrf_k)
```

**What to look for in the code**

- The two searches are awaited **one after another**, not gathered concurrently. An `AsyncSession` is not safe for concurrent use, and both adapters typically close over the same one. Reaching for `asyncio.gather` here is the tempting bug.
- `candidate_k` lets each path return more candidates than the final `k`. Fusion works better with deeper lists, and `limit < k` is rejected because it would make the final truncation meaningless.
- The same `active_filters` object goes to both paths, so the two searches provably see one document set — and it is frozen, so neither adapter can alter it.
- Both searches run with no knowledge of each other. That is what makes reranking, in M2.6, a layer that can be added without touching this function.

Writing this much completes `app/retrieval/hybrid.py`. The four blocks concatenated in order are the checkpoint file itself.

The path, then:

#### No file changes — reading the fusion path end to end

```
ordered vector hits + ordered lexical hits → per-list deduplication → one-based ranks → RRF contributions → sum by chunk_id → stable top-k ChunkHit list
```

### Focused tests and the contracts they protect

#### Run `tests/retrieval/test_05_hybrid.py`

```bash
uv run pytest tests/retrieval/test_05_hybrid.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A duplicate chunk inside one component list | One list contributes one rank per chunk. |
| Zero-based instead of one-based ranks | The formula matches the published definition. |
| A native score fed into the formula | Incomparable units never get compared. |
| Chunks tied on the fused sum | Ordering stays deterministic across runs. |
| Truncation applied before fusion | A chunk lifted by the second list survives. |
| Concurrent component calls | One `AsyncSession` is never used concurrently. |

A clean pass means all hybrid tests pass for duplicate handling, one-based ranks, deterministic ties, top-k truncation, and component call order.

The rule for moving on is simple: do not accept M2.5 if native scores enter the RRF formula or a duplicate can contribute twice within one component list.

When it fails, print ranks, not scores. Deduplicate before `enumerate(..., start=1)`, key the accumulator by `chunk_id`, and apply `sort_hits` only after all contributions are summed.

### What you should be able to explain now

- **Why does a weighted average of the two scores mean nothing?**
  - **Answer:** Cosine similarity and `ts_rank_cd` use different scales and units, so a numeric weight cannot make their values semantically comparable.
- **What problem does min-max normalization introduce that RRF does not have?**
  - **Answer:** A document's normalized score changes when the result set or an outlier changes, even if that document's native score does not. RRF depends only on rank positions.
- **What would break if deduplication ran after ranks were assigned?**
  - **Answer:** A duplicate would consume multiple rank positions and contribute more than once, allowing an accidental repeat to outvote a genuinely strong chunk.
- **Why must truncation to `k` come after fusion rather than before?**
  - **Answer:** A candidate that is moderately high in both deeper lists may deserve the final top k; cutting each list first can discard it before those two signals combine.
- **Why are the two component searches not run concurrently?**
  - **Answer:** Both adapters normally share one `AsyncSession`, which is unsafe to use concurrently.

## M2.6 — Build reranking, but leave it off

Cross-encoder reranking is a standard way to lift RAG performance. Feeding the query and the document into a model **together** is more accurate than embedding each and comparing.

It costs something.

- one model call per candidate, so it is **slow**
- hundreds of megabytes of dependency for a local model, or **money** for an API
- and above all, **nobody knows yet whether it actually helps**

The last one is the point. "Cross-encoders are good" is generally true, but how much it helps **on this corpus for these question types** has to be measured.

So M2 **defines the boundary only and leaves the default off.** Just the `RerankProvider` abstract class and a helper that passes candidates through untouched when no provider is configured.

M3 attaches a real provider and compares it as an ablation arm. That produces numbers for how much recall rises and how much latency grows, and those numbers decide whether it goes on.

**Not switching on a "known-good technique" without measurement** is this project's habit. It is the same reason HNSW was deferred in M2.3.

### What to define, what to implement, and what to inspect

M2.6 builds `app/retrieval/rerank.py` in four steps. It is the smallest file in the module and the one whose *absent* path matters most.

| Area | Learning action | What to take away |
|---|---|---|
| Module header | **Define the structure** | Why no model library is imported |
| `RerankProvider` | **Review the design decision** | What a boundary with no implementation buys |
| `_scores` | **Implement** the score validation yourself | Why a reranker's output needs the same guards as an embedder's |
| `rerank_hits` | **Implement** the pass-through branch yourself | Why on and off must share one code path |

### 1. Module header

#### Create `app/retrieval/rerank.py` — module header

**Learning action — define the structure:** the docstring says "dependency-free," and the imports prove it.

```python
"""Optional async reranking behind a dependency-free provider boundary."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
import math
from numbers import Real

from app.retrieval.types import ChunkHit, sort_hits
```

**What to look for in the code**

- No model library, no HTTP client, no `torch`. Declaring the boundary costs the project nothing in dependencies, which is what makes "build it but leave it off" cheap.

### 2. The boundary with no implementation

#### Extend `app/retrieval/rerank.py` — the provider boundary

**Learning action — review the design decision:** one abstract method. Ask what its signature already commits the project to.

The answer is that it commits to a cross-encoder, which is filled in at M2.11 in [Tutorial 9](09-cross-encoder.md). Leaving it empty here is what lets that arrival cost one optional parameter.

<!-- src: app/retrieval/rerank.py::RerankProvider -->
```python
class RerankProvider(ABC):
    """Provider boundary for scoring query/document pairs."""

    @abstractmethod
    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Return one relevance score per document in caller order."""
```

**What to look for in the code**

- `Sequence[float]` is the static contract for valid provider output. Below it, `_scores` still runs its `Real` check as runtime validation of the values actually returned.
- `score` takes the whole batch, not one document. A per-document signature would force N sequential round trips on any provider that supports batching.
- "in caller order" is the contract that makes the result usable without an id. The provider never sees a `chunk_id`, so position is the only correspondence.
- The method is `async` even though no implementation exists yet. Making it synchronous now would force every future API-backed provider to block the event loop.

### 3. Validating what a reranker returns

#### Extend `app/retrieval/rerank.py` — score validation

**Learning action — implement the score validation:** the shape echoes M2.2's `validate_embeddings`. Write it and note what is *not* checked.

<!-- src: app/retrieval/rerank.py::_scores -->
```python
def _scores(values: Sequence[float], *, expected_count: int) -> list[float]:
    """Validate provider scores before replacing immutable hit scores."""
    if len(values) != expected_count:
        raise ValueError(f"reranker returned {len(values)} scores for {expected_count} hits")
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("reranker returned a nonnumeric score")
        score = float(value)
        if not math.isfinite(score):
            raise ValueError("reranker returned a non-finite score")
        scores.append(score)
    return scores
```

**What to look for in the code**

- No range is enforced. A cross-encoder may return logits of any magnitude, and M2.1's `Score` type only requires finiteness. Constraining to 0–1 here would reject valid providers.
- The count check is what protects the positional contract from step 2. A provider that drops one score would otherwise shift every subsequent hit onto the wrong document.
- The `bool` and `math.isfinite` rejections repeat M2.2 because a NaN score would make `sort_hits` non-deterministic rather than fail.

### 4. On and off through one code path

This function has one branch that does nothing, and that branch is the reason the file exists.

Think about what M3 is going to ask: *does reranking help?* Answering it means running the pipeline twice and comparing. Which only works if the two runs differ in exactly one respect — whether a provider was attached.

The tempting shortcut is to skip this function entirely when reranking is off. But `rerank_hits` also sorts and truncates. Skip it and the off-run is missing a `sort_hits` call the on-run performed, so the two results now differ in tie order as well as in scoring. The measured gap includes that difference, and no one can tell how much.

An experiment is only as good as its control. The `provider is None` branch is the control.

#### Complete `app/retrieval/rerank.py` — optional rescoring

**Learning action — implement the pass-through branch:** write the guards and both branches. The `provider is None` branch is the one that protects M3's measurement.

<!-- src: app/retrieval/rerank.py::rerank_hits -->
```python
async def rerank_hits(
    query: str,
    hits: Sequence[ChunkHit],
    *,
    provider: RerankProvider | None = None,
    top_k: int = 5,
) -> list[ChunkHit]:
    """Optionally rescore top candidates and return deterministic top-k hits."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("rerank query must be nonempty")
    if top_k < 0:
        raise ValueError("rerank top_k must not be negative")
    if top_k == 0 or not hits:
        return []
    if provider is None:
        return sort_hits(hits)[:top_k]

    scores = _scores(
        await provider.score(query, [hit.index_text for hit in hits]),
        expected_count=len(hits),
    )
    rescored = [
        hit.model_copy(update={"score": score}) for hit, score in zip(hits, scores, strict=True)
    ]
    return sort_hits(rescored)[:top_k]
```

**What to look for in the code**

- Both branches end in `sort_hits(...)[:top_k]`. Reranking off and reranking on traverse **the same code path**, so the difference between two results is entirely the effect of reranking. Take a different function when it is off and M3's comparison is contaminated.
- The provider receives `index_text`, not `body`. It must judge the same text the retrieval matched, or its score would be about something the ranking never saw.
- `model_copy` again replaces the score on a frozen model, leaving all provenance intact — reranking changes order, never evidence.
- `strict=True` on `zip` is a second guard behind the count check in `_scores`, since a silent length mismatch here would misattribute scores.

Writing this much completes `app/retrieval/rerank.py`. The four blocks concatenated in order are the checkpoint file itself.

The path, then:

#### No file changes — reading the optional rerank path

```
query + candidate index_text  ──▶ RerankProvider present ──▶ validated scores ──▶ reordered top-k
                              └─▶ absent ──────────────────────────────────────▶ top-k unchanged
```

### Focused tests and the contracts they protect

#### Run `tests/retrieval/test_06_rerank.py`

```bash
uv run pytest tests/retrieval/test_06_rerank.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A blank or non-string query | A reranker is never asked to score nothing. |
| A score count unlike the candidate count | Scores stay attached to the right documents. |
| A NaN or boolean score | Ordering cannot become non-deterministic. |
| Partial evidence text sent to the provider | The reranker judges the text retrieval matched. |
| Results with no provider configured | The off path is identical to the unreranked baseline. |

A clean pass means all rerank tests pass for input validation, one score per candidate, finiteness, stable ties, and no-provider behavior.

The rule for moving on is simple: do not accept M2.6 if the provider sees partial evidence text, returns a different score count, or changes results when no provider is configured.

When it fails, verify the provider receives `index_text` in candidate order. Reject non-numeric, non-finite, or count-mismatched results before constructing updated hits.

### What you should be able to explain now

- **Why is the boundary built now when nothing implements it?**
  - **Answer:** It fixes a dependency-free, replaceable interface without coupling the default path to a model library. The current M3 matrix has no reranking arm, but the interface leaves a clean extension point for a future experiment.
- **Why does `score` take a batch rather than one document?**
  - **Answer:** A batch-capable provider can score all candidates in one round trip; a one-document signature would force N sequential calls.
- **Why is no range enforced on a reranker's scores?**
  - **Answer:** Valid rerankers may return logits of any magnitude, so the contract requires only the correct count and finite numeric values.
- **What would a separate off-path do to M3's ablation comparison?**
  - **Answer:** The current M3 ablation has no reranking arm, so that comparison does not exist yet. In a future reranking ablation, a separate off-path could also change sorting or truncation unless both arms share that path, contaminating the measured effect.
- **Why does the provider receive `index_text` rather than `body`?**
  - **Answer:** It must judge the same context-enriched text that retrieval matched; scoring only `body` would evaluate different evidence.

---

[← Previous: Retrieval paths](03-retrieval-paths.md) · [Module overview](../03-build.md) · [Next →: Service](05-service.md)
