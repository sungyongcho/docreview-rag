# M9 Build — The model picks the route, the contracts pick the winner

## Here is where the route becomes negotiable

Every module so far decided the route in code. M9 hands that decision to the model: it reads a question, chooses a tool, reads the observation, and chooses again. What makes this safe is not trust — it is that every choice passes through contracts this repository already knows how to enforce: strict schemas at the boundary, explicit observations for every failure, budgets that fail closed, and citations that must point at retrieved evidence.

## Checkpoint map

| Order | Checkpoint | Goal | Canonical files |
|---:|---|---|---|
| 1 | M9.1 | Strict contracts and one tool registry | `app/agent/types.py`, `tools.py`, `registry.py`, `__init__.py` |
| 2 | M9.2 | Provider turns with usage accounting | `app/agent/provider.py` |
| 3 | M9.3 | The hand-rolled agent loop | `app/agent/loop.py` |
| 4 | M9.4 | Built-in filing tools over M2 | `app/agent/builtin_tools.py` |
| 5 | M9.5 | Decomposition and its measurement | `app/agent/decompose.py`, `eval.py` |
| 6 | M9.6 | MCP server and the acceptance CLI | `app/agent/mcp_server.py`, `__main__.py` |

## Tutorial — built in six sittings

M9 produces eleven files and 1,526 lines of source. Each document targets **under 30 minutes** to read and implement.

| Document | Checkpoint | Files built | Approx. |
|---|---|---|---|
| [1. Contracts and registry](tutorial/01-contracts-registry.md) | M9.1 | `types.py`, `tools.py`, `registry.py`, `__init__.py` | 30 min |
| [2. Providers](tutorial/02-providers.md) | M9.2 | `provider.py` | 25 min |
| [3. The loop](tutorial/03-loop.md) | M9.3 | `loop.py` | 30 min |
| [4. Built-in tools](tutorial/04-builtin-tools.md) | M9.4 | `builtin_tools.py` | 25 min |
| [5. Decomposition](tutorial/05-decomposition.md) | M9.5 | `decompose.py`, `eval.py` | 30 min |
| [6. MCP and the CLI](tutorial/06-mcp-cli.md) | M9.6 | `mcp_server.py`, `__main__.py` | 25 min |

Follow them in order. Do not move on while a stretch's focused test is failing.

## Starting conditions

M1 through M8 are complete: the corpus is seeded, retrieval and its evaluation exist, the workflow and its providers exist, and the serving surface runs. M9 adds one package, `app/agent/`, and touches nothing else — every capability it exposes is a typed wrapper over something already measured.

## M9.1 — Contracts before autonomy

The value objects come first, exactly as in M1 and M4: answers, observations, steps, and results are frozen, fail-closed, and mutually exclusive by construction. The registry is the single schema source for three consumers — the LLM's function specs, the MCP tool list, and the prompt manual — so the documentation the model reads can never drift from the schema it must satisfy.

**Document:** [1. Contracts and registry](tutorial/01-contracts-registry.md) · **Passing:** `uv run pytest tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q`

## M9.2 — A turn is a measured unit

The provider boundary mirrors M4's: one abstract `_request`, a deterministic queue-backed implementation for offline tests, and an OpenAI Responses adapter that refuses responses without token usage. Every turn returns the same neutral shape, so the loop never knows which provider ran.

**Document:** [2. Providers](tutorial/02-providers.md) · **Passing:** `uv run pytest tests/agent/test_03_provider.py -q`

## M9.3 — The loop is the safety boundary

The Thought → Tool → Observation loop is hand-rolled and fail-closed. Every tool failure becomes an observation the model can read; a final answer may cite only chunk ids a tool returned in the same run, and a violation comes back as a correctable rejection instead of a dead run; budgets stop the loop before another request, never after.

**Document:** [3. The loop](tutorial/03-loop.md) · **Passing:** `uv run pytest tests/agent/test_04_loop.py -q`

## M9.4 — Tools stay thin

The built-in tools add no retrieval logic. `search_filings`, `fetch_chunk`, and `compare_years` translate validated arguments into M2 calls and payloads into evidence ids. If a tool ever needs a smarter ranking, that ranking belongs in `app/retrieval`, measured by M3 — not hidden inside a tool.

**Document:** [4. Built-in tools](tutorial/04-builtin-tools.md) · **Passing:** `uv run pytest tests/agent/test_05_builtin_tools.py -q`

## M9.5 — An improvement is a measured delta

Multi-hop questions lose recall under a single query; the golden set has carried a `multi_hop` category since M3 for exactly this moment. Decomposition splits the question with the M4 provider, retrieves per sub-question, and fuses with rank-only RRF — and the whole point is that the decomposed retriever plugs into the unmodified M3 harness, so the claim ships as per-category deltas in paired artifacts, not as prose.

**Document:** [5. Decomposition](tutorial/05-decomposition.md) · **Passing:** `uv run pytest tests/agent/test_06_decompose.py -q`

## M9.6 — One contract, exposed twice

The MCP server publishes the registry's strict schemas byte for byte, so an external MCP client and the in-process loop see one contract. The CLI mirrors M2's acceptance pattern: one command, machine-readable JSON evidence, and an offline deterministic mode that proves the loop against the real corpus without an API key.

**Document:** [6. MCP and the CLI](tutorial/06-mcp-cli.md) · **Passing:** `uv run pytest tests/agent/test_07_mcp_cli.py -q`

## What you should be able to explain now

- **Why does handing the model the route require harder contracts, not softer ones?**
- **What stops the agent from citing evidence it never retrieved?**
- **Why must every tool failure become an observation?**
- **Why does the decomposition claim need per-category metrics?**
- **What guarantees the MCP client and the LLM see the same tool contract?**

The tutorials answer each of these with a failing value and the code that rejects it.

## What this module hands to the next one

A bounded agent whose every run is a JSON audit trail: steps, tool calls, observations, usage, and either a cited answer or a typed failure. Any future surface — an API route, a demo pane, a benchmark report — consumes `AgentResult` without reinterpreting it.

---

## Reference baseline — the complete canonical files

The chapters above are the chronological build. The generated section below is the machine-verified final reference against the pinned `reference_revision`, not a bundle to paste before M9.1.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M9.1 — Complete checkpoint

#### Create or replace `app/agent/__init__.py`

<!-- file: app/agent/__init__.py -->
```python
"""Public contracts and production entry points for the agent milestone."""

from app.agent.builtin_tools import build_default_registry
from app.agent.decompose import (
    QueryDecomposition,
    decompose_query,
    make_decomposed_retriever,
    merge_ranked_lists,
)
from app.agent.eval import category_metrics, run_decomposition_comparison
from app.agent.loop import FINAL_ANSWER_NAME, build_instructions, final_answer_spec, run_agent
from app.agent.mcp_server import build_mcp_server, serve_stdio
from app.agent.provider import (
    DeterministicToolProvider,
    OpenAIToolProvider,
    ProviderTurn,
    ToolCallingProvider,
)
from app.agent.registry import ToolRegistry
from app.agent.tools import Tool
from app.agent.types import (
    AgentAnswer,
    AgentBudget,
    AgentCitation,
    AgentResult,
    AgentStep,
    Observation,
    StepUsage,
    ToolCall,
)

__all__ = [
    "FINAL_ANSWER_NAME",
    "AgentAnswer",
    "AgentBudget",
    "AgentCitation",
    "AgentResult",
    "AgentStep",
    "DeterministicToolProvider",
    "Observation",
    "OpenAIToolProvider",
    "ProviderTurn",
    "QueryDecomposition",
    "StepUsage",
    "Tool",
    "ToolCall",
    "ToolCallingProvider",
    "ToolRegistry",
    "build_default_registry",
    "build_instructions",
    "build_mcp_server",
    "category_metrics",
    "decompose_query",
    "final_answer_spec",
    "make_decomposed_retriever",
    "merge_ranked_lists",
    "run_agent",
    "run_decomposition_comparison",
    "serve_stdio",
]
```

#### Create or replace `app/agent/types.py`

<!-- file: app/agent/types.py -->
```python
"""Strict value objects for the M9 tool-calling agent."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import model_validator

type AgentStatus = Literal["ok", "no_answer", "budget_exceeded", "provider_error"]

NonBlank = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
NonnegativeFloat = Annotated[StrictFloat, Field(ge=0)]


class StrictAgentModel(BaseModel):
    """Frozen fail-closed base for every M9 boundary value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AgentBudget(StrictAgentModel):
    """Hard limits one agent run may never exceed.

    The limits are cumulative across every iteration of a run, so a model that
    burns tokens exploring cannot spend what the final answer would need.
    """

    max_iterations: Annotated[StrictInt, Field(gt=0, le=64)] = 8
    max_total_input_tokens: PositiveInt = 60_000
    max_total_output_tokens: PositiveInt = 8_000


class ToolCall(StrictAgentModel):
    """One tool invocation requested by the model, with raw JSON arguments."""

    call_id: NonBlank
    name: NonBlank
    arguments_json: StrictStr


class Observation(StrictAgentModel):
    """The explicit result the loop feeds back for one tool call.

    Errors are observations too: a failed call must come back as a typed
    message the model can read, never as a silently dropped step.
    """

    call_id: NonBlank
    name: NonBlank
    output_json: StrictStr = ""
    error: NonBlank | None = None

    @model_validator(mode="after")
    def require_output_or_error(self) -> Self:
        """Keep successful output and typed failure mutually exclusive."""
        if self.error is None and not self.output_json:
            raise ValueError("observations require output_json or an error")
        if self.error is not None and self.output_json:
            raise ValueError("failed observations must not also carry output")
        return self


class StepUsage(StrictAgentModel):
    """Provider accounting for one agent iteration."""

    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    request_time_ms: NonnegativeFloat
    retries: NonnegativeInt = 0


class AgentStep(StrictAgentModel):
    """One Thought → Tool → Observation iteration with full provenance."""

    step: PositiveInt
    output_text: StrictStr
    tool_calls: tuple[ToolCall, ...]
    observations: tuple[Observation, ...]
    usage: StepUsage

    @model_validator(mode="after")
    def observations_match_calls(self) -> Self:
        """Reject observations that answer a call this step never made."""
        call_ids = {call.call_id for call in self.tool_calls}
        for observation in self.observations:
            if observation.call_id not in call_ids:
                raise ValueError("observation call_id does not match any tool call")
        return self


class AgentCitation(StrictAgentModel):
    """One retrieved chunk the final answer stands on."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    citation: NonBlank


class AgentAnswer(StrictAgentModel):
    """The structured final answer with the M4 label and citation contract."""

    label: Literal["SUPPORTED", "NOT_IN_DOCS"]
    answer: NonBlank
    citations: tuple[AgentCitation, ...]
    rationale: NonBlank

    @model_validator(mode="after")
    def validate_label_contract(self) -> Self:
        """Keep supported and absent answers mutually exclusive."""
        chunk_ids = [citation.chunk_id for citation in self.citations]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("citation chunk ids must be unique")
        if self.label == "SUPPORTED":
            if not self.citations:
                raise ValueError("SUPPORTED answers require at least one citation")
            if self.answer == "NOT_IN_DOCS":
                raise ValueError("SUPPORTED answers require a supported answer")
        else:
            if self.answer != "NOT_IN_DOCS":
                raise ValueError("NOT_IN_DOCS answers must use the NOT_IN_DOCS answer")
            if self.citations:
                raise ValueError("NOT_IN_DOCS answers must not carry citations")
        return self


class AgentResult(StrictAgentModel):
    """One terminal agent run: an answer or a typed failure, never both."""

    status: AgentStatus
    answer: AgentAnswer | None
    failure: NonBlank | None
    iterations: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
    steps: tuple[AgentStep, ...]

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Keep success and failure states mutually exclusive."""
        if self.status == "ok":
            if self.answer is None or self.failure is not None:
                raise ValueError("successful runs require an answer and no failure")
        else:
            if self.answer is not None or self.failure is None:
                raise ValueError("failed runs require a failure and no answer")
        return self
```

#### Create or replace `app/agent/tools.py`

<!-- file: app/agent/tools.py -->
```python
"""Typed tool boundary shared by the agent loop and the MCP server."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import re
from typing import Any

from pydantic import BaseModel

TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_TOOL_NAMES = frozenset({"final_answer"})

type EvidenceExtractor = Callable[[Any], tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class Tool[ParamsT: BaseModel]:
    """One callable capability with a validated parameter schema.

    ``run`` receives the already-validated parameters model and returns any
    JSON-serializable payload. ``evidence_ids`` optionally names the chunk ids
    a payload puts into evidence, so the loop can hold final answers to the
    chunks the run actually saw.
    """

    name: str
    description: str
    parameters: type[ParamsT]
    run: Callable[[ParamsT], Awaitable[Any]]
    evidence_ids: EvidenceExtractor | None = None

    def __post_init__(self) -> None:
        """Reject tools whose identity or schema cannot be published."""
        if TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("tool name must be snake_case ascii")
        if self.name in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name {self.name!r} is reserved for the agent loop")
        if not self.description.strip():
            raise ValueError("tool description must not be blank")
        if not isinstance(self.parameters, type) or not issubclass(self.parameters, BaseModel):
            raise ValueError("tool parameters must be a Pydantic model class")
```

#### Create or replace `app/agent/registry.py`

<!-- file: app/agent/registry.py -->
```python
"""Tool registry that publishes one schema to the LLM, the MCP server, and the prompt."""

from __future__ import annotations

from typing import Any

from app.agent.tools import Tool
from app.llm import strict_response_format


class ToolRegistry:
    """Named, immutable-by-convention collection of agent tools.

    The registry is the single source for three consumers: the provider gets
    strict function specs, the MCP server gets input schemas, and the system
    prompt gets a generated manual. One registration feeds all three, so the
    documentation the model reads can never drift from the schema it must obey.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any]] = {}

    def register(self, tool: Tool[Any]) -> None:
        """Add one tool, rejecting duplicates instead of silently replacing them."""
        if not isinstance(tool, Tool):
            raise TypeError("only Tool values can be registered")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any]:
        """Return one registered tool or fail with the known names."""
        try:
            return self._tools[name]
        except KeyError:
            known = ", ".join(self.names) or "none"
            raise ValueError(f"unknown tool: {name} (registered: {known})") from None

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered tool names in deterministic order."""
        return tuple(sorted(self._tools))

    @property
    def tools(self) -> tuple[Tool[Any], ...]:
        """Return registered tools in deterministic name order."""
        return tuple(self._tools[name] for name in self.names)

    def specs(self) -> list[dict[str, Any]]:
        """Return strict Responses-API function specs for every tool."""
        specs: list[dict[str, Any]] = []
        for tool in self.tools:
            payload = strict_response_format(tool.parameters)
            specs.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": payload["schema"],
                    "strict": True,
                }
            )
        return specs

    def manual(self) -> str:
        """Render the tool manual the system prompt feeds to the model."""
        lines = ["Available tools:"]
        for tool in self.tools:
            properties = tool.parameters.model_json_schema().get("properties", {})
            arguments = ", ".join(sorted(properties)) or "no arguments"
            lines.append(f"- {tool.name}({arguments}): {tool.description}")
        return "\n".join(lines)
```

Run the checkpoint:

```bash
uv run pytest tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M9.2 — Complete checkpoint

#### Create or replace `app/agent/provider.py`

<!-- file: app/agent/provider.py -->
```python
"""Tool-calling providers: one abstract turn boundary, offline and OpenAI adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
import time
from typing import Any, cast

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam, ToolParam

from app.agent.types import NonnegativeInt, StrictAgentModel, ToolCall

type Clock = Callable[[], int]


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

Run the checkpoint:

```bash
uv run pytest tests/agent/test_03_provider.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M9.3 — Complete checkpoint

#### Create or replace `app/agent/loop.py`

<!-- file: app/agent/loop.py -->
```python
"""Hand-rolled Thought → Tool → Observation loop with fail-closed budgets."""

from __future__ import annotations

from collections.abc import Callable
import json
import time
from typing import Any

from pydantic import ValidationError

from app.agent.provider import ProviderTurn, ToolCallingProvider
from app.agent.registry import ToolRegistry
from app.agent.types import (
    AgentAnswer,
    AgentBudget,
    AgentResult,
    AgentStep,
    Observation,
    StepUsage,
    ToolCall,
)
from app.llm import strict_response_format

type WallClock = Callable[[], float]

FINAL_ANSWER_NAME = "final_answer"

INSTRUCTIONS_TEMPLATE = """You are an evidence-checked review agent over SEC filings.

Work in explicit steps: decide what evidence you still need, call exactly the
tool that provides it, read the observation, and repeat. Never invent an
observation — every fact must come from a tool result in this conversation.

{manual}
- final_answer(label, answer, citations, rationale): Finish the run. \
SUPPORTED answers must cite only chunk_id values returned by earlier tool \
calls in this run; when the filings do not contain the answer, return the \
NOT_IN_DOCS label with no citations.

Call final_answer exactly once, only after the evidence in hand actually
supports the answer."""


def build_instructions(registry: ToolRegistry) -> str:
    """Render the default system prompt from the registry's generated manual."""
    return INSTRUCTIONS_TEMPLATE.format(manual=registry.manual())


def final_answer_spec() -> dict[str, Any]:
    """Return the strict function spec for the loop-owned final_answer tool."""
    payload = strict_response_format(AgentAnswer)
    return {
        "type": "function",
        "name": FINAL_ANSWER_NAME,
        "description": "Finish the run with a structured, citation-checked answer.",
        "parameters": payload["schema"],
        "strict": True,
    }


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _parse_arguments(arguments_json: str) -> dict[str, Any]:
    value = json.loads(arguments_json, object_pairs_hook=_strict_json_object)
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")
    return value


async def _dispatch(call: ToolCall, registry: ToolRegistry) -> tuple[Observation, tuple[int, ...]]:
    """Run one tool call and always return an explicit observation."""
    try:
        tool = registry.get(call.name)
    except ValueError as error:
        return Observation(call_id=call.call_id, name=call.name, error=str(error)), ()
    try:
        parameters = tool.parameters.model_validate(_parse_arguments(call.arguments_json))
    except (ValueError, ValidationError) as error:
        message = f"invalid arguments for {call.name}: {error}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    try:
        output = await tool.run(parameters)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    try:
        output_json = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        message = f"{call.name} returned a non-JSON payload: {error}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    evidence = tool.evidence_ids(output) if tool.evidence_ids is not None else ()
    return (
        Observation(call_id=call.call_id, name=call.name, output_json=output_json),
        tuple(evidence),
    )


def _final_answer(call: ToolCall, evidence: frozenset[int]) -> tuple[AgentAnswer | None, str]:
    """Validate one final_answer call against the evidence this run actually saw."""
    try:
        answer = AgentAnswer.model_validate(_parse_arguments(call.arguments_json), strict=False)
    except (ValueError, ValidationError) as error:
        return None, f"invalid final_answer: {error}"
    uncited = tuple(
        citation.chunk_id for citation in answer.citations if citation.chunk_id not in evidence
    )
    if uncited:
        cited = ", ".join(str(chunk_id) for chunk_id in uncited)
        return None, (
            f"final_answer cites chunk ids no tool returned in this run: {cited}. "
            "Cite only retrieved evidence or answer NOT_IN_DOCS."
        )
    return answer, ""


def _result(
    status: str,
    *,
    answer: AgentAnswer | None,
    failure: str | None,
    steps: list[AgentStep],
    input_tokens: int,
    output_tokens: int,
    seconds: float,
) -> AgentResult:
    return AgentResult.model_validate(
        {
            "status": status,
            "answer": answer,
            "failure": failure,
            "iterations": len(steps),
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "total_time_seconds": seconds,
            "steps": tuple(steps),
        }
    )


async def run_agent(
    question: str,
    *,
    registry: ToolRegistry,
    provider: ToolCallingProvider,
    budget: AgentBudget | None = None,
    instructions: str | None = None,
    wall_clock: WallClock = time.perf_counter,
) -> AgentResult:
    """Run the agent loop until final_answer, a budget stop, or a provider failure.

    Every iteration is one provider turn followed by explicit observations for
    each requested tool call. The loop is fail-closed: exhausted budgets and
    provider failures return a typed result instead of a partial answer, and a
    final answer may only cite chunk ids that a tool actually returned.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    if not isinstance(provider, ToolCallingProvider):
        raise TypeError("provider must implement ToolCallingProvider")
    limits = budget or AgentBudget()
    if not isinstance(limits, AgentBudget):
        raise TypeError("budget must be an AgentBudget")
    system_prompt = instructions or build_instructions(registry)

    tool_specs = [*registry.specs(), final_answer_spec()]
    input_items: list[dict[str, Any]] = [{"role": "user", "content": question}]
    steps: list[AgentStep] = []
    evidence: set[int] = set()
    total_input = 0
    total_output = 0
    started = wall_clock()

    def elapsed() -> float:
        seconds = wall_clock() - started
        if seconds < 0:
            raise ValueError("agent wall clock must be monotonic")
        return seconds

    while len(steps) < limits.max_iterations:
        remaining_output = limits.max_total_output_tokens - total_output
        if total_input >= limits.max_total_input_tokens or remaining_output <= 0:
            return _result(
                "budget_exceeded",
                answer=None,
                failure="token budget exhausted before the run could finish",
                steps=steps,
                input_tokens=total_input,
                output_tokens=total_output,
                seconds=elapsed(),
            )
        try:
            turn, request_ms = await provider.turn(
                system_prompt,
                input_items,
                tool_specs,
                max_output_tokens=remaining_output,
            )
        except Exception as error:
            return _result(
                "provider_error",
                answer=None,
                failure=f"{type(error).__name__}: {error}",
                steps=steps,
                input_tokens=total_input,
                output_tokens=total_output,
                seconds=elapsed(),
            )
        total_input += turn.input_tokens
        total_output += turn.output_tokens
        usage = StepUsage(
            model_name=provider.model_name,
            api_url=provider.api_url,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            request_time_ms=request_ms,
        )

        final_call = next(
            (call for call in turn.tool_calls if call.name == FINAL_ANSWER_NAME),
            None,
        )
        if final_call is not None:
            answer, problem = _final_answer(final_call, frozenset(evidence))
            if answer is not None:
                steps.append(
                    AgentStep(
                        step=len(steps) + 1,
                        output_text=turn.output_text,
                        tool_calls=turn.tool_calls,
                        observations=(),
                        usage=usage,
                    )
                )
                return _result(
                    "ok",
                    answer=answer,
                    failure=None,
                    steps=steps,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    seconds=elapsed(),
                )
            rejection = Observation(
                call_id=final_call.call_id,
                name=final_call.name,
                error=problem,
            )
            steps.append(
                AgentStep(
                    step=len(steps) + 1,
                    output_text=turn.output_text,
                    tool_calls=turn.tool_calls,
                    observations=(rejection,),
                    usage=usage,
                )
            )
            _append_exchange(input_items, turn, {final_call.call_id: f"ERROR: {problem}"})
            continue

        if not turn.tool_calls:
            steps.append(
                AgentStep(
                    step=len(steps) + 1,
                    output_text=turn.output_text,
                    tool_calls=(),
                    observations=(),
                    usage=usage,
                )
            )
            if turn.output_text.strip():
                input_items.append({"role": "assistant", "content": turn.output_text})
            input_items.append(
                {
                    "role": "user",
                    "content": "No tool was called. Call a tool, or finish with final_answer.",
                }
            )
            continue

        observations: list[Observation] = []
        outputs: dict[str, str] = {}
        for call in turn.tool_calls:
            observation, chunk_ids = await _dispatch(call, registry)
            observations.append(observation)
            evidence.update(chunk_ids)
            if observation.error is not None:
                outputs[call.call_id] = f"ERROR: {observation.error}"
            else:
                outputs[call.call_id] = observation.output_json
        steps.append(
            AgentStep(
                step=len(steps) + 1,
                output_text=turn.output_text,
                tool_calls=turn.tool_calls,
                observations=tuple(observations),
                usage=usage,
            )
        )
        _append_exchange(input_items, turn, outputs)

    return _result(
        "budget_exceeded",
        answer=None,
        failure="iteration budget exhausted before final_answer",
        steps=steps,
        input_tokens=total_input,
        output_tokens=total_output,
        seconds=elapsed(),
    )


def _append_exchange(
    input_items: list[dict[str, Any]],
    turn: ProviderTurn,
    outputs: dict[str, str],
) -> None:
    """Replay one assistant turn and its observations into the conversation."""
    if turn.output_text.strip():
        input_items.append({"role": "assistant", "content": turn.output_text})
    for call in turn.tool_calls:
        input_items.append(
            {
                "type": "function_call",
                "call_id": call.call_id,
                "name": call.name,
                "arguments": call.arguments_json,
            }
        )
        if call.call_id in outputs:
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": outputs[call.call_id],
                }
            )
```

Run the checkpoint:

```bash
uv run pytest tests/agent/test_04_loop.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M9.4 — Complete checkpoint

#### Create or replace `app/agent/builtin_tools.py`

<!-- file: app/agent/builtin_tools.py -->
```python
"""Built-in filing tools: typed wrappers over the M2 retrieval surface."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import ToolRegistry
from app.agent.tools import Tool
from app.db.models import Chunk
from app.retrieval import DEFAULT_RRF_K, ChunkHit, EmbeddingProvider, RetrievalFilters, retrieve

DEFAULT_SEARCH_K = 5
SNIPPET_CHARS = 320
BODY_CHARS = 4_000


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

Run the checkpoint:

```bash
uv run pytest tests/agent/test_05_builtin_tools.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M9.5 — Complete checkpoint

#### Create or replace `app/agent/decompose.py`

<!-- file: app/agent/decompose.py -->
```python
"""LLM query decomposition and the merged multi-hop retriever."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.types import StrictAgentModel
from app.llm import LLMProvider, Prompt, ProviderBudget
from app.retrieval import (
    DEFAULT_RRF_K,
    ChunkHit,
    EmbeddingProvider,
    RetrievalFilters,
    retrieve,
)

MAX_SUB_QUESTIONS = 4

DECOMPOSE_SYSTEM_PROMPT = (
    "You split one retrieval question into independent sub-questions. "
    "Each sub-question must be answerable from a single passage of an SEC filing. "
    "Return between one and four sub-questions; return the original question "
    "unchanged when it already targets a single fact."
)


class QueryDecomposition(StrictAgentModel):
    """The structured decomposition contract returned by the LLM."""

    sub_questions: tuple[Annotated[StrictStr, Field(min_length=1)], ...]

    @model_validator(mode="after")
    def validate_sub_questions(self) -> Self:
        """Reject empty, oversized, blank, or duplicated decompositions."""
        if not 1 <= len(self.sub_questions) <= MAX_SUB_QUESTIONS:
            raise ValueError(f"decomposition requires 1 to {MAX_SUB_QUESTIONS} sub-questions")
        normalized = [" ".join(question.split()).casefold() for question in self.sub_questions]
        if any(not question for question in normalized):
            raise ValueError("sub-questions must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("sub-questions must be unique")
        return self


async def decompose_query(
    question: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> tuple[str, ...]:
    """Return validated sub-questions, falling back to the original on failure.

    The fallback is deliberate: decomposition is an optimization, and an
    unavailable or refusing provider must degrade to the measured single-query
    baseline instead of failing the retrieval request outright.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    prompt = Prompt(system=DECOMPOSE_SYSTEM_PROMPT, user=question)
    result = await llm_provider.complete(prompt, QueryDecomposition, provider_budget)
    if result.status != "ok" or result.parsed is None:
        return (question,)
    return result.parsed.sub_questions


def merge_ranked_lists(
    ranked_lists: tuple[tuple[ChunkHit, ...], ...],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> tuple[ChunkHit, ...]:
    """Fuse per-sub-question rankings with reciprocal-rank scores over n lists.

    This is the M2.5 fusion rule generalized from two fixed components to one
    list per sub-question: only ranks contribute, so sub-questions with
    incomparable native scores still merge deterministically.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    scores: dict[int, float] = {}
    first_seen: dict[int, ChunkHit] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            first_seen.setdefault(hit.chunk_id, hit)
    fused = sorted(
        first_seen.values(),
        key=lambda hit: (
            -scores[hit.chunk_id],
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
    return tuple(hit.model_copy(update={"score": scores[hit.chunk_id]}) for hit in fused[:k])


def make_decomposed_retriever(
    session: AsyncSession,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
):
    """Return an M3-compatible ``Retriever`` that decomposes before retrieving.

    The callable signature matches ``evaluate_retriever``'s ``Retriever``
    contract exactly, so the decomposed strategy plugs into the existing
    evaluation harness without modifying any M3 file.
    """

    async def retrieve_decomposed(question: str, k: int) -> tuple[ChunkHit, ...]:
        sub_questions = await decompose_query(
            question,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        ranked_lists = []
        for sub_question in sub_questions:
            result = await retrieve(
                session,
                sub_question,
                provider=embedding_provider,
                k=k,
                candidate_k=candidate_k,
                filters=filters,
                rrf_k=rrf_k,
            )
            ranked_lists.append(result.hits)
        return merge_ranked_lists(tuple(ranked_lists), k, rrf_k=rrf_k)

    return retrieve_decomposed
```

#### Create or replace `app/agent/eval.py`

<!-- file: app/agent/eval.py -->
```python
"""Category-sliced comparison of single-query and decomposed retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals.retrieval_eval import (
    RetrievalEvaluation,
    Retriever,
    evaluate_retriever,
    write_evaluation_artifact,
)
from app.evals.types import GoldenCase


def category_metrics(evaluation: RetrievalEvaluation) -> dict[str, dict[str, float]]:
    """Return macro retrieval metrics per golden category, scored cases only.

    The suite-level score hides exactly the split this module exists to show:
    a decomposition change should move ``multi_hop`` without touching
    ``simple_lookup``. Absent cases stay excluded, mirroring M3's scoring rule.
    """
    grouped: dict[str, list[Any]] = {}
    for case in evaluation.cases:
        if case.score is None:
            continue
        grouped.setdefault(case.golden.category, []).append(case.score)
    metrics: dict[str, dict[str, float]] = {}
    for category in sorted(grouped):
        scores = grouped[category]
        count = len(scores)
        metrics[category] = {
            "scored_case_count": float(count),
            "recall_at_k": sum(score.recall_at_k for score in scores) / count,
            "hit_rate_at_k": sum(score.hit_at_k for score in scores) / count,
            "mrr": sum(score.reciprocal_rank for score in scores) / count,
        }
    return metrics


def _arm_payload(evaluation: RetrievalEvaluation) -> dict[str, Any]:
    return {
        "metrics": evaluation.metric_values(),
        "categories": category_metrics(evaluation),
    }


def _artifact_name(recorded_at: datetime, label: str) -> str:
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{label}.json"


async def run_decomposition_comparison(
    cases: Sequence[GoldenCase],
    *,
    baseline_retriever: Retriever,
    decomposed_retriever: Retriever,
    baseline_config: Mapping[str, Any],
    decomposed_config: Mapping[str, Any],
    suite: str,
    artifact_dir: str | Path,
    k: int = 5,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate both retrievers on one golden suite and write paired artifacts.

    Both arms run through the unmodified M3 harness, so their artifacts have
    the same schema as every other evaluation and remain comparable with the
    stored baselines. The returned payload adds the per-category split and the
    metric deltas the ablation narrative needs.
    """
    moment = recorded_at or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    baseline = await evaluate_retriever(
        cases,
        baseline_retriever,
        suite=suite,
        config=baseline_config,
        k=k,
        recorded_at=moment,
    )
    decomposed = await evaluate_retriever(
        cases,
        decomposed_retriever,
        suite=suite,
        config=decomposed_config,
        k=k,
        recorded_at=moment,
    )
    directory = Path(artifact_dir)
    baseline_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-baseline"),
        baseline,
    )
    decomposed_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-decomposed"),
        decomposed,
    )
    baseline_categories = category_metrics(baseline)
    decomposed_categories = category_metrics(decomposed)
    deltas = {
        category: {
            "recall_at_k": decomposed_categories[category]["recall_at_k"]
            - baseline_categories[category]["recall_at_k"],
            "mrr": decomposed_categories[category]["mrr"] - baseline_categories[category]["mrr"],
        }
        for category in sorted(set(baseline_categories) & set(decomposed_categories))
    }
    return {
        "suite": suite,
        "k": k,
        "baseline": _arm_payload(baseline),
        "decomposed": _arm_payload(decomposed),
        "category_deltas": deltas,
        "artifacts": {
            "baseline": str(baseline_path),
            "decomposed": str(decomposed_path),
        },
    }
```

Run the checkpoint:

```bash
uv run pytest tests/agent/test_06_decompose.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M9.6 — Complete checkpoint

#### Create or replace `app/agent/mcp_server.py`

<!-- file: app/agent/mcp_server.py -->
```python
"""Expose the agent tool registry as a Model Context Protocol stdio server."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.context import ServerRequestContext
import mcp.types as mcp_types
from pydantic import ValidationError

from app.agent.registry import ToolRegistry
from app.llm import strict_response_format

SERVER_NAME = "docreview-agent"


def build_mcp_server(registry: ToolRegistry) -> Server:
    """Build one MCP server whose tool list mirrors the registry exactly.

    The input schemas come from the same strict transform the agent loop sends
    to the LLM, so an MCP client and the in-process agent see one contract.
    Tool failures come back as ``is_error`` results with a readable message —
    the same explicit-observation rule the loop applies.
    """
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    server: Server = Server(SERVER_NAME)

    async def list_tools(
        context: ServerRequestContext[Any],
        params: mcp_types.PaginatedRequestParams,
    ) -> mcp_types.ListToolsResult:
        del context, params
        return mcp_types.ListToolsResult(
            tools=[
                mcp_types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=dict(strict_response_format(tool.parameters)["schema"]),
                )
                for tool in registry.tools
            ]
        )

    async def call_tool(
        context: ServerRequestContext[Any],
        params: mcp_types.CallToolRequestParams,
    ) -> mcp_types.CallToolResult:
        del context
        try:
            tool = registry.get(params.name)
            parameters = tool.parameters.model_validate(params.arguments or {})
            output = await tool.run(parameters)
            payload = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        except (ValueError, ValidationError) as error:
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(error))],
                is_error=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=payload)],
            is_error=False,
        )

    server.add_request_handler("tools/list", mcp_types.PaginatedRequestParams, list_tools)
    server.add_request_handler("tools/call", mcp_types.CallToolRequestParams, call_tool)
    return server


async def serve_stdio(registry: ToolRegistry) -> None:
    """Run the registry-backed MCP server over stdio until the client closes it."""
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
```

#### Create or replace `app/agent/__main__.py`

<!-- file: app/agent/__main__.py -->
```python
"""Command-line acceptance path for the M9 tool-calling agent."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
import json
from typing import Literal

from app.agent.builtin_tools import build_default_registry
from app.agent.loop import run_agent
from app.agent.mcp_server import serve_stdio
from app.agent.provider import (
    DeterministicToolProvider,
    OpenAIToolProvider,
    ProviderTurn,
    ToolCallingProvider,
)
from app.agent.types import AgentBudget, ToolCall
from app.db.session import Session
from app.retrieval import get_embedding_provider

ProviderName = Literal["deterministic", "openai"]


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse agent acceptance arguments."""
    parser = argparse.ArgumentParser(description="Run the evidence-checked filing agent.")
    parser.add_argument("--question", help="Nonempty review question.")
    parser.add_argument("--k", type=int, default=5, help="Hits per search tool call.")
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai"),
        default="deterministic",
        help=(
            "deterministic runs an offline two-turn demo that searches and then "
            "answers NOT_IN_DOCS; openai runs the real tool-calling loop."
        ),
    )
    parser.add_argument("--model", default="gpt-5-mini", help="OpenAI model for --provider openai.")
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Serve the tool registry over MCP stdio instead of answering a question.",
    )
    return parser.parse_args(argv)


def _demo_provider(question: str, k: int) -> DeterministicToolProvider:
    """Script the offline demo: one real search, then an honest NOT_IN_DOCS."""
    search_arguments = json.dumps(
        {"query": question, "k": k, "tickers": None, "fiscal_years": None, "forms": None}
    )
    answer_arguments = json.dumps(
        {
            "label": "NOT_IN_DOCS",
            "answer": "NOT_IN_DOCS",
            "citations": [],
            "rationale": (
                "The offline demo provider cannot ground an answer; "
                "run with --provider openai for a real agent run."
            ),
        }
    )
    return DeterministicToolProvider(
        [
            ProviderTurn(
                output_text="Searching the corpus for evidence.",
                tool_calls=(
                    ToolCall(
                        call_id="demo-1",
                        name="search_filings",
                        arguments_json=search_arguments,
                    ),
                ),
                input_tokens=0,
                output_tokens=0,
            ),
            ProviderTurn(
                output_text="",
                tool_calls=(
                    ToolCall(
                        call_id="demo-2",
                        name="final_answer",
                        arguments_json=answer_arguments,
                    ),
                ),
                input_tokens=0,
                output_tokens=0,
            ),
        ]
    )


async def _run(args: argparse.Namespace) -> dict[str, object]:
    """Run one agent request over a live database session."""
    if not args.question or not args.question.strip():
        raise SystemExit("--question is required unless --mcp is set")
    async with Session() as session:
        registry = build_default_registry(
            session,
            embedding_provider=get_embedding_provider(),
        )
        provider: ToolCallingProvider
        if args.provider == "openai":
            provider = OpenAIToolProvider(model_name=args.model)
        else:
            provider = _demo_provider(args.question, args.k)
        result = await run_agent(
            args.question,
            registry=registry,
            provider=provider,
            budget=AgentBudget(max_iterations=args.max_iterations),
        )
    return result.model_dump(mode="json")


async def _serve_mcp() -> None:
    """Serve the registry tools over MCP stdio with one live session."""
    async with Session() as session:
        registry = build_default_registry(
            session,
            embedding_provider=get_embedding_provider(),
        )
        await serve_stdio(registry)


def main() -> None:
    """Run the M9 acceptance command and print machine-readable evidence."""
    args = arguments()
    if args.mcp:
        asyncio.run(_serve_mcp())
        return
    print(json.dumps(asyncio.run(_run(args)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

Run the checkpoint:

```bash
uv run pytest tests/agent/test_07_mcp_cli.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
