# M8.3 Tutorial 3 — Two ideas, entered as arms

You now have a before-table showing what happens when a Korean question meets an English index. Two fixes suggest themselves: stop asking the component that cannot answer, or translate the question so it can. Both are plausible, and **a plausible retrieval idea that does not enter the matrix as its own named arm is a belief, not an improvement.** This document builds language detection, wires routing into the production query path, and adds translation through the existing fail-closed provider boundary.

**Prerequisite:** M8.2 is complete and `uv run pytest tests/crosslingual/test_02_crosslingual.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `detect_query_language` | **Implement** the character scan | Presence, not proportion — and no model |
| `retrieve(route_by_language=...)` | **Implement** the skip | A skipped component must be observable |
| `translate_query` | **Implement** the fail-closed call | Where decomposition falls back, translation raises |
| `make_crosslingual_retriever` | **Write the wrappers** | Handling is a wrapper, never a fork of the harness |

### 1. Detection needs no model

The obvious implementations are all worse than the boring one. A language-detection library is a dependency and a probability; an LLM call is money and latency on every query; a majority-script heuristic sounds careful and is actively wrong here, because a real Korean question about this corpus looks like `AMD의 7nm 공급 위험` — a ticker, a unit, and a number in Latin script around a few Korean particles. **A majority-script rule would classify as English exactly the queries this module exists to route.**

#### Create `app/retrieval/language.py` — the scan

**Learning action — implement the character scan:** decide which Unicode ranges matter before writing the loop, and say why each one can appear.

<!-- src: app/retrieval/language.py::HANGUL_SYLLABLES,HANGUL_JAMO,HANGUL_COMPATIBILITY_JAMO,HANGUL_RANGES,contains_hangul,detect_query_language -->
```python
HANGUL_SYLLABLES = (0xAC00, 0xD7A3)
HANGUL_JAMO = (0x1100, 0x11FF)
HANGUL_COMPATIBILITY_JAMO = (0x3130, 0x318F)
HANGUL_RANGES = (HANGUL_SYLLABLES, HANGUL_JAMO, HANGUL_COMPATIBILITY_JAMO)


def contains_hangul(text: str) -> bool:
    """Return whether any character of ``text`` is a Hangul syllable or jamo."""
    return any(start <= ord(character) <= end for character in text for start, end in HANGUL_RANGES)


def detect_query_language(query: str) -> QueryLanguage:
    """Classify one nonblank query as Korean or English.

    Any Hangul makes the query Korean. Korean questions about this corpus are
    mixed by nature — ``"AMD의 7nm 공급 위험"`` carries a ticker, a unit, and a
    number in Latin script — so a majority-script rule would route exactly the
    queries this module exists to route. The rule is therefore presence, not
    proportion, and it is deliberately asymmetric: an English query never
    contains Hangul, so no English query can be misrouted.

    The blank rejection mirrors ``retrieve`` and ``lexical_statement``: a query
    that carries no language at all is a caller error, not a default to English.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    return "ko" if contains_hangul(query) else "en"
```

**What to look for in the code**

- Three ranges, not one. Precomposed syllables are what you normally see; conjoining jamo arrive from decomposed (NFD) input; compatibility jamo arrive from an input method emitting a bare consonant or vowel. **Scanning all three means the query is classified from its own characters, with no dependency on how the client normalized the text.**
- The rule is asymmetric on purpose: an English query never contains Hangul, so no English query can be misrouted. The whole risk of this classifier lives on one side.
- A blank query raises instead of defaulting to English, matching `retrieve`. A query with no language at all is a caller error.

### 2. Skipping is a route; ignoring is a guess

#### Extend `app/config.py` — one field, defaulted off

**Learning action — add the setting:** write the comment that explains why it ships `false`.

```python
# The lexical index is built with the "english" text-search configuration, so a
# Korean query produces no lexical candidates and hybrid fusion silently degrades
# to the vector arm. Enabling this makes retrieve() skip the lexical component for
# a Korean query instead, which is observable in ComponentRankings. Off by default:
# M8 measures the collapse before changing the shipped query path.
query_language_routing: bool = False
```

#### Extend `app/retrieval/service.py` — the parameter and the skip

**Learning action — implement the skip:** follow the shape M2.6 used for `reranker` rather than inventing a new one.

```python
active_routing = (
    settings.query_language_routing if route_by_language is None else route_by_language
)
skip_lexical = active_routing and detect_query_language(normalized_query) == "ko"
```

The flag is resolved once, right after the query is normalized, and the lexical component reads it:

```python
if skip_lexical:
    return []
```

**What to look for in the code**

- `route_by_language: bool | None = None` resolves from `Settings` when omitted — the same three-state pattern M2.6 used for the reranker, so the call site can force either behaviour in a test without touching global configuration.
- The skip returns an empty list from the lexical component rather than short-circuiting the fusion. **`ComponentRankings.lexical` is then empty in the result, so the route that was taken can be read off the response instead of inferred from configuration.** A skip that left no trace would be indistinguishable from a component that ran and found nothing.
- Detection runs on the *normalized* query, so routing sees the same string the retrievers do.
- The setting ships `false`. M8 measures before it changes the shipped path.

### 3. Translation raises where decomposition falls back

#### Create `app/retrieval/translate.py` — the contract

**Learning action — implement the fail-closed call:** compare it line by line with `decompose_query` and name the difference.

<!-- src: app/retrieval/translate.py::QueryTranslationError,QueryTranslation -->
```python
class QueryTranslationError(RuntimeError):
    """One translation request refused, failed validation, or stayed non-English."""


class QueryTranslation(StrictSchema):
    """One structured translation of a query into the corpus language."""

    translated_query: Annotated[StrictStr, Field(min_length=1)]
    source_language: QueryLanguage

    @model_validator(mode="after")
    def reject_blank_translation(self) -> Self:
        """Reject a whitespace-only translation instead of passing it downstream."""
        if not self.translated_query.strip():
            raise ValueError("translated_query must not be blank")
        return self
```

<!-- src: app/retrieval/translate.py::translate_query -->
```python
async def translate_query(
    query: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> QueryTranslation:
    """Translate one query into English, or raise rather than return the original.

    The provider is injected, never read from ``Settings``. A translation arm costs
    money and adds a network hop to the query path, so it can only be switched on by
    a caller that already holds a provider — a configuration flag could turn it on
    everywhere, including inside a request that never asked for it.

    Unlike ``decompose_query``, this call does not fall back to the input on failure.
    Decomposition is an optimization over a query the retriever can already run; a
    failed translation would leave the Korean query to be scored as if it had been
    translated, and the measured number would then describe an arm that never ran.

    Raises
    ------
    QueryTranslationError
        If the provider refuses, exhausts its budget, fails schema validation after
        one repair, or returns a query that still contains Hangul.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    prompt = Prompt(system=TRANSLATE_SYSTEM_PROMPT, user=query)
    result = await llm_provider.complete(prompt, QueryTranslation, provider_budget)
    if result.status != "ok" or result.parsed is None:
        raise QueryTranslationError(f"query translation failed: {result.status}")
    translation = result.parsed
    if detect_query_language(translation.translated_query) != "en":
        raise QueryTranslationError("translated query is not English")
    return translation
```

**What to look for in the code**

- The provider and the budget are parameters, never read from `Settings`. **A configuration flag could put a paid network call inside a request that never asked for one; a required argument cannot.**
- M9.5's `decompose_query` returns the original question on any failure, and that is right there: decomposition is an optimization over a query the retriever can already run. Here the opposite is right. A silent fallback would score the untranslated Korean query as if it had been translated, and the reported number would describe an arm that never ran.
- The last check re-uses `detect_query_language` on the *output*. A model that echoes the Korean query back in a valid JSON envelope passes schema validation and fails this line.
- `StrictSchema` and the existing `LLMProvider.complete` boundary do the rest — no new provider, no new retry policy, no new budget type.

### 4. Handling is a wrapper, never a fork

#### Extend `app/evals/crosslingual.py` — the three query paths

**Learning action — write the wrappers:** notice which one does not go through `make_retriever`, and what that implies for a test.

<!-- src: app/evals/crosslingual.py::make_crosslingual_retriever -->
```python
def make_crosslingual_retriever(
    session: AsyncSession,
    arm: CrosslingualArm,
    *,
    provider: EmbeddingProvider | None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one arm's query handling on top of the unmodified M3 retriever factory.

    Every handling value is a wrapper, never a fork of the harness: ``direct`` is
    ``make_retriever`` itself, ``routed`` is the same production ``retrieve`` call
    with language routing switched on, and ``translated`` rewrites the query before
    handing it to the direct arm. The comparison is therefore between query paths,
    not between evaluation code paths.
    """
    if arm.handling == "direct":
        return make_retriever(
            session,
            strategy=arm.strategy,
            provider=provider,
            lexical_ranker=arm.lexical_ranker,
            candidate_k=arm.candidate_k,
            rrf_k=arm.rrf_k,
            filters=filters,
        )

    if arm.handling == "routed":

        async def routed(query: str, k: int) -> Sequence[ChunkHit]:
            result = await retrieve(
                session,
                query,
                provider=provider,
                k=k,
                candidate_k=arm.candidate_k,
                filters=filters,
                rrf_k=arm.rrf_k,
                route_by_language=True,
                lexical_ranker=arm.lexical_ranker,
            )
            return result.hits

        return routed

    if llm_provider is None or provider_budget is None:
        raise ValueError("translated handling requires an LLM provider and a budget")
    inner = make_retriever(
        session,
        strategy=arm.strategy,
        provider=provider,
        lexical_ranker=arm.lexical_ranker,
        candidate_k=arm.candidate_k,
        rrf_k=arm.rrf_k,
        filters=filters,
    )

    async def translated(query: str, k: int) -> Sequence[ChunkHit]:
        translation = await translate_query(
            query,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        if translation_log is not None:
            translation_log.record(query, translation)
        return await inner(translation.translated_query, k)

    return translated
```

**What to look for in the code**

- All three wrappers return the same `Retriever` callable the M3 harness already takes. **The comparison is between query paths, not between evaluation code paths — nothing in `app/evals/retrieval_eval.py` learns that languages exist.**
- `routed` calls `retrieve` directly instead of `make_retriever`, because routing is a property of the production query path and that is the code being measured. The consequence is a real one: a test that fakes the retriever for a routed arm must fake `retrieve`, or it reaches a live session.
- `translated` records every rewritten query in a log. A translation arm is the one non-deterministic part of this matrix, and a reported score for queries nobody can reconstruct is not evidence.
- The translated arm refuses to be built without a provider and a budget. There is no default that quietly becomes a paid call.

### Focused tests and the contract they keep

```bash
uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q
```

Expected: `22 passed` — 15 for detection and routing, 7 for translation — with no network.

| What the test breaks | Contract it protects |
|---|---|
| A mixed-script query like `AMD의 매출` | Presence, not proportion, decides the language |
| Conjoining or compatibility jamo | All three Hangul ranges are scanned |
| A blank query | Detection raises instead of defaulting to English |
| Routing left on for an English query | Only Korean queries skip the lexical component |
| A provider that refuses or returns Korean | Translation raises instead of returning the input |
| A translated arm built without a provider | No default path can become a paid call |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why is the language rule presence rather than proportion?**
  - **Answer:** Real Korean questions here are mixed-script around tickers and units, so a majority rule would classify as English exactly the queries that need routing.
- **Why does routing skip the component instead of discarding its result?**
  - **Answer:** The empty `ComponentRankings.lexical` makes the route observable in the result, where a silent discard would be indistinguishable from a component that ran and found nothing.
- **Why does `translate_query` raise where `decompose_query` falls back?**
  - **Answer:** A fallback would score the untranslated query as if it had been translated, so the number would describe an arm that never ran.

---

[← Previous: measuring the collapse](02-measuring-the-collapse.md) · [Module overview](../03-build.md) · [Next: the parity gate →](04-parity-gate.md)
