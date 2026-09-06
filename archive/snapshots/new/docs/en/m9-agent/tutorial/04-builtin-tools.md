# M9.4 Tutorial 4 — Tools stay thin

The agent needs something to call. This document wraps M2 retrieval as three typed tools — and the discipline is entirely negative: **a tool translates arguments in and evidence out, and any intelligence beyond that belongs in `app/retrieval`, where M3 can measure it.**

**Prerequisite:** M9.3 is complete and `uv run pytest tests/agent/test_04_loop.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| The parameter models | **Write the argument contracts** | Strict schemas force `X \| None`, not defaults |
| Payload and evidence helpers | **Implement** the translation layer | Evidence ids are extracted, never invented |
| `build_default_registry` | **Implement the wiring** | Three tools, zero new retrieval logic |

### 1. Arguments are contracts, not suggestions

#### Create `app/agent/builtin_tools.py` — the parameter models

**Learning action — write the argument contracts:** for each field, name the failure the constraint prevents.

<!-- src: app/agent/builtin_tools.py::ToolParams,CompareYearsParams -->
```python
class ToolParams(BaseModel):
    """Closed base for tool parameters so unknown arguments always fail."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchFilingsParams(ToolParams):
    """Arguments for one hybrid retrieval call."""

    query: Annotated[str, Field(min_length=1)]
    k: Annotated[int, Field(gt=0, le=20)] | None
    tickers: tuple[str, ...] | None
    fiscal_years: tuple[int, ...] | None
    forms: tuple[str, ...] | None


class FetchChunkParams(ToolParams):
    """Arguments for reading one retrieved chunk in full."""

    chunk_id: Annotated[int, Field(gt=0)]


class CompareYearsParams(ToolParams):
    """Arguments for retrieving the same question across fiscal years."""

    query: Annotated[str, Field(min_length=1)]
    ticker: Annotated[str, Field(min_length=1, max_length=16)]
    fiscal_years: tuple[int, ...]
    k: Annotated[int, Field(gt=0, le=10)] | None

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def validate_years(cls, years: tuple[int, ...]) -> tuple[int, ...]:
        """Require a real comparison: two to four distinct years."""
        if not 2 <= len(years) <= 4:
            raise ValueError("fiscal_years must contain two to four years")
        if len(set(years)) != len(years):
            raise ValueError("fiscal_years must be unique")
        return years
```

**What to look for in the code**

- Every optional field is `X | None` with no default value in the schema sense — **strict function schemas require every key, so "optional" means "the model must explicitly pass null", never "the model may omit it."** This is the same strict-schema consequence M4.4 met, arriving from the tool side.
- `k` is capped at 20 and years at four: the model chooses values, so the schema is where over-asking is stopped — not a code review of the model's behavior.
- `CompareYearsParams` validates the count and uniqueness of years in the model itself, so a nonsense comparison fails at the boundary with a message the dispatch layer will relay as an observation.

### 2. Payloads carry their own evidence

#### Extend `app/agent/builtin_tools.py` — payload shaping and evidence extraction

**Learning action — implement the translation layer:** trace one `ChunkHit` from M2 into a payload dict and its evidence ids.

<!-- src: app/agent/builtin_tools.py::_hit_payload,_chunk_evidence -->
```python
def _hit_payload(hit: ChunkHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "citation": hit.citation,
        "score": hit.score,
        "snippet": hit.index_text[:SNIPPET_CHARS],
    }


def _search_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return tuple(hit["chunk_id"] for hit in output["hits"])


def _compare_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return tuple(hit["chunk_id"] for year in output["years"] for hit in year["hits"])


def _chunk_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return (output["chunk_id"],)
```

**What to look for in the code**

- Snippets are truncated to `SNIPPET_CHARS` and bodies to `BODY_CHARS`. The model's context is a budget too; a tool that dumps whole filings would spend it for everyone.
- Each extractor knows only its own payload shape. **The loop learns which chunk ids became citable evidence from these extractors — this is the supply side of the citation gate built in tutorial 3.**
- The payload keeps `chunk_id`, `doc_id`, and the human citation on every hit, so a later `final_answer` can cite without a second lookup.

### 3. The wiring is the whole tool

#### Extend `app/agent/builtin_tools.py` — the default registry

**Learning action — implement the wiring:** confirm each runner body is a translation plus one M2 call, nothing else.

<!-- src: app/agent/builtin_tools.py::build_default_registry -->
```python
def build_default_registry(
    session: AsyncSession,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> ToolRegistry:
    """Register the built-in filing tools over one caller-owned session.

    Every tool is a thin typed wrapper: retrieval semantics stay in M2, and the
    tools only decide which arguments the model may vary and which payload
    fields become evidence.
    """

    async def search_filings(params: SearchFilingsParams) -> dict[str, Any]:
        result = await retrieve(
            session,
            params.query,
            provider=embedding_provider,
            k=params.k or DEFAULT_SEARCH_K,
            candidate_k=candidate_k,
            filters=RetrievalFilters(
                tickers=params.tickers or (),
                fiscal_years=params.fiscal_years or (),
                forms=params.forms or (),
            ),
            rrf_k=rrf_k,
        )
        return {"hits": [_hit_payload(hit) for hit in result.hits]}

    async def fetch_chunk(params: FetchChunkParams) -> dict[str, Any]:
        chunk = await session.get(Chunk, params.chunk_id)
        if chunk is None:
            raise ValueError(f"chunk {params.chunk_id} does not exist")
        return {
            "chunk_id": chunk.id,
            "doc_id": chunk.doc_id,
            "citation": chunk.citation,
            "context_header": chunk.context_header,
            "body": chunk.body[:BODY_CHARS],
        }

    async def compare_years(params: CompareYearsParams) -> dict[str, Any]:
        years: list[dict[str, Any]] = []
        for fiscal_year in sorted(params.fiscal_years):
            result = await retrieve(
                session,
                params.query,
                provider=embedding_provider,
                k=params.k or 3,
                candidate_k=candidate_k,
                filters=RetrievalFilters(
                    tickers=(params.ticker,),
                    fiscal_years=(fiscal_year,),
                ),
                rrf_k=rrf_k,
            )
            years.append(
                {
                    "fiscal_year": fiscal_year,
                    "hits": [_hit_payload(hit) for hit in result.hits],
                }
            )
        return {"ticker": params.ticker, "years": years}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search_filings",
            description=(
                "Hybrid-search the 10-K corpus and return scored, citable chunks. "
                "Optional tickers, fiscal_years, and forms narrow the corpus; "
                "null means unrestricted."
            ),
            parameters=SearchFilingsParams,
            run=search_filings,
            evidence_ids=_search_evidence,
        )
    )
    registry.register(
        Tool(
            name="fetch_chunk",
            description="Read one previously retrieved chunk in full by its chunk_id.",
            parameters=FetchChunkParams,
            run=fetch_chunk,
            evidence_ids=_chunk_evidence,
        )
    )
    registry.register(
        Tool(
            name="compare_years",
            description=(
                "Run the same question against one ticker across two to four "
                "fiscal years and return the evidence grouped by year."
            ),
            parameters=CompareYearsParams,
            run=compare_years,
            evidence_ids=_compare_evidence,
        )
    )
    return registry
```

**What to look for in the code**

- `search_filings` and `compare_years` both bottom out in M2's `retrieve` with different filters; `fetch_chunk` is a primary-key lookup. No new ranking, no new scoring.
- `compare_years` runs one filtered search per year and returns them side by side — the comparison intelligence stays with the model, which can read both result sets.
- **If a tool ever seems to need smarter retrieval, that is a feature request for `app/retrieval` with an M3 evaluation attached — not a private ranking hidden where no harness measures it.** Tutorial 5 does exactly this, the right way.

### Focused tests and the contract they keep

```bash
uv run pytest tests/agent/test_05_builtin_tools.py -q
```

| What the test breaks | Contract it protects |
|---|---|
| Arguments that skip validation | Filters reaching M2 are exactly the validated ones |
| A payload without ids and citations | Every hit stays citable downstream |
| Evidence ids diverging from the payload | The citation gate's supply side stays honest |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why does "optional" become "explicitly null" in these schemas?**
  - **Answer:** Strict schemas require every key, so optionality must be expressed in the type, not by omission — the M4.4 rule seen from the tool side.
- **Why is truncation a tool responsibility?**
  - **Answer:** Tool output becomes model input; an unbounded payload spends the context budget that the loop's token guard is trying to protect.
- **Where would a smarter search ranking belong, and why not here?**
  - **Answer:** In `app/retrieval` under the M3 harness — logic inside a tool is unmeasured logic, and this repository does not ship unmeasured ranking.

---

[← Previous: the loop](03-loop.md) · [Module overview](../03-build.md) · [Next: decomposition →](05-decomposition.md)
