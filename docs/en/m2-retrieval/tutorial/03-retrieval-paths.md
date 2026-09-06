# M2.3–M2.4 Tutorial 3 — Two retrieval paths

**Prerequisite:** Tutorial 2's `uv run pytest tests/retrieval/test_02_embeddings.py -q` passes.

## M2.3 — Start with deliberately slow exact search

Now vector search. Most pgvector tutorials reach straight for an HNSW index, because it is fast.

Here **no index is built.** It starts with exact search that scans everything.

### Why the approximate index is deferred

Vector indexes like HNSW and IVFFlat are **approximate**. They trade a little accuracy for speed. Usually a good deal.

The problem is order. Lay down an approximate index from the start and, when retrieval quality later comes out low, the cause is unknown.

- is the embedding bad?
- is the chunking bad?
- did the index miss it?

**An exact baseline separates those three.** If exact search gives recall 0.82 and turning on the index gives 0.79, that 0.03 is the index's cost. Without the baseline there is no telling whether 0.79 is good or bad.

M3's evaluation runs on top of this baseline. **Optimize after a measurable baseline exists.** It also helps that a full scan over 9,172 rows is fast enough.

### Where distance and similarity get flipped

pgvector's `<=>` operator gives **cosine distance**. Closer means smaller, and 0 is an exact match.

But a retrieval result's `score` reads naturally as bigger-is-better. Making the sorting and fusion code remember "this one is better when smaller" invites mistakes.

So it is **flipped once at the boundary.** The SQL sorts by distance (`distance.asc()`), and building the public `ChunkHit` converts to similarity with `1 - distance`. Everything leaving the module is uniformly bigger-is-better.

### What to define, what to implement, and what to inspect

M2.3 builds `app/retrieval/vector.py` in five steps. The statement builder and the executor are separate so that SQL can be tested without a database.

| Area | Learning action | What to take away |
|---|---|---|
| Module header | **Define the structure** | Which contracts this file depends on |
| `validate_query_vector` | **Implement** the input guard yourself | Why the query side needs its own validation |
| `_filtered_statement` | **Implement** the filter mapping yourself | Which filter semantics both retrieval paths must match |
| `vector_search_statement` | **Implement** the ordering decision yourself | Where determinism is actually pinned |
| `vector_search` | **Write the field mapping, then inspect boundary conversions** | Where distance becomes similarity |

### 1. Module header

#### Create `app/retrieval/vector.py` — module header

**Learning action — define the structure:** note that `DIM` comes from the ORM, not from settings. The column decides the dimension.

```python
"""Filtered, deterministic pgvector cosine retrieval."""

from collections.abc import Sequence
import math
from numbers import Real
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM, Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters
```

### 2. Guarding the query vector

M2.2 validated provider output. This is the other side: a vector arriving as a query argument. It may come from a caller who never touched a provider.

The instinct is to skip it. The vector came from our own embedder two lines ago, so what is there to check?

Except it did not, necessarily. A test constructs vectors by hand. An evaluation harness loads them from a cached file written by a different model run. M5's API accepts a vector from a client. Each of those paths reaches this function without passing through `validate_embeddings`, and each one can arrive with 1,536 dimensions when the column holds 384, or with a NaN in position 200 because a normalization divided by zero upstream.

The wrong-dimension case at least fails loudly inside pgvector. The NaN does not: every comparison against NaN is false, so the query returns rows, just never the right ones.

#### Extend `app/retrieval/vector.py` — query vector validation

**Learning action — implement the input guard:** the shape mirrors `validate_embeddings`, with one difference worth finding.

<!-- src: app/retrieval/vector.py::validate_query_vector -->
```python
def validate_query_vector(values: Sequence[float], *, dimensions: int = DIM) -> list[float]:
    """Return a finite vector whose shape matches the database column."""
    if len(values) != dimensions:
        raise ValueError(f"query vector has dimension {len(values)}, expected {dimensions}")
    vector: list[float] = []
    for component in values:
        if isinstance(component, bool) or not isinstance(component, Real):
            raise ValueError("query vector contains a nonnumeric component")
        number = float(component)
        if not math.isfinite(number):
            raise ValueError("query vector contains a non-finite component")
        vector.append(number)
    return vector
```

**What to look for in the code**

- `Sequence[float]` in the signature is the static contract established in M2.2; `isinstance(component, Real)` inside the function is runtime validation. The two types do not belong in the same position.
- The default `dimensions=DIM` reads the ORM column width. A query vector that disagrees with the stored column can never produce a meaningful distance.
- The `bool` and `math.isfinite` rejections repeat M2.2's rules because this input never passed through a provider.
- A NaN component would make every distance comparison false, so the query would silently return nothing rather than fail.

### 3. One filter mapping for both retrieval paths

Filters look like the boring part of a retrieval module. They are, right up until the moment they are not.

The thing to hold onto is that M2.5 will fuse two ranked lists and present the result as a single answer. That presentation is only honest if both lists were drawn from the same population. A filter is precisely what defines that population — so a filter that behaves differently on the two paths does not produce a slightly worse ranking, it produces a ranking of nothing coherent at all.

Which means the mapping below is not plumbing. It is half of a contract whose other half lives in M2.4, and the two halves have to agree exactly.

#### Extend `app/retrieval/vector.py` — shared filter predicates

**Learning action — implement the filter mapping:** write the branches in order. The `items` branch is the only one that is not a plain `IN` clause.

<!-- src: app/retrieval/vector.py::_filtered_statement -->
```python
def _filtered_statement(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    """Apply exact-match chunk and document filters with AND semantics."""
    if filters.tickers or filters.fiscal_years or filters.forms:
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    if filters.doc_ids:
        statement = statement.where(Chunk.doc_id.in_(filters.doc_ids))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates = []
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        statement = statement.where(or_(*item_predicates))
    if filters.kinds:
        statement = statement.where(Chunk.kind.in_(filters.kinds))
    if filters.tickers:
        statement = statement.where(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        statement = statement.where(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        statement = statement.where(Document.form.in_(filters.forms))
    return statement
```

**What to look for in the code**

- The join is added only when a document-level filter is present. Joining unconditionally would cost a join on every query that filters on chunks alone.
- `items` cannot use a single `IN` because `None` means "unnumbered section" and SQL `IN` never matches NULL. The `or_` combines an `IS NULL` predicate with the `IN` list.
- Each populated field appends another `where`, which is how AND semantics arise. An empty tuple simply adds nothing.
- M2.4 does not import this function; it writes its own `_filter_predicates`. What the two paths share is the `RetrievalFilters` contract, not the code — so their semantics have to be kept identical by hand. Change one and forget the other and the paths look at different document sets, and then the fused result cannot be explained.

### 4. The statement, where determinism is pinned

Everything so far has been preparation. This function is the query.

Read it once for what it does — cosine distance, exclude nulls, apply filters, order, limit — and then read it a second time asking a narrower question: *which line here is a decision someone could get wrong, and what would happen if they did?* There are three, and they are not the lines that look complicated.

#### Extend `app/retrieval/vector.py` — the exact cosine statement

**Learning action — implement the ordering decision:** build the statement, then write the six sort keys yourself and justify each one.

<!-- src: app/retrieval/vector.py::vector_search_statement -->
```python
def vector_search_statement(
    query_vector: Sequence[float],
    *,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build the exact cosine query used by runtime and SQL contract tests."""
    if k <= 0:
        raise ValueError("vector search k must be positive")
    vector = validate_query_vector(query_vector)
    restrictions = filters or RetrievalFilters()
    distance = Chunk.embedding.cosine_distance(vector).label("distance")
    statement = select(Chunk, distance).where(Chunk.embedding.is_not(None))
    statement = _filtered_statement(statement, restrictions)
    return statement.order_by(
        distance.asc(),
        Chunk.doc_id.asc(),
        Chunk.source_sha256.asc(),
        Chunk.start_char.asc(),
        Chunk.end_char.asc(),
        Chunk.id.asc(),
    ).limit(k)
```

**What to look for in the code**

- `Chunk.embedding.is_not(None)` — the nullable column from M1.4 earns its keep again. Chunks not yet backfilled are excluded from retrieval. Had the column defaulted to a zero vector, those chunks would have mixed in as results "equally irrelevant to every query."
- `distance.asc()` sorts by distance, not similarity. The flip to bigger-is-better happens later, in step 5, and only once.
- Five tie-breaking keys follow the distance: `doc_id`, `source_sha256`, `start_char`, `end_char`, `id`. It looks excessive, and there is a reason. When chunks tie on distance the database guarantees no order. If result order shifts between runs, **M3's evaluation score shifts between runs** and there is no telling regression from noise. Pinning the sort to a complete source identity is what makes it deterministic.
- Returning a `Select` rather than rows is what lets the contract tests compile this SQL and inspect it with no database running.

### 5. Executing and converting at the boundary

One line in this function matters and eleven do not.

The eleven are field assignments, copying a database row into a `ChunkHit`. Tedious, and the tedium is the point: nothing is dropped, so the validator from M2.1 gets everything it needs to check.

The one is `score`, where cosine distance becomes similarity. After it, no other module in this project ever has to remember which direction is better.

#### Complete `app/retrieval/vector.py` — execution and similarity conversion

**Learning action — write the field mapping, then inspect the boundary conversion:** the twelve field assignments are mechanical. The last one is the decision.

<!-- src: app/retrieval/vector.py::vector_search -->
```python
async def vector_search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Return complete chunk evidence ordered by cosine similarity."""
    if k < 0:
        raise ValueError("vector search k must not be negative")
    if k == 0:
        return []

    statement = vector_search_statement(query_vector, k=k, filters=filters)
    rows = (await session.execute(statement)).all()
    return [
        ChunkHit(
            chunk_id=chunk.id,
            doc_id=chunk.doc_id,
            item=chunk.item,
            kind=chunk.kind,
            citation=chunk.citation,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            source_sha256=chunk.source_sha256,
            body=chunk.body,
            context_header=chunk.context_header,
            index_text=chunk.index_text,
            score=1.0 - float(distance),
        )
        for chunk, distance in rows
    ]
```

**What to look for in the code**

- `score=1.0 - float(distance)` is the single flip. Past this line nothing in the codebase has to remember that smaller was better.
- `k == 0` returns early rather than reaching the statement builder, which rejects non-positive `k`. The two functions have deliberately different contracts: the builder requires a real query, the executor tolerates an empty request.
- Every `ChunkHit` field is filled from the row, so `index_text` and `body` arrive together and M2.1's validator can check their relationship. Selecting fewer columns to save bandwidth would break that check.

Writing this much completes `app/retrieval/vector.py`. The five blocks concatenated in order are the checkpoint file itself.

The path, then:

#### No file changes — reading the vector path end to end

```
query vector → dimension/finiteness validation → cosine-distance query → filtering → similarity conversion → sorted ChunkHit
```

### Focused tests and the contracts they protect

#### Run `tests/retrieval/test_03_vector.py`

```bash
uv run pytest tests/retrieval/test_03_vector.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A query vector of the wrong width | Query and column share one dimension. |
| Chunks whose embedding is still null | Unembedded rows never appear as results. |
| An index hint in the compiled SQL | The exact baseline stays exact. |
| Distance sorted in the wrong direction | Nearest evidence ranks first. |
| A public score that is not `1 - distance` | Everything outside the module is bigger-is-better. |
| Input order of chunks tied on distance | Evaluation scores do not move without a code change. |

A clean pass means all vector tests pass, including compiled PostgreSQL SQL, null-vector exclusion, filters, complete hit mapping, deterministic ties, and the no-HNSW guard.

The rule for moving on is simple: do not accept M2.3 if cosine distance is sorted in the wrong direction, the public score is not `1 - distance`, or any filter/tie-breaker test fails.

When it fails, inspect the compiled SQL before database code. Confirm `<=>` produces distance, null embeddings are excluded, and every source-identity column participates in the final ordering.

### What you should be able to explain now

- **What would an approximate index make impossible to measure?**
  - **Answer:** Without an exact-search baseline, the recall lost specifically because the approximate index skipped true neighbours cannot be isolated.
- **Why does the query vector need validation when provider output was already validated?**
  - **Answer:** Query vectors can also arrive from tests, caches, or clients without passing through the provider validator, so their dimension and finiteness must be checked at this boundary.
- **Why can the `items` filter not be one `IN` clause?**
  - **Answer:** `None` means an unnumbered section, but SQL `IN` never matches `NULL`; matching it requires an `IS NULL` predicate joined to the named items with `OR`.
- **Which failure appears when the five tie-breaking keys are removed?**
  - **Answer:** Equal-distance rows have no guaranteed database order, so rankings and M3 evaluation scores fluctuate between identical runs.
- **Why is the distance-to-similarity flip done exactly once, and where?**
  - **Answer:** A single conversion prevents different callers from reversing the direction inconsistently. It happens in `vector_search` when `score` is set to `1 - distance`.

## M2.4 — A second path for what embeddings miss

Look concretely at why vector search alone is not enough.

What happens when a user asks about "Item 7A"? To an embedding model, "Item 7A" is a short, featureless token. In the semantic space it sits almost exactly where "Item 7" and "Item 8" sit. The amount `26,974` is the same story, and so is the ticker `MU`.

Such **exact tokens** are far better served by lexical retrieval, which only has to check whether the characters match.

### No separate search engine

This is usually the point where Elasticsearch or OpenSearch gets added. It is not needed here.

**PostgreSQL already has full-text search, and the data is already inside it.** That is what M1.4's generated `content_tsv` column and GIN index were for.

Stand up a separate search engine and the data must be synchronized in two places, which from that moment introduces a new class of bug: "is the index current?" There is no reason to buy that complexity for 9,172 rows.

**Do not grow infrastructure before it is needed.** Should the corpus reach millions later, move then — and at that point only the `lexical_search` function changes.

### Turning user input into a tsquery safely

There is a common accident in full-text search: assembling user input into tsquery syntax by hand. Build a string like `"NVIDIA & risk"` and the moment a user types `&`, `!`, or a parenthesis, it blows up on a syntax error.

`websearch_to_tsquery` solves this. It accepts a natural string of the kind you would type into a search box — quotes, `or`, `-` included — and **converts it into a valid tsquery on its own.** Odd input yields an empty result rather than an exception.

And the query is always passed as a **bind parameter**. Interpolating it into SQL with string formatting opens an injection path.

### What to define, what to implement, and what to inspect

M2.4 builds `app/retrieval/lexical.py` in four steps. It mirrors M2.3's shape — statement builder separate from executor — so the SQL stays testable without a database.

| Area | Learning action | What to take away |
|---|---|---|
| Module header | **Define the structure** | Why the module docstring states what this is *not* |
| `_filter_predicates` | **Implement** the filter mapping yourself | Where it must agree with M2.3, and where it deliberately differs |
| `lexical_statement` | **Implement** the safe query construction yourself | How raw user text reaches SQL without becoming syntax |
| `lexical_search` | **Review the design decision** | Why this score must never be compared against a vector score |

### 1. Module header

#### Create `app/retrieval/lexical.py` — module header

**Learning action — define the structure:** read the docstring closely. It exists to stop a specific false claim.

```python
"""PostgreSQL full-text lexical retrieval.

This is the project's mandatory lexical baseline. It uses PostgreSQL full-text
search with cover-density ranking; ``ts_rank_cd`` is not literal BM25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters

TEXT_SEARCH_CONFIG = "english"

# ``ts_rank_cd`` normalization bitmask (PostgreSQL, "Ranking Search Results").
# Bit 4 divides the rank by the mean harmonic distance between extents, so query
# terms that appear close together outrank the same terms scattered apart; bit 1
# divides by ``1 + log(document length)``, so a long chunk stuffed with one common
# term cannot outrank a short chunk that actually answers. With the default of 0,
# rank degenerates into occurrence counting and, measured on the golden suite,
# recall@5 is exactly zero; 4|1 is the best-scoring native combination.
TS_RANK_NORMALIZATION = 4 | 1
```

**What to look for in the code**

- The docstring says `ts_rank_cd` is **not** BM25. Cover density and BM25 are different formulas, and calling this "BM25" in a paper or a README would be a false claim about the system. Real BM25 is written out in [Tutorial 7](07-bm25.md); it waits for M2.9 so that swapping it in can prove this adapter boundary holds.
- `TEXT_SEARCH_CONFIG` is a module constant, not an inline literal. The stemming dictionary used at query time must match the one M1.4 used to generate `content_tsv`; a mismatch silently stops matching stemmed words.
- `TS_RANK_NORMALIZATION` is measured, not guessed. Every one of PostgreSQL's normalization bitmasks was swept against the golden suite, and this comment records why the winner wins. The sweep itself is the story of section 3.

### 2. Filters that must agree with vector search

Here is the other half of the contract M2.3 opened, and the honest thing to say about it is that the project got this one only half right.

The two filter functions are not shared code. They are two separate private functions in two separate modules, written to mean the same thing. Read them side by side and you will find they do — same six dimensions, same AND semantics, same `None`-means-unnumbered handling — but nothing except care keeps them that way.

That is a real design cost, and it is worth naming rather than papering over. The reason it survives is that the two statements are shaped differently enough that a shared helper would have to be told which shape to produce, and a helper with a mode flag is its own kind of trap. The reason it is dangerous is that the failure it invites — one path filtering differently from the other — is exactly the failure M2.5 cannot detect.

Write it, then compare the two functions deliberately. That comparison is the actual exercise here.

#### Extend `app/retrieval/lexical.py` — filter predicates

**Learning action — implement the filter mapping:** implement the same six dimensions as M2.3. Then compare the two functions and name every difference.

<!-- src: app/retrieval/lexical.py::_filter_predicates -->
```python
def _filter_predicates(filters: RetrievalFilters) -> tuple[ColumnElement[bool], ...]:
    """Translate the shared exact-match filters to composable SQL predicates."""
    predicates: list[ColumnElement[bool]] = []
    if filters.doc_ids:
        predicates.append(Chunk.doc_id.in_(filters.doc_ids))
    if filters.tickers:
        predicates.append(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        predicates.append(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        predicates.append(Document.form.in_(filters.forms))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(Chunk.kind.in_(filters.kinds))
    return tuple(predicates)
```

**What to look for in the code**

- This returns a tuple of predicates instead of taking a statement and returning a modified one, the way M2.3's `_filtered_statement` does. Two shapes, one meaning.
- There is no conditional join here. `lexical_statement` joins `Document` unconditionally, so this function never has to decide.
- The `items` branch builds the same `or_` of `IN` and `IS NULL`, only with the two predicates appended in the opposite order. Order inside `or_` does not change the result set, but it is worth noticing that these are two hand-maintained copies.
- **This is duplicated logic, and that is the risk to remember.** Nothing forces the two functions to stay in step. Add a filter dimension to one and forget the other, and vector and lexical retrieval quietly search different document sets.

### 3. Building the query without letting user text become syntax

Three failures live in this one function. Two are dangers everyone eventually learns to look for; the third stayed invisible until the evaluation suite measured it.

The first is injection: never format user text into SQL. SQLAlchemy handles that as long as the query travels as a value.

The second is subtler and specific to full-text search. Even with perfect parameter binding, `to_tsquery` treats its *argument* as a language. A bound parameter containing `risk & (a|b` is not an injection — it is a syntactically invalid tsquery, and PostgreSQL raises. Your search box now returns a 500 to anyone who types a stray parenthesis.

`websearch_to_tsquery` closes the second hole by parsing its argument as prose rather than as syntax. Two dangers, two mechanisms, one function call.

The third failure is what that function call *produces*. `websearch_to_tsquery` joins every content lexeme with `&`, so the golden question "What was the total revenue reported for fiscal 2024?" becomes five AND-ed stems, and only a chunk containing all five matches. On this corpus that is no chunk at all: the first M3 run recorded **zero hits for all 28 evaluation cases**, recall@5 exactly 0.000, and nothing raised anywhere, because an empty result set is not an error. A retrieval path can be injection-safe, syntax-safe, and completely useless at the same time.

The statement therefore relaxes the parsed query before using it. The tsquery's text form quotes each lexeme and never contains `&` inside one, so rewriting `&` to `|` and reparsing with `to_tsquery` turns the conjunction into a disjunction while leaving quoted phrases (`<->`) intact.

Relaxing the match then exposes the next layer of the same problem. With candidates flowing at last, `ts_rank_cd`'s default normalization ranks by little more than occurrence counting, and a chunk stuffed with one ubiquitous term — `AMD`, `fiscal` — beats the chunk that answers: measured recall stayed 0.000 *with* candidates. A sweep of every normalization bitmask against the golden suite picked `4 | 1`, which rewards query terms that co-occur closely and damps long term-stuffed chunks, and lifted recall@5 to 0.271. That number, next to BM25's 0.521 on the same corpus, is exactly the honest comparison M3 exists to make.

#### Extend `app/retrieval/lexical.py` — the safe FTS statement

**Learning action — implement the safe query construction:** write the two guards first, then the parse-and-relax pair, then the normalized `score` expression, then the twelve selected columns.

<!-- src: app/retrieval/lexical.py::lexical_statement -->
```python
def lexical_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build a safe PostgreSQL FTS statement ranked by cover density.

    ``websearch_to_tsquery`` accepts raw user text without exposing ``to_tsquery``
    syntax errors, and SQLAlchemy binds ``query`` as a value instead of interpolating
    it. But its output joins every content lexeme with ``&``: a natural-language
    question like "What was the total revenue reported for fiscal 2024?" becomes
    five AND-ed stems, and only a chunk containing all five matches. On this corpus
    that describes almost no chunk, and the baseline silently returns nothing.

    The statement therefore relaxes the parsed query before using it. The tsquery's
    text form quotes each lexeme and can never contain ``&`` inside one, so
    rewriting ``&`` to ``|`` and reparsing with ``to_tsquery`` turns the conjunction
    into a disjunction while leaving quoted phrases (``<->``) intact. Matching any
    query term is enough to become a candidate, and ``TS_RANK_NORMALIZATION`` makes
    the ranking prefer chunks where more of the query co-occurs closely over chunks
    that merely repeat one common term. One semantic is knowingly weakened: an
    explicit ``-term`` exclusion is relaxed along with everything else.

    PostgreSQL FTS is the lexical baseline here; this statement does not implement BM25.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    active_filters = filters or RetrievalFilters()
    parsed = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)
    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, func.replace(cast(parsed, Text), "&", "|"))
    score = func.ts_rank_cd(Chunk.content_tsv, tsquery, TS_RANK_NORMALIZATION).label("score")
    return (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.doc_id,
            Chunk.item,
            Chunk.kind,
            Chunk.citation,
            Chunk.start_char,
            Chunk.end_char,
            Chunk.source_sha256,
            Chunk.body,
            Chunk.context_header,
            Chunk.index_text,
            score,
        )
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(Chunk.content_tsv.op("@@")(tsquery), *_filter_predicates(active_filters))
        .order_by(
            score.desc(),
            Chunk.doc_id.asc(),
            Chunk.source_sha256.asc(),
            Chunk.start_char.asc(),
            Chunk.end_char.asc(),
            Chunk.id.asc(),
        )
        .limit(k)
    )
```

**What to look for in the code**

- `func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)` passes `query` as a function argument, which SQLAlchemy binds as a parameter. That is the whole injection defence — no formatting, no concatenation.
- The relaxation happens to the tsquery's *text form*, not to the user's text. Rewriting the raw query in Python would mean tokenizing it a second time, and a second tokenizer that can disagree with PostgreSQL's is exactly the class of bug this module avoids everywhere else. Lexemes cannot contain `&`, so the rewrite cannot corrupt one.
- Quoted phrases survive the relaxation because `websearch_to_tsquery` compiles them to the `<->` operator, and only `&` is rewritten. One semantic is knowingly weakened: an explicit `-term` exclusion is relaxed along with everything else.
- The `tsquery` expression is built once and used twice: for `score` and for the `@@` match. Building it twice would compile two identical subexpressions and invite them to drift apart. Candidates and ranks must come from the same relaxed query, or a chunk could be ranked by a query it never matched.
- `TS_RANK_NORMALIZATION` rides along as `ts_rank_cd`'s third argument. Without it the fix would look complete and measure nothing: matching was necessary, ranking was sufficient.
- `score.desc()` sorts descending here, unlike M2.3's ascending distance. `ts_rank_cd` is already bigger-is-better, so there is nothing to flip.
- The five tie-breakers after `score` are the same five as M2.3, for the same reason.
- `Chunk.id.label("chunk_id")` renames the column so the row maps straight onto `ChunkHit`, which is what step 4 relies on.

### 4. Executing, and the score that must not be compared

#### Complete `app/retrieval/lexical.py` — execution

**Learning action — review the design decision:** this function is two lines. The docstring carries the constraint that M2.5 depends on.

<!-- src: app/retrieval/lexical.py::lexical_search -->
```python
async def lexical_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Run the PostgreSQL FTS baseline and return typed, deterministically ordered hits.

    The returned score is the native ``ts_rank_cd`` cover-density score, not BM25
    and not a probability. Fusion must consume its rank instead of comparing this
    value directly with another retrieval strategy's score.
    """
    result = await session.execute(lexical_statement(query, k, filters))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
```

**What to look for in the code**

- `ChunkHit.model_validate(row)` over `result.mappings()` works only because step 3 selected column names that match the field names exactly. M2.3 built each `ChunkHit` by hand instead, because it had to compute `score` from a distance.
- Validation still runs on every row, so a lexical hit whose `index_text` disagrees with its `body` is rejected here just as it would be on the vector path.
- The docstring's last sentence is a hard constraint, not advice. `ts_rank_cd` values have no fixed range and no meaning across queries. M2.5 exists because of this line.

Writing this much completes `app/retrieval/lexical.py`. The four blocks concatenated in order are the checkpoint file itself.

### Focused tests and the contracts they protect

#### Run `tests/retrieval/test_04_lexical.py`

```bash
uv run pytest tests/retrieval/test_04_lexical.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A query with tsquery punctuation in it | User text never becomes query syntax. |
| An interpolated instead of bound query | No injection path exists. |
| A filter that behaves unlike the vector path | Both retrieval paths see one document set. |
| A missing evidence column | Every lexical hit carries complete provenance. |
| Input order of hits tied on rank | Ordering stays deterministic across runs. |
| A conjunction that requires every query term | A partial match is still a candidate; recall cannot silently be zero. |
| A rank computed with default normalization | Occurrence counting cannot outrank close co-occurrence. |

A clean pass means all lexical tests pass with parameterized SQL, shared filters, complete evidence fields, and deterministic ordering.

The rule for moving on is simple: do not accept M2.4 if the raw query is interpolated, filter behavior differs from vector search, or the implementation is described as BM25.

When it fails, inspect the compiled PostgreSQL statement. The query must remain a bound value, `websearch_to_tsquery` must parse it, the relaxed `to_tsquery` rewrite must feed both the match and the rank, and the `Document` join must support the same metadata filters used by vector search.

### What you should be able to explain now

- **Which query would vector search handle badly, and why?**
  - **Answer:** Queries dominated by exact tokens such as `Item 7A`, `26,974`, or `MU` are weak cases because embeddings tend to blur short, similar-looking identifiers.
- **What new class of bug does a separate search engine introduce?**
  - **Answer:** It creates synchronization drift: the database and the external index can contain different versions of the corpus.
- **What does `websearch_to_tsquery` protect against that hand-built syntax does not?**
  - **Answer:** It converts ordinary user text and punctuation into valid tsquery syntax, preventing malformed operators or parentheses from turning a search into a PostgreSQL syntax error.
- **Why does this path sort descending while M2.3 sorts ascending?**
  - **Answer:** `ts_rank_cd` is already bigger-is-better, whereas M2.3 orders cosine distance, where smaller means closer.
- **Why can this score not be compared directly with a vector score?**
  - **Answer:** A cover-density rank has no fixed range and uses different units from cosine similarity, so only their within-retriever ranks are comparable.
- **Why is the parsed query relaxed from AND to OR before it is used?**
  - **Answer:** `websearch_to_tsquery` requires one chunk to contain every content lexeme of the question, and on this corpus no chunk does — the unrelaxed baseline measured zero hits across the entire golden suite without raising anything.
- **Why does the relaxation rewrite the tsquery's text form instead of the user's text?**
  - **Answer:** The text form quotes each lexeme and cannot contain `&` inside one, so the rewrite is safe; editing the raw question would require a second tokenizer that could disagree with PostgreSQL's.
- **What did the normalization bitmask change that the relaxation alone did not?**
  - **Answer:** With candidates but default normalization, rank degenerates into occurrence counting and chunks stuffed with one common term win — recall stayed at zero until `4 | 1` made close co-occurrence outrank repetition.

---

[← Previous: Embeddings](02-embeddings.md) · [Module overview](../03-build.md) · [Next →: Fusion](04-fusion.md)
