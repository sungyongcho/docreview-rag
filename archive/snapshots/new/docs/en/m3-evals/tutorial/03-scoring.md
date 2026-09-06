# M3.2 Tutorial 3 — How is "correct" decided?

Tutorial 2 ended with verified answer spans: the golden loader hands over coordinates it byte-verified against the exact raw-source snapshot they cite, and the retrieval layer hands over scored chunks carrying coordinates of their own. What no layer has said yet is when a chunk counts as having *found* an answer — and the two ranges will almost never match exactly.

A real pair from the committed evaluation artifact: case `m3c-24` has a golden span of 58 characters at `[517875, 517933)`, and the top-ranked chunk covers `[516437, 518187)` — 1,750 characters that contain the answer completely. Is that a hit? What about a chunk that only grazes the last few characters of an answer? Without a fixed rule, every evaluation table becomes an argument about "close enough", and a wrong rule silently distorts every number the later layers — regression comparison, ablation — inherit from this one.

So this tutorial defines the rule once, as pure functions, with one invariant: the same golden spans, the same hits, and the same `k` must produce the identical score on every run, byte for byte — no database, no clock, no randomness anywhere in the computation.

**Prerequisite:** Tutorial 2's `uv run pytest tests/evals/test_02_loader.py -q` passes.

### IoU quantifies the overlap

**IoU (Intersection over Union)** — intersection divided by union — is used. The same metric object detection uses.

```
IoU = overlapping length / (answer length + chunk length - overlapping length)
```

> **Concept — why the union is the denominator**
>
> IoU is a general agreement score for two regions, borrowed from computer-vision evaluation; here both regions are half-open character intervals. The denominator is the union — every character covered by at least one of the two intervals — so the value reads as the fraction of all touched text that both intervals agree on. That choice of denominator makes the penalty symmetric: an interval that is too narrow gives up intersection, one that sprawls too wide inflates the union, and either error pushes the ratio down. Nothing in the formula favors the golden side or the hit side — swap the two intervals and the value is identical.
>
> Applied to character spans, the same symmetry has a consequence to know up front: a chunk that fully contains the answer still scores low when the chunk is much larger than the answer, because the oversized chunk inflates the union. Under full containment the formula collapses to answer length divided by chunk length, so a threshold of 0.05 accepts a fully containing chunk only up to 20 times the answer's size.

The threshold is `IoU >= 0.05`, and the committed evaluation artifact shows why it has to sit that low. In `data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json` — recorded by the evaluation run of tutorial 7 against an isolated temporary PostgreSQL and committed to the repository as the raw evidence that later tutorials and regression baselines read — the golden answer spans have a median width of 453 characters (the shortest is 58), while the retrieved text chunks have a median width of 1,549 characters. Size mismatch is the normal case, not the exception.

Case `m3c-24` makes the consequence concrete. Its top-ranked chunk spans `[516437, 518187)` — 1,750 characters — and fully contains both golden answers, one 111 characters long and one 58. The 111-character span scores 111/1750 = 0.0634 and passes; the 58-character span scores 58/1750 = 0.0331 and fails. **The same chunk holds both answers in full, and the case records recall 0.5 — the metric halved the score on answer length alone.**

```bash
python3 -c "import json; c=[x for x in json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json'))['cases'] if x['golden']['id']=='m3c-24'][0]; h=c['hits'][0]; print('hit width :', h['end_char']-h['start_char']); print('gold widths:', [a['end_char']-a['start_char'] for a in c['golden']['answers']]); print('case score :', c['score'])"
```

Table chunks push the mismatch further. The rank-5 hit of case `m3c-28` is a table chunk 12,860 characters wide, and at that width the threshold is already decided before any question of content: even if the case's 639-character golden span had fallen entirely inside this chunk, the IoU would be 639/12860 = 0.0497 — full containment, still under the threshold. In the committed artifact the case in fact scores zero, because both of its golden spans sit at other coordinates in the filing. **And 0.05 is not an empirically tuned value.** No measurement in this repository derives it; it is a deliberately low bar chosen to admit most fully containing text chunks, and its sharp edges show up in measurements like the two cases above.

And **intervals that merely touch count as not overlapping.** `[100, 200)` and `[200, 300)` are half-open and share no character at all, so an `overlap == 0` returns 0.0.

### Why the hash is checked first

`span_iou`'s first line compares `doc_id` and `source_sha256`, before any coordinate math.

That different documents are unrelated even at identical coordinates is obvious. Checking the **hash** is the important part.

The same `doc_id` with a different hash means that chunk was **built from a different snapshot** — the filing was refetched, the bytes changed, and old chunks linger in the database. The coordinate numbers may coincidentally overlap while **the text they point at differs.**

Count that as relevant and the evaluation score is quietly inflated. So it is cut to 0.0 outright.

### Three metrics answer three different questions

| Metric | Question |
|---|---|
| **Recall@k** | how many of the answer spans were found |
| **Hit Rate@k** | was there **any** relevant result |
| **MRR** | at what rank was the first relevant result |

Recall counts **unique** gold spans. Retrieving three chunks that cover the same answer must not triple recall, or a trick appears where cutting chunks smaller raises the score.

> **Concept — macro average versus micro average**
>
> There are two defensible ways to average a suite. The macro average scores each case first and then averages the case scores, so every question weighs the same. The micro average pools all answer spans into one pot and divides spans found by spans total, so every span weighs the same — which means a question backed by many answer spans weighs proportionally more.
>
> Neither is wrong; they answer different questions. Macro asks how a typical question fares, micro asks how much of the required evidence is found overall. This suite treats a case as one question no matter how many spans back it, so it macro-averages.

The macro choice also fixes the metric's grain, and the grain is far coarser than the printed digits. The committed suite scores 24 cases — 14 with one answer span, 10 with two — so one span flipping between found and missed moves suite recall by at least 0.5/24 ≈ 0.0208. The ablation tables print six decimal places, but at this suite size any difference below about 0.02 is noise: one span in one case, nothing more.

### Why there is no I/O in this layer

`scoring.py` has no database, no provider call, no clock, no file reads. **Only pure functions.**

That is a deliberate constraint, and a counterexample makes it concrete. Suppose the scorer re-read chunk text from the database instead of trusting the coordinates in the hits it was handed. Then a score that moved between two runs could mean the retriever ranked differently — or that a re-seed changed the rows behind the same ids. Two causes, one number, and no way to decide from the score alone. Because the scorer is a pure function of golden spans, hits, and `k`, a changed score has exactly one possible source: its inputs changed.

**The measuring instrument itself has to be simpler and more deterministic than the thing it measures.**

### What to define, what to implement, and what to inspect

`app/evals/scoring.py` is built in four steps. The whole file is pure functions, so all of it is testable with no database.

| Area | Learning action | What to take away |
|---|---|---|
| `CaseScore` and `SuiteScore` | **Write the record declarations** | What evidence must travel with a score |
| `span_iou` | **Implement** the overlap calculation yourself | The hash gate and what half-open means |
| `score_case` | **Implement** the recall rule yourself | How duplicates are stopped from inflating a score |
| The aggregation functions | **Implement** the macro average yourself | What makes each case weigh the same |

### 1. Module header and threshold

#### Create `app/evals/scoring.py` — module header

**Learning action — define the structure:** note that the imports are only M3's `GoldenSpan` and M2's `ChunkHit`.

```python
"""Deterministic span-overlap scoring for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.evals.types import GoldenSpan
from app.retrieval.types import ChunkHit

IOU_THRESHOLD: Final[float] = 0.05
```

**What to look for in the code**

- `IOU_THRESHOLD` is a module constant declared `Final`, not an inline literal, so the rule is at least visible and greppable. Be honest about what that does not buy: the threshold is recorded nowhere in the experiment config that runs carry, and the regression baseline matcher pairs runs by suite and config alone. Change this constant and old and new runs would still be paired as comparable — falsely, because the measuring instrument changed between them. That is a known sharp edge of the current code, worth knowing before trusting any cross-run comparison.
- There are only two imports: the ground-truth type and the retrieval-result type. This file does nothing except hold those two against each other.

`ChunkHit` deserves a recap here, because this file consumes it without ever showing its definition. It is the retrieval layer's validated result model — a pydantic class in `app/retrieval/types.py` — carrying citation text, body, and score for reporting. Scoring reads none of that. It touches exactly four identity fields — `doc_id`, `source_sha256`, `start_char`, `end_char` — plus the order of the hits list, and `GoldenSpan` carries the same four fields. Everything the verdict depends on lives in coordinates and provenance, nothing in text.

### 2. The evidence that travels with a score

#### Extend `app/evals/scoring.py` — result records

**Learning action — write the record declarations:** note what `CaseScore` carries beyond the three metrics.

<!-- src: app/evals/scoring.py::CaseScore,SuiteScore -->
```python
@dataclass(frozen=True, slots=True)
class CaseScore:
    """Retrieval metrics and matching provenance for one positive golden case."""

    case_id: str
    k: int
    gold_span_count: int
    matched_gold_count: int
    recall_at_k: float
    hit_at_k: float
    reciprocal_rank: float
    first_relevant_rank: int | None


@dataclass(frozen=True, slots=True)
class SuiteScore:
    """Macro-averaged retrieval metrics plus deterministic per-case results."""

    k: int
    case_count: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float
    cases: tuple[CaseScore, ...]
```

**What to look for in the code**

- `gold_span_count` and `matched_gold_count` are stored **alongside** recall. A recall of 0.5 alone cannot say whether that is 1/2 or 5/10, and in diagnosis that difference is everything.
- `first_relevant_rank` is `int | None`. With no relevant result the rank is not 0 — it is **absent**. Flattening it to 0 makes it indistinguishable from "it was ranked first."
- `SuiteScore` carries the whole `cases` tuple. Keeping only aggregate scores makes it impossible to trace which question dragged them down.

> **Concept — why pydantic there but a dataclass here**
>
> The retrieval types are pydantic models because they stand at a trust boundary: rows from the database and JSON from artifacts are outside input, and every field must be validated before the rest of the code may rely on it. That validation costs work on every construction, and at a boundary the cost is worth paying.
>
> A score record has no such boundary. It is produced in-process, by this module, from values that were already validated on the way in. A frozen, slotted dataclass gives what is actually needed — immutability, low memory, value equality — without re-validating trusted values. Reaching for the heavier tool here would buy nothing.

### 3. Overlap calculation and the hash gate

#### Extend `app/evals/scoring.py` — IoU calculation

**Learning action — implement the overlap calculation:** write the two guard lines first, then implement intersection and union yourself.

<!-- src: app/evals/scoring.py::_validate_k,span_iou -->
```python
def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")


def _span_identity(span: GoldenSpan) -> tuple[str, str, int, int]:
    return (
        span.doc_id,
        span.source_sha256,
        span.start_char,
        span.end_char,
    )


def span_iou(golden: GoldenSpan, hit: ChunkHit) -> float:
    """Return half-open span IoU after exact document-snapshot matching.

    Touching boundaries have zero overlap. A stale hit from another source snapshot
    is never relevant even if its document id and numeric offsets happen to match.
    """
    if golden.doc_id != hit.doc_id or golden.source_sha256 != hit.source_sha256:
        return 0.0

    # IoU = overlapping length / (answer length + chunk length - overlapping length)
    overlap = max(
        0,
        min(golden.end_char, hit.end_char) - max(golden.start_char, hit.start_char),
    )
    if overlap == 0:
        return 0.0
    union = (golden.end_char - golden.start_char) + (hit.end_char - hit.start_char) - overlap
    return overlap / union
```

**What to look for in the code**

- The hash comparison comes **before any coordinate arithmetic**. A chunk from another snapshot is not worth computing.
- `max(0, min(ends) - max(starts))` clamps negative overlap to zero. Two disjoint intervals produce a negative value there, and leaving it would corrupt the union.
- `overlap == 0` gets its own early return. Without it a touching interval would still yield 0/union = 0.0, but writing the intent into the code is better.
- `_validate_k` rejects `isinstance(k, bool)` first. `True` is a subtype of `int`, so `k=True` would quietly behave as `k=1`.

### 4. Stopping duplicates from inflating the score

#### Extend `app/evals/scoring.py` — case scoring

**Learning action — implement the recall rule:** you should be able to say why `matched_gold` is collected as a set.

<!-- src: app/evals/scoring.py::_is_relevant,score_case -->
```python
def _is_relevant(golden: GoldenSpan, hit: ChunkHit) -> bool:
    return span_iou(golden, hit) >= IOU_THRESHOLD


def score_case(
    case_id: str,
    golden_spans: Sequence[GoldenSpan],
    retrieved_hits: Sequence[ChunkHit],
    k: int,
) -> CaseScore:
    """Score the top-k hits for one positive golden case.

    Recall counts unique gold spans covered. Duplicate retrieved hits cannot count
    one gold span twice, while one broad hit may cover multiple distinct gold spans
    when it independently reaches the IoU threshold for each.
    """
    _validate_k(k)
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must not be blank")
    if not golden_spans:
        raise ValueError("golden_spans must not be empty; exclude absent cases")

    identities = [_span_identity(span) for span in golden_spans]
    if len(identities) != len(set(identities)):
        raise ValueError("golden_spans must be unique")

    top_hits = retrieved_hits[:k]
    matched_gold = {
        index
        for index, golden in enumerate(golden_spans)
        if any(_is_relevant(golden, hit) for hit in top_hits)
    }
    first_relevant_rank = next(
        (
            rank
            for rank, hit in enumerate(top_hits, start=1)
            if any(_is_relevant(golden, hit) for golden in golden_spans)
        ),
        None,
    )
    matched_count = len(matched_gold)
    recall = matched_count / len(golden_spans)
    hit_at_k = float(bool(matched_count))
    reciprocal_rank = 1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
    return CaseScore(
        case_id=case_id,
        k=k,
        gold_span_count=len(golden_spans),
        matched_gold_count=matched_count,
        recall_at_k=recall,
        hit_at_k=hit_at_k,
        reciprocal_rank=reciprocal_rank,
        first_relevant_rank=first_relevant_rank,
    )
```

**What to look for in the code**

- `matched_gold` is a **set of gold-span indices**. It counts ground truth, not retrieval results. So three chunks covering the same answer raise recall only once.
- The opposite direction is allowed. One broad chunk covering two distinct gold spans, each independently above threshold, counts for both. It genuinely did find both.
- Empty `golden_spans` is rejected. An absent case arriving here makes the recall denominator zero — a crash, or worse, a count of 0 that aggregates as retrieval failure. M3.1's separation is enforced here.
- `first_relevant_rank` counts from 1 via `enumerate(top_hits, start=1)`, because MRR is defined one-based.

### 5. Weighing every case the same

#### Complete `app/evals/scoring.py` — aggregation

**Learning action — implement the macro average:** note why all four aggregation functions call `_validated_scores` first.

<!-- src: app/evals/scoring.py::_validated_scores,score_suite -->
```python
def _validated_scores(case_scores: Sequence[CaseScore]) -> tuple[CaseScore, ...]:
    if not case_scores:
        raise ValueError("case_scores must not be empty")

    ordered = tuple(sorted(case_scores, key=lambda result: result.case_id))
    if len({result.case_id for result in ordered}) != len(ordered):
        raise ValueError("case_ids must be unique")
    if len({result.k for result in ordered}) != 1:
        raise ValueError("all case scores must use the same k")
    return ordered


def recall_at_k(case_scores: Sequence[CaseScore]) -> float:
    """Return macro recall across a nonempty suite of positive cases."""
    scores = _validated_scores(case_scores)
    return sum(result.recall_at_k for result in scores) / len(scores)


def hit_rate_at_k(case_scores: Sequence[CaseScore]) -> float:
    """Return the fraction of positive cases with at least one relevant top-k hit."""
    scores = _validated_scores(case_scores)
    return sum(result.hit_at_k for result in scores) / len(scores)


def mrr(case_scores: Sequence[CaseScore]) -> float:
    """Return mean reciprocal rank of the first relevant top-k hit per case."""
    scores = _validated_scores(case_scores)
    return sum(result.reciprocal_rank for result in scores) / len(scores)


def mean_reciprocal_rank(case_scores: Sequence[CaseScore]) -> float:
    """Return MRR using its unabbreviated public name."""
    return mrr(case_scores)


def score_suite(case_scores: Sequence[CaseScore]) -> SuiteScore:
    """Aggregate one nonempty, single-k suite in deterministic case-id order."""
    scores = _validated_scores(case_scores)
    return SuiteScore(
        k=scores[0].k,
        case_count=len(scores),
        recall_at_k=sum(result.recall_at_k for result in scores) / len(scores),
        hit_rate_at_k=sum(result.hit_at_k for result in scores) / len(scores),
        mrr=sum(result.reciprocal_rank for result in scores) / len(scores),
        cases=scores,
    )
```

**What to look for in the code**

- `_validated_scores` sorts by `case_id`. Whatever order the input arrives in, `SuiteScore.cases` comes out in the same order, so two runs compare directly.
- It checks that `k` is uniform. Averaging cases scored at k=5 with cases scored at k=10 produces a number that is not any metric at all.
- Every aggregate is `sum(...) / len(scores)`. Dividing by case count keeps questions with many answers from pulling the average — the macro average expressed as code.
- `mean_reciprocal_rank` simply calls `mrr`. Both the abbreviation and the full name are public so call sites can use whichever reads better.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/evals/test_02_scoring.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A hit with matching coordinates but a different hash | A chunk from another snapshot never inflates the score. |
| Two intervals that merely touch | Overlap is zero at a half-open boundary. |
| Several chunks covering one gold span | Recall does not rise more than once. |
| `k=True` | A boolean never passes as an integer k. |
| Cases mixing different values of k | No meaningless average is produced. |
| The same cases in a different input order | Aggregates do not move between runs. |

One boundary in that suite is measured rather than asserted: against the golden span `[100, 200)`, the test drives a hit of `[190, 300)` — overlap 10, union 200, IoU exactly 10/200 = 0.05 — and requires it to pass, pinning the comparison as an inclusive `>=`. Slide the hit five characters to `[195, 300)` and it must fail. If an implementation ever drifts to a strict comparison, this is the test that catches it.

### What you should be able to explain now

- **Why is the IoU threshold as low as 0.05?**
  - **Answer:** Under full containment IoU reduces to answer length over chunk length, and the measured chunks are routinely many times wider than the answers, so even a fully containing chunk can fall under 0.05. The low bar exists to admit most containment; it is not an empirically tuned value.
- **Why does the hash comparison precede the coordinate math?**
  - **Answer:** Equal offsets in different source snapshots may point to different text, so stale evidence must be rejected before numeric overlap can inflate relevance.
- **Why does recall count gold spans rather than retrieval results?**
  - **Answer:** Recall measures how much required evidence was found; counting hits would let several chunks covering the same gold span raise the score repeatedly.
- **Why was the macro average chosen over the micro average?**
  - **Answer:** Macro averaging gives each question equal weight, while a micro average would let questions with many answer spans dominate the suite.
- **What becomes impossible to judge if the scoring layer performs any I/O?**
  - **Answer:** When a score changes, it becomes impossible to tell whether retrieval changed or external state inside the scoring process changed.

---

[← Previous: Golden loader](02-golden-loader.md) · [Module overview](../03-build.md) · [Next: Regression →](04-regression.md)
