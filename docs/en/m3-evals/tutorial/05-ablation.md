# M3.4 Tutorial 5 — Turning the deferred question into an experiment

Tutorial 4 ended on a deliberate refusal: regression judgment compares a run only against the newest baseline whose suite and canonical configuration match exactly, so it can say "this configuration got worse over time" but never "this configuration beats that one." The questions M2 deferred — which chunk size, which retrieval path, which lexical ranker — are precisely such cross-configuration questions. This document builds the layer that makes them answerable without breaking tutorial 4's rule: `app/evals/ablation.py` turns every combination of settings into a named experiment arm with recorded provenance, so the comparison happens between arms measured side by side in one run. Only the definition layer is written here; the numbers arrive in tutorial 7, where the execution layer is built.

Skip this layer and the comparison still happens — by hand, and it fails in a specific way. The committed evidence shows what is at stake: `data/eval_runs/` holds one artifact whose recall is 0.458333 and another whose recall is 0.520833, and the only reasons anyone can still tell that the first measured a 500-character corpus and the second a 1,200-character one are the arm name in each filename and the config block inside each file. Strip those and both numbers become unusable the moment the terminal scrolls away — a measurement that cannot state its own settings is not evidence, only a rumor with decimals.

So this document enforces one invariant: **every axis of an experiment appears in the arm's name, in its artifact filename, and inside the artifact's own config block — an arm that cannot state its settings is never written to disk.**

> **Concept — Ablation**
>
> The word comes from ablation studies: remove or vary exactly one component of a working system, measure again, and credit the difference to that component. Machine learning borrowed the method from lesion experiments in neuroscience, and its entire force lives in the "exactly one" — when two measurements differ in a single deliberate way, the cause has nowhere to hide.
>
> The discipline binds reading as much as running. Running a whole grid of combinations at once is fine; comparing two results that differ in more than one axis is not. A 500-character lexical arm against a 1,200-character hybrid arm says nothing about chunk size and nothing about strategy, no matter how carefully both were measured.

The matrix starts from the two axes that were recorded when the decisions were deferred.

```text
chunk target: 500, 1200          ← the value M1.3 called an experimental arm, not a conclusion
retrieval:    lexical, vector, hybrid   ← the three paths built in M2
```

Neither 500 nor 1,200 is a measured value, and nothing in this repository justifies them — that is the point. 1,200 is the M1.3 default `DEFAULT_TARGET_TEXT_CHARS`, the value whose own comment refuses to call it a conclusion; 500 is the size fixed-length splitting folklore reaches for. Both were chosen in order to be measured, not because either is known to be right.

The picture above is the plan as first drawn, and it is no longer the whole matrix. M2.9 quietly added a third axis: every strategy that actually runs a lexical query now exists once per ranker (`ts_rank_cd`, `bm25`), while `vector`, which never runs one, is not crossed — a ranker label on a vector arm would describe code that never executed. The result is a full cross over three axes with one structural hole: per chunk target, two lexical arms, two hybrid arms, and one vector arm. Ten arms, not six. The committed run proves the count:

```bash
ls data/eval_runs/20260824T203336Z-*.json | grep -v budgets | wc -l
```

This prints 10 — one raw artifact per arm of the 2026-08-24 run. "One axis at a time" therefore describes how the results are read, not how the runs are scheduled: ten rows side by side show whether hybrid beats its component paths, which ranker carries the lexical path, and which chunk size helps — and each of those judgments is read off a pair of rows that differ in that one axis alone.

The cheaper textbook design would be one-factor-at-a-time: fix a base arm and vary each axis once, five runs instead of ten. It is rejected because it assumes the axes do not interact — it would measure the ranker at one chunk size and silently generalize to the other. With the deterministic embedding provider the extra arms cost seconds, and the full cross lets every one-axis comparison be checked at both levels of the other axes.

**Because golden identity is coordinate-based, chunk size can change and the same ground truth still compares** — exactly as designed in M3.1.

**Prerequisite:** Tutorial 4's `uv run pytest tests/evals/test_03_regression.py -q` passes.

**Verification point:** This document only finishes `ablation.py`. The `RetrievalEvaluation`, `write_evaluation_artifact`, and `evaluate_retriever` symbols that it depends on are completed in tutorials 6 and 7, so run `tests/evals/test_04_ablation.py` only after tutorial 7.

### What to define, what to implement, and what to inspect

M3.4 builds three files. This document covers only `app/evals/ablation.py` — the layer that defines the arms and commits results to disk. Running the actual evaluation is the next two documents.

| Area | Learning action | What to take away |
|---|---|---|
| Strategy vocabulary and sort order | **Define the settings schema** | Why arm order must be fixed |
| `ExperimentConfig` | **Implement** the invariants yourself | How a contradictory experiment setting is made impossible |
| `to_dict()` | **Write the field mapping** | What baseline comparison looks at to decide sameness |
| `AblationOutcome` and `AblationReport` | **Write the record declarations** | What travels with a result and the comparison-table shape |
| `experiment_matrix` | **Implement** the combination generation yourself | How a stable order is imposed on three crossed axes |
| `run_ablation` | **Implement** the execution order yourself | The guard that keeps an arm and its result from drifting apart |

### 1. Strategy vocabulary and sort order

#### Create `app/evals/ablation.py` — module header

**Learning action — define the structure:** `retrieval_eval` is among the imports. This file does not evaluate; it **calls** the evaluator.

```python
"""Configurable M3 retrieval ablations with stable raw artifact paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Literal

from app.config import LexicalRanker
from app.evals.retrieval_eval import RetrievalEvaluation, write_evaluation_artifact
```

The import direction is the layering promise. This file depends on `RetrievalEvaluation` — the record shape tutorial 6 defines — and on `write_evaluation_artifact`, the writer tutorial 7 completes; it never depends on how an evaluation is executed. That is exactly why the whole file can be written now and exercised only after tutorial 7.

#### Extend `app/evals/ablation.py` — strategy vocabulary and naming rule

**Learning action — define the settings schema:** note why `STRATEGY_ORDER` is a dictionary rather than a set.

<!-- src: app/evals/ablation.py::RetrievalStrategy,EXPERIMENT_NAME -->
```python
type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type ExperimentEvaluator = Callable[["ExperimentConfig"], Awaitable[RetrievalEvaluation]]

STRATEGY_ORDER = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
DEFAULT_LEXICAL_RANKERS: tuple[LexicalRanker, ...] = ("ts_rank_cd", "bm25")
EXPERIMENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
```

**What to look for in the code**

- `STRATEGY_ORDER` maps names to integers, so one structure serves as both the validity check and the **sort key**. Alphabetical order would give hybrid, lexical, vector — backwards, because lexical and vector are the component paths and hybrid is the path that consumes them, and the comparison table should read in pipeline order.
- The `type` statement is Python 3.12's alias syntax (PEP 695): it declares `RetrievalStrategy` as a named alias whose right-hand side is evaluated lazily, so an alias may reference names defined later in the file. (The evaluator alias here writes the class name as a quoted string, which would resolve as a forward reference even without that laziness.)
- `EXPERIMENT_NAME` enforces kebab-case. An experiment name becomes part of a filename, so a space or a slash would break the artifact path.

Why not `enum.Enum`, the textbook home for a closed vocabulary? Because these values must cross module boundaries as plain strings — into config dictionaries, JSON artifacts, and test fixtures — and an enum member is not a plain string. Every boundary would need a `.value` conversion or a str-subclass workaround, and the f-string that builds an arm name would, on one forgotten conversion, render the member's qualified name into the filename instead of its value. `Literal` plus two small dictionaries keeps the vocabulary as data: the same bytes in the type checker, the filename, and the artifact.

#### Extend `app/evals/ablation.py` — arm names and the sort key

**Learning action — implement yourself:** write both functions and note what each of the four `sort_key` tuple elements pins down.

<!-- src: app/evals/ablation.py::experiment_name,sort_key -->
```python
def experiment_name(
    target_text_chars: int,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker | None,
) -> str:
    """Return the arm name, which must survive being used as a filename."""
    stem = f"structure-{target_text_chars}-{strategy}"
    return stem if lexical_ranker is None else f"{stem}-{RANKER_SLUG[lexical_ranker]}"


def sort_key(config: ExperimentConfig) -> tuple[int, int, int, str]:
    """Order arms by corpus, then retrieval path, then lexical ranker."""
    return (
        config.target_text_chars,
        STRATEGY_ORDER[config.strategy],
        -1 if config.lexical_ranker is None else RANKER_ORDER[config.lexical_ranker],
        config.name,
    )
```

**What to look for in the code**

- `experiment_name` builds the name through `RANKER_SLUG`. Leaving the underscore of `ts_rank_cd` in a filename would fail the kebab-case check in `EXPERIMENT_NAME`, so the slug table renames it to `ts-rank-cd`.
- The `sort_key` tuple orders by chunk target, then strategy, then ranker, then name. A vector arm takes `-1` for its missing ranker — the substitution keeps that slot an integer so ordering stays defined for any mix of arms, and it reads as "before every real ranker." The trailing `name` breaks ties when the first three values match.

### 2. Making a contradictory experiment setting impossible

#### Extend `app/evals/ablation.py` — experiment arm configuration

**Learning action — implement the invariants:** implement the guard chain in `__post_init__` yourself — each check refuses one whole class of contradictory arms — and work out why `to_dict()` is nested.

<!-- src: app/evals/ablation.py::ExperimentConfig -->
```python
@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """One explicit chunking and retrieval experiment arm."""

    name: str
    target_text_chars: int
    strategy: RetrievalStrategy
    embedding_provider: str
    dimensions: int
    lexical_ranker: LexicalRanker | None = None
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if EXPERIMENT_NAME.fullmatch(self.name) is None:
            raise ValueError("experiment name must be lowercase kebab-case")
        if self.target_text_chars <= 0 or self.dimensions <= 0:
            raise ValueError("chunk target and embedding dimensions must be positive")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if not self.embedding_provider.strip():
            raise ValueError("embedding_provider must be nonblank")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in RANKER_ORDER:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")

    def to_dict(self) -> dict[str, object]:
        """Return stable nested config provenance for artifacts and baselines."""
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
                "k": self.k,
                "candidate_k": self.candidate_k,
                "rrf_k": self.rrf_k,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "dimensions": self.dimensions,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
        }
```

**What to look for in the code**

- `candidate_k < self.k` is rejected. Drawing fewer candidates than the final k leaves fusion nothing to truncate — the mirror of the condition M2.5 rejected.
- `to_dict()` builds a **nested structure**, not a flat dictionary. Grouping into `chunking`, `retrieval`, `embedding`, and `measurement` means adding an axis later does not move existing keys — and the committed artifacts show the shape absorbing exactly that: the ranker axis arrived as one new key inside its own group.
- The `measurement` block matters most. `paid_api_calls` and `populated_corpus_embeddings_modified` are stored with the result, so whoever reads these numbers later knows **whether money was spent and whether the real corpus was touched.**
- `golden_identity` is pinned to `"source-sha256-and-half-open-span"`. Change how ground truth is identified and the config differs, which severs baseline comparison automatically.

> **Concept — The config is the experiment's identity**
>
> Tutorial 4 reduced "may these two runs be compared" to a mechanical rule: same suite, byte-identical canonical configuration. That rule is what gives this dataclass its real job. It is not a bag of parameters — it is the identity of the experiment, and the serialized configuration is the only thing baseline selection will consult when it decides, months from now, which past runs measured the same thing.
>
> The dangerous failure is an axis that changes behavior but is missing from the record. Two runs differing only in that axis then carry identical configurations, the regression gate matches them, and a change of measurement conditions gets reported as a quality delta. That is why the introduction's invariant demands three appearances: the name makes the axis visible to a person scanning a directory, the filename makes it visible in a list of artifacts, and the config block makes it visible to the machine. All three are generated from one dataclass, so they cannot drift apart.
>
> The honest edge: a configuration records only the axes this layer knows about. The rule that decides whether a hit counts as relevant lives in the scoring layer and appears nowhere in this dictionary, so a change to that rule would leave old and new runs looking comparable when they are not. Trusting a fingerprint includes knowing exactly where its boundary runs.

> **Concept — A measurement that records its own blast radius**
>
> An arm with chunk target 500 can only be measured against a corpus actually chunked at 500 characters, so the runner built in tutorial 7 re-chunks and re-indexes the corpus once per chunk target, and the arms of that target share it. Aimed at the production tables, that rebuild would overwrite the chunks and embeddings the seeding and backfill work already paid for. The runner therefore builds each corpus inside temporary tables that vanish when their connection closes, and the environment string in this block is the artifact's standing declaration of that isolation — every committed result carries the claim that no shared state produced it and none was harmed.
>
> The other two fields answer what a reader of an old artifact cannot reconstruct after the fact: did this run cost money, and did it modify the populated corpus. Note that the paid flag is computed conservatively — any provider other than the deterministic one is marked as paid, so a local sentence-transformers run that calls no external API still records true. Caution that overstates cost is safer than optimism that hides it, but it is a simplification worth knowing about.

### 3. The shape that puts results side by side

#### Extend `app/evals/ablation.py` — outcome records

**Learning action — write the record declarations:** note what `AblationOutcome` carries alongside the evaluation.

<!-- src: app/evals/ablation.py::AblationOutcome,AblationReport -->
```python
@dataclass(frozen=True, slots=True)
class AblationOutcome:
    """One evaluated arm and its committed raw artifact path."""

    config: ExperimentConfig
    evaluation: RetrievalEvaluation
    artifact_path: Path


@dataclass(frozen=True, slots=True)
class AblationReport:
    """Deterministically ordered experiment outcomes."""

    outcomes: tuple[AblationOutcome, ...]

    def comparison_markdown(self) -> str:
        """Render a compact comparison table backed by raw artifacts."""
        lines = [
            "| Config | Chunk target | Retrieval | Lexical ranker | Recall@k | Hit rate@k "
            "| MRR | P95 ms | Raw |",
            "|---|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for outcome in self.outcomes:
            score = outcome.evaluation.score
            lines.append(
                "| "
                f"{outcome.config.name} | {outcome.config.target_text_chars} | "
                f"{outcome.config.strategy} | {outcome.config.lexical_ranker or '-'} | "
                f"{score.recall_at_k:.6f} | "
                f"{score.hit_rate_at_k:.6f} | {score.mrr:.6f} | "
                f"{outcome.evaluation.latency.p95_ms:.3f} | "
                f"[{outcome.artifact_path.name}]({outcome.artifact_path.as_posix()}) |"
            )
        return "\n".join(lines)
```

**What to look for in the code**

- `AblationOutcome` carries `artifact_path`. One row of the table leads straight to the raw evidence file — the "never keep only aggregates" principle embedded in the data structure.
- `comparison_markdown()` fixes six decimals with `:.6f`. When two arms differ by 0.001, rounding must not make them look identical. Be honest about what the width means, though: it is a rendering guarantee, not resolution. The golden suite scores 24 positive cases carrying one or two spans each, so macro-averaged recall cannot move in steps finer than 0.5/24 ≈ 0.0208 — digits past the second decimal keep text diffs stable; they do not carry signal.
- Latency `p95_ms` sits in the same table as the quality metrics, so an arm cannot win on recall alone. How that percentile is computed — and why the tail is reported rather than the mean — is tutorial 6's subject; a forward pointer is all this table needs.

The shape is deliberately boring: frozen dataclasses in memory, JSON files on disk, one markdown table out. The industry alternative is an experiment tracker — MLflow, Weights & Biases — and it is rejected with reasons, not reflexes. A tracker earns its keep at hundreds of runs across machines and teams, but it moves the evidence out of the repository into a service. These ten arms must be reviewable in the same git history as the code that produced them, diffable in review, and readable years later with a text editor. The table is regenerated from the outcome records at will; the artifacts remain the source of record.

### 4. Deciding order across two axes

Two axes were the original design, and the section keeps that name; the pinned code crosses three, with the ranker axis subdividing every strategy that runs a lexical query. What this section actually decides is the order that keeps the larger matrix readable, and the guards that keep the crossing honest.

#### Extend `app/evals/ablation.py` — experiment matrix and artifact naming

**Learning action — implement the combination generation:** write the nested loops and the structural hole for `vector` yourself, and be able to justify every rejection guard.

<!-- src: app/evals/ablation.py::experiment_matrix,artifact_filename -->
```python
def experiment_matrix(
    *,
    target_text_chars: Sequence[int] = (500, 1200),
    strategies: Sequence[RetrievalStrategy] = ("lexical", "vector", "hybrid"),
    lexical_rankers: Sequence[LexicalRanker] = DEFAULT_LEXICAL_RANKERS,
    embedding_provider: str = "deterministic",
    dimensions: int = 384,
    k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60,
) -> tuple[ExperimentConfig, ...]:
    """Build the sorted M3 chunking-by-retrieval-by-ranker comparison matrix.

    The ranker axis crosses only the strategies that actually run a lexical query.
    Crossing it with ``vector`` as well would evaluate the same retrieval path once
    per ranker and write two artifacts that differ only in a label they did not
    use, so ``vector`` contributes exactly one arm per chunk target.
    """
    if not target_text_chars or not strategies:
        raise ValueError("experiment matrix axes must not be empty")
    if len(set(target_text_chars)) != len(target_text_chars):
        raise ValueError("chunk targets must be unique")
    if len(set(strategies)) != len(strategies):
        raise ValueError("retrieval strategies must be unique")
    lexical_strategies = [strategy for strategy in strategies if strategy != "vector"]
    if lexical_strategies:
        if not lexical_rankers:
            raise ValueError(f"{lexical_strategies[0]} retrieval requires a lexical ranker")
        if len(set(lexical_rankers)) != len(lexical_rankers):
            raise ValueError("lexical rankers must be unique")

    configs = []
    for target in target_text_chars:
        for strategy in strategies:
            rankers: tuple[LexicalRanker | None, ...] = (
                (None,) if strategy == "vector" else tuple(lexical_rankers)
            )
            for ranker in rankers:
                configs.append(
                    ExperimentConfig(
                        name=experiment_name(target, strategy, ranker),
                        target_text_chars=target,
                        strategy=strategy,
                        embedding_provider=embedding_provider,
                        dimensions=dimensions,
                        lexical_ranker=ranker,
                        k=k,
                        candidate_k=candidate_k,
                        rrf_k=rrf_k,
                    )
                )
    return tuple(sorted(configs, key=sort_key))


def artifact_filename(recorded_at: datetime, config: ExperimentConfig) -> str:
    """Return a UTC timestamped stable artifact filename."""
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{config.name}.json"
```

**What to look for in the code**

- The closing `sorted(configs, key=sort_key)` reuses section 1's four-element key. Chunk target leads, so every arm that shares one chunked corpus sits adjacent — the runner can build that corpus once per group, and the axis being compared has to be next to itself to be visible.
- Duplicate axes are rejected. `target_text_chars=(500, 500)` would run the same experiment twice and have the artifacts overwrite each other.
- `artifact_filename` requires timezone-aware input and converts to UTC. Filenames that vary with whoever ran them make sorting meaningless.
- The filename is `{timestamp}-{name}.json`, so lexical sorting is chronological sorting.
- The full ten-arm order for the default axes is pinned tuple by tuple in `tests/evals/test_04_ablation.py` — the matrix is a contract, not a convenience.

> **Concept — The life of an evaluation artifact**
>
> Born: the command tutorial 7 completes calls this file's run function, which writes one JSON per arm into the artifact directory — in this repository, data/eval_runs. The timestamp is taken once per run, so all files of one run share a single UTC prefix: a run is a family of files under one prefix.
>
> State: a committed artifact is evidence, and evidence is append-only. A new run never touches an old file — it gets a new prefix — so the directory accumulates generations instead of replacing them. It already holds two: the 2026-08-12 run has six arm files from before the ranker axis existed (their config blocks contain no ranker key at all) and preserves the finding that unrelaxed lexical retrieval scored recall 0.000000; the 2026-08-24 run has the ten arm files of the current matrix.
>
> Read: the module findings document reads the first generation and the shipped evaluation report reads the second — every row of their comparison tables links to the raw artifact it summarizes — and later modules cite those reports rather than the raw files.
>
> End of life: nothing deletes an artifact. A corpus change or a redefinition of an axis changes the configuration of future runs, which severs baseline comparison on tutorial 4's side; the old files stay behind as the honest record of a system that no longer exists.

### 5. Keeping an arm and its result from drifting apart

#### Complete `app/evals/ablation.py` — running the ablation

**Learning action — implement the execution order:** implement the three guards yourself. One of them is a different kind from the other two.

<!-- src: app/evals/ablation.py::run_ablation -->
```python
async def run_ablation(
    configs: Sequence[ExperimentConfig],
    evaluator: ExperimentEvaluator,
    *,
    artifact_dir: str | Path,
    recorded_at: datetime,
) -> AblationReport:
    """Evaluate sorted unique arms and write one raw artifact per arm."""
    if not configs:
        raise ValueError("ablation configs must not be empty")
    names = [config.name for config in configs]
    if len(names) != len(set(names)):
        raise ValueError("ablation config names must be unique")
    ordered = sorted(configs, key=sort_key)
    directory = Path(artifact_dir)
    outcomes: list[AblationOutcome] = []
    for config in ordered:
        evaluation = await evaluator(config)
        if evaluation.config != config.to_dict():
            raise ValueError(f"evaluation config does not match arm {config.name}")
        path = directory / artifact_filename(recorded_at, config)
        write_evaluation_artifact(path, evaluation)
        outcomes.append(
            AblationOutcome(
                config=config,
                evaluation=evaluation,
                artifact_path=path,
            )
        )
    return AblationReport(outcomes=tuple(outcomes))
```

**What to look for in the code**

- `if evaluation.config != config.to_dict()` is that different one. It verifies the result the evaluator returned **really belongs to this arm**. Without it, an evaluator bug stores a 500-character result in the 1200-character arm's artifact, and whoever reads that file can never find out. It is also the moment the introduction's invariant gets enforced: name, filename, and recorded config all come off the same dataclass right here, at write time, so the three appearances cannot drift.
- `sorted` is called again here. `experiment_matrix` already sorted, but a caller may pass a hand-built list. Artifact order must not depend on input order.
- Duplicate names are rejected. Identical names make the second artifact overwrite the first.
- The evaluator is **injected**. That lets tests verify this layer's ordering and guards entirely without a database or embeddings.

### Contracts to verify after tutorial 7

The focused test for these contracts needs both the record and execution layers of `retrieval_eval.py`. Run it after tutorial 7; for now, finish writing only `ablation.py`.

| Value the test breaks | Contract being protected |
|---|---|
| A config with `candidate_k` below `k` | No arm is built where fusion has nothing to truncate. |
| Duplicate chunk targets or strategies | The same experiment does not run twice and overwrite artifacts. |
| A naive `datetime` | Artifact names do not depend on the host timezone. |
| An evaluator returning a different config | A result is never stored under the wrong arm. |
| The same arms in a different order | Artifact order does not depend on input order. |

### What you should be able to explain now

- **Why does an ablation change only one axis at a time?**
  - **Answer:** If two axes change together, the resulting difference cannot be attributed to either one.
- **Why is `STRATEGY_ORDER` a dictionary rather than a set?**
  - **Answer:** The dictionary provides both membership validation and a stable pipeline-order number; a set supplies no deterministic order.
- **Why must the `measurement` block of `to_dict()` be stored with the result?**
  - **Answer:** It preserves whether paid calls were made and whether the real corpus was modified, so later readers know the conditions and cost behind the number.
- **Why does chunk size precede strategy in the sort key?**
  - **Answer:** It groups all strategies that share one chunked corpus, giving the matrix a stable order and allowing that corpus to be built once for the group.
- **Which fault stays hidden forever if the evaluator's returned config is not re-checked?**
  - **Answer:** A result produced for one arm can be stored under another arm's name, permanently misattributing its metrics to the wrong settings.

---

[← Previous: Regression](04-regression.md) · [Module overview](../03-build.md) · [Next: Evaluation records →](06-evaluation-records.md)
