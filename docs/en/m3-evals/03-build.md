# M3 Build — Make Every Number Answerable

## Three decisions M2 deferred

The previous chapter closed by writing this down.

- the HNSW index is measured and decided **later**
- reranking is built but **not switched on**
- `rrf_k = 60` is **subject to experiment**

All of them were deferred on the grounds that "measurement will tell." Now the measuring instrument gets built.

The catch is that measuring is not easy. Producing the number "recall 0.82" is not hard. Making that number **trustworthy** is.

- what evidence was treated as correct when measuring it?
- what configuration was running?
- is it even permissible to compare it against yesterday's 0.79?

A score that cannot answer those three is no better than none. Tuning always reaches a moment where you must judge "improvement or noise," and without an answer you decide by feel.

## What you will build

| Step | Concept | Canonical files | Focused test |
|---|---|---|---|
| M3.1 | Golden evidence is immutable raw-source identity | `types.py`, `loader.py`, `__init__.py` | `test_01_contract.py`, `test_02_loader.py` |
| M3.2 | Ranking quality is pure deterministic span math | `scoring.py` | `test_02_scoring.py` |
| M3.3 | Only identical configs share a baseline | `regression.py`, existing `EvalResult` | `test_03_regression.py` |
| M3.4 | Experiments preserve raw evidence and measured cost | `ablation.py`, `retrieval_eval.py`, `__main__.py` | `test_04_ablation.py`, `test_05_runner.py` |
| M3.5 | Suite growth is gated curation, not appending | `curation.py`, `breakdown.py` | `test_07_curation.py` |

```text
raw corpus + manifest + golden JSON   →  strict GoldenCase values
GoldenCase spans + ranked ChunkHit    →  deterministic SuiteScore
SuiteScore + canonical config         →  regression comparison  →  EvalResult
experiment matrix                     →  isolated PostgreSQL corpus → raw artifacts + budget evidence
candidate JSON + review decisions     →  gated golden growth + taxonomy breakdown
```

One principle runs through every layer. **The raw source hash and half-open span remain the identity at each level.** M3 measures retrieval behavior; it never rewrites golden evidence to make a result pass.

## Starting conditions

Install the locked environment, start loopback PostgreSQL, and prove the M2 boundary.

```bash
uv sync --group dev
docker compose up -d db
uv run pytest tests/retrieval -q
```

The M3.1–M3.3 contract tests need no database apart from an optional persistence proof. M3.4 uses temporary PostgreSQL tables so experiments never overwrite the real corpus vectors.

Work on `zero` and do not create `_mine.py` files or alternate test modules.


---

## Tutorial — built in nine sittings

M3 produces ten files and 2,210 lines of source. That is more than one sitting, so it is split into nine stretches. Each document targets **under 30 minutes** to read and implement.

| Document | Checkpoint | Files built | Approx. |
|---|---|---|---|
| [1. Golden types](tutorial/01-golden-types.md) | M3.1 | `types.py` | 20 min |
| [2. Golden loader](tutorial/02-golden-loader.md) | M3.1 | `loader.py`, `__init__.py` | 30 min |
| [3. Scoring](tutorial/03-scoring.md) | M3.2 | `scoring.py` | 25 min |
| [4. Regression](tutorial/04-regression.md) | M3.3 | `regression.py` | 30 min |
| [5. Ablation](tutorial/05-ablation.md) | M3.4 | `ablation.py` | 25 min |
| [6. Evaluation records](tutorial/06-evaluation-records.md) | M3.4 | `retrieval_eval.py` (front) | 30 min |
| [7. Evaluation run](tutorial/07-evaluation-run.md) | M3.4 | `retrieval_eval.py` (execution) | 30 min |
| [8. Isolated run and CLI](tutorial/08-evaluation-cli.md) | M3.4 | `retrieval_eval.py` (close), `__main__.py` | 30 min |
| [9. Golden curation](tutorial/09-golden-curation.md) | M3.5 | `curation.py`, `breakdown.py` | 30 min |

Follow them in order. Do not move on while a stretch's focused test is failing.

The [reference baseline](#reference-baseline--the-complete-canonical-files) below is not a shortcut past the learning; it is the **standard you check your own work against**.

---

## When the numbers look wrong

When a gate fails, preserve the failing raw file first. Then investigate **from the lowest layer upward.**

```
source identity  →  span math  →  comparable config  →  retrieval
```

If a lower layer is wrong, every number above it is meaningless, so starting from the top wastes time.

And the most important rule in this chapter: **never edit golden spans to make an experiment pass.** Fit the answers to the results and this entire apparatus becomes pointless. See [bugs and design traps](04-bugs.md) for specific symptoms and [verification](05-verify.md) for the final command order.

### Measurement boundary — retrieval and generation are different evaluations

Recall@k, Hit Rate@k, and MRR in this chapter are all **retrieval evaluations**. They can say whether the source spans needed for an answer appeared among the top results. They cannot say whether an LLM given that evidence wrote a factually supported answer. Retrieval recall can be 1.0 while the model transcribes a number incorrectly, mixes fiscal years, or adds a conclusion absent from the evidence.

The reverse distinction matters too. A wrong final answer does not necessarily mean retrieval failed: the right evidence may have been retrieved and then misread during generation. Diagnosis therefore has to measure **retrieval failure** and **generation failure** as separate layers. M3 implements only the former, and M4 validates citation provenance rather than scoring claim-level factual support.

---

## Not all nine stretches are equally hard

There are five checkpoints but nine documents because M3.4 is large. Split by kind, they look like this.

| Kind | Checkpoints | Learning action |
|---|---|---|
| Contract declaration | M3.1 | **Write the model declarations** — deciding how to express the answer is the whole job |
| Algorithm | M3.2 | **Implement** the metric calculations yourself — spend the time here |
| Decision rules | M3.3 | **Implement** the comparability test yourself |
| Execution and arrangement | M3.4 | **Write the structure, then review the call order** |
| Data governance | M3.5 | **Implement** the curation gates yourself — the breakdown reuses M3.2 |

The decision in M3.1 to define the answer as a **source coordinate range** rather than a chunk id governs the whole chapter. Change that one line and the premise of the other eight documents collapses.

## Concepts you meet here first

Retrieval quality metrics have similar names and are easy to conflate. Each answers a different question.

**Golden set.** A hand-curated list of questions and the evidence that answers them. Here the answer is recorded not as "chunk 12" but as a **character range in the source**. Change the chunk size and every chunk id changes, but the source coordinates do not — so the same golden set can compare different chunking strategies.

**Recall@k.** Asks how many of the answer spans appear in the top k. Five answers with three in the top ten gives 0.6. It **counts against the answers, not against the results**.

**Hit rate@k.** A binary value asking whether the top k contains any answer at all. Blunter than recall@k, but it directly counts the cases where a user gets nothing.

**MRR (Mean Reciprocal Rank).** Asks what position the first answer took. First place scores 1, second 1/2, third 1/3, averaged over questions. Instead of counting answers it measures the **distance to the first one** — the metric that matters when a system shows only the top few on screen.

**Ablation.** An experiment that varies one setting at a time to measure how much that setting contributes. It answers questions like how much recall shifts when `rrf_k` goes from 60 to 10. Change several at once and there is no telling which one contributed, so **only one changes per run**.

## M3.1 — Fix the answer as source coordinates

Record golden evidence as chunk ids and the entire golden set becomes invalid the moment chunk size changes. So the answer is recorded as the source document's SHA-256 plus a half-open character range. This is where M1.3's coordinate-based citation design pays off. The loader reads that JSON strictly and rejects — rather than quietly skipping — a reversed range or a hash that does not match the corpus.

**Document:** [1. Golden types](tutorial/01-golden-types.md), [2. Golden loader](tutorial/02-golden-loader.md) · **Passing:** `uv run pytest tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q`

## M3.2 — Keep scoring a pure calculation

The scoring layer performs no I/O at all. It takes golden ranges and ranked hits and returns numbers. The reason that constraint matters is simple: if scoring reads the database, a changed score gives no way to tell whether retrieval changed or the data did. Range matches are decided by overlap ratio rather than exact equality, and a per-case (macro) average keeps questions with many answers from dominating the result.

**Document:** [3. Scoring](tutorial/03-scoring.md) · **Passing:** `uv run pytest tests/evals/test_02_scoring.py -q`

## M3.3 — Regression baselines

Comparing yesterday's 0.79 with today's 0.82 requires that the two runs **measured the same thing**. If the golden set changed, or top-k differed, or the embedding model was swapped, the two numbers are not comparable. So the baseline stores a configuration fingerprint alongside the score, and when the fingerprints differ it declares neither improvement nor regression. Treating incomparability as a quiet pass is the most dangerous mistake available in this layer.

**Document:** [4. Regression](tutorial/04-regression.md) · **Passing:** `uv run pytest tests/evals/test_03_regression.py -q`

## M3.4 — Experiments preserve raw evidence and cost

Now the questions deferred in M2 get answered. Ablation runs vary one setting at a time and keep each run's raw artifacts alongside its tokens and cost. Keep only the summary number and there is later no way to answer how that value came about. Runs use temporary PostgreSQL tables so they never overwrite the real corpus vectors.

**Document:** [5. Ablation](tutorial/05-ablation.md) through [8. Isolated runs and CLI](tutorial/08-evaluation-cli.md) · **Passing:** `uv run pytest tests/evals/test_04_ablation.py tests/evals/test_05_runner.py tests/evals/test_06_postgres.py -q`

## M3.5 — Suite growth is gated curation

The golden set is now the measuring instrument, so growing it is a governed pipeline rather than an append. Generated candidates enter a separate `m3s` namespace, machine gates re-run every mechanical proof the loader trusts plus duplicate and span-width checks, and only an explicitly recorded human decision lets promotion mint the next `m3c` ids — still pending author approval, because admission is not certification. The same checkpoint adds the taxonomy breakdown that turns one aggregate recall into a per-category failure map.

**Document:** [9. Golden curation](tutorial/09-golden-curation.md) · **Passing:** `uv run pytest tests/evals/test_07_curation.py -q`

## What you should be able to explain now

- **Why is a golden answer recorded as a source coordinate rather than a chunk id?**
  - **Answer:** Source coordinates remain stable when the same filing is re-chunked, while chunk IDs change, so one golden set can compare different chunk sizes.
- **How do the questions answered by Recall@k and MRR differ?**
  - **Answer:** Recall@k measures the fraction of gold spans matched within the first k hits. MRR uses the reciprocal rank of the first match within those same k hits and is zero when no match appears there.
- **What becomes undecidable if the scoring layer performs even one I/O?**
  - **Answer:** A changed score can no longer be attributed confidently to retrieval rather than to changing external state or an I/O failure inside the measuring instrument.
- **What false conclusion follows from comparing two scores with different configuration fingerprints?**
  - **Answer:** A change caused by a different experiment can be mislabeled as an improvement or regression in the retrieval system.
- **Why does an ablation change only one setting at a time?**
  - **Answer:** Holding every other axis fixed is the only way to attribute the score difference to the setting under test.
- **What becomes impossible later if only summary numbers are kept and raw artifacts discarded?**
  - **Answer:** The result cannot be audited or diagnosed case by case, because the exact hits and evidence that produced the aggregate are gone.
- **Why can the final answer still be wrong after the retrieval evaluation passes?**
  - **Answer:** M3 has no absolute retrieval-quality pass. Its metrics measure how much the top-k results overlap annotated spans under the 0.05 IoU rule; they do not prove evidence completeness or claim support, and generation can still misread the evidence or add unsupported claims.
- **Why does a generated candidate never carry an `m3c` id?**
  - **Answer:** The golden namespace is the frozen answer key, so ids are minted only at promotion after an explicit human approval; anything earlier would open a path for unreviewed claims to enter measurements.

## What this module hands to the next one

M3 completes the **retrieval system**. From here M4 puts an LLM on top of it.

| What M3 produced | Receiver | What happens there |
|---|---|---|
| the validated configuration (chunk size, strategy, k) | **M4, M5** | the basis for production defaults |
| `EvalResult` regression baselines | **M7** | the quality gate in CI |
| budget measurements | **M5, M7** | the basis for latency budgets |
| the 28 golden cases | **M4** | the starting point for workflow evaluation |
| raw artifacts | **M6** | the evidence shown in the demo |

M3's real output is not code but **grounds for saying "this configuration is better."** Reaching here means parameters can be set with numbers instead of instinct.

The next chapter, M4, builds an LLM workflow on this retrieval. And the moment an LLM enters, new problems arrive — **the output is not deterministic, it costs money, and it states wrong answers with confidence.** So M4 nails budget ceilings, schema validation, and citation-provenance checks into the workflow. M3's principle of putting evidence behind every number becomes "make every citation trace back to retrieved evidence" there. Evaluating the factual support of each sentence remains a separate task.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M3.1 — Complete checkpoint

#### Create or replace `app/evals/__init__.py`

<!-- file: app/evals/__init__.py -->
```python
"""Public contracts and loader for the M3 evaluation milestone."""

from app.evals.loader import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_MANIFEST_PATH,
    GoldenDataError,
    load_golden_cases,
    validate_golden_sources,
)
from app.evals.types import (
    ExpectedLabel,
    GoldenCase,
    GoldenCategory,
    GoldenFacet,
    GoldenSpan,
    GoldenTag,
)

__all__ = [
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_MANIFEST_PATH",
    "ExpectedLabel",
    "GoldenCase",
    "GoldenCategory",
    "GoldenDataError",
    "GoldenFacet",
    "GoldenSpan",
    "GoldenTag",
    "load_golden_cases",
    "validate_golden_sources",
]
```

#### Create or replace `app/evals/types.py`

<!-- file: app/evals/types.py -->
```python
"""Strict, source-stable value objects for retrieval evaluation data."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

GoldenCategory = Literal["simple_lookup", "exact_number", "multi_hop", "absent"]
GoldenFacet = Literal["factual", "comparison", "risk", "policy", "numeric"]
ExpectedLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]
GoldenTag = Annotated[StrictStr, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class GoldenSpan(BaseModel):
    """One half-open answer span in an immutable raw filing snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: Annotated[StrictStr, Field(min_length=1, max_length=32)]
    source_sha256: SourceSha256
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]

    @model_validator(mode="after")
    def validate_half_open_span(self) -> Self:
        """Reject empty or reversed source intervals."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


class GoldenCase(BaseModel):
    """One reviewed-question candidate and its retrieval ground truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[StrictStr, Field(pattern=r"^m3c-[0-9]{2}$")]
    question: Annotated[StrictStr, Field(min_length=1)]
    category: GoldenCategory
    facet: GoldenFacet
    tags: tuple[GoldenTag, ...]
    answers: tuple[GoldenSpan, ...]
    expected_label: ExpectedLabel
    reference_answer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]
    curation_status: Literal["agent-curated"]
    approval_status: Literal["pending-author-approval"]
    human_verified: Literal[False]

    @field_validator("human_verified", mode="before")
    @classmethod
    def require_literal_false(cls, value: object) -> object:
        """Reject false-like values that could imply an ambiguous review status."""
        if value is not False:
            raise ValueError("human_verified must be the JSON boolean false")
        return value

    @field_validator("question", "reference_answer", "note", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject strings that contain only whitespace."""
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value

    @field_validator("tags", mode="after")
    @classmethod
    def reject_duplicate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        """Keep tag membership unambiguous without silently rewriting input."""
        if len(tags) != len(set(tags)):
            raise ValueError("tags must be unique")
        return tags

    @model_validator(mode="after")
    def validate_label_and_answers(self) -> Self:
        """Keep positive and absent-case contracts mutually exclusive."""
        identities = {
            (answer.doc_id, answer.source_sha256, answer.start_char, answer.end_char)
            for answer in self.answers
        }
        if len(identities) != len(self.answers):
            raise ValueError("answer spans must be unique within a case")

        if self.category == "absent":
            if self.answers:
                raise ValueError("absent cases must not contain answer spans")
            if self.expected_label != "NOT_IN_DOCS":
                raise ValueError("absent cases must expect NOT_IN_DOCS")
            if self.reference_answer != "NOT_IN_DOCS":
                raise ValueError("absent cases must use the NOT_IN_DOCS reference answer")
        else:
            if not self.answers:
                raise ValueError("positive cases must contain at least one answer span")
            if self.expected_label != "SUPPORTED":
                raise ValueError("positive cases must expect SUPPORTED")
            if self.reference_answer == "NOT_IN_DOCS":
                raise ValueError("positive cases must include a supported reference answer")
        return self
```

#### Create or replace `app/evals/loader.py`

<!-- file: app/evals/loader.py -->
```python
"""Load strict golden cases and bind every positive span to the raw corpus."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pydantic import TypeAdapter, ValidationError

from app.evals.types import GoldenCase

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "corpus" / "manifest.json"
GOLDEN_CASES = TypeAdapter(list[GoldenCase])


class GoldenDataError(ValueError):
    """A golden file or its cited source snapshot violates the M3 contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoldenDataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except GoldenDataError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenDataError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _golden_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise GoldenDataError(f"no golden JSON files found in {path}")
        return files
    return [path]


def _validate_unique_cases(cases: Iterable[GoldenCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    answer_identities: set[tuple[str, str, int, int]] = set()
    for case in cases:
        if case.id in ids:
            raise GoldenDataError(f"duplicate golden case id: {case.id}")
        ids.add(case.id)

        normalized = " ".join(case.question.casefold().split())
        if normalized in questions:
            raise GoldenDataError(f"duplicate normalized question: {case.question}")
        questions.add(normalized)

        for answer in case.answers:
            identity = (
                answer.doc_id,
                answer.source_sha256,
                answer.start_char,
                answer.end_char,
            )
            if identity in answer_identities:
                raise GoldenDataError(f"duplicate answer span identity in {case.id}")
            answer_identities.add(identity)


def _resolve_source_path(file_name: str, manifest_path: Path) -> Path:
    source = Path(file_name)
    if source.is_absolute() and source.is_file():
        return source

    bases = [Path.cwd(), REPO_ROOT, manifest_path.resolve().parent]
    bases.extend(manifest_path.resolve().parents)
    for base in bases:
        candidate = (base / source).resolve()
        if candidate.is_file():
            return candidate
    raise GoldenDataError(f"manifest source file does not exist: {file_name}")


def _manifest_sources(manifest_path: Path) -> dict[str, Path]:
    payload = _read_json(manifest_path)
    if not isinstance(payload, list):
        raise GoldenDataError("corpus manifest root must be a JSON array")

    sources: dict[str, Path] = {}
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise GoldenDataError(f"manifest entry {index} must be an object")
        try:
            ticker = entry["ticker"]
            report_date = entry["report_date"]
            file_name = entry["file"]
        except KeyError as exc:
            raise GoldenDataError(f"manifest entry {index} is missing {exc.args[0]}") from exc
        if not all(isinstance(value, str) and value for value in (ticker, report_date, file_name)):
            raise GoldenDataError(f"manifest entry {index} has invalid identity fields")
        if len(report_date) < 4 or not report_date[:4].isdigit():
            raise GoldenDataError(f"manifest entry {index} has an invalid report_date")

        doc_id = f"{ticker}-FY{report_date[:4]}"
        if doc_id in sources:
            raise GoldenDataError(f"duplicate manifest document id: {doc_id}")
        sources[doc_id] = _resolve_source_path(file_name, manifest_path)
    return sources


def validate_golden_sources(
    cases: Iterable[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Verify each positive span against its exact UTF-8 source and SHA-256."""
    sources = _manifest_sources(Path(manifest_path))
    cache: dict[str, tuple[str, str]] = {}

    for case in cases:
        for answer in case.answers:
            source_path = sources.get(answer.doc_id)
            if source_path is None:
                raise GoldenDataError(f"{case.id} cites unknown corpus document {answer.doc_id}")
            if answer.doc_id not in cache:
                try:
                    source_bytes = source_path.read_bytes()
                    raw_source = source_bytes.decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    raise GoldenDataError(
                        f"cannot read UTF-8 source for {answer.doc_id}: {exc}"
                    ) from exc
                cache[answer.doc_id] = (
                    raw_source,
                    hashlib.sha256(source_bytes).hexdigest(),
                )

            raw_source, source_sha256 = cache[answer.doc_id]
            if answer.source_sha256 != source_sha256:
                raise GoldenDataError(f"{case.id} source hash does not match {answer.doc_id}")
            if answer.end_char > len(raw_source):
                raise GoldenDataError(
                    f"{case.id} span ends beyond {answer.doc_id}: "
                    f"{answer.end_char} > {len(raw_source)}"
                )
            evidence = BeautifulSoup(
                raw_source[answer.start_char : answer.end_char],
                "html.parser",
            ).get_text(" ", strip=True)
            if not evidence:
                raise GoldenDataError(
                    f"{case.id} span has no visible source evidence in {answer.doc_id}"
                )


def load_golden_cases(
    path: str | Path = DEFAULT_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[GoldenCase]:
    """Load one file or a directory of files and validate all source citations."""
    cases: list[GoldenCase] = []
    for golden_path in _golden_files(Path(path)):
        payload = _read_json(golden_path)
        if not isinstance(payload, list):
            raise GoldenDataError(f"golden file root must be a JSON array: {golden_path}")
        try:
            cases.extend(GOLDEN_CASES.validate_python(payload))
        except ValidationError as exc:
            raise GoldenDataError(f"invalid golden cases in {golden_path}: {exc}") from exc

    _validate_unique_cases(cases)
    validate_golden_sources(cases, manifest_path)
    return cases
```

Run the checkpoint:

```bash
uv run pytest tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M3.2 — Complete checkpoint

#### Create or replace `app/evals/scoring.py`

<!-- file: app/evals/scoring.py -->
```python
"""Deterministic span-overlap scoring for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.evals.types import GoldenSpan
from app.retrieval.types import ChunkHit

IOU_THRESHOLD: Final[float] = 0.05


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

Run the checkpoint:

```bash
uv run pytest tests/evals/test_02_scoring.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M3.3 — Complete checkpoint

#### Create or replace `app/evals/regression.py`

<!-- file: app/evals/regression.py -->
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

type MetricName = Literal["recall_at_k", "hit_rate_at_k", "mrr"]

HIGHER_IS_BETTER_METRICS: Final[tuple[MetricName, ...]] = (
    "recall_at_k",
    "hit_rate_at_k",
    "mrr",
)


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

Run the checkpoint:

```bash
uv run pytest tests/evals/test_03_regression.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M3.4 — Complete checkpoint

#### Create or replace `app/evals/ablation.py`

<!-- file: app/evals/ablation.py -->
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

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type ExperimentEvaluator = Callable[["ExperimentConfig"], Awaitable[RetrievalEvaluation]]

STRATEGY_ORDER = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
DEFAULT_LEXICAL_RANKERS: tuple[LexicalRanker, ...] = ("ts_rank_cd", "bm25")
EXPERIMENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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

#### Create or replace `app/evals/retrieval_eval.py`

<!-- file: app/evals/retrieval_eval.py -->
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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
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

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]
type Clock = Callable[[], int]

INDEXING_BUDGET_SECONDS = 300.0
QUERY_BUDGET_COUNT = 200
QUERY_BUDGET_SECONDS = 90.0
RAW_ARTIFACT_SCHEMA_VERSION = 1


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


async def evaluate_retriever(
    cases: Sequence[GoldenCase],
    retriever: Retriever,
    *,
    suite: str,
    config: Mapping[str, Any],
    k: int = 5,
    clock: Clock = time.perf_counter_ns,
    recorded_at: datetime | None = None,
) -> RetrievalEvaluation:
    """Evaluate every case once while scoring only source-bearing positives."""
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be nonblank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    ordered = tuple(sorted(cases, key=lambda case: case.id))
    if not ordered:
        raise ValueError("golden cases must not be empty")
    if len({case.id for case in ordered}) != len(ordered):
        raise ValueError("golden case ids must be unique")
    provenance = _golden_provenance(ordered)

    results: list[CaseEvaluation] = []
    scores: list[CaseScore] = []
    latencies: list[float] = []
    for case in ordered:
        started = clock()
        hits = tuple(await retriever(case.question, k))
        elapsed_ms = (clock() - started) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        case_score = score_case(case.id, case.answers, hits, k) if case.answers else None
        if case_score is not None:
            scores.append(case_score)
        results.append(
            CaseEvaluation(
                golden=case,
                latency_ms=elapsed_ms,
                hits=hits,
                score=case_score,
            )
        )

    return RetrievalEvaluation(
        suite=suite,
        recorded_at=recorded_at or datetime.now(UTC),
        config=_canonical_config(config),
        provenance=provenance,
        score=score_suite(scores),
        latency=_latency_summary(latencies),
        cases=tuple(results),
    )


def write_evaluation_artifact(path: str | Path, evaluation: RetrievalEvaluation) -> Path:
    """Write one stable UTF-8 raw artifact and return its path."""
    artifact_path = Path(path)
    if artifact_path.suffix != ".json":
        raise ValueError("evaluation artifact path must end in .json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        evaluation.artifact_payload(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    artifact_path.write_text(payload + "\n", encoding="utf-8")
    return artifact_path


async def measure_query_budget(
    queries: Sequence[str],
    retriever: Retriever,
    *,
    k: int = 5,
    query_count: int = QUERY_BUDGET_COUNT,
    budget_seconds: float = QUERY_BUDGET_SECONDS,
    clock: Clock = time.perf_counter_ns,
) -> QueryBudgetMeasurement:
    """Repeat nonempty queries sequentially and assess the wall-clock budget."""
    if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("queries must contain nonblank strings")
    if isinstance(query_count, bool) or not isinstance(query_count, int) or query_count <= 0:
        raise ValueError("query_count must be a positive integer")
    if k <= 0:
        raise ValueError("k must be positive")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")

    previous = clock()
    latencies: list[float] = []
    for index in range(query_count):
        await retriever(queries[index % len(queries)], k)
        current = clock()
        elapsed_ms = (current - previous) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        previous = current

    summary = _latency_summary(latencies)
    total_seconds = summary.total_ms / 1_000
    return QueryBudgetMeasurement(
        query_count=query_count,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
        mean_ms=summary.mean_ms,
        p50_ms=summary.p50_ms,
        p95_ms=summary.p95_ms,
        max_ms=summary.max_ms,
    )


def assess_indexing_budget(
    *,
    target_text_chars: int,
    document_count: int,
    chunk_count: int,
    embedding_provider: str,
    total_seconds: float,
    budget_seconds: float = INDEXING_BUDGET_SECONDS,
) -> IndexingBudgetMeasurement:
    """Validate and assess one measured indexing duration."""
    if target_text_chars <= 0 or document_count <= 0 or chunk_count <= 0:
        raise ValueError("indexing counts and target_text_chars must be positive")
    if not embedding_provider.strip():
        raise ValueError("embedding_provider must be nonblank")
    if not math.isfinite(total_seconds) or total_seconds < 0:
        raise ValueError("total_seconds must be finite and nonnegative")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")
    return IndexingBudgetMeasurement(
        target_text_chars=target_text_chars,
        document_count=document_count,
        chunk_count=chunk_count,
        embedding_provider=embedding_provider,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
    )


def make_retriever(
    session: AsyncSession,
    *,
    strategy: RetrievalStrategy,
    provider: EmbeddingProvider | None,
    lexical_ranker: LexicalRanker | None = None,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one explicit retrieval strategy and lexical ranker to a session.

    The ranker is required exactly when the strategy runs a lexical query, so an
    arm can never be measured under a ranker it did not use, and a vector arm can
    never be labelled with one it never touched.
    """
    if strategy not in {"lexical", "vector", "hybrid"}:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    if strategy == "vector":
        if lexical_ranker is not None:
            raise ValueError("vector retrieval must not name a lexical ranker")
    elif lexical_ranker not in {"ts_rank_cd", "bm25"}:
        raise ValueError(f"{strategy} retrieval requires an explicit lexical ranker")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if strategy in {"vector", "hybrid"} and provider is None:
        raise ValueError(f"{strategy} retrieval requires an embedding provider")

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        if candidate_k < k:
            raise ValueError("candidate_k must be at least k")
        if strategy == "lexical":
            if lexical_ranker == "bm25":
                return await bm25_search(session, query, k, filters)
            return await lexical_search(session, query, k, filters)
        assert provider is not None
        if strategy == "vector":
            query_vector = await provider.embed_query(query)
            return await vector_search(session, query_vector, k=k, filters=filters)
        result = await retrieve(
            session,
            query,
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
            lexical_ranker=lexical_ranker,
        )
        return result.hits

    return run


async def persist_evaluation(
    session: AsyncSession,
    evaluation: RetrievalEvaluation,
    *,
    raw_artifact_path: str | Path,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> PersistedEvaluation:
    """Persist one run and compare it with the latest suite/config baseline."""
    baseline = await latest_comparable_baseline(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
    )
    comparison = (
        compare_against_baseline(
            baseline.metrics,
            evaluation.metric_values(),
            tolerances=tolerances,
        )
        if baseline is not None
        else None
    )
    result = await persist_eval_result(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
        metrics=evaluation.metric_values(),
        raw_artifact_path=raw_artifact_path,
        created_at=evaluation.recorded_at,
    )
    if result.id is None:
        raise RuntimeError("persisted evaluation did not receive an id")
    return PersistedEvaluation(
        result_id=result.id,
        baseline_id=baseline.id if baseline is not None else None,
        comparison=comparison,
    )


def build_chunking_batch(
    target_text_chars: int,
    *,
    settings: Settings | None = None,
) -> SeedBatch:
    """Build one source-stable corpus arm without changing the canonical golden spans."""
    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / "manifest.json")
    chunk_config = ChunkConfig(target_text_chars=target_text_chars)
    return build_seed_batch(
        entries,
        expected_documents=20,
        chunker=lambda filing: chunk_filing(filing, chunk_config),
    )


async def _create_temporary_corpus_tables(connection: AsyncConnection, dimensions: int) -> None:
    extension = await connection.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    if extension is None:
        raise RuntimeError("the configured PostgreSQL database does not have pgvector")
    await connection.execute(
        text(
            """
            CREATE TEMP TABLE documents (
                doc_id varchar(32) PRIMARY KEY,
                ticker varchar(16) NOT NULL,
                cik bigint NOT NULL,
                fiscal_year integer NOT NULL,
                form varchar(16) NOT NULL,
                filing_date varchar(10) NOT NULL,
                report_period varchar(10) NOT NULL,
                accession varchar(32) NOT NULL,
                url text NOT NULL,
                parse_status varchar(32) NOT NULL,
                item_index jsonb NOT NULL,
                source_length bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(
        text(
            f"""
            CREATE TEMP TABLE chunks (
                id bigserial PRIMARY KEY,
                doc_id varchar(32) NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                item varchar(8),
                kind varchar(16) NOT NULL,
                ordinal integer NOT NULL,
                body text NOT NULL,
                context_header text NOT NULL,
                index_text text NOT NULL,
                start_char bigint NOT NULL,
                end_char bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL,
                citation text NOT NULL,
                embedding vector({dimensions}),
                content_tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', index_text)
                ) STORED,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (doc_id, ordinal)
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(text("CREATE INDEX ON chunks USING gin (content_tsv)"))
    for statement in (
        """
        CREATE TEMP TABLE chunk_terms (
            chunk_id bigint NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            lexeme text NOT NULL,
            tf integer NOT NULL,
            PRIMARY KEY (chunk_id, lexeme)
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE chunk_lengths (
            chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            dl integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE lexeme_stats (
            lexeme text PRIMARY KEY,
            df integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        "CREATE INDEX ON chunk_terms (lexeme)",
    ):
        await connection.execute(text(statement))
    await connection.commit()


@asynccontextmanager
async def temporary_corpus_session(
    engine: AsyncEngine,
    batch: SeedBatch,
    provider: EmbeddingProvider,
    *,
    target_text_chars: int,
    embedding_provider: str,
    clock: Clock = time.perf_counter_ns,
    started_at_ns: int | None = None,
) -> AsyncIterator[tuple[AsyncSession, IndexingBudgetMeasurement]]:
    """Index one isolated corpus arm and discard it when its connection closes."""
    started = clock() if started_at_ns is None else started_at_ns
    connection = await engine.connect()
    session: AsyncSession | None = None
    try:
        await _create_temporary_corpus_tables(connection, provider.dimensions)
        session = AsyncSession(bind=connection, expire_on_commit=False)
        await persist_seed_batch(session, batch)
        # One rebuild per corpus arm. Every BM25 experiment on this chunking shares
        # it, and the next chunk target gets its own corpus and its own statistics,
        # because df, avgdl, and dl are all properties of a particular chunking.
        await backfill_term_stats(session)
        backfill = await embed_missing_chunks(session, provider)
        if backfill.embedded != len(batch.chunks) or backfill.skipped_stale:
            raise RuntimeError("temporary corpus embedding backfill was incomplete")
        elapsed_seconds = (clock() - started) / 1_000_000_000
        measurement = assess_indexing_budget(
            target_text_chars=target_text_chars,
            document_count=len(batch.documents),
            chunk_count=len(batch.chunks),
            embedding_provider=embedding_provider,
            total_seconds=elapsed_seconds,
        )
        yield session, measurement
    finally:
        if session is not None:
            await session.close()
        await connection.close()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the isolated M3 ablation command."""
    parser = argparse.ArgumentParser(
        description="Run isolated source-span retrieval ablations and latency budgets."
    )
    parser.add_argument("--suite", default="m3-retrieval-v1")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=("deterministic", "openai"), default="deterministic")
    parser.add_argument("--target-text-chars", type=_positive_int, nargs="+", default=[500, 1200])
    parser.add_argument(
        "--strategies",
        choices=("lexical", "vector", "hybrid"),
        nargs="+",
        default=["lexical", "vector", "hybrid"],
    )
    parser.add_argument(
        "--lexical-rankers",
        choices=("ts_rank_cd", "bm25"),
        nargs="+",
        default=["ts_rank_cd", "bm25"],
        help="Lexical rankers to cross with every lexical and hybrid arm.",
    )
    parser.add_argument("-k", type=_positive_int, default=5)
    parser.add_argument("--candidate-k", type=_positive_int, default=20)
    parser.add_argument("--rrf-k", type=_positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--budget-queries", type=_positive_int, default=QUERY_BUDGET_COUNT)
    parser.add_argument("--persist-results", action="store_true")
    return parser.parse_args(argv)


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    from app.db.bootstrap import bootstrap_schema
    from app.evals.ablation import ExperimentConfig, experiment_matrix, run_ablation

    if args.candidate_k < args.k:
        raise ValueError("candidate_k must be at least k")
    settings = get_settings().model_copy(update={"embedding_provider": args.provider})
    provider = get_embedding_provider(settings)
    cases = load_golden_cases(args.golden)
    recorded_at = datetime.now(UTC)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    all_outcomes = []
    indexing_measurements: list[IndexingBudgetMeasurement] = []
    query_budget: QueryBudgetMeasurement | None = None
    budget_ranker: LexicalRanker | None = None
    try:
        for target_text_chars in sorted(set(args.target_text_chars)):
            indexing_started_at_ns = time.perf_counter_ns()
            batch = build_chunking_batch(target_text_chars, settings=settings)
            configs = experiment_matrix(
                target_text_chars=(target_text_chars,),
                strategies=tuple(args.strategies),
                lexical_rankers=tuple(dict.fromkeys(args.lexical_rankers)),
                embedding_provider=args.provider,
                dimensions=provider.dimensions,
                k=args.k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
            )
            async with temporary_corpus_session(
                engine,
                batch,
                provider,
                target_text_chars=target_text_chars,
                embedding_provider=args.provider,
                started_at_ns=indexing_started_at_ns,
            ) as (session, indexing):
                indexing_measurements.append(indexing)

                async def evaluator(config: ExperimentConfig) -> RetrievalEvaluation:
                    retriever = make_retriever(
                        session,
                        strategy=config.strategy,
                        provider=provider,
                        lexical_ranker=config.lexical_ranker,
                        candidate_k=config.candidate_k,
                        rrf_k=config.rrf_k,
                    )
                    return await evaluate_retriever(
                        cases,
                        retriever,
                        suite=args.suite,
                        config=config.to_dict(),
                        k=config.k,
                        recorded_at=recorded_at,
                    )

                report = await run_ablation(
                    configs,
                    evaluator,
                    artifact_dir=args.artifact_dir,
                    recorded_at=recorded_at,
                )
                all_outcomes.extend(report.outcomes)

                if target_text_chars == max(args.target_text_chars):
                    budget_strategy = (
                        "hybrid" if "hybrid" in args.strategies else args.strategies[-1]
                    )
                    budget_ranker = None if budget_strategy == "vector" else args.lexical_rankers[0]
                    budget_retriever = make_retriever(
                        session,
                        strategy=budget_strategy,
                        provider=provider,
                        lexical_ranker=budget_ranker,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                    query_budget = await measure_query_budget(
                        [case.question for case in cases],
                        budget_retriever,
                        k=args.k,
                        query_count=args.budget_queries,
                    )

        if query_budget is None:
            raise RuntimeError("query budget was not measured")

        timestamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
        budget_path = args.artifact_dir / f"{timestamp}-budgets.json"
        budget_payload = {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "recorded_at": _utc_text(recorded_at),
            "measurement_provenance": {
                "embedding_provider": args.provider,
                "budget_lexical_ranker": budget_ranker,
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": args.provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
        }
        budget_path.parent.mkdir(parents=True, exist_ok=True)
        budget_path.write_text(
            json.dumps(budget_payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        persisted = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                for outcome in all_outcomes:
                    persisted.append(
                        await persist_evaluation(
                            session,
                            outcome.evaluation,
                            raw_artifact_path=outcome.artifact_path,
                        )
                    )
                await session.commit()

        from app.evals.ablation import AblationReport

        combined = AblationReport(outcomes=tuple(all_outcomes))
        return {
            "comparison_table": combined.comparison_markdown(),
            "artifacts": [str(outcome.artifact_path) for outcome in all_outcomes],
            "budget_artifact": str(budget_path),
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
            "persisted": [asdict(result) for result in persisted],
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the complete isolated M3 evaluation command."""
    result = asyncio.run(_run_cli(arguments()))
    print(result["comparison_table"])
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "comparison_table"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
```

#### Create or replace `app/evals/__main__.py`

<!-- file: app/evals/__main__.py -->
```python
"""Command-line entry point for the complete M3 evaluation matrix."""

from app.evals.retrieval_eval import main

if __name__ == "__main__":
    main()
```

Run the checkpoint:

```bash
uv run pytest tests/evals/test_04_ablation.py tests/evals/test_05_runner.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M3.5 — Complete checkpoint

#### Create or replace `app/evals/curation.py`

<!-- file: app/evals/curation.py -->
```python
"""Candidate intake, machine validation, review queue, and fail-closed promotion."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError
from pydantic.functional_validators import field_validator

from app.evals.loader import DEFAULT_MANIFEST_PATH, GoldenDataError, validate_golden_sources
from app.evals.types import GoldenCase

# A committed answer span never exceeds this many raw characters. A wider span is
# reconnaissance, not an answer: it inflates IoU denominators and hides whether the
# generator actually located the evidence.
MAX_CANDIDATE_SPAN_CHARS: Final[int] = 2_500

DecisionLabel = Literal["approve", "reject"]
CandidateState = Literal["pending", "approved", "rejected"]


class CurationError(ValueError):
    """A candidate file, review decision, or promotion violates the curation contract."""


class CandidateCase(GoldenCase):
    """One generated golden candidate that has not earned an ``m3c`` id yet.

    A candidate carries the full golden payload plus generator provenance, so every
    golden invariant is inherited and enforced at intake. Only promotion may mint a
    golden id, and a candidate can never claim any status beyond the pinned pending
    literals it inherits.
    """

    id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
    generator: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("generator", mode="after")
    @classmethod
    def reject_blank_generator(cls, value: str) -> str:
        """Keep generator provenance non-empty, single-line, and table-safe."""
        if not value.strip():
            raise ValueError("generator must not be blank")
        if "|" in value or "\n" in value:
            raise ValueError("generator must not contain pipes or newlines")
        return value


class ReviewDecision(BaseModel):
    """One explicit human verdict on one candidate. Absence of a verdict is pending."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
    decision: DecisionLabel
    reviewer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("reviewer", "note", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject strings that contain only whitespace."""
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value


CANDIDATE_CASES = TypeAdapter(list[CandidateCase])
REVIEW_DECISIONS = TypeAdapter(list[ReviewDecision])


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except CurationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurationError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _candidate_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise CurationError(f"no candidate JSON files found in {path}")
        return files
    return [path]


def _normalized_question(question: str) -> str:
    return " ".join(question.casefold().split())


def _span_identities(case: GoldenCase) -> list[tuple[str, str, int, int]]:
    return [
        (answer.doc_id, answer.source_sha256, answer.start_char, answer.end_char)
        for answer in case.answers
    ]


def _validate_unique_candidates(candidates: Sequence[CandidateCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    identities: set[tuple[str, str, int, int]] = set()
    for candidate in candidates:
        if candidate.id in ids:
            raise CurationError(f"duplicate candidate id: {candidate.id}")
        ids.add(candidate.id)

        normalized = _normalized_question(candidate.question)
        if normalized in questions:
            raise CurationError(f"duplicate normalized candidate question: {candidate.question}")
        questions.add(normalized)

        for identity in _span_identities(candidate):
            if identity in identities:
                raise CurationError(f"duplicate answer span identity in {candidate.id}")
            identities.add(identity)

        for answer in candidate.answers:
            width = answer.end_char - answer.start_char
            if width > MAX_CANDIDATE_SPAN_CHARS:
                raise CurationError(
                    f"{candidate.id} span is reconnaissance, not an answer: "
                    f"{width} > {MAX_CANDIDATE_SPAN_CHARS} chars"
                )


def _validate_disjoint_from_golden(
    candidates: Sequence[CandidateCase],
    golden_cases: Sequence[GoldenCase],
) -> None:
    golden_questions = {_normalized_question(case.question) for case in golden_cases}
    golden_identities = {identity for case in golden_cases for identity in _span_identities(case)}
    for candidate in candidates:
        if _normalized_question(candidate.question) in golden_questions:
            raise CurationError(
                f"{candidate.id} duplicates a golden question: {candidate.question}"
            )
        for identity in _span_identities(candidate):
            if identity in golden_identities:
                raise CurationError(f"{candidate.id} reuses a golden answer span identity")


def load_candidate_cases(
    path: str | Path,
    *,
    golden_cases: Sequence[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[CandidateCase]:
    """Load one file or a directory of candidate files and run every machine gate.

    Structural validation, uniqueness, disjointness from the committed golden set,
    and raw-source binding all run here, so a candidate that survives intake fails
    later only on human judgment, never on mechanics.
    """
    candidates: list[CandidateCase] = []
    for candidate_path in _candidate_files(Path(path)):
        payload = _read_json(candidate_path)
        if not isinstance(payload, list):
            raise CurationError(f"candidate file root must be a JSON array: {candidate_path}")
        try:
            candidates.extend(CANDIDATE_CASES.validate_python(payload))
        except ValidationError as exc:
            raise CurationError(f"invalid candidate cases in {candidate_path}: {exc}") from exc

    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    try:
        validate_golden_sources(candidates, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    return candidates


def load_review_decisions(path: str | Path) -> list[ReviewDecision]:
    """Load explicit review decisions. A missing file is an error, never an empty set."""
    decisions_path = Path(path)
    if not decisions_path.is_file():
        raise CurationError(f"decisions file does not exist: {decisions_path}")
    payload = _read_json(decisions_path)
    if not isinstance(payload, list):
        raise CurationError(f"decisions file root must be a JSON array: {decisions_path}")
    try:
        decisions = REVIEW_DECISIONS.validate_python(payload)
    except ValidationError as exc:
        raise CurationError(f"invalid review decisions in {decisions_path}: {exc}") from exc

    seen: set[str] = set()
    for decision in decisions:
        if decision.candidate_id in seen:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        seen.add(decision.candidate_id)
    return decisions


def candidate_states(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> dict[str, CandidateState]:
    """Map every candidate id to pending, approved, or rejected.

    Every decision must name a known candidate, and at most one decision may exist
    per candidate. A candidate without a decision stays pending — silence never
    approves anything.
    """
    known = {candidate.id for candidate in candidates}
    if len(known) != len(candidates):
        raise CurationError("candidate ids must be unique")

    states: dict[str, CandidateState] = {candidate.id: "pending" for candidate in candidates}
    decided: set[str] = set()
    for decision in decisions:
        if decision.candidate_id not in known:
            raise CurationError(f"decision references unknown candidate: {decision.candidate_id}")
        if decision.candidate_id in decided:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        decided.add(decision.candidate_id)
        states[decision.candidate_id] = "approved" if decision.decision == "approve" else "rejected"
    return states


def review_queue_markdown(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> str:
    """Render the deterministic review queue an author walks before any promotion."""
    states = candidate_states(candidates, decisions)
    lines = [
        "| ID | Category | Facet | Positive source | Generator | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for candidate in sorted(candidates, key=lambda case: case.id):
        doc_ids = sorted({answer.doc_id for answer in candidate.answers})
        source = ", ".join(doc_ids) if doc_ids else "none"
        lines.append(
            f"| {candidate.id} | {candidate.category} | {candidate.facet} | "
            f"{source} | {candidate.generator} | {states[candidate.id]} |"
        )
    return "\n".join(lines)


def _next_golden_number(golden_cases: Sequence[GoldenCase]) -> int:
    return max((int(case.id.split("-", 1)[1]) for case in golden_cases), default=0) + 1


def promote_approved(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision],
    golden_cases: Sequence[GoldenCase],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> tuple[GoldenCase, ...]:
    """Mint golden cases from explicitly approved candidates only.

    Promotion re-runs every machine gate — uniqueness, disjointness from the
    committed set, and raw-source binding for the approved cases — assigns the next
    free ``m3c`` ids in candidate-id order, and keeps the pinned pending-approval
    provenance: entering the golden pool queues a case for the author, it never
    certifies one.
    """
    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    states = candidate_states(candidates, decisions)

    approved = [
        candidate
        for candidate in sorted(candidates, key=lambda case: case.id)
        if states[candidate.id] == "approved"
    ]
    try:
        validate_golden_sources(approved, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    number = _next_golden_number(golden_cases)
    promoted: list[GoldenCase] = []
    for candidate in approved:
        if number > 99:
            raise CurationError("golden id namespace m3c-NN is exhausted")
        payload = candidate.model_dump(mode="json", exclude={"generator"})
        payload["id"] = f"m3c-{number:02d}"
        try:
            promoted.append(GoldenCase.model_validate(payload))
        except ValidationError as exc:
            raise CurationError(f"promoted case from {candidate.id} is invalid: {exc}") from exc
        number += 1
    return tuple(promoted)


def write_golden_cases(path: str | Path, cases: Sequence[GoldenCase]) -> Path:
    """Write promoted cases as a golden-shaped JSON array for a reviewed merge."""
    target = Path(path)
    if target.suffix != ".json":
        raise CurationError(f"golden output must be a .json file: {target}")
    payload = [case.model_dump(mode="json") for case in cases]
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
```

#### Create or replace `app/evals/breakdown.py`

<!-- file: app/evals/breakdown.py -->
```python
"""Taxonomy-grouped retrieval metrics over one scored golden suite."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import get_args

from app.evals.scoring import CaseScore, score_suite
from app.evals.types import GoldenCase, GoldenCategory, GoldenFacet


@dataclass(frozen=True, slots=True)
class GroupScore:
    """Macro-averaged retrieval metrics for one taxonomy group of positive cases."""

    group: str
    k: int
    case_count: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float


def _positive_case_index(cases: Sequence[GoldenCase]) -> dict[str, GoldenCase]:
    index: dict[str, GoldenCase] = {}
    for case in cases:
        if case.id in index:
            raise ValueError(f"duplicate golden case id: {case.id}")
        index[case.id] = case
    return index


def _validated_pairs(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> list[tuple[GoldenCase, CaseScore]]:
    """Pair every score with its positive case and reject partial or stray scoring.

    A breakdown over a subset would silently misrepresent a group, so every positive
    case must carry exactly one score, an absent case must carry none, and every
    score must point at a known case.
    """
    index = _positive_case_index(cases)
    if not scores:
        raise ValueError("scores must not be empty")
    if len({score.k for score in scores}) != 1:
        raise ValueError("all case scores must use the same k")

    pairs: list[tuple[GoldenCase, CaseScore]] = []
    scored_ids: set[str] = set()
    for score in scores:
        case = index.get(score.case_id)
        if case is None:
            raise ValueError(f"score references unknown golden case: {score.case_id}")
        if case.category == "absent":
            raise ValueError(f"absent case cannot carry a retrieval score: {score.case_id}")
        if score.case_id in scored_ids:
            raise ValueError(f"duplicate case score: {score.case_id}")
        scored_ids.add(score.case_id)
        pairs.append((case, score))

    unscored = [
        case.id for case in cases if case.category != "absent" and case.id not in scored_ids
    ]
    if unscored:
        raise ValueError(f"positive cases missing a score: {', '.join(sorted(unscored))}")
    return pairs


def _grouped(
    pairs: Sequence[tuple[GoldenCase, CaseScore]],
    groups: Sequence[str],
    key: Callable[[GoldenCase], str],
) -> tuple[GroupScore, ...]:
    results: list[GroupScore] = []
    for group in groups:
        members = [score for case, score in pairs if key(case) == group]
        if not members:
            continue
        suite = score_suite(members)
        results.append(
            GroupScore(
                group=group,
                k=suite.k,
                case_count=suite.case_count,
                recall_at_k=suite.recall_at_k,
                hit_rate_at_k=suite.hit_rate_at_k,
                mrr=suite.mrr,
            )
        )
    return tuple(results)


def breakdown_by_category(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden category in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenCategory), lambda case: case.category)


def breakdown_by_facet(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden facet in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenFacet), lambda case: case.facet)


def breakdown_markdown(dimension: str, groups: Sequence[GroupScore]) -> str:
    """Render one taxonomy breakdown as a compact comparison table."""
    if not dimension.strip():
        raise ValueError("dimension must not be blank")
    if not groups:
        raise ValueError("groups must not be empty")
    lines = [
        f"| {dimension} | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---:|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(
            f"| {group.group} | {group.case_count} | {group.recall_at_k:.6f} | "
            f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
        )
    return "\n".join(lines)
```

Run the checkpoint:

```bash
uv run pytest tests/evals/test_07_curation.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
