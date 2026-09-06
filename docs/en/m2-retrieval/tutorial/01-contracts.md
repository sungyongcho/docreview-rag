# M2.1 Tutorial 1 — Make evidence impossible to blur

A retriever must not return a string.

That sounds obvious, and most RAG examples do exactly that: `retriever.search(q)` → a list of texts. Simple, and it drops straight into a prompt.

But where that text came from disappears. If the coordinates and SHA-256 that M1 worked so hard to protect evaporate at the retrieval boundary, M4 has nothing to cite when it writes the report.

So a retrieval result has to be a **complete database chunk**, carrying both citation text for people and coordinates for machines. The three fields split in M1.3 survive intact.

- `body` — evidence that came from the source
- `context_header` — retrieval context we produced
- `index_text` — the two combined, the text that went into the index

And the relationship among them is nailed down at the type level.

**Prerequisite:** M1.4 passes and the database holds the seeded chunks. Start from the point where `uv run pytest tests/db -q` is green.

## What to define, what to implement, and what to inspect

M2.1 builds one file. Four steps appended to `app/retrieval/types.py` produce the checkpoint file exactly.

| Area | Learning action | What to take away |
|---|---|---|
| Module scaffold and type aliases | **Define the structure** | Why constraints collect into aliases instead of repeating per field |
| `ChunkHit` field declarations | **Write the model declaration, then review the design** | Why evidence and indexed text live in one type |
| `model_validator` in `ChunkHit` | **Implement** the core validation yourself | Which invalid states are blocked at construction |
| Canonicalizing validators in `RetrievalFilters` | **Write the field mapping, then inspect boundary conversions** | What makes the same request serialize the same way |
| Sort key in `sort_hits` | **Implement** the determinism rule yourself | What actually breaks a tie |

Separating what Pydantic does for you from what you must state explicitly is the goal of this step.

## 1. Lay down the scaffold and constraint aliases first

Before reaching for `ChunkHit`, build the aliases. The constraint that `doc_id` is a non-empty string of at most 32 characters is needed more than six times in this file alone. An alias states it once.

That sounds like tidiness, and it is not. Picture the version without aliases: the same `Field(min_length=1, max_length=32)` copied into `ChunkHit`, into `RetrievalFilters`, and into whatever M3 and M4 build on top. Then someone widens the database column to 64 and updates four of the six copies. Nothing fails. No test breaks. The two forgotten copies simply start rejecting identifiers the database happily stores, and the symptom surfaces weeks later as a filing that "sometimes doesn't come back from search."

A constraint that lives in one place cannot drift out of step with itself. That is the entire argument, and it is worth more than the keystrokes it saves.

### Create `app/retrieval/types.py` — module header

**Learning action — define the structure:** there is no need to memorize the import list. Just note what comes from Pydantic.

```python
"""Shared value objects and deterministic ordering for retrieval results."""

from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator
```

### Extend `app/retrieval/types.py` — constraint aliases

**Learning action — define the settings schema:** write these while checking which database column constraint each alias carries over.

<!-- src: app/retrieval/types.py::ChunkKind,Score -->
```python
ChunkKind = Literal["text", "table"]

ChunkId = Annotated[StrictInt, Field(gt=0)]
DocId = Annotated[StrictStr, Field(min_length=1, max_length=32)]
Ticker = Annotated[StrictStr, Field(min_length=1, max_length=16)]
FiscalYear = Annotated[StrictInt, Field(gt=0)]
Form = Annotated[StrictStr, Field(min_length=1, max_length=16)]
Item = Annotated[StrictStr, Field(min_length=1, max_length=8)]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Score = Annotated[StrictFloat, Field(allow_inf_nan=False)]
```

**What to look for in the code**

- The `Strict*` types: Pydantic by default coerces `"3"` into `3`. `StrictInt` refuses that. A silently coerced database value means drifted coordinates.
- `max_length` matches the `String(32)` and `String(16)` of M1.4's ORM. Stating the same constraint at two layers is not duplication but **fail-closed at every boundary**.
- The pattern on `SourceSha256` accepts lowercase only. It must match exactly the format M1 stored for coordinates to reference the same snapshot.
- `allow_inf_nan=False` on `Score`: a NaN in the mix makes sort order non-deterministic.

## 2. `ChunkHit` — bind evidence and indexed text into one type

Now the type this whole module exists for. Twelve fields, and the temptation is to skim them as a database row transcribed into Python.

Resist that reading. A row is whatever the database happens to hold; this type is a claim about what a retrieval result is *allowed* to be. The difference shows up in the validator at the bottom, which refuses to build certain rows that PostgreSQL would store without complaint.

Think about what a retrieval hit has to answer. A person reading the report asks "where does this come from?" and needs `citation`. A machine re-opening the filing asks "which bytes?" and needs `start_char`, `end_char`, and `source_sha256` together. And the system itself has to be able to ask "what text actually matched?" — which is `index_text`, and which is the field most easily gotten wrong, because it is the one nobody looks at.

### Extend `app/retrieval/types.py` — `ChunkHit`

**Learning action — write the model declaration and implement the validation:** write the field declarations against the aliases above. Then implement `model_validator` yourself before comparing.

<!-- src: app/retrieval/types.py::ChunkHit -->
```python
class ChunkHit(BaseModel):
    """One scored database chunk with human and machine citation data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: ChunkId
    doc_id: DocId
    item: Item | None
    kind: ChunkKind
    citation: Annotated[StrictStr, Field(min_length=1)]
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]
    source_sha256: SourceSha256
    body: Annotated[StrictStr, Field(min_length=1)]
    context_header: StrictStr
    index_text: Annotated[StrictStr, Field(min_length=1)]
    score: Score

    @model_validator(mode="after")
    def validate_source_and_index_text(self) -> Self:
        """Reject invalid spans and indexed text detached from its evidence."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")

        expected = f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
        if self.index_text != expected:
            raise ValueError("index_text must equal context_header plus body")
        return self
```

| `ChunkHit` field | Value or constraint | Role |
|---|---|---|
| `chunk_id` | positive database identity | Provides a unique ranking and citation identity. |
| `doc_id` | non-empty filing identity | Ties the hit to one filing. |
| `item` | SEC Item or `None` | Preserves the section identifier when one exists. |
| `kind` | `"text"` or `"table"` | Indicates how the evidence is represented. |
| `citation` | non-empty text | Provides the human-readable source label. |
| `start_char`, `end_char` | valid half-open range | Locates the evidence inside the filing snapshot. |
| `source_sha256` | 64 lowercase hex characters | Binds coordinates to an exact source version. |
| `body` | non-empty source-derived text | Carries the evidence shown to the user. |
| `context_header` | possibly empty synthetic context | Carries filing and heading context apart from the evidence. |
| `index_text` | exactly `context_header + body` | Preserves the text that retrieval actually matched. |
| `score` | finite strict float | Orders hits inside one retrieval component. |

**What to look for in the code**

- `extra="forbid"`: an unknown key is rejected rather than silently ignored. A typo cannot slip through when a column name changes.
- `frozen=True`: a hit's score or coordinates cannot change midway through ranking.
- Only `context_header` carries no `min_length` constraint, because a chunk without context is normal. `body` and `index_text` must never be empty.

## What `model_validator` protects

The validator checks two things.

**First, that the half-open span is valid.** `end_char > start_char`. M1.3's fail-closed principle continues here: a retrieval result with a bad range is never built.

**Second, that `index_text` really is `context_header + body`.** Why is that needed?

Several places build a `ChunkHit` from a database row — vector search, lexical search, reranking. If one of them mistakenly supplies only `body` while putting something else in `index_text`, retrieval matched text A while the user is shown text B.

**Checking the relationship at construction closes that path.** Whatever built it, the existence of a `ChunkHit` means the three fields are consistent.

## 3. `RetrievalFilters` — freeze request conditions as immutable

The fused result is only explainable when one request reaches vector search and lexical search under **identical conditions**. So filters are value objects, and they do not change once built.

It is worth being concrete about how that goes wrong, because the failure is quiet. Suppose filters were a plain mutable object and a caller reused one across requests, adjusting it between calls. Vector search runs first and reads `tickers=("NVDA",)`. Before lexical search runs, the caller appends `"AMD"`. Now the two ranked lists cover different corpora, RRF fuses them anyway, and the output is a ranking over a document set that never existed as a single query.

Nothing raises. The numbers look plausible. And the only way to notice is to already suspect it.

Freezing the object removes the possibility rather than documenting against it.

### Extend `app/retrieval/types.py` — `RetrievalFilters`

**Learning action — write the field mapping, then inspect boundary conversions:** write the six field declarations first. Implement the four canonicalizing validators while checking what each one makes equivalent.

<!-- src: app/retrieval/types.py::RetrievalFilters -->
```python
class RetrievalFilters(BaseModel):
    """Optional exact-match restrictions shared by every retrieval strategy.

    Values within a field are alternatives, while populated fields are combined.
    Empty tuples mean that the corresponding database dimension is unrestricted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_ids: tuple[DocId, ...] = ()
    tickers: tuple[Ticker, ...] = ()
    fiscal_years: tuple[FiscalYear, ...] = ()
    forms: tuple[Form, ...] = ()
    items: tuple[Item | None, ...] = ()
    kinds: tuple[ChunkKind, ...] = ()

    @field_validator("doc_ids", "tickers", "forms", mode="after")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Remove duplicates and make equivalent string filters serialize equally."""
        return tuple(sorted(set(values)))

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def canonicalize_years(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        """Remove duplicate years and store them in ascending order."""
        return tuple(sorted(set(values)))

    @field_validator("items", mode="after")
    @classmethod
    def canonicalize_items(cls, values: tuple[str | None, ...]) -> tuple[str | None, ...]:
        """Canonicalize Item filters while retaining support for unnumbered sections."""
        return tuple(sorted(set(values), key=lambda item: (item is not None, item or "")))

    @field_validator("kinds", mode="after")
    @classmethod
    def canonicalize_kinds(cls, values: tuple[ChunkKind, ...]) -> tuple[ChunkKind, ...]:
        """Canonicalize kinds in the schema's text-then-table order."""
        order = {"text": 0, "table": 1}
        return tuple(sorted(set(values), key=order.__getitem__))
```

| `RetrievalFilters` field | Restricts |
|---|---|
| `doc_ids` | exact filing identities |
| `tickers` | company tickers |
| `fiscal_years` | fiscal years |
| `forms` | SEC form types |
| `items` | numbered Items or unnumbered sections through `None` |
| `kinds` | `"text"` or `"table"` chunks |

**What to look for in the code**

- All four validators use `mode="after"`, so canonicalization applies only to values that already passed type checking.
- The sort key in `canonicalize_items` is `(item is not None, item or "")`. Comparing `None` against a string directly raises `TypeError`; pushing `None` to the front avoids it.
- Only `canonicalize_kinds` uses schema order (`"text"` then `"table"`) rather than alphabetical. Canonicalization exists to make **the same request hold the same representation**, not to sort lexically.

## Why `RetrievalFilters` uses tuples and canonicalization

Filters are not `list` but `tuple`, with `frozen=True`. If a caller mutates a filter while a request is running, vector search and lexical search can run under **different conditions** — and then the fused result cannot be explained.

Canonicalization (dedupe plus sort) exists for a different reason. `tickers=("NVDA", "AMD")` and `("AMD", "NVDA", "AMD")` are the same request, but without canonicalization they serialize differently. The same request then records as two different ones in a cache key or an evaluation log.

Populated filter fields combine with AND; values inside one field are alternatives. An empty tuple means that dimension is unrestricted.

## 4. `sort_hits` — break ties deterministically

When hits tie on score and their order changes between runs, M3's evaluation numbers move without any code change. So sorting uses not one score but **a key that becomes unique**.

Ties are not an edge case here. Two chunks from the same filing, cut at adjacent boundaries, routinely land on identical cosine distance to four decimal places — and once M2.5 replaces scores with reciprocal-rank sums, exact ties become common rather than rare.

Leave the order underdetermined and here is what a Tuesday looks like: recall@5 reads 0.82. You change the chunker, rerun, and get 0.79. Three points. Is that the change, or is it two tied chunks that happened to swap? There is no way to answer without rerunning the old code several times to see how much it moves on its own — and at that point the evaluation harness is measuring its own noise floor instead of your system.

A deterministic sort is what makes a difference in the number mean a difference in the system.

### Complete `app/retrieval/types.py` — `sort_hits`

**Learning action — implement the determinism rule:** build the sort key tuple yourself before comparing. You should be able to say why the last element is `chunk_id`.

<!-- src: app/retrieval/types.py::sort_hits -->
```python
def sort_hits(hits: Iterable[ChunkHit]) -> list[ChunkHit]:
    """Return hits in deterministic relevance order without mutating the input.

    Higher scores sort first. Equal scores use the stable source citation identity,
    followed by the database chunk id as a final unique tie-breaker.
    """
    return sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
```

**What to look for in the code**

- `-hit.score` is the first element. Using `reverse=True` would flip not just the score but **every tie-breaker**, reversing source order.
- `chunk_id` comes last. It is the primary key, so reaching it always breaks the tie. Without that element, sort results depend on input order.
- `sorted()` builds a new list. The sequence the caller passed is left alone.

Writing this much completes `app/retrieval/types.py`. The four blocks concatenated in order are the checkpoint file itself.

## Why one type deserves this much care

Because this identity is **the foundation of every later ranking, citation, and evaluation decision.**

If coordinates or `index_text` can drift from `body`, the path from a plausible answer back to the snapshot that produced it is severed. M3's evaluation and M4's citations both stand on this type.

The flow, then:

```
DB row     ──▶  strict ChunkHit       ──▶  deterministic sort_hits
request fields ──▶ immutable RetrievalFilters ──▶ identical constraints in vector/lexical SQL
```

## 5. The public API as of M2.1

The later modules do not exist yet, so the package exports only what was just built.

This file is deliberately temporary, and saying so matters. Writing the finished M2.7 version now would be faster in the moment and would break every step in between: the package would import `app.retrieval.vector` before that module exists, and the contract tests for this step would fail on an `ImportError` that has nothing to do with the code under test.

Each checkpoint has to be runnable at the checkpoint. That is the rule the temporary file serves.

### Create `app/retrieval/__init__.py` — temporary M2.1 public API

**Learning action — define the structure:** M2.7 replaces this file. For now it is a temporary surface.

```python
"""Public retrieval contracts available after M2.1."""

from app.retrieval.types import ChunkHit, ChunkKind, RetrievalFilters, sort_hits

__all__ = ["ChunkHit", "ChunkKind", "RetrievalFilters", "sort_hits"]
```

## Focused tests and the contracts they protect

```bash
uv run pytest tests/retrieval/test_01_contract.py -q
```

Read test names first. Each broken value points back to one boundary you just wrote.

| Value the test breaks | Contract being protected |
|---|---|
| A field set drifted from the ORM columns | Retrieval types follow the real database surface. |
| An unknown extra key | A typo or renamed column cannot pass silently. |
| An integer arriving as a string, a NaN score | Coercion and non-deterministic sorting are blocked. |
| A `body` drifted from `index_text` | Matched text and displayed evidence are the same. |
| Duplicate filters differing only in order | One request keeps one serialization and cache key. |
| Input order of tied hits | Ranking does not change between runs. |
| A missing public symbol | The surface later steps depend on actually exists. |

Done correctly, every contract test passes with no test skipped for a missing symbol.

The bar for moving on is simple: a failing test, or a skip caused by a missing canonical symbol, means M2.1 is not complete.

On failure, an import error usually means `__init__.py` was created before the file it depends on. A validation error usually means a field coerced a value, a range was not half-open, or `index_text` did not join `context_header` and `body` exactly.

## What you should be able to explain now

- **Why use `Strict*` instead of Pydantic's default types?**
  - **Answer:** Pydantic's default types may silently coerce values such as `"3"` into `3`; `Strict*` rejects that drift at the boundary.
- **Why re-check in the retrieval type when the ORM `CheckConstraint` already exists?**
  - **Answer:** The ORM constraint protects persisted rows, but retrieval values can be constructed before or outside a database write. Re-checking makes every boundary fail closed.
- **Which explanation of a fused result becomes impossible without `frozen=True`?**
  - **Answer:** If filters can mutate mid-request, the vector and lexical paths may search different populations, so the fused ranking can no longer be attributed to one set of conditions.
- **What exactly breaks in an evaluation log when canonicalization is absent?**
  - **Answer:** The same logical request can serialize in different orders or forms, so identical runs appear as different configurations and their results cannot be compared reliably.
- **What symptom appears if the final `chunk_id` is dropped from the sort key of `sort_hits`?**
  - **Answer:** Fully tied hits fall back to input order, so their ranking—and therefore evaluation output—can change between otherwise identical runs.

---

[Module overview](../03-build.md) · [Next →: Embeddings](02-embeddings.md)
