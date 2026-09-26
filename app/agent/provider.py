"""Tool-calling providers: one abstract turn boundary, offline and OpenAI adapters."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Self, cast

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam, ToolParam
from pydantic.functional_validators import model_validator

from app.agent.types import ToolCall
from app.contracts.validation import NonBlank, NonNegativeInt
from app.llm.openai import openai_usage
from app.llm.schemas import TokenPricing, TokenUsageDetails
from app.openai_models import ReasoningEffort, resolve_openai_model


class ProviderTurn(TokenUsageDetails):
    """One raw provider response: prose, requested tool calls, and usage.

    ``incomplete_reason`` names why a cut-off turn stopped (``max_output_tokens``
    or ``content_filter``) so the loop can tell a budget stop from a provider one.
    """

    output_text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    request_id: str | None = None
    incomplete: bool = False
    incomplete_reason: NonBlank | None = None

    @model_validator(mode="after")
    def unique_call_ids(self) -> Self:
        """Reject ambiguous turns whose call outputs could overwrite each other."""
        call_ids = [call.call_id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("provider tool call ids must be unique")
        if self.incomplete_reason is not None and not self.incomplete:
            raise ValueError("incomplete_reason requires an incomplete turn")
        return self._validate_token_totals(self.input_tokens, self.output_tokens)


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

    async def turn(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Record the request and return the next replayed turn."""
        del instructions, input_items, tools, max_output_tokens
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
        model_name: str | None = None,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
    ) -> None:
        selection = resolve_openai_model("agent", model_name)
        self.model_name = selection.model
        self.reasoning_effort: ReasoningEffort | None = selection.reasoning_effort
        self.pricing = selection.pricing
        if client is None:
            owned = AsyncOpenAI(api_key=api_key, max_retries=0)
            self._owned_client: AsyncOpenAI | None = owned
            self._client: AsyncOpenAI = owned
        else:
            self._owned_client = None
            self._client = client
        # Record the endpoint the SDK actually uses, including caller configuration.
        resolved = str(self._client.base_url)
        self.api_url = f"{resolved.rstrip('/')}/responses"

    async def aclose(self) -> None:
        """Close the HTTP client this provider opened for itself.

        A caller-supplied client remains the caller's responsibility. Providers
        constructed from an API key release their own connection pool here.
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
            If the response omits authoritative token usage or carries invalid
            usage details.
        RuntimeError
            If the response status is ``failed`` or ``cancelled``: the model
            produced no turn, and replaying an empty turn would nudge the model
            and bill another request for a provider-side failure.

        Notes
        -----
        Responses are not stored and SDK retries are disabled so every billed
        request is represented by exactly one agent step. An ``incomplete``
        response is surfaced with its reason so the loop can tell the
        output-token ceiling from a content filter instead of nudging a
        truncated turn.
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
        status = getattr(response, "status", None)
        if status in {"failed", "cancelled"}:
            code = getattr(getattr(response, "error", None), "code", None) or "unknown"
            raise RuntimeError(f"OpenAI response {status} ({code})")
        incomplete = status == "incomplete"
        reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
        (
            input_tokens,
            output_tokens,
            cached_input_tokens,
            cache_write_input_tokens,
            reasoning_tokens,
        ) = openai_usage(response)
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
            incomplete=incomplete,
            incomplete_reason=(
                reason if incomplete and isinstance(reason, str) and reason.strip() else None
            ),
        )
