# M3.3 Tutorial 4 — May yesterday's 0.79 be compared with today's 0.82?

Tutorial 3 (M3.2) ends with a scorer that turns one evaluation run into one set of numbers, deterministically — same spans, same hits, same score, byte for byte. What that layer cannot do is remember. It keeps no record of past runs and no record of the conditions a number was measured under, so the question every tuning session asks — is today better than yesterday? — has no honest answer yet.

Recall was 0.79 yesterday and 0.82 today. Is that an improvement? **Unknown.** In between, the embedding provider may have changed, the chunking target may have changed, or the retrieval depth may have gone from 5 to 10. The committed evaluation artifacts show how much one such condition moves the number on its own: the same lexical BM25 retrieval scores recall 0.5208 with 1,200-character chunking and 0.4583 with 500-character chunking. That 0.0625 gap is pure measurement-condition difference — compare across it and a chunking change gets reported as a retrieval improvement.

Without a comparison rule this failure is quiet and cumulative: parameter after parameter gets tuned, each run is declared "better than last time", and nobody can reconstruct what last time actually measured. A gate built on such comparisons does not catch regressions — it certifies noise.

So this tutorial gives scores a memory and a comparison rule, under one invariant: **two scores are compared only when their suite matches and their configurations are equal after canonicalization — equivalently, when their canonical JSON strings are byte-identical.** Anything else is not a looser comparison; it is no comparison, and it must be reported as exactly that.

**Prerequisite:** Tutorial 3's `uv run pytest tests/evals/test_02_scoring.py -q` passes.

### Comparison only when the configuration matches completely

So `EvalResult` stores not only the metrics but **the entire canonical configuration.** Chunking, retrieval method, provider, dimensions, depth — differ in any one and it is a different experiment.

> **Concept — the configuration fingerprint is the comparison key**
>
> A regression verdict is a claim about one system measured twice, so before any subtraction happens the gate has to establish that both runs measured the same thing. This layer establishes it structurally: every axis the measurement depends on is canonicalized into one configuration object stored beside the metrics, and the baseline query matches on the suite name plus that canonical configuration — nothing else. Equality of the canonical form is the definition of "same experiment" here. There is no similarity scoring, no partial credit, no "only the ranker differs, close enough".
>
> The fingerprint cuts both ways. Two runs whose configurations match are comparable even weeks apart, because everything that shapes the number is pinned. Two runs that differ in a single field are strangers: their delta measures the configuration change entangled with everything else, and no arithmetic performed afterwards can separate the two again.

`latest_comparable_baseline()` fetches only the newest result whose configuration matches **exactly.** With none, it reports that there is no comparison target. It never stretches to find something similar.

> **Concept — an incomparable run must not pass quietly**
>
> A gate has three honest outcomes: passed, regressed, and no comparison target. Collapsing the third into the first is the most dangerous failure available to this layer, because it activates precisely when the measurement conditions changed — the moment comparison is least valid is the moment the gate goes silent and green. A configuration change would then always launder its own impact: the first run under the new configuration finds no true baseline, gets waved through, and every later run is compared against numbers the old world produced.
>
> Returning nothing and making the caller say "no baseline" keeps the third state visible. The first run of a new configuration establishes a baseline; it is not judged, and it must not claim to have been.

The committed artifacts show the size of the error a quiet fallback would make. The two lexical BM25 arms of the committed evaluation run differ only in the chunking target (and the arm name derived from it), and they score recall 0.5208 versus 0.4583:

```bash
python3 -c "import json; a=json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json')); b=json.load(open('data/eval_runs/20260824T203336Z-structure-500-lexical-bm25.json')); print('recall  :', a['metrics']['recall_at_k'], 'vs', b['metrics']['recall_at_k']); print('config ==', a['config'] == b['config']); print('chunking:', a['config']['chunking']['target_text_chars'], 'vs', b['config']['chunking']['target_text_chars'])"
```

A lookup that ignored the configuration would hand the 500-character row to the 1,200-character run as its baseline and report a +0.0625 recall "improvement" in which not one retrieval parameter changed. The gate answers `None` instead, and tutorial 7's runner records that as its own outcome — comparison skipped, baseline established.

That is also why `serialize_config()` emits canonical JSON. The same configuration must not record differently because dictionary key order differs. Non-JSON values, infinities, and NaNs are rejected too — values that would make later comparison impossible. Section 4 dissects both choices.

### Direction and tolerance are explicit

Gating requires knowing which direction is better. Recall@k, Hit Rate@k, and MRR are all **higher-is-better**, which keeps the arithmetic simple.

```text
delta = current - baseline
regressed = delta < -tolerance
```

> **Concept — a metric without a declared direction cannot be gated**
>
> The subtraction delta = current minus baseline only becomes a verdict once someone declares which sign is good. For recall, hit rate, and MRR, up is better, so one fixed rule — regressed when the drop exceeds the tolerance — covers all three. Latency inverts the sign: lower is better, and the same rule applied to it congratulates every slowdown and flags every speedup as a regression.
>
> That is why the comparator iterates over an explicit allow-list of three names instead of over whatever keys the two mappings share. The stored metrics of a committed run carry latency right next to quality — the 1,200-character lexical BM25 arm records a p95 latency of 55.36 ms beside its recall of 0.5208, and the slowest arm at the same chunking records 238.23 ms. A gate that assumed higher-is-better for every shared key would read the jump from 55.36 to 238.23 as a +182.87 improvement. Skipping undeclared metrics is not leniency toward sloppy inputs; it is the refusal to guess a direction that was never declared.

`tolerance` exists so that a real but acceptable drop is not mistaken for a regression. The default is 0.0 — no drop tolerated. That strictness is affordable here because the whole scoring path is deterministic by tutorial 3's invariant: identical conditions produce identical numbers, so there is no measurement noise for a zero tolerance to misfire on. The tolerance becomes load-bearing the day a genuinely noisy axis enters the configuration, and it is raised per metric, deliberately — not as a blanket fudge factor.

A negative tolerance is rejected by `__post_init__`. A negative tolerance would mean "treat improvements as regressions too," which is meaningless.

### Persistence flushes without committing

Saving an `EvalResult` **only flushes inside the caller's transaction.** The caller commits.

Same philosophy as M1.4's `persist_seed_batch`. Sometimes the evaluation result has to be bound into the same transaction as the runner's other work, and a hidden commit here makes that control impossible.

The failure a hidden commit invites is a half-recorded run: the result row commits, a later step of the runner fails, and the database now holds a baseline whose run never finished — which the next run will happily compare against. Flush-without-commit gives the row an ID inside the still-open transaction, and a rollback erases it together with everything else the run wrote. All-or-nothing is decided by the caller, in one place.

### What to define, what to implement, and what to inspect

First the result table is added to `app/db/models.py`, then `app/evals/regression.py` is built in five steps. The first three are pure computation; the last two touch the database.

| Area | Learning action | What to take away |
|---|---|---|
| The `EvalResult` table | **Define the structure** | Why baselines persist as rows, not files |
| Metric names and direction | **Define the settings schema** | Only metrics with a known direction are gated |
| `RegressionTolerances` | **Implement** the invariants yourself | Why a negative tolerance is meaningless |
| `compare_against_baseline` | **Implement** the comparison rule yourself | Whether the boundary value passes or fails |
| Config canonicalization and validation | **Inspect the boundary conversions** | What makes the same experiment produce the same string |
| Persistence and baseline lookup | **Define the structure, then inspect call order** | The boundary between flush and commit |

### 1. Only metrics with a known direction are gated

#### Extend `app/db/models.py` — the `EvalResult` table

Keeping baselines as database rows instead of files needs a table first. It goes into the same file as M1.4's tables, under the same rules. No tutorial has built this table yet — it is written here for the first time.

Rows instead of files is a queryability decision. The lookup this module ends with — the newest row whose suite and canonical config both match — is one indexed SQL query, because PostgreSQL can test JSONB equality in a `WHERE` clause; a directory of baseline files would have to encode the configuration into filenames or reopen and parse every file per lookup, and "newest" would rest on filesystem timestamps that no constraint protects. The files are not gone, though — they change jobs. `raw_artifact_path` points from every row to the full per-case JSON under `data/eval_runs/`, so the row is the queryable summary and the file is the auditable evidence. Note who lives where: the JSON artifacts are committed to the repository, while `eval_results` rows exist only in the local PostgreSQL — the committed runs record the suite name `m3-retrieval-v1`, and re-running the evaluation is what recreates the rows.

**Learning action — define the structure:** write it while checking which malformed row each of the three `CheckConstraint`s rejects.

<!-- src: app/db/models.py::EvalResult -->
```python
class EvalResult(Base):
    """One persisted evaluation run used for comparable regression baselines."""

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suite: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("btrim(suite) <> ''", name="ck_eval_results_suite_nonempty"),
        CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name="ck_eval_results_config_object",
        ),
        CheckConstraint(
            "jsonb_typeof(metrics) = 'object'",
            name="ck_eval_results_metrics_object",
        ),
        CheckConstraint(
            "btrim(raw_artifact_path) <> ''",
            name="ck_eval_results_raw_artifact_path_nonempty",
        ),
        Index("ix_eval_results_suite_created_at", "suite", "created_at"),
    )
```

**What to look for in the code**

- `config` and `metrics` are `JSONB`, and constraints enforce `jsonb_typeof(...) = 'object'`. The column type alone accepts any JSON value — an array, a string, a bare number. A config stored as an array would never equal any canonical object, so every later lookup would return no baseline without a word of complaint; the constraint converts that silently never-matching row into a loud error at insert time.
- `suite` and `raw_artifact_path` reject blank values by constraint. A blank suite is a lookup key nothing can ever match, and a result without an artifact path is a claim with its evidence discarded — the aggregate numbers would stand with no per-case record left to audit them against.
- `created_at` uses `server_default=func.now()`. The database stamps the time, not the application, so baselines sort on one clock even when several processes write. The index on suite and `created_at` serves exactly the query this module ends with: newest first, within one suite.
- The table stores measurements and their conditions — no pass/fail verdict. Verdicts are recomputed at comparison time, so the tolerance policy can change tomorrow without rewriting history; a stored verdict would freeze whatever policy happened to be active at write time into the row and misreport under every later policy.

#### Create `app/evals/regression.py` — module header

**Learning action — define the structure:** `EvalResult` is among the imports. The table defined a moment ago gets its first use here.

```python
"""Typed regression comparison and PostgreSQL evaluation-result persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Final, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalResult
```

#### Extend `app/evals/regression.py` — metric names and direction

**Learning action — define the settings schema:** note why there are only three metrics.

<!-- src: app/evals/regression.py::MetricName,HIGHER_IS_BETTER_METRICS -->
```python
type MetricName = Literal["recall_at_k", "hit_rate_at_k", "mrr"]

HIGHER_IS_BETTER_METRICS: Final[tuple[MetricName, ...]] = (
    "recall_at_k",
    "hit_rate_at_k",
    "mrr",
)
```

**What to look for in the code**

- The name is `HIGHER_IS_BETTER_METRICS`. Direction is baked into the name, so putting a lower-is-better value like latency in it feels wrong immediately.
- Latency is absent from the list, correctly. Feeding a metric with the opposite direction into the same comparison function judges improvements as regressions. M3.4 handles budgets separately.
- The three names are exactly the three ratios tutorial 3's scorer emits, and `MetricName` narrows them as a `Literal`. A typo in a metric name becomes a type error at the call site instead of a metric that silently never gets gated.

### 2. A negative tolerance is meaningless

#### Extend `app/evals/regression.py` — tolerances and comparison records

**Learning action — implement the invariants:** implement `__post_init__` yourself, noting why there are two separate checks.

<!-- src: app/evals/regression.py::RegressionTolerances,BaselineComparison -->
```python
@dataclass(frozen=True, slots=True)
class RegressionTolerances:
    """Maximum accepted absolute drop for each higher-is-better metric."""

    recall_at_k: float = 0.0
    hit_rate_at_k: float = 0.0
    mrr: float = 0.0

    def __post_init__(self) -> None:
        """Reject non-finite or negative tolerance values at construction."""
        for metric in HIGHER_IS_BETTER_METRICS:
            value = getattr(self, metric)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{metric} tolerance must be a finite nonnegative number")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{metric} tolerance must be a finite nonnegative number")

    def for_metric(self, metric: MetricName) -> float:
        """Return the configured tolerance for one supported metric."""
        return float(getattr(self, metric))


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One current metric compared with its higher-is-better baseline."""

    metric: MetricName
    baseline: float
    current: float
    delta: float
    tolerance: float
    regressed: bool


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """Deterministically ordered comparisons for all regression-gated metrics."""

    metrics: tuple[MetricComparison, ...]

    @property
    def regressed_metrics(self) -> tuple[MetricName, ...]:
        """Return metric names whose drop exceeds the configured tolerance."""
        return tuple(result.metric for result in self.metrics if result.regressed)

    @property
    def passed(self) -> bool:
        """Return whether every metric stayed within its allowed drop."""
        return not self.regressed_metrics
```

**What to look for in the code**

- `isinstance(value, bool)` is rejected first. Because `True` is an `int`, a `tolerance=True` passing as `1.0` would mean a recall drop of 1.0 is not a regression.
- `value < 0` is rejected. A negative tolerance means "treat improvements as regressions too," which is meaningless.
- `MetricComparison` keeps `baseline`, `current`, `delta`, and `tolerance` all together. With only the `regressed` boolean there is no way to trace why the verdict came out that way.
- `BaselineComparison.passed` derives from `regressed_metrics`. The two cannot disagree.

### 3. The boundary value passes

#### Extend `app/evals/regression.py` — baseline comparison

**Learning action — implement the comparison rule:** write the `regressed` line yourself, and be able to say why `math.isclose` is attached to it.

<!-- src: app/evals/regression.py::_metric_value,compare_against_baseline -->
```python
def _metric_value(metrics: Mapping[str, float], metric: MetricName, owner: str) -> float:
    try:
        value = metrics[metric]
    except KeyError as exc:
        raise ValueError(f"{owner} metrics are missing {metric}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{owner} {metric} must be a finite number between 0 and 1")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{owner} {metric} must be a finite number between 0 and 1")
    return numeric


def compare_against_baseline(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> BaselineComparison:
    """Compare current values with an explicit higher-is-better metric baseline.

    A drop exactly equal to its tolerance passes. Extra metrics are ignored so
    lower-is-better values such as latency are never interpreted implicitly.
    """
    if not isinstance(baseline, Mapping) or not isinstance(current, Mapping):
        raise ValueError("baseline and current metrics must be mappings")
    if tolerances is None:
        limits = RegressionTolerances()
    elif isinstance(tolerances, RegressionTolerances):
        limits = tolerances
    else:
        if not isinstance(tolerances, Mapping) or not all(
            isinstance(metric, str) for metric in tolerances
        ):
            raise ValueError("tolerances must map supported metric names to numbers")
        unknown = set(tolerances) - set(HIGHER_IS_BETTER_METRICS)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported metric tolerances: {names}")
        limits = RegressionTolerances(**tolerances)
    comparisons: list[MetricComparison] = []
    for metric in HIGHER_IS_BETTER_METRICS:
        baseline_value = _metric_value(baseline, metric, "baseline")
        current_value = _metric_value(current, metric, "current")
        tolerance = limits.for_metric(metric)
        delta = current_value - baseline_value
        boundary = -tolerance
        regressed = delta < boundary and not math.isclose(
            delta,
            boundary,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        comparisons.append(
            MetricComparison(
                metric=metric,
                baseline=baseline_value,
                current=current_value,
                delta=delta,
                tolerance=tolerance,
                regressed=regressed,
            )
        )
    return BaselineComparison(metrics=tuple(comparisons))
```

**What to look for in the code**

- `delta < boundary and not math.isclose(...)` is the crux. Floating-point subtraction can produce `-0.30000000000000004` where exactly `-tolerance` was expected. Without `isclose`, **a drop exactly equal to the tolerance passes on some runs and fails on others.**
- Metrics not in the list are silently ignored. Even if a caller mixes in latency, a value whose direction is unknown is never interpreted.
- `_metric_value` enforces the 0–1 range. All three metrics are ratios, so a value like 1.2 is a calculation bug rather than a good result.
- Tolerances may arrive as a mapping, but unknown keys are rejected. A typo like `{"recal_at_k": 0.01}` must not create the illusion of gating at tolerance 0.

The focused test pins this exact boundary with measured values: baseline recall 0.8, current 0.79, tolerance 0.01 — a drop of exactly the tolerance. Run the subtraction Python actually performs there:

```bash
python3 -c "print(repr(0.79 - 0.8))"
```

The result is `-0.010000000000000009` — below the `-0.01` boundary by roughly 9e-18, because neither 0.79 nor 0.8 has an exact binary representation. Under a bare `delta < boundary` this allowed boundary drop regresses, and whether any given boundary case passes would depend on which decimal fractions happen to round which way. `abs_tol=1e-12` absorbs that representation error while staying far below any real drop this suite's rank-based ratios can produce, and `rel_tol=0.0` keeps the epsilon absolute — these metrics live on a fixed 0-to-1 scale, and a relative epsilon would shrink to nothing exactly where tolerances are smallest. Rounding both mappings before comparing could also stabilize this boundary, but it would merge genuinely different values near every rounding edge; the one-sided epsilon touches only the boundary itself.

### 4. Making the same experiment produce the same string

#### Extend `app/evals/regression.py` — config canonicalization and value validation

**Learning action — inspect the boundary conversions:** note what `sort_keys=True` and `allow_nan=False` each prevent.

<!-- src: app/evals/regression.py::_validate_config_keys,_artifact_path -->
```python
def _validate_config_keys(value: object) -> None:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("config keys must be strings")
        for child in value.values():
            _validate_config_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _validate_config_keys(child)


def serialize_config(config: Mapping[str, Any]) -> str:
    """Serialize a JSON-object config canonically for stable comparability."""
    if not isinstance(config, Mapping):
        raise ValueError("config must be a JSON object")
    try:
        _validate_config_keys(config)
        return json.dumps(
            dict(config),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("config must contain only finite JSON values") from exc


def _canonical_config(config: Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(serialize_config(config))
    return cast(dict[str, Any], value)


def _validated_metrics(metrics: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(metrics, Mapping) or not metrics:
        raise ValueError("metrics must be a nonempty JSON object")
    validated: dict[str, float] = {}
    for name, value in metrics.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric names must be nonblank strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric {name} must be a finite number")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"metric {name} must be a finite number")
        validated[name] = numeric
    return validated


def _validated_suite(suite: str) -> str:
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be a nonblank string")
    if len(suite) > 128:
        raise ValueError("suite must be at most 128 characters")
    return suite


def _artifact_path(raw_artifact_path: str | Path) -> str:
    if not isinstance(raw_artifact_path, (str, Path)):
        raise ValueError("raw_artifact_path must be a string or Path")
    path = str(raw_artifact_path)
    if not path.strip():
        raise ValueError("raw_artifact_path must be nonblank")
    return path
```

**What to look for in the code**

- **`sort_keys=True` keeps the same config serializing to the same string, so the recorded configuration text and artifacts stay deterministic.** The JSONB equality behind `latest_comparable_baseline` ignores key order, so the lookup holds without the sort — but without it the recorded text changes between runs and artifact diffs break.
- `allow_nan=False` rejects `NaN` and infinities. They are outside the JSON standard, and once stored, no later comparison holds.
- `_validate_config_keys` walks nested structures recursively. Checking only top-level keys lets an integer key inside a nested dictionary through, to explode at serialization time.
- `_canonical_config` serializes and then re-parses. That guarantees what gets stored is **the canonicalized value**.

> **Concept — one canonical text, two different consumers**
>
> The sorted, minimal serialization serves two consumers with different needs. The database is the less demanding one: PostgreSQL stores JSONB in a normalized internal form whose object equality ignores key order, so the baseline lookup would match with or without sorted keys. The consumers that need the sorting live outside the database — the configuration text recorded in artifacts, and every diff a human or a script takes between two of them. Unsorted, the same experiment can serialize differently between runs depending on dictionary construction order, and a diff then shows serialization accidents as if they were configuration changes.
>
> Canonicalize-once also explains the round trip: serialize, then parse back, and store the parsed value. What reaches the database is guaranteed to be the canonical form — not the caller's original object with whatever leftovers survived inside it.

Why the full configuration and not a hash of it? A digest of the canonical string would be an even cheaper equality key, and it is rejected for diagnosability: when a run finds no baseline, the first question is *which field differs from the last run*, and a stored JSON object answers it with one diff, while a hash can only say "something differs". A schema-version integer is the opposite extreme — trivially cheap to bump, but it partitions nothing unless it is itself part of the compared configuration, and it says nothing about what changed.

One sharp edge is worth carrying forward honestly: the fingerprint partitions baselines only over what the configuration records. The committed experiment configs pin the chunking, retrieval, embedding, and measurement axes — and nothing about tutorial 3's matching rule or its threshold. If that scoring rule ever changed, old-rule and new-rule runs would still match byte-for-byte and be compared as if only retrieval had moved. The gate is exactly as honest as the configuration is complete; what is not recorded cannot separate.

### 5. Flush, but do not commit

#### Complete `app/evals/regression.py` — persistence and baseline lookup

**Learning action — define the structure, then inspect call order:** you should be able to explain the difference between `flush` and `commit`.

<!-- src: app/evals/regression.py::persist_eval_result,latest_comparable_baseline -->
```python
async def persist_eval_result(
    session: AsyncSession,
    *,
    suite: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, float],
    raw_artifact_path: str | Path,
    created_at: datetime | None = None,
) -> EvalResult:
    """Flush one validated result without committing the caller's transaction."""
    values: dict[str, Any] = {
        "suite": _validated_suite(suite),
        "config": _canonical_config(config),
        "metrics": _validated_metrics(metrics),
        "raw_artifact_path": _artifact_path(raw_artifact_path),
    }
    if created_at is not None:
        if not isinstance(created_at, datetime):
            raise ValueError("created_at must be a timezone-aware datetime")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        values["created_at"] = created_at

    result = EvalResult(**values)
    session.add(result)
    await session.flush()
    return result


async def latest_comparable_baseline(
    session: AsyncSession,
    *,
    suite: str,
    config: Mapping[str, Any],
) -> EvalResult | None:
    """Return the newest row with the same suite and canonical JSON config."""
    statement = (
        select(EvalResult)
        .where(
            EvalResult.suite == _validated_suite(suite),
            EvalResult.config == _canonical_config(config),
        )
        .order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        .limit(1)
    )
    return await session.scalar(statement)
```

**What to look for in the code**

- It is `await session.flush()` and not `commit()`. The row reaches the database and gets an ID while the transaction stays open. The caller decides when to commit — the same philosophy as M1.4's `persist_seed_batch`.
- A supplied `created_at` must be timezone-aware. A naive datetime mixed in makes baseline ordering depend on the local timezone of whatever machine ran it.
- The lookup orders by two keys, `created_at.desc(), EvalResult.id.desc()`. Two rows written in the same instant still order deterministically.
- `config` is canonicalized through `_canonical_config` before comparison. Storing and finding must pass through the same canonicalization to match.

> **Concept — why only the newest comparable row can be the baseline**
>
> Once several comparable rows exist, choosing which one to compare against is policy, and the policy here is deliberately not configurable: the newest, full stop. Any looser rule invites baseline shopping — after a bad change, comparing against the weakest historical run makes the drop vanish, and comparing against the best-ever run manufactures a crisis. Pinning the baseline to the newest comparable row means every run is judged against the world immediately before it, which is the only comparison that isolates the most recent change.
>
> The honest cost: a gate anchored to the previous run detects steps, not drift. With a nonzero tolerance, a slow slide distributed over many runs can pass every individual comparison. That trade is accepted here; watching for long-horizon drift against a fixed anchor is a different instrument, not a better default.

The focused suite's live PostgreSQL test pins the selection with three rows in one suite: a hybrid-config row at 12:00 with MRR 0.6, a vector-config row at 12:02 with MRR 0.7, and a second hybrid-config row at 12:01 with MRR 0.61. The lookup for the hybrid configuration must return the 12:01 row — the 12:02 row is newer but measures a different experiment, and the 12:00 row is comparable but no longer newest. Each wrong answer is exactly one missing filter or one missing sort away.

Lifecycle of one row, wired fully in tutorial 7: the runner measures an evaluation and records its raw per-case artifact under `data/eval_runs/`; in one transaction it asks `latest_comparable_baseline` for the previous comparable row, computes the comparison, and only then hands the new result to `persist_eval_result` — the lookup runs before the insert, so a run can never be compared against itself. The caller's commit makes the row durable, and from that moment it is the baseline the next identically configured run will find.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/evals/test_03_regression.py -q
```

Nineteen tests as of the pinned revision — the comparison rules and guards run anywhere, and the last one proves persistence against a live PostgreSQL, skipping itself with an explanation when no loopback database is reachable.

| Value the test breaks | Contract being protected |
|---|---|
| A drop exactly equal to the tolerance | The boundary verdict does not move between runs. |
| A negative or boolean tolerance | Settings that make gating meaningless are refused. |
| The same config with a different key order | The same experiment finds the same baseline. |
| A config containing `NaN` or infinity | Values that break later comparison are never stored. |
| A metric name outside the list | A value with unknown direction is never interpreted. |
| A naive `datetime` | Baseline ordering does not depend on the host environment. |

### What you should be able to explain now

- **What becomes impossible when metrics are stored without their configuration?**
  - **Answer:** No one can determine whether two numbers measured the same experiment, so a difference cannot be classified honestly as improvement or regression.
- **Why does a drop exactly equal to the tolerance need `math.isclose`?**
  - **Answer:** Floating-point subtraction may put the computed delta microscopically below the boundary, and `math.isclose` keeps an allowed boundary drop from failing unpredictably.
- **Why must latency not be passed to this comparison function?**
  - **Answer:** The current comparator does not reverse latency: it ignores latency in the metric mappings and rejects a latency tolerance. Latency is excluded because the comparator defines direction only for its three higher-is-better retrieval metrics.
- **How does baseline lookup fail without `sort_keys=True`?**
  - **Answer:** It does not fail for that reason: PostgreSQL JSONB equality ignores object-key order. Sorting keys makes serialized configuration text and artifacts deterministic, but it is not required for the database equality check.
- **Why does the difference between `flush` and `commit` matter here?**
  - **Answer:** `flush` writes the row and obtains its ID while leaving the transaction open; `commit` would take transaction ownership away from the caller.

---

[← Previous: Scoring](03-scoring.md) · [Module overview](../03-build.md) · [Next: Ablation →](05-ablation.md)
