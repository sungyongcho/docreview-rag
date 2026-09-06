# M4.4 Tutorial 9 — Enforce the schema in decoding, not in the prompt

The provider you built in tutorial 3 already survives malformed output: parse, repair once, then refuse. That guard has a cost profile worth staring at. **The repair path only runs after a bad response has been paid for, so every schema failure is one full extra request — and after the single repair, the run still ends in a refusal.**

There is a second place to enforce a schema, and it sits below prompting entirely.

**Prerequisite:** tutorials 1–8 are complete and `uv run pytest tests/workflow/test_04_nodes.py tests/workflow/test_05_runner.py -q` passes.

### Two layers, two different guarantees

A language model emits one token at a time, and at each step the API can mask every token that would leave a declared JSON schema. That is constrained decoding: invalid continuations get their probability forced to zero, so the output cannot be malformed in the first place. OpenAI exposes this as strict structured outputs — a `text.format` payload with `"strict": true`.

> **Concept — Token masking needs a closed grammar**
>
> At every step the model produces a probability for each token in its vocabulary, and the API holds a compiled form of your schema that knows, at the current position, exactly which continuations are still legal — a closing brace here, a quote there, next one of a known set of key names. Masking means zeroing out everything else before sampling.
>
> The word "exactly" is the entire requirement. The mask is computed per position from the set of legal continuations, so that set must be finite and known in advance. An object that leaves `additionalProperties` open declares that any key name at all is legal next — and a set that contains everything masks nothing. Optional keys fail the same way: if a key may or may not appear, both emitting it and closing the object are legal, so the grammar can no longer force the field you rely on.
>
> That is the causal link to the two rewrites you are about to implement — close every object, require every key. They are not style preferences; they are the minimum that turns a JSON schema into something a per-token mask can enforce.

If you have met OpenAI's older `json_object` mode, note what it did not promise: some syntactically valid JSON object, with no guarantee about keys or types. Strict structured outputs is the `json_schema` variant with `"strict": true` — the schema itself becomes the grammar. One naming trap: in the Responses API the parameter is `text.format`, while the older chat-completions API called the same idea `response_format`; the SDK type this file imports, `ResponseFormatTextJSONSchemaConfigParam`, still carries the older family name.

That guarantee is real but narrow. **Strict decoding promises syntax and shape — parseable JSON with exactly the declared keys and types — and nothing more. It cannot know that a `SUPPORTED` label requires at least one citation, because that rule lives across fields, not in the grammar.** The cross-field invariants stay in the Pydantic validators you wrote in tutorial 1.

| | Decoding-level (strict format) | Application-level (validate-repair) |
|---|---|---|
| Guarantees | parseable JSON, declared keys and types | business invariants across fields |
| Cannot see | label–citation exclusivity, blank-text rules | anything the model never emitted — it validates only the value that arrived |
| Failure timing | during generation, before you pay for garbage | after a full response arrives |
| Applies to | providers that support strict mode | every provider, including deterministic |

So the two layers are not alternatives. **The strict format removes the failure class that repair was built for, and the validate-repair loop stays as the outer guard for every invariant the grammar cannot express — and for every provider that has no strict mode at all.**

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `_strict_schema` | **Implement** the rewrite yourself | What a schema must look like before decoding can enforce it |
| `strict_response_format` | **Write the boundary payload** | Where our contract becomes an API parameter |
| `_request` branch | **Inspect the boundary conversion** | Why both paths converge on one neutral record |

### 1. What strict mode demands from a schema

Strict decoding can only mask tokens against a grammar it can fully close. An open object — one that admits unknown keys — has no closed grammar. A defaulted field fails for a subtler reason: the rewrite below forces every key into `required`, so the model could never actually omit the field anyway — but a `default` left in the schema would keep promising that omission is fine. A schema that promises one thing while the grammar enforces another is exactly the kind of silent contradiction this function refuses to ship.

Why derive the strict schema from the Pydantic model instead of authoring the JSON schema by hand? Because the model class is already the single source of truth for two enforcement layers: decoding-time shape (this tutorial) and validation-time invariants (tutorial 1). A hand-written schema would be a second declaration of the same contract, and two declarations drift — the first time someone adds a field to `AnswerDecision` and forgets the JSON twin, the grammar silently stops matching the validators. `model_json_schema()` makes that drift structurally impossible, and the rewrite only has to make the generated schema strict.

#### Extend `app/llm/provider.py` — the strict rewrite

**Learning action — implement the rewrite:** write the recursion first, then decide which constructs must be rejected rather than rewritten.

<!-- src: app/llm/provider.py::_strict_schema,strict_response_format -->
```python
def _strict_schema(node: object, path: str) -> None:
    """Rewrite one JSON-schema node in place to satisfy strict decoding rules."""
    if isinstance(node, list):
        for index, child in enumerate(node):
            _strict_schema(child, f"{path}[{index}]")
        return
    if not isinstance(node, dict):
        return
    for keyword in ("allOf", "oneOf", "not"):
        if keyword in node:
            raise ValueError(f"strict schema does not support {keyword} at {path}")
    if "default" in node:
        raise ValueError(f"strict schema does not support defaults at {path}")
    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False
        node["required"] = list(node.get("properties", {}))
    for keyword in ("properties", "$defs"):
        for name, child in node.get(keyword, {}).items():
            _strict_schema(child, f"{path}.{name}")
    for keyword in ("items", "prefixItems", "anyOf"):
        if keyword in node:
            _strict_schema(node[keyword], f"{path}.{keyword}")


def strict_response_format(schema: type[BaseModel]) -> ResponseFormatTextJSONSchemaConfigParam:
    """Return the strict ``text.format`` payload that constrains decoding to one schema.

    Strict structured outputs move schema enforcement from prompting into decoding:
    the API masks every token that would leave the declared JSON schema, so the
    response is guaranteed to parse and to carry exactly the declared keys. The
    guarantee covers syntax and shape only — business invariants such as label and
    citation exclusivity still run in the Pydantic validators downstream.

    Parameters
    ----------
    schema : type[BaseModel]
        Pydantic model describing the required completion payload.

    Returns
    -------
    ResponseFormatTextJSONSchemaConfigParam
        OpenAI ``text.format`` payload with every object closed and required.

    Raises
    ------
    ValueError
        If the generated JSON schema uses a construct strict mode cannot enforce.
    """
    json_schema = schema.model_json_schema()
    _strict_schema(json_schema, "$")
    return {
        "type": "json_schema",
        "name": schema.__name__,
        "schema": json_schema,
        "strict": True,
    }
```

**What to look for in the code**

- Every object is closed with `additionalProperties: false` and every property becomes `required`. **A grammar can only mask tokens when the set of valid keys is finite and known, so strict mode refuses open objects and optional keys by design.** Run the rewrite on `AnswerDecision` and `required` comes out as exactly the four declared keys — `label`, `answer`, `citation_chunk_ids`, `reason` — in declaration order.
- `default` is rejected instead of rewritten. The rewrite already forces every key into the required list, so the model could never actually omit a defaulted field — the real casualty would be honesty, because silently dropping the default would change what the schema promises without telling anyone. The test pins the failure to the character: a model with one defaulted `label` field raises `strict schema does not support defaults at $.label`, and the `path` argument threaded through every recursive call exists solely so this message can name the offending node.
- `allOf`, `oneOf`, and `not` are rejected with the offending path in the message, while `anyOf` is recursed into and survives. The asymmetry is the most interesting decision in the function. `anyOf` means "one of these branches" — a decoder can commit to a branch and keep masking inside it. `oneOf` means "exactly one branch matches", a claim about the branches the output does not match, which no per-token mask can check. `allOf` demands the intersection of several grammars at once, and `not` is outright negation. Failing at request-build time is cheaper than a provider error after the call — and this asymmetry is why a field typed `X | None`, which Pydantic compiles to a two-branch `anyOf`, passes through untouched.
- The recursion also walks `$defs`, so a nested model such as `ChunkRelevance` inside `RelevanceJudgment` gets closed exactly like the root.

> **Concept — In-place mutation, and why it is safe here**
>
> `_strict_schema` returns `None`; it edits the dict it receives. Mutation is usually the part of a design you apologize for, so it is worth saying why there is nothing to apologize for here. The dict comes from `schema.model_json_schema()`, which builds a fresh structure on every call — no other code holds a reference to it, so mutating it can affect no one. The test suite states this as a fact rather than a hope: calling `strict_response_format` twice on the same model yields equal payloads, an equality that could not hold if one call's mutations leaked into the next.
>
> The second parameter earns separate mention. `path` is never used for navigation — the recursion always knows where it is. It exists purely so that a rejection can say where: `$.label`, not "somewhere in your schema". An error message that names the node turns a debugging session into a one-line fix.

> **Concept — `$defs` and `$ref`: where Pydantic hides nested models**
>
> Pydantic does not inline a nested model's schema at the field that uses it. It hoists the definition into a top-level `$defs` table and leaves only a pointer at the field site. Generate the schema for `RelevanceJudgment` and look at the `grades` field: its `items` entry is nothing but `{"$ref": "#/$defs/ChunkRelevance"}` — no properties, no types, nothing a rewrite could close.
>
> That is why the recursion cannot only descend through `properties` — it must walk `$defs` as a sibling key. A walker that followed only the property tree would reach the `$ref` node, find nothing rewritable, and return — leaving `ChunkRelevance` open inside a payload that claims to be strict. The nested assertion in the test file checks exactly this: the definition under `$defs` ends up closed and fully required, just like the root.

The schema dict's whole life fits in one sentence, and it is worth narrating precisely because nothing about it survives. It is born inside `strict_response_format` from `schema.model_json_schema()`, mutated in place until every object is closed, wrapped into a `text.format` payload — labeled with the model class's `__name__` — serialized onto the wire, and discarded. It is never cached and never stored: `_request` rebuilds it on every call, the repair attempt included. That is exactly why the determinism test matters — rebuilding per request is only correct because two builds are guaranteed identical. One design callback: the return type `ResponseFormatTextJSONSchemaConfigParam` is a `TypedDict` from the SDK, and the function returns a plain dict literal that satisfies it structurally — the same structural-typing idea as tutorial 5's `Protocol`s, applied at the API boundary instead of the observability seam.

`strict_response_format` is also the only underscore-free function that `app/llm/__init__.py` exports from this file. The provider classes travel with it; the nine underscore-prefixed helpers stay private. The boundary is deliberate: a caller building its own adapter for another strict-capable provider needs the payload builder — and none of the parsing or budget internals.

First pay the header its one new line — the return annotation below needs the SDK's strict format type:

```python
from openai.types.responses import ResponseFormatTextJSONSchemaConfigParam
```

### 2. One branch, one neutral record

#### Inspect `app/llm/provider.py` — the request branch

**Learning action — inspect the boundary conversion:** trace both branches to the shared `RawProviderResponse` construction and note what never changes.

Tutorial 3 built this class in its SDK-parsed form. Replace its constructor and `_request` with the final version — the strict default path, with `structured_output=False` as the escape hatch:

<!-- src: app/llm/provider.py::OpenAILLMProvider -->
```python
class OpenAILLMProvider(LLMProvider):
    """OpenAI Responses API adapter with injected-client offline testability.

    By default every request carries a strict ``text.format`` built by
    :func:`strict_response_format`, so schema conformance is enforced at decoding
    time. ``structured_output=False`` keeps the legacy SDK-parsed path for models
    or gateways that do not support strict mode; either way the shared
    validate-repair loop in :meth:`LLMProvider.complete` remains the outer guard.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        model_name: str,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        api_url: str = "https://api.openai.com/v1/responses",
        structured_output: bool = True,
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip() or not api_url.strip():
            raise ValueError("model_name and api_url must not be blank")
        super().__init__(clock=clock)
        self.model_name = model_name
        self.api_url = api_url
        self._structured_output = structured_output
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        if self._structured_output:
            response = await self._client.responses.create(
                model=self.model_name,
                instructions=prompt.system,
                input=prompt.user,
                text={"format": strict_response_format(schema)},
                max_output_tokens=budget.max_output_tokens,
                store=False,
            )
        else:
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
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("OpenAI response did not include token usage")
        return RawProviderResponse(
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=getattr(response, "id", None),
            refusal=_openai_refusal(response),
        )
```

First untangle the two SDK entry points, because they do not return the same shape. `responses.create` is the raw call: it takes a `text.format` payload and hands back `output_text`, a string. `responses.parse` is the SDK's convenience wrapper: it takes the Pydantic class itself as `text_format` and hands back `output_parsed`, an already-validated instance. The default path calls `responses.create` with `text={"format": strict_response_format(schema)}` — the branch arrives with the replacement below; the helper it calls is the one you just implemented. `structured_output=False` keeps the `responses.parse` path for gateways and models without strict support, and `_request` refuses to care which branch ran: it prefers `output_text`, falls back on the parsed path to re-serializing `output_parsed`, and exits both branches as one `RawProviderResponse`. Everything after the call — refusal mapping, usage extraction, the neutral record — is shared, and the validate-repair loop in `complete` wraps both.

Two design questions hide in that one flag. Why a constructor flag rather than a per-call parameter? Because strict support is a property of the model-and-gateway pairing the provider was built for, not of an individual request — a per-call switch would let two call sites disagree about what the same provider guarantees, and the guarantee is the whole point. And why opt-out (`structured_output: bool = True`) rather than opt-in? Because the strict path is strictly safer wherever it works: an opt-in flag is a flag somebody forgets, and the price of forgetting is the exact failure class this tutorial opened with — paid-for garbage and repair requests. The default encodes the recommendation; the escape hatch exists for the environments that need it.

It also helps to name the exact point where the strict guarantee ends. It holds from the API's decoder up to the string that lands in `RawProviderResponse.output_text` — that far, the mask vouches for shape. The moment `complete` hands that string to `_parse_output`, every guarantee is ours: our JSON parsing with duplicate-key rejection, our strict Pydantic validation, our cross-field invariants. The adapter never assumes the wire kept its promise — it re-validates as if strict mode did not exist.

**The repair loop is not dead code on the strict path. It is the only guard for cross-field invariants, for providers without strict mode, and for the day a gateway silently ignores the format parameter.** Defense in depth means the inner guarantee never becomes an excuse to delete the outer one.

The test suite proves that sentence instead of asserting it. In `test_repair_loop_still_guards_the_strict_path`, the fake strict endpoint first returns `{"label":"SUPPORTED"}` — decodable, but missing every other required field, exactly what a gateway that ignored the format parameter would produce. The result is still `ok`, with `retries` at 1 and exactly two recorded calls: the outer loop caught the violation and repaired it under strict decoding. The sharpest assertion in the file is the quietest one: the second request's `text` payload is identical to the first's. The repair attempt is strict-decoded too — between attempt one and attempt two, the only thing that changes is the prompt. That single equality is the best available evidence for the invariant at the top of this tutorial, and it also bounds the intro's cost claim with a measurement: one schema failure cost exactly one extra request.

The public surface gains its last name. Replace `app/llm/__init__.py` with the final form — one import line and one `__all__` entry more than tutorial 3's version:

```python
"""Strict LLM schemas and provider boundaries for M4."""

from app.llm.provider import (
    DeterministicLLMProvider,
    LLMProvider,
    MockLLMProvider,
    OpenAILLMProvider,
    strict_response_format,
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
    "strict_response_format",
]
```

Across this upgrade `tests/workflow/test_02_provider.py` stays green — its adapter test accepts either schema-binding mechanism — while `tests/workflow/test_07_structured_outputs.py` pins the strict default.


### Focused tests and the contract they keep

```bash
uv run pytest tests/workflow/test_02_provider.py tests/workflow/test_07_structured_outputs.py -q
```

The command above currently collects 21 tests across the two files. The five in `tests/workflow/test_07_structured_outputs.py` map one-to-one onto the rows below — 116 lines of test, five contracts, no filler.

| What the test breaks | Contract it protects |
|---|---|
| A model with a defaulted field | Constructs decoding cannot enforce fail at build time, with a path |
| A nested `$defs` schema | Closure rules apply to every object, not just the root |
| The default adapter call | The strict `text.format` payload is actually sent |
| `structured_output=False` | The legacy SDK-parsed path stays available and unchanged |
| Schema-invalid text on the strict path | The outer repair loop still runs when the inner guarantee fails — `test_repair_loop_still_guards_the_strict_path` proves it end to end |

### What you should be able to explain now

The answers are in the **bold key sentences** above. Connect each answer to the layer that owns it.

- **Why is a schema failure expensive even though repair usually fixes it?**
  - **Answer:** The bad response is already paid for before repair sees it, so every failure costs one extra full request — and a second failure still ends in a refusal.
- **What does strict decoding guarantee, and what can it never guarantee?**
  - **Answer:** It guarantees syntax and shape — parseable JSON with exactly the declared keys and types. Cross-field business rules like label–citation exclusivity are invisible to the grammar and stay in the validators.
- **Why must every object be closed and every key required?**
  - **Answer:** Token masking needs a finite, known set of valid continuations; open objects and optional keys make "something else" a valid completion.
- **Why reject `default` instead of quietly removing it?**
  - **Answer:** Removing it would change what the schema promises without telling anyone; rejecting it forces the model owner to decide, at build time, with the offending path in hand.
- **Why does the validate-repair loop survive on the strict path?**
  - **Answer:** Strict mode covers shape only, only on providers that support it — the outer loop still guards cross-field invariants, non-strict providers, and misbehaving gateways.

---

[← Previous: the runner](08-runner.md) · [Module overview](../03-build.md)
