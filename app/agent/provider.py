"""Tool-calling providers: one abstract turn boundary, offline and OpenAI adapters."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Self, cast

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam, ToolParam
from pydantic.functional_validators import model_validator

from app.agent.types import ToolCall
from app.llm.schemas import NonNegativeInt, StrictSchema, TokenPricing
from app.openai_models import ReasoningEffort, resolve_openai_model

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class ProviderTurn(StrictSchema):
    """One raw provider response: prose, requested tool calls, and usage."""

    output_text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt = 0
    cache_write_input_tokens: NonNegativeInt = 0
    reasoning_tokens: NonNegativeInt = 0
    request_id: str | None = None
    incomplete: bool = False

    @model_validator(mode="after")
    def unique_call_ids(self) -> Self:
        """Reject ambiguous turns whose call outputs could overwrite each other."""
        call_ids = [call.call_id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("provider tool call ids must be unique")
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ValueError("detailed input tokens must not exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens must not exceed output_tokens")
        return self


class ToolCallingProvider(ABC):
    """Async boundary that turns conversation state into one provider turn.

    Implementations return the normalized turn and nothing else; the agent loop
    owns request timing and cumulative token accounting, so a provider cannot
    hide a retry or a clock from the budget.
    """

    provider_name: str
    model_name: str
    api_url: str
    pricing: TokenPricing

    @abstractmethod
    async def turn(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Run one provider request and return the provider-neutral turn.

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
        ProviderTurn
            Normalized output text, tool calls, usage, and completion state.

        Notes
        -----
        Provider exceptions propagate to the loop, which converts them into a
        secret-safe terminal failure.
        """


class DeterministicToolProvider(ToolCallingProvider):
    """Queue-backed offline provider for deterministic agent tests and demos."""

    provider_name = "deterministic"
    api_url = "deterministic://local"
    pricing = TokenPricing(
        input_per_million_usd=Decimal("0"),
        output_per_million_usd=Decimal("0"),
    )

    def __init__(
        self,
        turns: Sequence[ProviderTurn],
        *,
        model_name: str = "deterministic-agent",
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        if any(not isinstance(turn, ProviderTurn) for turn in turns):
            raise TypeError("turns must contain ProviderTurn values")
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

    async def turn(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Record the request and return the next replayed turn."""
        del max_output_tokens
        self._requests.append(
            (instructions, tuple(dict(item) for item in input_items), tuple(tools))
        )
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
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        selection = resolve_openai_model("agent", model_name)
        if base_url is not None and not base_url.strip():
            raise ValueError("base_url must not be blank")
        self.model_name = selection.model
        self.reasoning_effort: ReasoningEffort | None = selection.reasoning_effort
        self.pricing = TokenPricing(
            input_per_million_usd=selection.pricing.input_per_million_usd,
            output_per_million_usd=selection.pricing.output_per_million_usd,
            cached_input_per_million_usd=selection.pricing.cached_input_per_million_usd,
            cache_write_input_per_million_usd=(selection.pricing.cache_write_input_per_million_usd),
        )
        if client is None:
            owned = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
            self._owned_client: AsyncOpenAI | None = owned
            self._client: AsyncOpenAI = owned
        else:
            self._owned_client = None
            self._client = client
        # Recorded provenance mirrors where requests actually go: the explicit
        # base_url, the owned client's resolved URL (env overrides included), or
        # the SDK default when a caller injected an opaque client.
        if base_url is not None:
            resolved = base_url
        elif client is None:
            resolved = str(self._client.base_url)
        else:
            resolved = str(getattr(client, "base_url", "") or DEFAULT_BASE_URL)
        self.api_url = f"{resolved.rstrip('/')}/responses"

    async def aclose(self) -> None:
        """Close the HTTP client this provider opened for itself.

        An injected client belongs to its caller and is left untouched, so a test
        fake needs no shutdown surface. Without this the connection pool of every
        provider built from an api key survives until interpreter exit.
        """
        if self._owned_client is not None:
            await self._owned_client.close()

    async def turn(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Call the Responses API once and normalize tool calls, usage, and status.

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
            Provider-neutral output, calls, authoritative usage, request id, and
            whether the response was cut off before it finished.

        Raises
        ------
        ValueError
            If the response omits authoritative token usage.

        Notes
        -----
        Responses are not stored and SDK retries are disabled so every billed
        request is represented by exactly one agent step. An ``incomplete``
        response (the output-token ceiling interrupted generation) is surfaced
        so the loop can stop instead of nudging a truncated turn.
        """
        response = await self._client.responses.create(
            model=self.model_name,
            instructions=instructions,
            input=cast(ResponseInputParam, list(input_items)),
            tools=cast(list[ToolParam], list(tools)),
            max_output_tokens=max_output_tokens,
            reasoning={"effort": self.reasoning_effort},
            store=False,
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("OpenAI response did not include token usage")
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        cached_input_tokens = getattr(input_details, "cached_tokens", 0)
        cache_write_input_tokens = getattr(input_details, "cache_write_tokens", 0)
        reasoning_tokens = getattr(output_details, "reasoning_tokens", 0)
        if not all(
            isinstance(value, int)
            for value in (cached_input_tokens, cache_write_input_tokens, reasoning_tokens)
        ):
            raise ValueError("OpenAI response included invalid token usage details")
        output_text = getattr(response, "output_text", "")
        return ProviderTurn(
            output_text=output_text if isinstance(output_text, str) else "",
            tool_calls=_turn_tool_calls(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            reasoning_tokens=reasoning_tokens,
            request_id=getattr(response, "id", None),
            incomplete=getattr(response, "status", None) == "incomplete",
        )
