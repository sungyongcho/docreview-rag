# M9.2 Tutorial 2 — A turn is a measured unit

The loop needs one question answered per iteration: given the conversation so far and the published tools, what does the model want to do next? This document builds the provider boundary that answers it — because **the loop must never know which provider ran, and no provider may return a turn without its cost attached.**

**Prerequisite:** M9.1 is complete and `uv run pytest tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `ProviderTurn` and the ABC | **Write the neutral turn shape** | Usage accounting is part of the contract, not telemetry |
| `DeterministicToolProvider` | **Implement** the scripted queue | Offline tests exercise the real loop, not a mock of it |
| `OpenAIToolProvider` | **Implement** the Responses adapter | Where the wire format ends and the neutral shape begins |

### 1. The neutral turn

#### Create `app/agent/provider.py` — the shape every provider returns

**Learning action — write the neutral turn shape:** decide what the loop is allowed to see, then compare with `LLMProvider` from M4.

<!-- src: app/agent/provider.py::ProviderTurn,ToolCallingProvider -->
```python
class ProviderTurn(StrictAgentModel):
    """One raw provider response: prose, requested tool calls, and usage."""

    output_text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    request_id: str | None = None


class ToolCallingProvider(ABC):
    """Async boundary that turns conversation state into one provider turn."""

    provider_name: str
    model_name: str
    api_url: str

    def __init__(self, *, clock: Clock = time.perf_counter_ns) -> None:
        self._clock = clock

    @abstractmethod
    async def _request(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Return one provider-neutral turn without retrying."""

    async def turn(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> tuple[ProviderTurn, float]:
        """Run one timed request and return the turn with its wall-clock milliseconds."""
        started = self._clock()
        result = await self._request(
            instructions,
            input_items,
            tools,
            max_output_tokens=max_output_tokens,
        )
        elapsed_ms = (self._clock() - started) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("provider clock must be monotonic")
        return result, elapsed_ms
```

**What to look for in the code**

- `ProviderTurn` carries text, parsed tool calls, and token counts — nothing provider-specific survives past this boundary. **The loop consumes turns, not responses, so swapping providers can never change loop behavior.**
- The ABC times `_request` itself, exactly like M4's provider: latency is measured once, in one place, and no subclass can forget it.
- `request_id` rides along for observability. When a live run misbehaves, the step trace names the exact provider request to look up.

### 2. The deterministic provider is the test harness

#### Extend `app/agent/provider.py` — the scripted queue

**Learning action — implement the scripted queue:** note what it records, not just what it returns.

<!-- src: app/agent/provider.py::DeterministicToolProvider -->
```python
class DeterministicToolProvider(ToolCallingProvider):
    """Queue-backed offline provider for deterministic agent tests and demos."""

    provider_name = "deterministic"
    api_url = "deterministic://local"

    def __init__(
        self,
        turns: Sequence[ProviderTurn],
        *,
        model_name: str = "deterministic-agent",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        if any(not isinstance(turn, ProviderTurn) for turn in turns):
            raise TypeError("turns must contain ProviderTurn values")
        super().__init__(clock=clock)
        self.model_name = model_name
        self._turns = list(turns)
        self._requests: list[
            tuple[str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]
        ] = []

    @property
    def requests(
        self,
    ) -> tuple[tuple[str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]], ...]:
        """Return (instructions, input items, tool specs) per request, in order."""
        return tuple(self._requests)

    async def _request(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        del max_output_tokens
        self._requests.append((instructions, tuple(input_items), tuple(tools)))
        if not self._turns:
            raise RuntimeError("deterministic tool provider turn queue is empty")
        return self._turns.pop(0)
```

**What to look for in the code**

- Turns are consumed from a queue, so a test scripts an entire multi-step conversation up front — search first, then answer — and the loop under test is the real loop.
- `requests` records every input the provider received. **Tests assert on what the loop sent — the replayed function calls and observations — which is how the conversation-assembly logic stays pinned without a network.**
- Exhausting the queue raises. A test that runs one turn too many is a wrong test, and it fails loudly instead of feeding the loop empty turns.

### 3. The OpenAI adapter

#### Extend `app/agent/provider.py` — the Responses API adapter

**Learning action — implement the Responses adapter:** trace one `function_call` item from the raw response into a `ToolCall`.

<!-- src: app/agent/provider.py::_turn_tool_calls,OpenAIToolProvider -->
```python
def _turn_tool_calls(response: object) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for item in getattr(response, "output", ()):
        if getattr(item, "type", None) != "function_call":
            continue
        calls.append(
            ToolCall(
                call_id=str(getattr(item, "call_id", "") or ""),
                name=str(getattr(item, "name", "") or ""),
                arguments_json=str(getattr(item, "arguments", "") or ""),
            )
        )
    return tuple(calls)


class OpenAIToolProvider(ToolCallingProvider):
    """OpenAI Responses API adapter with strict function tools and injected clients."""

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

    async def _request(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        response = await self._client.responses.create(
            model=self.model_name,
            instructions=instructions,
            input=cast(ResponseInputParam, list(input_items)),
            tools=cast(list[ToolParam], list(tools)),
            max_output_tokens=max_output_tokens,
            store=False,
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("OpenAI response did not include token usage")
        output_text = getattr(response, "output_text", "")
        return ProviderTurn(
            output_text=output_text if isinstance(output_text, str) else "",
            tool_calls=_turn_tool_calls(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=getattr(response, "id", None),
        )
```

**What to look for in the code**

- The request passes `tools=` from `registry.specs()` untouched and sets `store=False` — the API sees exactly the strict schemas M9.1 generated, and no conversation state lives server-side.
- `_turn_tool_calls` reads only output items with `type == "function_call"`; reasoning and text items pass through as prose. Arguments stay as the raw JSON string — parsing belongs to dispatch, where failure can become an observation.
- A response without usage raises instead of defaulting to zero. **A turn with unknown cost would silently disarm the token budget, so the adapter refuses to produce one.**

### Focused tests and the contract they keep

```bash
uv run pytest tests/agent/test_03_provider.py -q
```

| What the test breaks | Contract it protects |
|---|---|
| A subclass reporting its own latency | Timing is owned by the ABC, uniformly |
| A scripted queue running dry | Test scripts must match the loop's actual turn count |
| A response missing token usage | No turn enters the loop without its cost |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why does the loop consume `ProviderTurn` instead of the OpenAI response?**
  - **Answer:** The neutral shape is the whole point — swapping providers cannot change loop behavior because nothing provider-specific crosses the boundary.
- **Why does the deterministic provider record its inputs?**
  - **Answer:** Asserting on what the loop sent pins the conversation-assembly logic offline; returning canned turns alone would only test the script.
- **Why raise on missing usage instead of defaulting to zero tokens?**
  - **Answer:** A zero-cost turn would let the token budget pass forever; the budget only means something if every turn is honestly priced.

---

[← Previous: contracts and registry](01-contracts-registry.md) · [Module overview](../03-build.md) · [Next: the loop →](03-loop.md)
