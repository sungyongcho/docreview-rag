# M2.11 Tutorial 9 — Cross-encoder reranking

**Prerequisite:** Tutorial 8's `uv run pytest tests/retrieval/test_10_sbert.py -q` passes.

M2.6 built a reranking boundary and deliberately left it empty. Five checkpoints later the model that fills it is finally installed, so this is where the empty slot gets an occupant.

The model is the same family as M2.10's. What changes is where the query meets the document, and everything else in this chapter follows from that one difference.

## Files this checkpoint touches

| Action | Path | Role |
|---|---|---|
| Read only | `app/retrieval/rerank.py` | The `RerankProvider` and `rerank_hits` boundary M2.6 already built |
| Create | `app/retrieval/cross_encoder.py` | The lazily loaded cross-encoder provider |
| Modify | `app/retrieval/service.py` | Wires an optional reranker in to rescore the whole candidate list |
| Modify | `app/retrieval/__main__.py` | Adds `--rerank` and constructs the provider it passes through |
| Modify | `app/retrieval/__init__.py` | Exports `CrossEncoderReranker` on the public package surface |
| Verify | `tests/retrieval/test_11_cross_encoder.py` | Verifies the provider and its service and CLI wiring |

The diagrams and shell commands below are not copied into files. All three method blocks for `cross_encoder.py` belong inside the `CrossEncoderReranker` class, and the service code goes only into the separately marked `service.py` block.

## What the bi-encoder cannot do

M2.10 ended on the bi-encoder shape: each text passes through the model alone and the two results meet afterwards as vectors. That separation is what made the whole retrieval path affordable.

It is also a hard limit. **The model never sees the query and the document at the same time.** It compresses a chunk into 384 numbers without knowing what will be asked of it, and it compresses the question into 384 numbers without knowing what is stored. Whatever nuance depends on reading both together is gone before the comparison starts.

### Reading them together

A cross-encoder joins the two texts into a single input and runs the model once over the pair.

#### No file changes — comparing the bi-encoder and cross-encoder shapes

```text
bi-encoder (M2.3)
    query    ──> [model] ──> vector ─┐
                                     ├─> cosine similarity ─> score
    document ──> [model] ──> vector ─┘

cross-encoder (M2.11)
    query    ─┐
              ├─> [model] ──> score
    document ─┘
```

There is no vector to store. The output is a relevance score for that specific pair, produced by a model that read both halves with full attention between them.

|  | bi-encoder | cross-encoder |
|---|---|---|
| Model runs on | each text alone | the pair together |
| Result | a reusable vector | a score for one pair |
| Precompute documents | yes | **no** |
| Cost per query | one forward pass | **one per candidate** |
| Accuracy | lower | higher |

### Cost decides the order

Read the last two rows together, because they are the whole design.

A cross-encoder cannot precompute anything. Nothing about a document can be prepared in advance, because the score only exists once a query arrives. Scoring 9,172 chunks would mean 9,172 forward passes **per query**.

That is unaffordable, and it is why reranking never replaces retrieval. It runs after it.

#### No file changes — reading the two-stage retrieval flow

```text
stage 1   vector + lexical + RRF   9,172 chunks -> 20 candidates    cheap, wide
stage 2   cross-encoder            20 candidates -> 5 hits          expensive, narrow
```

**Two-stage retrieval exists because the accurate model is too expensive to run widely and the cheap model is too blunt to run alone.** Each stage covers the other's weakness. The first stage's job is recall: the second stage can only reorder what it is handed, so anything the first stage misses is lost for good.

## The boundary M2.6 left open

Nothing about `rerank.py` changes here. Go back and read it: `RerankProvider` declares one method, and its signature already assumes this chapter.

#### Read only `app/retrieval/rerank.py` — do not modify it

```python
async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
    """Return one relevance score per document in caller order."""
```

The query and the documents arrive **together**, in one call. A bi-encoder would never need that; it would embed the documents at index time and the query separately. **The shape of this method is a cross-encoder's shape**, decided in M2.6 before there was anything to put behind it.

That is what a provider boundary is for. The decision was made early, the implementation arrives late, and the code in between never learns which is which.

## Implementation

`app/retrieval/cross_encoder.py` is a new module for the same reason `sbert.py` was: `rerank.py` must stay importable with no backend installed, and a separate file makes that visible.

### 1. Construction and lazy loading

#### Create `app/retrieval/cross_encoder.py` — module header

```python
"""Cross-encoder reranking provider for the M2.6 boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence

from app.retrieval.rerank import RerankProvider
```

**What to look for in the code**

- The import list repeats M2.10's lesson: `sentence_transformers` is not on it, so `import app.retrieval` still needs no torch backend.
- `RerankProvider` is the only project import. The whole file exists to stand behind the boundary M2.6 drew, and the header already says so.

#### Modify `app/retrieval/cross_encoder.py` — `CrossEncoderReranker.__init__`

```python
def __init__(
    self,
    *,
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    batch_size: int = 32,
) -> None:
    if not model:
        raise ValueError("reranker model must be nonempty")
    if batch_size <= 0:
        raise ValueError("reranker batch size must be positive")
    self.model = model
    self.batch_size = batch_size
    self._encoder: object | None = None
```

**What to look for in the code**

- The default is trained on MS MARCO, a passage-ranking dataset of real search queries. That is the task being performed here, which is why a general-purpose model is not the default.
- There is no `dimensions` field, because there is no vector. The absence is the point: nothing this model produces gets stored.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "constructing or rejects_invalid"
```

- `test_constructing_reranker_loads_no_model`
- `test_reranker_rejects_invalid_construction`

### 2. Loading the model once, the first time it is needed

#### Modify `app/retrieval/cross_encoder.py` — `CrossEncoderReranker._load`

```python
def _load(self) -> object:
    """Import and construct the cross-encoder once, then reuse it."""
    if self._encoder is not None:
        return self._encoder

    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed; run one of "
            "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
        ) from exc

    self._encoder = CrossEncoder(self.model)
    return self._encoder
```

The `CrossEncoder` import sits inside the method for the same reason it did in M2.10. Importing the package or constructing the provider must not require an optional machine-learning dependency, and must not read model weights.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "missing_extra or constructs_the_model_once"
```

- `test_missing_extra_raises_an_actionable_runtime_error`
- `test_load_constructs_the_model_once`

### 3. Scores are logits

#### Modify `app/retrieval/cross_encoder.py` — `CrossEncoderReranker.score`

```python
async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
    """Score every query/document pair off the event loop, in caller order."""
    pairs = [(query, document) for document in documents]
    if not pairs:
        return []

    encoder = self._load()

    def _predict() -> list[float]:
        """Run the synchronous, CPU-bound forward passes in a worker thread."""
        return [float(value) for value in encoder.predict(pairs, batch_size=self.batch_size)]

    return await asyncio.to_thread(_predict)
```

**What to look for in the code**

- The default `cross-encoder/ms-marco-MiniLM-L-6-v2` returns raw logits: **not** probabilities, not bounded to any range, and frequently negative. That is a property of this model, not of cross-encoders in general — a model trained with a sigmoid head returns values in zero-to-one instead, and swapping one in must not require touching the boundary. M2.6's validator therefore requires only that each score is finite, and now you can see why constraining it to zero-to-one would have rejected the very provider this boundary was built for.
- `batch_size` does not change the amount of work. The model still runs one forward pass per candidate pair; batching only decides how many of those pairs cross into the model at a time. **The cost is set by how many candidates fusion handed over, which is why `candidate_k` and not `batch_size` is the knob that controls what reranking costs.**
- These scores are not comparable with cosine similarity or with BM25 either. A third incompatible scale is exactly what M2.5 anticipated by fusing ranks instead of values.
- `pairs` is built in caller order and `predict` preserves it, which is what the boundary promises. Reordering here would silently misalign every score with its hit.
- The forward passes go to a worker thread for the same reason M2.10's encoder did.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "score_preserves or empty_candidate"
```

- `test_score_preserves_pair_order_and_runs_predict_off_loop`
- `test_empty_candidate_list_does_not_load_a_model`

## Wiring it into the service

M2.7 composed one request and truncated the fused list to `k`. With a reranker there is a candidate pool to preserve.

In `app/retrieval/service.py`, import `RerankProvider` and `rerank_hits`, give `retrieve` the keyword-only parameter `reranker: RerankProvider | None = None`, and then replace the truncation point below.

#### Modify `app/retrieval/service.py` — `retrieve`

```python
fused = await hybrid_search(
    normalized_query,
    limit if reranker is not None else k,
    filters,
    vector_search=vector_component,
    lexical_search=lexical_component,
    candidate_k=limit,
    rrf_k=rrf_k,
)
if reranker is not None:
    fused = await rerank_hits(
        normalized_query,
        fused,
        provider=reranker,
        top_k=k,
    )
```

**What to look for in the code**

- Without a reranker, fusion truncates to `k` exactly as before. **M2.7's behaviour is not merely similar, it is identical**, which is what makes the reranker safe to leave off.
- With one, fusion keeps `limit` items and the reranker cuts to `k`. Handing the reranker only `k` items would let it reorder five hits it could never improve on, which is the most common way to build a reranker that does nothing.
- `rerank_hits` is called unchanged. The validation, the deterministic ordering, and the top-k truncation were all written in M2.6 and none of it is rewritten here.

Changing the service alone leaves no way to turn this path on from the command line. Give `app/retrieval/__main__.py` a `--rerank` flag, construct a `CrossEncoderReranker` when it is set, and pass it through as `retrieve(reranker=...)`. `app/retrieval/__init__.py` gains the import for the new class and its `__all__` entry.
- Component rankings still record what each retriever proposed, not what survived reranking. They describe retrieval, not the final answer.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "m27 or rescores or component_rankings or cli_accepts or public_surface"
```

- `test_no_reranker_keeps_the_m27_behaviour`
- `test_reranker_rescores_the_full_candidate_pool_then_truncates`
- `test_component_rankings_record_proposals_not_rerank_survivors`
- `test_cli_accepts_rerank_flag`
- `test_public_surface_exports_cross_encoder`

## Focused tests and the contracts they protect

#### Run `tests/retrieval/test_11_cross_encoder.py`

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A reranker handed `k` items instead of the pool | Reranking can actually change the outcome. |
| A result longer or shorter than `k` | The caller's limit is honoured. |
| Different output with and without a reranker set to `None` | M2.7's behaviour is preserved exactly. |
| Component rankings trimmed to the reranked survivors | Provenance describes retrieval, not the answer. |
| Scores constrained to a bounded range | Logits are valid provider output. |

The rule for moving on is simple: do not accept M2.11 if turning the reranker off changes any result, if the reranker sees fewer candidates than fusion produced, or if anything in `hybrid.py` or `rerank.py` had to be edited to attach it.

## Proving the boundary held

This is the claim M2.6 made and could not test. Run the acceptance path both ways.

#### Run — checking the search CLI with the reranker enabled

```bash
uv run python -m app.retrieval --query "NVDA 2024 R&D" --k 5 --rerank
```

An entire second model, with a different architecture and a different score scale, now participates in retrieval. Count what changed to allow it: two new files and one optional parameter. `hybrid.py`, `rerank.py`, `vector.py`, and `lexical.py` are untouched.

**Do not read a reordering as an improvement.** A different order is evidence that the reranker ran, nothing more. Whether it retrieves better on this corpus is a question for M3.4, which measures both arms against the golden set and picks the documented default from recall, MRR, and latency.

## What you should be able to explain now

- **Why can a cross-encoder not precompute anything?**
  - **Answer:** Its output is a score for one query-document pair, so nothing exists to compute until a query arrives.
- **Why does reranking run after retrieval instead of replacing it?**
  - **Answer:** It costs one forward pass per candidate, which is affordable on twenty items and not on 9,172.
- **What is the first stage responsible for that the second cannot fix?**
  - **Answer:** Recall. The reranker can only reorder what it is given, so anything retrieval missed stays missing.
- **Why would constraining provider scores to zero-to-one have been a mistake?**
  - **Answer:** Cross-encoders return unbounded logits that are often negative, so the range check would reject the intended provider.
- **Why does the reranker receive `candidate_k` items rather than `k`?**
  - **Answer:** Reranking only changes the outcome if it sees candidates that fusion would have discarded.
- **What did filling this boundary require changing elsewhere?**
  - **Answer:** Nothing. One optional parameter on the service, and no edit to fusion, reranking, or either retrieval path.

---

**Next:** M2 is complete. [Return to the build guide](../03-build.md), then start [M3 evaluation](../../m3-evals/00-README.md), where every arm built in this module is finally measured.
