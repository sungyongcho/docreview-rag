# M3.1 Tutorial 1 — What should an answer be expressed as?

Building an evaluation set means writing down "the correct evidence for this question." How should that answer be expressed?

The easiest choice is the **chunk ID**. Write `chunk_id: 4821` and you are done.

But that collapses the whole purpose of this chapter.

M1 left behind an immutable corpus — 20 filings across four tickers, committed under `data/corpus/` — and M2 left a retrieval stack that returns plausible chunks for a query. What neither left behind is a way to say whether those chunks are the right ones. This document begins building the measuring instrument, and it begins at the most dangerous spot: the typed contract for the answer key itself.

The danger is worth stating precisely, because a broken answer key does not look broken. A retrieval bug returns bad chunks and the evaluation catches it; a corrupted golden case — a swapped offset, a typo'd field, a stale hash — still grades, and every metric downstream inherits the error while every test stays green. Nothing sits above the answer key to check the answer key. So the invariant this file establishes is deliberately absolute: **a golden case either loads exactly as the curator committed it, or it refuses to load with an error naming the field. There is no third path where it loads as something slightly different.**

**Prerequisite:** M2 is complete and `uv run pytest tests/retrieval -q` passes.

### The golden set — grading needs an answer key first

Retrieval works by the end of M2. But "it works" and "it finds well" are different claims, and the second one needs evidence. Typing in one query and nodding at a plausible chunk is not measurement — it is appreciation.

That is why evaluation needs a **golden set**: a collection of pre-committed records saying "the correct evidence for this question is here in the source." Whatever the system returns is scored against these records. The answer key must exist before grading can, and only when grading exists does "I changed it and it got better" become a number instead of an anecdote.

This repository already carries that answer key: `data/golden/retrieval.json`. On top of the four-ticker 10-K corpus seeded in M1 it holds 28 cases — 24 positive ones with answer spans and 4 absent ones whose correct answer is "not in the documents." **What M3 builds is not this file, but the machinery that reads, validates, and scores it.**

Let the provenance be explicit. The classic way to build a golden set is for a domain expert to write it by hand. Here, the coding agent that built the reference implementation curated it by reading the corpus and selecting questions with their evidence spans, and machine checks finished the structural validation — hashes, bounds, uniqueness. But no human has yet judged the content correct. That is why every case carries the three status fields `curation_status`, `approval_status`, and `human_verified`, pinned by literal types to their pre-review values — the type system prevents unreviewed data from looking reviewed. The approval it waits on belongs to this repository's author, and the per-case review procedure lives in `data/golden/REVIEW.md`.

Spelled out as a lifecycle, this answer key has already passed through two states and is parked in a third. **Generated:** an LLM coding agent read the 20 immutable filings and drafted the 28 cases with their evidence spans. **Machine-validated:** every span's hash matches the committed file bytes, every interval is in bounds and nonempty, ids, questions, and span identities are unique, and no committed span exceeds the 2,500-character ceiling — the longest is 2,280 characters. **Awaiting review:** every one of the 28 cases carries the same status triple — `agent-curated`, `pending-author-approval`, `human_verified: false` — and what moves a case out of that state is not code but the author working through the review queue, confirming per case that every fact the reference answer needs sits inside the cited interval, and for an absent case that the fact is genuinely undisclosed in the corpus rather than merely hard to retrieve. Only the author may change an approval status; the machinery that promotes new candidates into this file is M3.5's subject.

The suite's shape is itself frozen as a test contract, so it cannot drift while nobody is looking. `tests/evals/golden.py` records the counts the committed file must satisfy, and the next document's loader tests (`tests/evals/test_02_loader.py`) assert every one of them — edit `retrieval.json` and the suite fails until the constants change in the same reviewed commit:

<!-- src: tests/evals/golden.py::CASE_COUNT,POSITIVE_TICKER_COUNTS -->
```python
CASE_COUNT = 28
POSITIVE_CASE_COUNT = 24
ABSENT_CASE_COUNT = 4
POSITIVE_DOCUMENT_COUNT = 20
DEMO_HERO_COUNT = 8
MAX_ANSWER_SPAN_CHARS = 2_500

CATEGORY_COUNTS = {
    "simple_lookup": 13,
    "exact_number": 5,
    "multi_hop": 6,
    "absent": 4,
}

FACET_COUNTS = {
    "factual": 6,
    "comparison": 6,
    "risk": 6,
    "policy": 5,
    "numeric": 5,
}

POSITIVE_TICKER_COUNTS = {"AMD": 6, "INTC": 6, "MU": 6, "NVDA": 6}
```

Those numbers are not decoration. Six positive cases per ticker with all 20 filings cited means no filing in the corpus is dead weight; fixed category and facet counts mean later breakdowns by difficulty and evidence type have no accidentally empty group; and even the eight `demo-hero` tags — two per ticker — are pinned, so no edit to the suite's shape can pass unnoticed.

And let the direction of use be explicit too. **Retrieval is what moves; the golden set is frozen.** Change an M2 setting — chunk size, fusion weights, embeddings — and the same answer key re-grades it, so the metric delta is the verdict. The opposite direction, editing the answer key to raise a score, invalidates the measurement itself.

### Writing answers as chunk IDs makes experiments impossible

One of the things we want to measure is **chunk size**. Change `target_text_chars` from 1,200 to 800 and see whether retrieval quality rises.

What happens when chunk size changes? **Every chunk is re-cut and every ID changes.** The answer file's `chunk_id: 4821` now points at nothing, or at the wrong text.

The answer data has to be rebuilt. For this suite that means re-deriving 34 answer spans by hand and re-reviewing every one, because a re-derived answer is a new claim. That is laborious enough that in practice **the experiment simply gets abandoned.**

It is worth naming what happens there. When the measuring instrument depends on the thing being measured, changing the thing invalidates the instrument. That leaves two options — rebuild the ground truth every time, or stop changing anything. In practice the second one always wins. **A system you cannot experiment on becomes a system nobody experiments on.**

### So answers are written as source coordinates

M1.3's reason for basing citations on source coordinates rather than chunk IDs pays off one last time here. Answers are written the same way.

```text
(doc_id, source_sha256, start_char, end_char)
```

However chunks are cut, **that position in the source does not move.** So chunk sizes can be varied and compared against the same answer file.

Including `source_sha256` matters. Coordinates mean something only against a specific file snapshot. Refetch the filing later and, if the bytes differ, the hash mismatches and the loader refuses. **That prevents evaluation from quietly running on stale ground.**

> **Concept — half-open intervals and offsets into the decoded raw source**
>
> `start_char` is included, `end_char` is excluded. That convention is what makes interval arithmetic stop producing off-by-one errors: the length is exactly `end_char - start_char` with no correction term, two adjacent spans tile with no overlap and no gap, and the pair follows Python's slicing convention, so slicing the decoded source with the recorded pair returns the evidence verbatim. A closed interval reintroduces a plus-or-minus-one decision at every one of those spots, and each such decision is a place to be silently wrong.
>
> Just as deliberate is what the offsets index: the raw filing decoded as UTF-8, not chunk ids and not cleaned text. Chunk ids die on re-chunking — this document's whole argument. Cleaned text is nearly as fragile: it shifts whenever a cleaning rule improves, and every improvement would strand the answer key. The raw snapshot is the one layer of the pipeline that never changes, and the hash exists to certify that it has not.

This is checkable against the committed data right now. Case `m3c-28` asks for NVIDIA's fiscal-2024 revenue and net income, and its first answer span claims 639 characters of the raw NVDA filing. Replay the claim from the repository root:

```bash
python3 -c "
import hashlib, json
case = [c for c in json.load(open('data/golden/retrieval.json')) if c['id'] == 'm3c-28'][0]
span = case['answers'][0]
raw = open('data/corpus/NVDA/2024-02-21_0001045810-24-000029.html', 'rb').read()
print('sha256 match:', hashlib.sha256(raw).hexdigest() == span['source_sha256'])
print('span length :', span['end_char'] - span['start_char'])
print('span head   :', raw.decode('utf-8')[span['start_char']:span['end_char']][:60])
"
```

```text
sha256 match: True
span length : 639
span head   : Revenue</span></td><td style="background-color:#f1f2f2;borde
```

Two honest observations about that output. The span head is raw table markup — the revenue figure 60,922 sits in `<td>` cells further into the interval — because the coordinates anchor to the immutable raw HTML; making evidence readable at review time is a renderer's job, not the coordinate's. And because the question needs two facts, the case carries two spans — net income lives in a second 649-character interval. A tuple of tight spans, not one stretched span, is how a multi-fact answer stays precise.

### Cases whose answer is "absent" go in the data too

There are two kinds of case.

- **positive** — one or more spans
- **absent** — no spans; the information is **correctly not present** in this document

Why is `absent` needed? Because a common RAG failure is **inventing what is not there.** Ask about something absent from NVDA's 10-K and it is dangerous for the system to find something and answer plausibly.

The four committed absent cases are engineered, not leftovers. They ask for a declared AMD quarterly dividend amount, an Intel commercial quantum-computing subscription, a Micron ransomware payment amount, and an NVIDIA board-approved password-rotation interval — each phrased to sound like something a 10-K would disclose while the corpus genuinely does not disclose it. The curating agent's full-corpus reconnaissance found no answer for any of the four, and the review queue still obliges the author to confirm each absence independently, because "the agent could not find it" and "it is not there" are different claims.

The care needed is that `absent` **must not be counted as a retrieval failure with recall 0.** It is a different question — a labeling candidate for "can it say there is nothing?" rather than retrieval. M3.2's scoring separates the two.

> The source of this golden data is data, not prose. Its current status is **agent-curated, awaiting author approval, unverified by a human.** Read the evaluation results with that limitation in view.

### What to define, what to implement, and what to inspect

This document builds one file, `app/evals/types.py`, in three steps. The loader comes in the next document.

| Area | Learning action | What to take away |
|---|---|---|
| Module header and value vocabulary | **Define the settings schema** | Evaluation deals in a closed set of values |
| `GoldenSpan` | **Write the model declaration, then review the design** | How an answer binds to the source rather than a chunk |
| Validators in `GoldenCase` | **Implement** the core validation yourself | What makes positive and absent mutually exclusive |

### 1. Module header and value vocabulary

#### Create `app/evals/types.py` — module header and type aliases

**Learning action — define the settings schema:** write the five aliases, checking why each is a closed list rather than a free string.

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
```

**What to look for in the code**

- `GoldenCategory` and `GoldenFacet` are `Literal`s. Adding a category means editing code, and at that moment you are forced to ask whether the new results stay comparable with the old. As free strings, a typo'd `"exact_numebr"` would have quietly split the statistics.
- The pattern on `GoldenTag` allows only kebab-case. Tags become group keys in analysis, so `"multi hop"` and `"multi-hop"` must not become two groups.
- `SourceSha256` is the same regex as the alias of that name in M2.1. Evaluation and retrieval have to name a snapshot the same way for coordinates to mean the same thing.

Why `Literal` and not an `Enum`? An enum would also give a closed set, but it inserts a translation layer: the JSON file would hold `"absent"` while code holds an enum member, and serialization, comparison, and error messages all pass through that mapping. `Literal` keeps the value in the file and the value in the type identical — what the curator wrote is exactly what the validator names when it rejects. For a vocabulary this small and this stable, the indirection buys nothing.

### 2. `GoldenSpan` — pointing at the source, not at a chunk

| `GoldenSpan` field | Value or constraint | Role |
|---|---|---|
| `doc_id` | non-empty filing identity | Selects the filing that contains the answer. |
| `source_sha256` | 64 lowercase hex characters | Pins the answer to one immutable source snapshot. |
| `start_char`, `end_char` | non-empty half-open range | Locates exact answer evidence without depending on chunk boundaries. |

#### Extend `app/evals/types.py` — `GoldenSpan`

**Learning action — write the model declaration, then review the design:** the four fields transcribe directly. You should be able to say why the validator uses `>` and not `>=`.

<!-- src: app/evals/types.py::GoldenSpan -->
```python
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
```

**What to look for in the code**

- There are only four fields. No question, no text, no chunk information. This type claims nothing beyond **one interval in the source**.
- Rejecting `end_char <= start_char` means an empty interval cannot be an answer. A zero-length answer overlaps no retrieval result at all, quietly creating a case that can never pass.
- `frozen=True` keeps ground truth from changing mid-scoring. In evaluation that is not ceremony — mutable ground truth makes the score meaningless.

> **Concept — strict types at the answer-key boundary**
>
> Pydantic's default validation is lenient by design: a plain `int` field accepts the string `"10"`, and accepts `True` as 1 because Python's bool is a subclass of int. Inside application code that tolerance smooths over harmless representation differences. At an answer-key boundary the same tolerance is a corruption channel: a curation script that emits offsets as strings, or slips a boolean where a number belongs, produces a file that loads without a sound and grades every run after it.
>
> `StrictInt` refuses both — the value must already be an integer, not something an integer can be made from. `extra="forbid"` closes the field vocabulary, so a key the schema does not declare — a typo, or a stale `chunk_id` — becomes an error instead of a silently ignored passenger. `frozen=True` closes the last window, the one after loading: no code path can reassign a field mid-scoring.
>
> The design rule underneath all three: the answer key must be harder to corrupt than the system it grades. A retrieval bug produces bad output and the evaluation flags it; an answer-key bug produces plausible evaluations of everything, and there is no second answer key to flag those.

### 3. `GoldenCase` — making positive and absent mutually exclusive

| `GoldenCase` field | Value or constraint | Role |
|---|---|---|
| `id` | `m3c-NN` | Gives a reviewed case a stable evaluation identity. |
| `question` | non-empty text | Stores the retrieval question under evaluation. |
| `category` | `"simple_lookup"`, `"exact_number"`, `"multi_hop"`, or `"absent"` | Groups cases by retrieval difficulty and absent behavior. |
| `facet` | `"factual"`, `"comparison"`, `"risk"`, `"policy"`, or `"numeric"` | Indicates the nature of the evidence required. |
| `tags` | unique kebab-case values | Adds narrower analysis labels without changing the core grouping. |
| `answers` | tuple of `GoldenSpan` values | Holds ground truth bound to the source, empty only for absent cases. |
| `expected_label` | `"SUPPORTED"` or `"NOT_IN_DOCS"` | States whether the corpus must support the answer. |
| `reference_answer` | non-empty text | Records the reviewed target answer or the absence phrase. |
| `note` | non-empty text | Preserves per-case review context. |
| `curation_status` | `"agent-curated"` | States who authored the case. |
| `approval_status` | `"pending-author-approval"` | Keeps a draft case from appearing author-approved. |
| `human_verified` | exactly `False` | Keeps unreviewed evidence from being presented as human-verified. |

#### Complete `app/evals/types.py` — `GoldenCase`

**Learning action — implement the validation:** write the field declarations first. Then implement the four validators yourself, checking which malformed answer file each one stops.

<!-- src: app/evals/types.py::GoldenCase -->
```python
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

**What to look for in the code**

- Beyond `human_verified: Literal[False]` there is also a `mode="before"` validator. The annotation alone accepts more than it appears to: Pydantic coerces a numeric `0` — including its float form — into the literal and stores it as `False`, while it does reject a string such as `""`. A file that writes the review status as `0` therefore loads indistinguishably from one whose curator deliberately wrote the boolean — **acceptance would no longer prove that an explicit review status was ever recorded.** So the validator runs before coercion, sees the raw JSON value, and rejects everything that is not exactly the boolean `false`.
- `validate_label_and_answers` looks at three fields at once. `category`, `expected_label`, and `answers` are each individually valid while their combination is contradictory — absent with spans, or positive expecting `NOT_IN_DOCS`.
- Why that contradiction is dangerous is the point. One answer span on an absent case sends it into M3.2's recall calculation, and a question that should be answered "not present" gets counted as a question that was missed. A number comes out and nobody knows what it measured.
- Duplicate answer spans are rejected too. The same span twice inflates the recall denominator.

> **Concept — Literal-pinned provenance as a fail-closed schema**
>
> The three status fields each admit exactly one value, which means today's schema cannot even express an approved case. A file claiming an approved, human-verified case does not load — not because some rule rejects it, but because the type has no spelling for it. That looks like a limitation and is the design: the claim "a human verified this" can enter the system only through a code change that widens a literal type, and a code change — unlike a quiet data edit — is reviewed, diffed, and signed off.
>
> The obvious alternative — declaring the full vocabulary up front, approved states included — fails open: from the day the schema ships, a data file could claim an approval that never happened, and the schema would nod along. Fail-closed inverts that default. Until the review machinery exists, its absence is itself enforced by the types; building the promotion path that widens this vocabulary is M3.5's work.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/evals/test_01_contract.py -q
```

These tests exist now but will not pass yet. They skip with `not implemented yet` until the next document's public-API step publishes the symbols on the package — from that point on all 18 of them turn green.

| Value the test breaks | Contract being protected |
|---|---|
| An unknown extra field | A typo in the answer file is never silently ignored. |
| A reversed or empty span | No answer exists that could overlap nothing. |
| A duplicate answer span | The recall denominator is not inflated. |
| An absent case carrying spans | Absence judgment never mixes with retrieval failure. |
| A positive case labeled `NOT_IN_DOCS` | Label and evidence state the same thing. |
| `human_verified` as `True` or `0` | The review status admits exactly the committed pre-review value; look-alike stand-ins are rejected before coercion. |

### What you should be able to explain now

- **Which experiment becomes impossible when answers are written as chunk IDs?**
  - **Answer:** A chunk-size experiment becomes impractical because re-chunking changes every ID and invalidates the ground truth being used for comparison.
- **Why must `source_sha256` travel with the answer?**
  - **Answer:** Coordinates identify evidence only within one exact source snapshot; the hash rejects a refetched or changed file instead of silently scoring stale ground truth.
- **Why must an `absent` case not be counted as recall 0?**
  - **Answer:** It has no gold span, so M3 runs retrieval but records its score as `None` and excludes it from retrieval metrics. This prevents a false recall penalty, but M3 does not test whether the system answers `NOT_IN_DOCS`.
- **Why does `human_verified` need a validator of its own?**
  - **Answer:** The type annotation can coerce numeric `0` into `False`; the validator requires the explicit JSON boolean so review provenance cannot be misrepresented.
- **Why can a three-field model validator not be replaced by per-field validation?**
  - **Answer:** `category`, `expected_label`, and `answers` may each be valid alone while their combination is contradictory, such as an absent case that still contains spans.
- **Why is it deliberate that the schema cannot express an approved case?**
  - **Answer:** The provenance fields are pinned to single literal values, so approval can enter only through a reviewed code change that widens the type — the schema fails closed instead of trusting data files with claims nobody has verified yet.

---

[Module overview](../03-build.md) · [Next: Golden loader →](02-golden-loader.md)
