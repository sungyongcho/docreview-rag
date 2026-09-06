# M8.4 Tutorial 4 — A parity claim needs a floor, a tolerance, and a verdict

"Korean works too" is not a claim anyone can check. **A parity statement without a defined ratio, a floor, and a tolerance regresses silently, because nothing in the system is watching the number it never named.** This document defines the ratio, gates it on the arms that claim to have fixed something, and then runs the loop once in public: baseline, failure analysis, change, re-measure, delta table.

**Prerequisite:** M8.3 is complete and `uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| The thresholds | **Write the constants** | A tolerance below single-case granularity is noise |
| `ParityMetric`, `ParityAssessment` | **Write the value objects** | An undefined ratio is `None`, never `1.0` |
| `assess_parity` | **Implement** the comparison | Comparability is checked before arithmetic |
| `parity_pairs`, `gated_assessments` | **Implement** the selection | The gate judges the fix, not the failure |
| The improvement cycle | **Run the measurement** | The deliverable is the delta table |

### 1. The numbers that set the thresholds

#### Create `app/evals/parity.py` — the constants

**Learning action — write the constants:** compute the single-case granularity of this suite first, then choose the tolerance.

<!-- src: app/evals/parity.py::DEFAULT_MIN_RECALL_RATIO,PARITY_REGRESSION_TOLERANCE,GATED_METRIC -->
```python
DEFAULT_MIN_RECALL_RATIO: Final[float] = 0.85

# One positive case out of 24 moves a macro metric by about 0.042. A tolerance below
# that would let a single flipped case fail the gate, so the standing per-language
# regression allowance sits deliberately above single-case granularity.
PARITY_REGRESSION_TOLERANCE: Final[float] = 0.05

GATED_METRIC: Final[MetricName] = "recall_at_k"
```

**What to look for in the code**

- Twenty-four scored positives per language means one case is worth about 0.042 of a macro metric. **A tolerance at or below that lets a single flipped case flap the gate, which trains everyone to ignore it.** 0.05 sits deliberately above it.
- One gated metric, not three. Recall is the claim this module makes; hit rate and MRR are reported so a reader can see *how* the recall moved, and gating all three would multiply the flap surface by three for no extra information.
- The same reasoning is why per-category slices are never gated: `exact_number` holds five cases, so one case is a fifth of the slice.

### 2. Undefined is not one

#### Extend `app/evals/parity.py` — the value objects

**Learning action — write the value objects:** decide the type of `ratio` before writing any arithmetic.

<!-- src: app/evals/parity.py::ParityMetric,ParityAssessment -->
```python
@dataclass(frozen=True, slots=True)
class ParityMetric:
    """One metric measured on both language slices of the same arm."""

    metric: MetricName
    en: float
    ko: float
    delta: float
    ratio: float | None


@dataclass(frozen=True, slots=True)
class ParityAssessment:
    """The complete cross-language verdict for one arm pair."""

    suite: str
    k: int
    case_count: int
    min_recall_ratio: float
    metrics: tuple[ParityMetric, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the gated ratio cleared its floor."""
        return not self.failures

    def metric(self, name: MetricName) -> ParityMetric:
        """Return one measured metric pair by name."""
        for result in self.metrics:
            if result.metric == name:
                return result
        raise KeyError(name)

    @property
    def recall_ratio(self) -> float | None:
        """Return the gated ko/en recall ratio, or None when the English slice is 0."""
        return self.metric(GATED_METRIC).ratio
```

**What to look for in the code**

- `ratio: float | None`. **`0/0` coerced to `1.0` reads as "the two languages agree perfectly" while describing two arms that retrieved nothing** — the type refuses to represent that.
- `passed` is derived from `failures`, not stored. A verdict that can be set independently of its reasons is a verdict that can be wrong.
- `case_count` travels with the assessment, so a rendered table can always print `n` beside the ratio.

### 3. Comparability before arithmetic

#### Extend `app/evals/parity.py` — the comparison

**Learning action — implement the comparison:** list everything that must match before a ratio means anything, then write those checks first.

<!-- src: app/evals/parity.py::assess_parity -->
```python
def assess_parity(
    en_eval: RetrievalEvaluation,
    ko_eval: RetrievalEvaluation,
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> ParityAssessment:
    """Compare two evaluations that differ only in query language.

    For each higher-is-better metric the assessment records ``delta = en - ko`` and
    ``ratio = ko / en``. The ratio is the claim the module makes — "Korean retrieves
    at least this fraction of what English retrieves" — and the delta is what the
    per-language regression gate watches over time.

    The ratio is undefined when the English slice scores 0, and that case fails
    closed. An arm whose English slice retrieves nothing has no parity to claim: the
    quotient 0/0 would read as perfect agreement while describing two dead arms.

    The two evaluations must be the same suite, the same ``k``, over the same case
    ids, under configs that agree on everything except ``query.language`` and the arm
    ``name`` that encodes it. Without that check a Korean run could be silently
    compared against an English run of a different provider or chunking, and the
    ratio would measure the wrong difference.
    """
    if not isinstance(en_eval, RetrievalEvaluation) or not isinstance(ko_eval, RetrievalEvaluation):
        raise TypeError("parity requires two RetrievalEvaluation values")
    if not math.isfinite(min_recall_ratio) or not 0.0 < min_recall_ratio <= 1.0:
        raise ValueError("min_recall_ratio must be in (0, 1]")
    if en_eval.suite != ko_eval.suite:
        raise ValueError("parity requires both evaluations to share one suite")
    if en_eval.score.k != ko_eval.score.k:
        raise ValueError("parity requires both evaluations to use the same k")

    en_ids, en_scored = _case_ids(en_eval)
    ko_ids, ko_scored = _case_ids(ko_eval)
    if en_ids != ko_ids or en_scored != ko_scored:
        raise ValueError("parity requires both evaluations to cover the same golden cases")
    if _config_identity(en_eval.config, "en") != _config_identity(ko_eval.config, "ko"):
        raise ValueError("parity arms must differ only in query language")

    en_values = en_eval.metric_values()
    ko_values = ko_eval.metric_values()
    metrics: list[ParityMetric] = []
    failures: list[str] = []
    for name in HIGHER_IS_BETTER_METRICS:
        english = en_values[name]
        korean = ko_values[name]
        ratio = None if english == 0.0 else korean / english
        metrics.append(
            ParityMetric(
                metric=name,
                en=english,
                ko=korean,
                delta=english - korean,
                ratio=ratio,
            )
        )
        if name != GATED_METRIC:
            continue
        if ratio is None:
            failures.append(f"{name}: English slice scored 0, so parity is undefined")
        elif ratio < min_recall_ratio and not math.isclose(
            ratio,
            min_recall_ratio,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            failures.append(f"{name}: ratio {ratio:.6f} is below the floor {min_recall_ratio:.6f}")

    return ParityAssessment(
        suite=en_eval.suite,
        k=en_eval.score.k,
        case_count=en_eval.score.case_count,
        min_recall_ratio=min_recall_ratio,
        metrics=tuple(metrics),
        failures=tuple(failures),
    )
```

**What to look for in the code**

- Five comparability checks run before a single division. **Without them a Korean run could be divided by an English run of a different provider or chunking, and the ratio would be a real number measuring the wrong difference.**
- `_config_identity` strips `name` and `query.language` and requires everything else to match, which is why the config contract from M8.2 had to be complete.
- The floor is inclusive at its boundary via `math.isclose`, matching the convention `app/evals/regression.py` already uses for tolerances.
- Delta and ratio are both recorded for all three metrics even though only one is gated — the ungated pair is how a reader tells "Korean found fewer spans" from "Korean found them lower down".

Parity is a ratio between two arms measured together, so it is only half the gate. `language_regression` runs each language against its own stored baseline at the 0.05 tolerance, because **raising the Korean slice while quietly dropping the English one would improve the ratio.**

### 4. The gate judges the fix, not the failure

#### Extend `app/evals/crosslingual.py` — pairing and selection

**Learning action — implement the selection:** ask what happens if the gate is pointed at the `direct` arm.

<!-- src: app/evals/crosslingual.py::parity_pairs,gated_assessments -->
```python
def parity_pairs(
    runs: Sequence[LanguageRun],
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Assess parity for every arm that was measured in both languages."""
    by_identity: dict[tuple[str, str, str | None], dict[str, LanguageRun]] = {}
    for run in runs:
        identity = (run.arm.strategy, run.arm.handling, run.arm.lexical_ranker)
        by_identity.setdefault(identity, {})[run.arm.language] = run
    assessments: list[tuple[CrosslingualArm, ParityAssessment]] = []
    ordered = sorted(
        by_identity,
        key=lambda key: (STRATEGY_ORDER[key[0]], HANDLING_ORDER[key[1]], key[2] or ""),
    )
    for identity in ordered:
        slices = by_identity[identity]
        if set(slices) != {"en", "ko"}:
            continue
        assessments.append(
            (
                slices["ko"].arm,
                assess_parity(
                    slices["en"].evaluation,
                    slices["ko"].evaluation,
                    min_recall_ratio=min_recall_ratio,
                ),
            )
        )
    return tuple(assessments)


def gated_assessments(
    assessments: Sequence[tuple[CrosslingualArm, ParityAssessment]],
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Select the shipping arms whose parity the gate is allowed to judge.

    Only a hybrid arm with language-aware handling can claim parity. The direct arm
    is the "before" measurement — gating it would make the gate report the very
    failure the module was built to expose, and passing it would mean the routing
    change had not been measured at all.
    """
    return tuple(
        (arm, assessment)
        for arm, assessment in assessments
        if arm.strategy == "hybrid" and arm.handling != "direct"
    )
```

**What to look for in the code**

- `parity_pairs` assesses everything measured in both languages, and `gated_assessments` narrows to what the gate may judge. Reporting and gating are separate on purpose: the `direct` row stays visible in every table, it just cannot fail the build.
- **Gating the `direct` arm would make the gate report the very failure the module was built to expose; passing it would mean the change had never been measured.** Neither is a gate.
- `--gate` with no routed or translated pair raises rather than exiting zero. A gate that passes because it found nothing to judge is worse than no gate.

### 5. The improvement cycle, once, in public

This is the part that makes the module a loop rather than a report. Every measured cell below is filled from the recorded run in [verification](../05-verify.md), on the `openai` provider — the arm where all three query paths were measured end to end.

#### Step 1 — baseline

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies vector hybrid --handling direct
```

| Slice | Cases | Recall@5 | Hit rate@5 | MRR |
|---|---:|---:|---:|---:|
| en | 24 | 0.395833 | 0.416667 | 0.362500 |
| ko | 24 | 0.208333 | 0.208333 | 0.105556 |
| ratio (ko/en) | 24 | 0.526316 | 0.500000 | 0.291188 |

#### Step 2 — failure analysis

Read the category slice and the diagnostics, not the aggregate. The lexical coverage run reports 4 Korean cases with zero candidates, and their ids are in `zero_candidate_case_ids`.

| Category | Cases | KO recall@5 | EN recall@5 | Gap |
|---|---:|---:|---:|---:|
| `simple_lookup` | 13 | 0.307692 | 0.653846 | 0.346154 |
| `exact_number` | 5 | 0.000000 | 0.000000 | 0.000000 |
| `multi_hop` | 6 | 0.166667 | 0.166667 | 0.000000 |

The whole gap is one category. `multi_hop` already scores the same in both languages, and `exact_number` scores zero on **both** sides, so it is an English-side retrieval gap this run happens to expose rather than a cross-lingual finding. Reading it as one would be the easiest false conclusion on this page.

Open the artifact for the worst Korean category and read the raw hits for one case. The question to answer is which component produced the top-5, and the measured answer contradicts the obvious guess: the Korean lexical component was *not* silent. Only 4 of 28 Korean questions returned nothing, the other 24 averaged 16.82 of 20 candidates, and Korean lexical recall@5 was still 0.000000. **The component that ruins a fusion is rarely the one that says nothing; it is the one that answers confidently and wrongly.**

#### Step 3 — change, then re-measure

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling direct routed translated --translator-model gpt-4.1-mini
```

| Handling | KO recall@5 | KO hit rate@5 | KO MRR | Ratio (recall) |
|---|---:|---:|---:|---:|
| direct | 0.208333 | 0.208333 | 0.105556 | 0.526316 |
| routed | 0.208333 | 0.208333 | 0.131944 | 0.526316 |
| translated | 0.395833 | 0.416667 | 0.336806 | 1.000000 |

**Routing did not fix Korean.** It flipped no case at all — recall and hit rate are unchanged to six decimals — and moved only MRR, from 0.105556 to 0.131944, by letting two already-found chunks rise once the wrong lexical list was dropped. That follows directly from step 2: dropping a component that only failed outright on 4 of 28 questions removes a ranking distortion, not a retrieval failure. Translation is what closes the gap, and it closes it exactly: the same five `simple_lookup` cases English gets, no more. Its recall and hit-rate ratios are 1.000000 while its MRR ratio is 0.929119, because the same documents come back at different ranks.

#### Step 4 — the verdict

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling routed translated --gate
echo "exit: $?"
```

| Gated arm | Ratio (recall) | Floor | Verdict |
|---|---:|---:|---|
| `xling-openai-hybrid-ts-rank-cd-routed-ko` | 0.526316 | 0.85 | FAIL |
| `xling-openai-hybrid-ts-rank-cd-translated-ko` | 1.000000 | 0.85 | PASS |

The command exits 1, because the overall gate is the conjunction over gated arms and the routed arm is below the floor. That is the cycle working: the change the design expected to succeed was entered as an arm, measured, and rejected by the gate it had to clear.

**A passing ratio is not automatically good news.** Run the same gate on `sbert-multi` and it exits 0 at a ratio of 0.909091 — while that arm's English recall is 0.229167, the weakest English hybrid number in the matrix, and its vector arm sits at a ratio of 1.666667 with Korean *above* English. The ratio cannot tell "Korean caught up" from "English fell down", which is the entire reason `language_regression` runs beside it. That same routing also lost `m3c-16`, whose Korean question carries `GDDR6` and `GDDR6X` in Latin script: genuine lexical signal, discarded wholesale by a route that assumes Korean queries have none.

**The delta table is the deliverable.** The sentence next to it is commentary, and if the two ever disagree, the table is right.

### Focused tests and the contract they keep

```bash
uv run pytest tests/crosslingual/test_05_parity.py -q
```

Expected: `11 passed`.

| What the test breaks | Contract it protects |
|---|---|
| An English slice that scored zero | The ratio is undefined and the gate fails closed |
| A ratio exactly at the floor | The boundary is inclusive, as everywhere else in this repo |
| Two evaluations of different providers | Comparability is checked before any division |
| A drop of one flipped case | The regression tolerance sits above single-case granularity |
| A rendered table with an undefined ratio | `undefined` is printed as a word, never as a number |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why is the regression tolerance 0.05 rather than 0.01?**
  - **Answer:** One case out of 24 moves a macro metric by about 0.042, so a tighter tolerance would fail the gate on noise and train everyone to ignore it.
- **Why is an undefined ratio a failure rather than a pass?**
  - **Answer:** `0/0` would read as perfect agreement while describing two arms that retrieved nothing; an arm with a dead English slice has no parity to claim.
- **Why does the gate refuse to judge the `direct` arm?**
  - **Answer:** It is the before-measurement — gating it would report the known failure, and passing it would mean the fix was never measured.
- **Why is a passing ratio not by itself good news?**
  - **Answer:** The ratio cannot tell "Korean caught up" from "English fell down", so it has to be read next to the per-language regression check.

---

[← Previous: routing and translation](03-routing-and-translation.md) · [Module overview](../03-build.md) · [Verification](../05-verify.md)
