# M4.1 Tutorial 3 — Provider implementations and the public surface

Tutorial 2 ended with seven module-level functions — parsers, budget judges, and a repair-prompt builder — and nothing that calls them. Each answers one question, and no function decides when it runs. That gap is not cosmetic: without a fixed order, nothing stops a caller from acting on a perfectly parsed answer whose call had already blown its budget, or from paying for a repair request that the remaining allowance could never cover.

This document builds `LLMProvider`, the abstract class that fixes the call order in exactly one place, and the two implementations above it. The invariant this file establishes: once the arguments pass the type guards, no exception raised by `_request` escapes `complete()` — every call, however it ends, comes back as one `ProviderResult`. Misuse of the boundary itself — an untyped argument, a clock that runs backwards — still raises, deliberately: those are programming errors, not run outcomes.

**Prerequisite:** The decision functions of `llm/provider.py` from tutorial 2 are written. Their tests run at the end of this document.

### What the abstract class does and does not do

`LLMProvider` **never sends a single request itself.** `_request` is abstract, and `complete()` calls it up to twice while handling validation, budget, and repair.

> **Concept — Template Method**
>
> The shape has a classic name: Template Method. A base class implements the whole algorithm as one concrete method and leaves a single abstract hole for the step that varies; each subclass fills the hole and inherits the algorithm unchanged.
>
> Here the algorithm is the validate-budget-repair loop and the hole is the request itself. Because the retry policy lives only in the base class, proving it once against an offline subclass proves it for every subclass — structurally, not by diligence.
>
> The pattern also names the failure mode: a subclass that overrides the concrete method instead of the hole forfeits every guarantee this document builds.

That separation is what lets the deterministic provider and the OpenAI provider **share one retry policy.** The repair behavior a test proves applies unchanged to the real provider. M2.2 built the exact same triangle for embeddings — `EmbeddingProvider` as the abstract base, `DeterministicEmbeddingProvider` as the offline double, `OpenAIEmbeddingProvider` as the network adapter — so this is the second time the codebase pays for one policy with one abstract hole.

Abstract is enforced here, not advisory: `ABC` plus `@abstractmethod` make instantiating `LLMProvider` itself a `TypeError`, and the test file opens by asserting `isabstract(LLMProvider)` — the base class exists only to be subclassed.

### The budget shrinks per attempt

The first line of `complete()`'s loop computes `remaining`. The budget handed to the second attempt is **the original minus whatever the first attempt already spent.**

Without it, the repair call receives the full original allowance and, at worst, spends twice the budget.

This is not asserted, it is measured. The suite's budget starts at 1,000 input and 100 output tokens; the first attempt spends 10 and 5; the test then reads the second request's allowance off the provider's recorder: `provider.budgets[1].max_input_tokens == 990` and `max_output_tokens == 95` (`tests/workflow/test_02_provider.py:117-118`). Reproduce it:

```bash
uv run pytest tests/workflow/test_02_provider.py -k repairs_once -q
```

> **Concept — model_copy on a frozen model**
>
> `ProviderBudget` inherits `StrictSchema`, whose config is frozen. A frozen Pydantic model rejects attribute assignment after construction, so the remaining allowance cannot be subtracted in place — `model_copy(update=...)` builds a new instance with the changed fields and leaves the caller's original untouched.
>
> That untouched original is the point: the loop always subtracts from the budget the caller approved, never from a value an earlier iteration already shrank, so allowances cannot drift.
>
> One honest caveat: `model_copy` skips validation and trusts the update. It is safe here because the repair gate runs first — `_repair_budget_failure` uses `>=`, so a second attempt only begins while a strictly positive allowance remains.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `LLMProvider.complete` | **Implement** the call order yourself | The order validation, budget, and repair sit in |
| `DeterministicLLMProvider` | **Define the structure** | Testing the boundary with no network |
| `OpenAILLMProvider` | **Inspect the boundary conversion** | Where an SDK response becomes a neutral record |
| `app/llm/__init__.py` | **Define the structure** | The surface M4.1 publishes |

### 1. The order validation, budget, and repair sit in

#### Extend `app/llm/provider.py` — the provider boundary

**Learning action — implement the call order:** implement the `for attempt in (1, 2)` loop yourself. Trace all six returns — `provider_error` when the call raises, `provider_refused` on an explicit refusal, `budget_exceeded` from two distinct sites (after a call, and before a repair), `schema_rejected` after the second parse failure, and `ok`.

<!-- src: app/llm/provider.py::LLMProvider -->
```python
class LLMProvider(ABC):
    """One async provider boundary for structured, budgeted completion calls."""

    provider_name: str
    model_name: str
    api_url: str

    def __init__(self, *, clock: Clock = time.perf_counter_ns) -> None:
        self._clock = clock

    @abstractmethod
    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        """Return one provider-neutral raw response without retrying."""

    async def complete[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> ProviderResult[OutputT]:
        """Validate, repair once after schema failure, then refuse explicitly."""
        if not isinstance(prompt, Prompt):
            raise TypeError("prompt must be a Prompt value")
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError("schema must be a Pydantic model class")
        if not isinstance(budget, ProviderBudget):
            raise TypeError("budget must be a ProviderBudget value")

        current_prompt = prompt
        raw_outputs: list[str] = []
        request_ids: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_request_time_ms = 0.0

        for attempt in (1, 2):
            remaining = budget.model_copy(
                update={
                    "max_input_tokens": budget.max_input_tokens - total_input_tokens,
                    "max_output_tokens": budget.max_output_tokens - total_output_tokens,
                    "max_cost_usd": budget.max_cost_usd
                    - budget.pricing.estimate(total_input_tokens, total_output_tokens),
                }
            )
            started = self._clock()
            try:
                raw = await self._request(current_prompt, schema, remaining)
            except Exception as error:
                elapsed_ms = (self._clock() - started) / 1_000_000
                if elapsed_ms < 0:
                    raise ValueError("clock must be monotonic") from error
                total_request_time_ms += elapsed_ms
                raw_outputs.append("")
                failure = ProviderRefusal(
                    status="provider_error",
                    message=f"{type(error).__name__}: {error}",
                    attempts=attempt,
                )
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )
            elapsed_ms = (self._clock() - started) / 1_000_000
            if elapsed_ms < 0:
                raise ValueError("clock must be monotonic")
            total_request_time_ms += elapsed_ms
            raw_outputs.append(raw.output_text)
            if raw.request_id is not None:
                request_ids.append(raw.request_id)
            total_input_tokens += raw.input_tokens
            total_output_tokens += raw.output_tokens
            estimated_cost = budget.pricing.estimate(
                total_input_tokens,
                total_output_tokens,
            )

            if raw.refusal is not None:
                failure = ProviderRefusal(
                    status="provider_refused",
                    message=raw.refusal,
                    attempts=attempt,
                )
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            if failure := _budget_failure(
                budget,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                estimated_cost_usd=estimated_cost,
                attempts=attempt,
            ):
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            parsed, errors = _parse_output(raw.output_text, schema)
            if parsed is None:
                if attempt == 1:
                    if failure := _repair_budget_failure(
                        budget,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        estimated_cost_usd=estimated_cost,
                    ):
                        return self._failed_result(
                            failure,
                            raw_outputs=raw_outputs,
                            request_ids=request_ids,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            request_time_ms=total_request_time_ms,
                            budget=budget,
                        )
                    current_prompt = _repair_prompt(prompt, raw.output_text, errors)
                    continue
                failure = SchemaRejected(errors=errors)
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            assert not errors
            metadata = self._metadata(
                raw_outputs=raw_outputs,
                request_ids=request_ids,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                request_time_ms=total_request_time_ms,
                budget=budget,
            )
            return ProviderResult(status="ok", parsed=parsed, refusal=None, metadata=metadata)

        raise AssertionError("completion attempt loop ended unexpectedly")

    def _metadata(
        self,
        *,
        raw_outputs: Sequence[str],
        request_ids: Sequence[str],
        input_tokens: int,
        output_tokens: int,
        request_time_ms: float,
        budget: ProviderBudget,
    ) -> ProviderMetadata:
        return ProviderMetadata(
            provider=self.provider_name,
            model_name=self.model_name,
            api_url=self.api_url,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=budget.pricing.estimate(input_tokens, output_tokens),
            request_time_ms=request_time_ms,
            retries=len(raw_outputs) - 1,
            request_ids=tuple(request_ids),
            llm_output=raw_outputs[-1],
            raw_outputs=tuple(raw_outputs),
        )

    def _failed_result[OutputT: BaseModel](
        self,
        failure: CompletionFailure,
        *,
        raw_outputs: Sequence[str],
        request_ids: Sequence[str],
        input_tokens: int,
        output_tokens: int,
        request_time_ms: float,
        budget: ProviderBudget,
    ) -> ProviderResult[OutputT]:
        metadata = self._metadata(
            raw_outputs=raw_outputs,
            request_ids=request_ids,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_time_ms,
            budget=budget,
        )
        return ProviderResult(
            status=failure.status,
            parsed=None,
            refusal=failure,
            metadata=metadata,
        )
```

**What to look for in the code**

- `remaining` is recomputed each attempt from the **original** `budget` and the running totals. `budget.model_copy(update=...)` sends the second call an allowance **minus what was already spent** — the 990/95 measured above.
- The order is refusal, then budget, then parsing. A refusing model leaves nothing to parse, and an over-budget call cannot use its result even if parsing succeeds. **The most decisive failure is checked first.**
- `_repair_budget_failure` runs **before** the repair prompt is sent. With no budget left, the repair is never attempted.
- `except Exception` is deliberately broad: the base class cannot know what a future `_request` implementation may raise — the deterministic provider raises `RuntimeError` on an empty queue, the OpenAI adapter surfaces SDK errors — so every escape becomes a typed `provider_error` whose `message` keeps the original exception's type name. Once past the argument guards, a caller therefore always receives a `ProviderResult`: the failure is contained, not hidden.
- `raw_outputs` grows on **every** path — the exception path appends `""` before returning. That empty string is load-bearing: `ProviderMetadata` refuses an empty tuple and requires raw outputs to number retries plus one, so without it a failed call could not be recorded at all. The exception test pins the terminal state: `metadata.raw_outputs == ("",)`.
- `request_ids` is appended only when a response actually carried an id. Attempts and ids can therefore differ in count, which is why the metadata validator merely forbids ids from **outnumbering** raw outputs instead of demanding equality.
- `total_request_time_ms` accumulates across both attempts, so a repaired call's recorded latency is the **sum** of two requests. The deterministic test clock yields exactly one millisecond per attempt, and the suite asserts `request_time_ms == 1.0` for the single-attempt path and `2.0` for the repaired one — read stored traces with that in mind.
- `current_prompt` is rebound for the repair while `prompt` stays pinned to the original. The repair prompt is built from the original user text plus the errors — never from an already-repaired prompt — so instructions cannot compound across attempts.
- The budget guards read as one line each because of the walrus operator: `if failure := _budget_failure(...)` assigns the verdict and tests it in the same expression. `None` is falsy, so a passing judgment falls through without ceremony.
- Every failure path passes the `total_*` values through. Tokens and time spent survive in the metadata even on failure.
- The `elapsed_ms < 0` check exists on the exception path too. A failed call's timing has to be accurate as well.

### 2. Testing the boundary with no network

#### Extend `app/llm/provider.py` — deterministic provider

**Learning action — define the structure:** note what this provider imitates and what it does not.

<!-- src: app/llm/provider.py::DeterministicLLMProvider,MockLLMProvider -->
```python
class DeterministicLLMProvider(LLMProvider):
    """Queue-backed offline provider for deterministic tests and canned runs."""

    provider_name = "deterministic"
    api_url = "deterministic://local"

    def __init__(
        self,
        responses: Sequence[RawProviderResponse],
        *,
        model_name: str = "deterministic-mock",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        if any(not isinstance(response, RawProviderResponse) for response in responses):
            raise TypeError("responses must contain RawProviderResponse values")
        super().__init__(clock=clock)
        self.model_name = model_name
        self._responses = list(responses)
        self._prompts: list[Prompt] = []
        self._budgets: list[ProviderBudget] = []

    @property
    def prompts(self) -> tuple[Prompt, ...]:
        """Return prompts in request order for deterministic assertions."""
        return tuple(self._prompts)

    @property
    def budgets(self) -> tuple[ProviderBudget, ...]:
        """Return remaining budgets supplied to each deterministic request."""
        return tuple(self._budgets)

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        del schema
        self._prompts.append(prompt)
        self._budgets.append(budget)
        if not self._responses:
            raise RuntimeError("deterministic provider response queue is empty")
        return self._responses.pop(0)


MockLLMProvider = DeterministicLLMProvider
```

**What to look for in the code**

- "Deterministic" promises replay, not purity: `_request` never looks at the prompt to choose an output. `del schema` marks the ignored parameter deliberately, the prompt and budget are recorded, and the response is `self._responses.pop(0)` — a FIFO queue the test seeded up front. The same prompt sent twice returns the first, then the second queued response.
- That queue is exactly what makes the repair path testable: seed one invalid response and one valid one, and a single `complete()` call walks the whole failure-repair-success arc. A double that computed output from the prompt could never script two different outcomes for the same prompt.
- The recorders are the other half of the value. `prompts` and `budgets` expose what `complete()` actually sent, in order — that is how the suite asserts the repair prompt carries the validation errors and the previous output verbatim, and that the second budget shrank to 990/95.
- An empty queue raises `RuntimeError`, and that too is a feature: it drives the `except Exception` path of `complete()` with zero network. The exception test constructs this provider with an empty response list for exactly that purpose.
- Nothing here prices at zero, because pricing does not live on providers at all. `TokenPricing` sits on the caller's `ProviderBudget` — the suite's deterministic budget prices tokens at 2 and 10 USD per million, which is how the happy path asserts an estimated cost of `Decimal("0.0004")` for 100 input and 20 output tokens. What the `priced` guard in `_repair_budget_failure` protects is any **budget** whose pricing is all-zero, whichever provider sits behind it.

`MockLLMProvider = DeterministicLLMProvider` is a plain alias, not a subclass: both names bind the same class object, so behavior and `isinstance` checks are identical. The primary name states the property that matters — deterministic replay — while the alias keeps the conventional test-double name resolvable for readers who reach for it. Today no test or application code imports the alias; only the public surface in the next section re-exports it.

### 3. Where an SDK response becomes a neutral record

#### Complete `app/llm/provider.py` — OpenAI provider

**Learning action — inspect the boundary conversion:** note where `_openai_refusal` searches in the SDK response.

The class below is the complete M4.1 form. Tutorial 9's strict upgrade will replace only the constructor and `_request`; everything else — `complete()`, the judgments, the refusal mapping — stays word for word.

```python
def _openai_refusal(response: object) -> str | None:
    for output in getattr(response, "output", ()):
        for content in getattr(output, "content", ()):
            if getattr(content, "type", None) == "refusal":
                refusal = getattr(content, "refusal", None)
                if isinstance(refusal, str) and refusal.strip():
                    return refusal
    return None


class OpenAILLMProvider(LLMProvider):
    """OpenAI Responses API adapter with injected-client offline testability."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        model_name: str,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        api_url: str = "https://api.openai.com/v1/responses",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip() or not api_url.strip():
            raise ValueError("model_name and api_url must not be blank")
        super().__init__(clock=clock)
        self.model_name = model_name
        self.api_url = api_url
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        response = await self._client.responses.parse(
            model=self.model_name,
            instructions=prompt.system,
            input=prompt.user,
            text_format=schema,
            max_output_tokens=budget.max_output_tokens,
            store=False,
        )
        parsed = getattr(response, "output_parsed", None)
        response_output_text = getattr(response, "output_text", "")
        if isinstance(response_output_text, str) and response_output_text:
            output_text = response_output_text
        elif isinstance(parsed, BaseModel):
            output_text = parsed.model_dump_json()
        elif parsed is not None:
            output_text = json.dumps(parsed, allow_nan=False, separators=(",", ":"))
        else:
            output_text = ""
        usage = getattr(response, "usage", None)
        if usage is None:
            raise ValueError("OpenAI response did not include token usage")
        return RawProviderResponse(
            output_text=output_text,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            request_id=getattr(response, "id", None),
            refusal=_openai_refusal(response),
        )
```

> **Concept — Duck typing at the SDK edge**
>
> Neither `_openai_refusal` nor the response-reading half of `_request` imports an OpenAI response type. They walk the object with `getattr`, defaulting at every step, and ask only whether each attribute exists and has a usable shape.
>
> The trade is real: no type checker can verify this code against the SDK's response classes, so a shape change in a new SDK version surfaces at runtime, not at review time.
>
> What buys the risk back is the explicit check at the end: token usage must survive `isinstance(input_tokens, int)`, and if it does not, the adapter raises — which `complete()` catches and returns as a typed `provider_error`. A shape surprise degrades into a recorded failure, never into a silently wrong number.

**What to look for in the code**

- `_openai_refusal` navigates the response defensively. The SDK changes shape between versions, and a refusal must not be missed — a missed refusal would flow into parsing as an empty output and be misreported as a schema failure.
- Token counts are read from the response rather than counted by us — the provider's own tally is what it bills on, so a local count that drifted from the invoice would make every budget judgment wrong about real money.
- The missing-usage guard is measured: `test_openai_adapter_rejects_missing_usage_as_typed_provider_error` feeds a fake response with `usage=None` and asserts the run ends as `provider_error` with zero recorded tokens — no invented usage, no crash.
- The Responses API splits one prompt into two wire fields where chat-style APIs used a single messages array: `prompt.system` is sent as `instructions`, `prompt.user` as `input`. One `Prompt` value in, two parameters out — the mapping is direct and lossless.
- `store=False` travels on **both** branches. It opts this exchange out of the API's server-side response storage — responses are otherwise persisted and retrievable by id. Filing text flows through these calls, and the deliberate stance is that the only durable copy is the one this system writes itself. It narrows what the vendor keeps as retrievable state; it is not a blanket data-handling switch.
- `client` and `api_key` coexist because they serve different callers. Tests inject a fake `client` and the injected object wins (`client or AsyncOpenAI(api_key=api_key)`); production passes an `api_key` and lets the adapter build a real client. One constructor, two audiences, no network in tests.
- `api_url` routes nothing. The SDK client decides where requests actually go; this string is recorded into metadata so traces name the endpoint the adapter believed it was calling. Changing it does not repoint the request — know that before you try.
- `_request` sends the schema through the SDK-parsed `text_format` path. Tutorial 9 replaces this constructor and `_request` with a strict decoding default; nothing typed here is throwaway, because `complete()` and every judgment function survive that upgrade unchanged.

> **Concept — What the boundary buys**
>
> The `RawProviderResponse` construction at the bottom of `_request` is the borderline: above that line OpenAI's types live; below it, only this project's types exist. Every judgment from tutorial 2 and every branch of `complete()` operates on the neutral record, never on an SDK object.
>
> One consequence is the payoff of the whole document: swapping providers means writing one `_request` that ends in a `RawProviderResponse`. The completion loop, the tests of its policy, and everything downstream stay untouched.

### 4. The surface M4.1 publishes

#### Create `app/llm/__init__.py` — public API

**Learning action — define the structure:** note that not one underscore-prefixed decision function leaves.

```python
"""Strict LLM schemas and provider boundaries for M4."""

from app.llm.provider import (
    DeterministicLLMProvider,
    LLMProvider,
    MockLLMProvider,
    OpenAILLMProvider,
)
from app.llm.schemas import (
    AnswerDecision,
    AnswerLabel,
    BudgetExceeded,
    ChunkRelevance,
    CompletionFailure,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    ProviderResult,
    ProviderStatus,
    RawProviderResponse,
    RelevanceJudgment,
    SchemaRejected,
    StrictSchema,
    TokenPricing,
)

__all__ = [
    "AnswerDecision",
    "AnswerLabel",
    "BudgetExceeded",
    "ChunkRelevance",
    "CompletionFailure",
    "DeterministicLLMProvider",
    "LLMProvider",
    "MockLLMProvider",
    "OpenAILLMProvider",
    "Prompt",
    "ProviderBudget",
    "ProviderMetadata",
    "ProviderRefusal",
    "ProviderResult",
    "ProviderStatus",
    "RawProviderResponse",
    "RelevanceJudgment",
    "SchemaRejected",
    "StrictSchema",
    "TokenPricing",
]
```

Tutorial 9 extends this surface by one name when `strict_response_format` exists; until then this is the complete public API.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/workflow/test_01_schemas.py tests/workflow/test_02_provider.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| Output missing the schema twice in a row | Repair happens once, then a typed refusal. |
| A first attempt that consumed the budget | The repair call never spends double. |
| An exception thrown by the call itself | A caller always receives a `ProviderResult`. |
| Model output containing `NaN` | A non-standard JSON value never passes parsing. |
| Token counts from a failed call | Failure still counts toward the budget. |

`tests/workflow/test_02_provider.py` holds 13 test functions, and the five contracts above map to named tests: the double schema miss is `test_second_schema_failure_returns_typed_rejection_without_third_call`, the consumed budget is `test_repair_does_not_start_after_the_first_attempt_exhausts_budget`, the raised exception is `test_provider_exception_becomes_typed_error_without_fake_usage`, the `NaN` output is `test_non_strict_json_is_repaired_instead_of_silently_interpreted`, and the failed call's token counts are `test_explicit_usage_and_cost_budgets_fail_closed`.

One assertion is worth noticing across the file: `metadata.retries == 1` appears on three different paths — repair then success, repair then a second failure, repair after non-strict JSON. The one-repair policy is not a docstring sentence; it is measured three ways.

The three `isinstance` guards at the top of `complete()` are also bought by a test: `test_provider_boundary_rejects_untyped_prompt_budget_and_mock_responses` hands in a dict shaped like a prompt and a dict shaped like a budget, and both are refused with `TypeError` before any request is made.

### What you should be able to explain now

- **Why does `complete()` check refusal, budget, and parsing in that order?**
  - **Answer:** A refusal leaves nothing usable to parse, and an over-budget result must be rejected even if its output is valid, so the most decisive failures are handled first.
- **How much is spent at worst if `remaining` is not recomputed?**
  - **Answer:** Two attempts can each receive the full allowance and spend up to twice the original budget.
- **What do the deterministic and OpenAI providers share?**
  - **Answer:** They share `LLMProvider`'s validation, budget, failure, and single-repair policy; only the request adapter differs.
- **Why are token counts read from the response rather than counted locally?**
  - **Answer:** The provider's usage tally is the value used for billing, so it is the authoritative count.
- **What does swallowing exceptions guarantee to the caller?**
  - **Answer:** The caller always receives a typed `ProviderResult`, including `provider_error` on call failure, instead of handling provider-specific exceptions.
- **How many ways can `complete()` return, and why do two of them share a status?**
  - **Answer:** Six — `provider_error`, `provider_refused`, `budget_exceeded` from two sites, `schema_rejected`, and `ok`; the two budget exits share one status but come from tutorial 2's two different judgments: spending already done versus room for one more call.

---

[← Previous: Parsing and budget](02-provider.md) · [Module overview](../03-build.md) · [Next: Observability types →](04-observability-types.md)
