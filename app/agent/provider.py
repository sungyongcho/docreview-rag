"""Tool-calling providers: one abstract turn boundary, offline and OpenAI adapters."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
import time
from typing import Any, Protocol, Self, cast

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam, ToolParam
from pydantic.functional_validators import model_validator

from app.agent.types import NonnegativeInt, StrictAgentModel, ToolCall

type Clock = Callable[[], int]


class _Responses(Protocol):
    """Minimum Responses API surface used by the tool-calling adapter."""

    async def create(self, **kwargs: object) -> object:
        """Create one response from provider-neutral request values."""
        ...


class _OpenAIClient(Protocol):
    """Structural client contract accepted by production and offline tests."""

    @property
    def responses(self) -> _Responses:
        """Expose the Responses API resource."""
        ...


class ProviderTurn(StrictAgentModel):
    """One raw provider response: prose, requested tool calls, and usage."""

    output_text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    request_id: str | None = None

    @model_validator(mode="after")
    def unique_call_ids(self) -> Self:
        """Reject ambiguous turns whose call outputs could overwrite each other."""
        call_ids = [call.call_id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("provider tool call ids must be unique")
        return self


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
        """Run one provider request and measure its wall-clock latency.

        Parameters
        ----------
        instructions : str
            Stable system instructions for the complete agent run.
        input_items : Sequence[dict[str, Any]]
            Replayed user, assistant, function-call, and observation items.
        tools : Sequence[dict[str, Any]]
            Strict provider tool specifications.
        max_output_tokens : int
            Remaining cumulative output allowance for this request.

        Returns
        -------
        tuple[ProviderTurn, float]
            Normalized provider turn and measured milliseconds.

        Raises
        ------
        ValueError
            If the injected clock moves backwards.

        Notes
        -----
        Provider exceptions propagate to the loop, which converts them into a
        secret-safe terminal failure.
        """
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
    """Project the SDK response output onto strict tool calls, ignoring other item types."""
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
        client: object | None = None,
        api_key: str | None = None,
        api_url: str = "https://api.openai.com/v1/responses",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip() or not api_url.strip():
            raise ValueError("model_name and api_url must not be blank")
        super().__init__(clock=clock)
        self.model_name = model_name
        self.api_url = api_url
        client_value = client if client is not None else AsyncOpenAI(api_key=api_key, max_retries=0)
        self._client = cast(_OpenAIClient, client_value)

    async def _request(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Call the Responses API once and normalize tool calls and usage.

        Parameters
        ----------
        instructions : str
            Agent system instructions.
        input_items : Sequence[dict[str, Any]]
            Stateless conversation replay sent as Responses input.
        tools : Sequence[dict[str, Any]]
            Strict custom-function specifications.
        max_output_tokens : int
            Hard output ceiling including reasoning tokens.

        Returns
        -------
        ProviderTurn
            Provider-neutral output, calls, authoritative usage, and request id.

        Raises
        ------
        ValueError
            If the response omits authoritative token usage.

        Notes
        -----
        Responses are not stored and SDK retries are disabled so every billed
        request is represented by exactly one agent step.
        """
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
