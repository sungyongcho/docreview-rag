# M3.4 Tutorial 6 — The container the measurement goes into

`ablation.py` defined the arms. Tutorial 5 fixed which experiments run, in what order, and what the comparison table looks like — but it deliberately left one question open: after a run ends, what evidence must a single evaluated case still hold? This document answers it by deciding what one experiment **leaves behind.**

There is no execution logic in this document — only record declarations and small helpers. What gets decided here determines everything a later reader of this evaluation can see. Get this layer wrong and the failure is quiet: the run finishes, aggregates land in a table, and months later nobody can say which question regressed or what was retrieved in place of the expected evidence. The case can never be audited, because the evidence was discarded the moment the average was computed.

The invariant this record layer is built around: **every aggregate in an artifact is recomputable from the per-case records in the same artifact.** Recall, hit rate, MRR, and every latency statistic must fall out of the stored cases with no extra input. Section 3 turns that sentence into a runnable check against a committed artifact.

**Prerequisite:** `app/evals/ablation.py` from tutorial 5 is written. This document builds only the first half of `retrieval_eval.py`; tutorial 5's focused test runs after tutorial 7 completes the execution functions, while this record layer's tests run together in tutorial 8.

### Aggregate scores alone cannot be reproduced

**Before** each arm collapses into metrics, per-case complete hits and latency are written out as raw JSON.

Keep only the aggregate — the committed structure-1200-lexical-bm25 arm reports recall 0.5208 — and nothing can be done later. There is no telling which of the 24 scored questions produced the misses, what was retrieved in their place, or why. Rerunning is not an answer either: after the provider, the corpus, or the code changes, that number no longer reproduces, and the old run's evidence is gone for good.

**Keep the raw evidence that produced a measurement alongside the measurement.** A UTC timestamp in the filename separates runs, so a new measurement never overwrites an old one — which run is newer is readable from the directory listing alone.

### 28 recorded, 24 scored

`evaluate_retriever()` **runs and records** all 28 golden cases but scores only the 24 positives.

That is the distinction from M3.1, enforced here. The 4 `absent` cases are not something retrieval recall should measure — there is no span a retriever could return to earn the point. The two obvious alternatives both lose information. Scoring them as zero folds unwinnable questions into the macro-average: with four zeros mixed in, the committed bm25 arm's recall would print 0.4464 instead of 0.5208, punishing retrieval for questions it could never win. Skipping them entirely is no better — then nothing records what the retriever actually returned when the corpus holds no answer, and there is no data left to analyze "can it say there is nothing?" So they are **run and recorded but excluded from the score.**

Running all 28 also matters for a quieter reason: every attempted case contributes one latency sample. The latency summary built in this document therefore describes 28 measurements, not 24 — section 5's percentile arithmetic depends on that count.

### What to define, what to implement, and what to inspect

The front half of `app/evals/retrieval_eval.py` is built in five steps. The execution functions come in the next document.

| Area | Learning action | What to take away |
|---|---|---|
| Module header and budget constants | **Define the structure** | This file depends on all of M1, M2, and M3 |
| Provenance, latency, and case records | **Write the record declarations** | What must travel with a measurement |
| `RetrievalEvaluation` | **Write the field mapping** | The shape of the artifact JSON |
| `_latency_summary` | **Implement** the percentile yourself | What p95 means on a small sample |
| `_golden_provenance` | **Implement** the uniformity check yourself | Why review status must not be mixed |

### 1. Module header and budget constants

#### Create `app/evals/retrieval_eval.py` — module header

**Learning action — define the structure:** scan the import list. This file calls almost every module built so far.

```python
"""Run source-grounded retrieval evaluations and measure M3 latency budgets."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import time
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import LexicalRanker, Settings, get_settings
from app.evals.loader import DEFAULT_GOLDEN_PATH, load_golden_cases
from app.evals.regression import (
    BaselineComparison,
    RegressionTolerances,
    compare_against_baseline,
    latest_comparable_baseline,
    persist_eval_result,
    serialize_config,
)
from app.evals.scoring import CaseScore, SuiteScore, score_case, score_suite
from app.evals.types import GoldenCase
from app.ingestion.chunk import ChunkConfig, chunk_filing
from app.ingestion.seed import SeedBatch, build_seed_batch, load_manifest, persist_seed_batch
from app.retrieval.bm25 import backfill_term_stats, bm25_search
from app.retrieval.embeddings import (
    EmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.lexical import lexical_search
from app.retrieval.service import retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search
```

**What to look for in the code**

- M1's `chunk_filing` and `persist_seed_batch`, M2's retrieval set, and M3's loader, scoring, and regression all converge here. Evaluation is the layer that **reassembles the whole pipeline** and runs it — which is exactly what lets one experiment change the chunking and measure the effect end to end, instead of trusting each layer's local tests to compose.
- `NullPool` is imported. Temporary tables are bound to a connection; a pool that recycled connections would leak one run's temporary corpus into the next. Tutorial 8 builds the isolation that depends on this.

#### Extend `app/evals/retrieval_eval.py` — budget constants

**Learning action — define the settings schema:** note why the three budget values are hard-coded.

<!-- src: app/evals/retrieval_eval.py::RetrievalStrategy,RAW_ARTIFACT_SCHEMA_VERSION -->
```python
type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]
type Clock = Callable[[], int]

INDEXING_BUDGET_SECONDS = 300.0
QUERY_BUDGET_COUNT = 200
QUERY_BUDGET_SECONDS = 90.0
RAW_ARTIFACT_SCHEMA_VERSION = 1
```

**What to look for in the code**

- The budgets are constants, not settings. A limit you can change per run is not a budget — you would raise it every time things got slower, and the green light would follow the slowness instead of resisting it. Making the relaxation a code change forces it through review and into history.
- `RAW_ARTIFACT_SCHEMA_VERSION` goes into the artifact. Change the payload's shape later, bump the version, and code reading old files still has grounds to decide what it is looking at. What this version does **not** do — separate baselines — is a sharp edge section 3 returns to.

### 2. What travels with a measurement

#### Extend `app/evals/retrieval_eval.py` — provenance, latency, and case records

**Learning action — write the record declarations:** note why `CaseEvaluation.score` is `| None`.

<!-- src: app/evals/retrieval_eval.py::GoldenProvenance,CaseEvaluation -->
```python
@dataclass(frozen=True, slots=True)
class GoldenProvenance:
    """Review provenance shared by every case in one strict golden suite."""

    total_cases: int
    scored_positive_cases: int
    unscored_absent_cases: int
    curation_status: str
    approval_status: str
    human_verified: bool


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Measured sequential retrieval latency in milliseconds."""

    query_count: int
    total_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    """Raw hits, latency, and optional positive-case retrieval score."""

    golden: GoldenCase
    latency_ms: float
    hits: tuple[ChunkHit, ...]
    score: CaseScore | None
```

**What to look for in the code**

- `GoldenProvenance` carries **both** `total_cases` and `scored_positive_cases`. The fact that 28 ran and 24 were scored survives in the result file.
- `human_verified` is in the provenance record. Anyone citing these numbers sees straight from the file that this data was never human-verified.
- `CaseEvaluation.score` is `CaseScore | None`. An absent case is `None` — not zero, but **not scored**. That distinction begins in M3.1 and reaches here intact.
- `hits` is stored whole as a tuple. Not just recall, but **what was retrieved instead**, survives.

> **Concept — A record is evidence, not a summary**
>
> The unit of this layer is one case, and its record holds four things: the question exactly as asked, everything the retriever returned, how long the attempt took, and — only where scoring is defined — the verdict. That is the full set a later reader needs to re-litigate the case without rerunning it. Drop any one and a class of questions becomes unanswerable: without the hits there is no diagnosing a miss, without the latency there is no attributing a slow run, and without the frozen question there is no telling whether the answer key drifted after the fact.
>
> The score is optional by type, not by accident. Retrieval quality is undefined when there is nothing to retrieve: an absent case has no correct span, so no retrieval result can be right or wrong about it. Whether the system can *say* there is nothing is a real measurement — but a different one, made at the answer layer, not here. Storing no score says this question sat outside the metric's domain; storing zero would say it was measured and failed, which is false.

> **Concept — A number without its answer-key status invites overclaiming**
>
> Every metric in this system is relative to an answer key, and the answer key has a review state. The committed golden set is agent-curated: a machine validated its spans against the corpus bytes, but no human has approved a single case, and the file says so. A recall figure copied into a report without that status quietly upgrades itself — machine-validated becomes human-approved in the retelling, because nothing traveled with the number to say otherwise.
>
> That is why provenance rides inside every artifact rather than beside it. The result file itself states how many cases ran, how many were scored, and that none were human-verified. Whoever quotes the number holds the caveat in the same file, and a suite evaluated against an unapproved answer key can never be mistaken for an approved benchmark.

The three status fields have a lifecycle behind them. The suite was assembled by the agent-driven curation flow that M3.5 gates, so every committed case carries `agent-curated` and `pending-author-approval`; the machine validation that state rests on is recorded in `data/golden/REVIEW.md`, and only the author may move a case out of the pending state, as a reviewed change. The current golden types even pin these values as literals, so an approved state cannot be expressed without a deliberate type change. `_golden_provenance` copies the suite's uniform state into the artifact — it never advances it.

### 3. The shape of the artifact JSON

#### Extend `app/evals/retrieval_eval.py` — the evaluation result

**Learning action — write the field mapping:** work out why `metric_values()` puts quality and latency in the same dictionary.

<!-- src: app/evals/retrieval_eval.py::RetrievalEvaluation -->
```python
@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    """One complete, artifact-ready retrieval experiment."""

    suite: str
    recorded_at: datetime
    config: dict[str, Any]
    provenance: GoldenProvenance
    score: SuiteScore
    latency: LatencySummary
    cases: tuple[CaseEvaluation, ...]

    def metric_values(self) -> dict[str, float]:
        """Return quality and latency values suitable for ``eval_results``."""
        return {
            "recall_at_k": self.score.recall_at_k,
            "hit_rate_at_k": self.score.hit_rate_at_k,
            "mrr": self.score.mrr,
            "query_count": float(self.latency.query_count),
            "total_latency_ms": self.latency.total_ms,
            "mean_latency_ms": self.latency.mean_ms,
            "p95_latency_ms": self.latency.p95_ms,
        }

    def artifact_payload(self) -> dict[str, Any]:
        """Return the stable raw JSON payload for this measured run."""
        return {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "suite": self.suite,
            "recorded_at": _utc_text(self.recorded_at),
            "config": self.config,
            "golden_provenance": asdict(self.provenance),
            "metrics": {
                "k": self.score.k,
                "scored_case_count": self.score.case_count,
                **self.metric_values(),
            },
            "latency": asdict(self.latency),
            "cases": [
                {
                    "golden": case.golden.model_dump(mode="json"),
                    "latency_ms": case.latency_ms,
                    "hits": [hit.model_dump(mode="json") for hit in case.hits],
                    "score": asdict(case.score) if case.score is not None else None,
                }
                for case in self.cases
            ],
        }
```

**What to look for in the code**

- `metric_values()` places recall and latency in **one dictionary**. It goes into `eval_results` verbatim, so a later query returns quality and cost together.
- Yet M3.3's `compare_against_baseline` gates only the first three. Latency is stored without being auto-judged in a direction nobody declared.
- `artifact_payload()` uses `model_dump(mode="json")`. `datetime` values and tuples convert into shapes JSON accepts directly.
- Each case re-stores `golden` in full. It looks redundant, but if the answer file changes later, **what this run treated as ground truth** stays inside the artifact.

This payload is where the run artifacts come from. Tutorial 7's `write_evaluation_artifact` serializes exactly this dictionary to disk, and the arm files committed under `data/eval_runs/` — six from the 2026-08-12 run, ten from the 2026-08-24 run — are these payloads frozen at the moment of measurement; each run also leaves one budget file beside them, a sibling record with its own shape. Nothing edits an artifact after it is written; a new run writes a new timestamped file next to the old ones, and the milestone's evaluation report links every row of its comparison table straight back to one of these files as its evidence.

> **Concept — Deterministic serialization makes artifacts diffable**
>
> Two artifacts are most useful side by side: "what changed between these runs" should be answerable by diffing the files. That only works when serialization is deterministic — same data, same bytes. Tutorial 7's writer therefore sorts keys and fixes the indentation, so a dictionary's arbitrary ordering can never masquerade as a change, and the schema version stamped into every artifact records when the payload's shape itself moved.
>
> One honest limit: the schema version describes the artifact, not the experiment. Baseline comparison selects its reference by suite plus byte-identical config, and the version field lives outside config — bumping it neither separates old results from new ones nor stops a comparison. Only what is recorded inside config partitions baselines. That is tutorial 4's contract, and the version number here is easy to over-trust.

The intro's invariant is now checkable against a committed artifact — every aggregate falls out of the per-case records in the same file:

```bash
python3 -c "import json; d=json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json')); s=[c['score'] for c in d['cases'] if c['score'] is not None]; print(sum(x['recall_at_k'] for x in s)/len(s) == d['metrics']['recall_at_k'], sum(c['latency_ms'] for c in d['cases']) == d['latency']['total_ms'])"
```

Both comparisons print `True`: the stored recall is exactly the mean of the 24 stored case recalls, and the stored total latency is exactly the sum of the 28 stored per-case latencies.

### 4. Percentiles on a small sample

#### Extend `app/evals/retrieval_eval.py` — budget measurement records

**Learning action — write the record declarations:** note that `passed` is a stored value.

<!-- src: app/evals/retrieval_eval.py::QueryBudgetMeasurement,PersistedEvaluation -->
```python
@dataclass(frozen=True, slots=True)
class QueryBudgetMeasurement:
    """Wall-clock evidence for the fixed 200-query retrieval budget."""

    query_count: int
    total_seconds: float
    budget_seconds: float
    passed: bool
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class IndexingBudgetMeasurement:
    """Wall-clock evidence for one isolated corpus indexing configuration."""

    target_text_chars: int
    document_count: int
    chunk_count: int
    embedding_provider: str
    total_seconds: float
    budget_seconds: float
    passed: bool


@dataclass(frozen=True, slots=True)
class PersistedEvaluation:
    """Database identity and optional comparison with the preceding baseline."""

    result_id: int
    baseline_id: int | None
    comparison: BaselineComparison | None
```

**What to look for in the code**

- `budget_seconds` is stored with the result, and so is `passed`. The obvious alternative — recompute the verdict later from the stored total and whatever the budget is now — silently rewrites history the day the budget changes. Freezing both means the file always records **which limit produced that verdict.**
- `IndexingBudgetMeasurement` carries `document_count` and `chunk_count`. When 300 seconds is exceeded, that separates "the corpus grew" from "the code got slower."
- `PersistedEvaluation.comparison` is `| None`. A first run with no baseline is distinguishable from "compared, no regression" — collapsing the two into one value would let the very first run pass for a verified one.

### 5. Percentiles and provenance uniformity

#### Extend `app/evals/retrieval_eval.py` — helpers

**Learning action — implement the percentile:** implement `percentile` yourself, then work out which value p95 lands on across 28 samples.

<!-- src: app/evals/retrieval_eval.py::_utc_text,_golden_provenance -->
```python
def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(serialize_config(config))


def _latency_summary(values: Sequence[float]) -> LatencySummary:
    if not values:
        raise ValueError("latency measurements must not be empty")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("latency measurements must be finite and nonnegative")
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = max(0, math.ceil(fraction * len(ordered)) - 1)
        return ordered[position]

    total = sum(values)
    return LatencySummary(
        query_count=len(values),
        total_ms=total,
        mean_ms=total / len(values),
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        max_ms=ordered[-1],
    )


def _golden_provenance(cases: Sequence[GoldenCase]) -> GoldenProvenance:
    positive_count = sum(bool(case.answers) for case in cases)
    if positive_count == 0:
        raise ValueError("evaluation requires at least one positive golden case")
    curation_statuses = {case.curation_status for case in cases}
    approval_statuses = {case.approval_status for case in cases}
    verification_states = {case.human_verified for case in cases}
    if len(curation_statuses) != 1 or len(approval_statuses) != 1:
        raise ValueError("golden review provenance must be uniform within a suite")
    if verification_states != {False}:
        raise ValueError("M3 golden cases must not claim human verification")
    return GoldenProvenance(
        total_cases=len(cases),
        scored_positive_cases=positive_count,
        unscored_absent_cases=len(cases) - positive_count,
        curation_status=next(iter(curation_statuses)),
        approval_status=next(iter(approval_statuses)),
        human_verified=False,
    )
```

**What to look for in the code**

- `percentile` uses `math.ceil(fraction * n) - 1`. Latency is recorded for all 28 attempted cases including the absent ones, so the sample count is 28 and p95 is `ceil(26.6) - 1 = 26`, the 27th sorted value. It picks one real observation rather than interpolating — it never reports a latency nobody measured.
- `max(0, ...)` prevents index -1 on a single sample.
- `_golden_provenance` enforces **uniformity** of review status. Mixing approved and unapproved cases in one suite would make the single `approval_status` line in the result file a lie. The obvious alternative — recording the set of statuses seen — would push mixed-status handling onto every later consumer; erroring instead treats a mixed suite as a curation mistake to stop at the door.
- `verification_states != {False}` is rejected. The promise that M3 golden data must not claim human verification is enforced in code.

> **Concept — The mean is a throughput number; p95 is an experience number**
>
> The mean answers "total time for N queries, divided by N" — the right number for budget arithmetic, which is exactly what section 4's query budget uses it for. But nobody experiences the mean: each request lands on one point of the distribution, and the slow tail is what gets remembered. A summary that carried only the mean would let a few very slow queries hide inside many fast ones.
>
> The committed bm25 arm shows the gap on real data: mean 35.6 ms, but p95 55.4 ms and max 62.0 ms. The tail runs roughly half again as slow as the mean, and only the percentile lines expose it.
>
> On 28 samples there is a second decision to make: what exactly is the 95th percentile of 28 numbers? The common interpolating definitions manufacture a value between two observations — a latency nobody measured. The nearest-rank method instead selects a position in the sorted list, here ceil(0.95 × 28) − 1 = 26, the 27th observation: a latency that actually happened. On a small sample, reporting only real observations is worth more than a smoother estimate.

The committed artifact confirms the arithmetic — 28 samples, and the stored p95 is exactly the 27th sorted observation:

```bash
python3 -c "import json; d=json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json')); lat=sorted(c['latency_ms'] for c in d['cases']); print(len(lat), lat[26], d['latency']['p95_ms'], d['latency']['mean_ms'])"
```

```text
28 55.356528 55.356528 35.56012882142857
```

### What you should be able to explain now

- **What becomes impossible later when only aggregate scores are stored?**
  - **Answer:** A regression cannot be traced to a particular question or inspected to see which hits replaced the expected evidence.
- **Why is `CaseEvaluation.score` `None` rather than zero?**
  - **Answer:** An absent case was not scored; zero would falsely say that it was scored and failed retrieval.
- **Why is re-storing `golden` per case not redundancy?**
  - **Answer:** It freezes the exact ground truth used by that run inside the artifact, even if the external answer file changes later.
- **Why must p95 on a small sample be an observation rather than an interpolation?**
  - **Answer:** Latency is recorded for all 28 attempted cases, including absent ones, so p95 is the 27th sorted observation; nearest-rank selection reports a latency that was actually measured, where interpolation would manufacture one that never happened.
- **Why must review status be uniform within a suite?**
  - **Answer:** The artifact has one suite-level provenance status, which would be false if approved and unapproved cases were mixed.
- **What does bumping the artifact schema version not do?**
  - **Answer:** It does not partition baselines — baseline selection matches on suite and config only, so only fields recorded inside the config separate old runs from new ones.

---

[← Previous: Ablation](05-ablation.md) · [Module overview](../03-build.md) · [Next: Evaluation run →](07-evaluation-run.md)
