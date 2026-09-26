"""OpenAI structured-generation adapter and response accounting."""

from __future__ import annotations

from decimal import Decimal
import json
import time

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.llm.completion import (
    Clock,
    LLMProvider,
    _OpenAIPreflightError,
    _OpenAIPreflightUnavailableError,
)
from app.llm.decoding import strict_response_format
from app.llm.estimate import estimate_prompt_tokens
from app.llm.schemas import BudgetExceeded, Prompt, ProviderBudget, RawProviderResponse
from app.openai_models import OpenAIModelRole, ReasoningEffort, resolve_openai_model
from app.release.ai_allowance import active_allowance, reserve_openai


def _openai_refusal(response: object) -> str | None:
    """Return the refusal text an OpenAI response carries, or ``None``."""
    for output in getattr(response, "output", ()):
        for content in getattr(output, "content", ()):
            if getattr(content, "type", None) == "refusal":
                refusal = getattr(content, "refusal", None)
                if isinstance(refusal, str) and refusal.strip():
                    return refusal
    return None


def openai_usage(response: object) -> tuple[int, int, int, int, int]:
    """Read the authoritative token usage an OpenAI Responses reply carries.

    Shared by the review adapter here and the agent tool adapter, so both budget
    boundaries account for the same usage fields under the same rules.

    Parameters
    ----------
    response : object
        Response returned by ``responses.create``.

    Returns
    -------
    tuple[int, int, int, int, int]
        Input, output, cached input, cache-write input and reasoning tokens, in
        that order; absent detail counters read as zero.

    Raises
    ------
    ValueError
        If the response did not include integer input and output token usage, or
        if a cached, cache-write or reasoning detail counter is not an integer.
    """
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
    return (
        input_tokens,
        output_tokens,
        cached_input_tokens,
        cache_write_input_tokens,
        reasoning_tokens,
    )


class OpenAILLMProvider(LLMProvider):
    """OpenAI Responses adapter with explicit HTTP client ownership.

    Every request carries a strict ``text.format`` built by
    :func:`strict_response_format`, so schema conformance is enforced at decoding
    time; the shared validate-repair loop in :meth:`LLMProvider.complete` remains
    the outer guard.
    """

    provider_name = "openai"
    api_url = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        model_name: str,
        role: OpenAIModelRole = "review",
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        selection = resolve_openai_model(role, model_name)
        super().__init__(clock=clock)
        self.model_name = selection.model
        self.reasoning_effort: ReasoningEffort | None = selection.reasoning_effort
        if client is None:
            owned = AsyncOpenAI(api_key=api_key, max_retries=0)
            self._owned_client: AsyncOpenAI | None = owned
            self._client: AsyncOpenAI = owned
        else:
            self._owned_client = None
            self._client = client

    async def aclose(self) -> None:
        """Close the HTTP client this provider opened for itself.

        A caller-supplied client remains the caller's responsibility. Providers
        constructed from an API key release their own connection pool here.
        """
        if self._owned_client is not None:
            await self._owned_client.close()

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        """Send one schema-bound OpenAI request and normalize its response.

        Parameters
        ----------
        prompt : Prompt
            Strict prompt sent to the configured endpoint.
        schema : type[OutputT]
            Pydantic output schema bound through strict decoding.
        budget : ProviderBudget
            Remaining output-token allowance for this request.

        Returns
        -------
        RawProviderResponse
            Provider-neutral output, usage, request id, and optional refusal.

        Raises
        ------
        ValueError
            If the response omits authoritative token usage.
        """
        # Include the exact output schema, instructions, input and framing in the
        # configured-price reservation. Token estimates are not a provider billing proof.
        serialized_schema = json.dumps(strict_response_format(schema), ensure_ascii=False)
        projected = estimate_prompt_tokens(
            Prompt(system=prompt.system, user=prompt.user + "\n" + serialized_schema),
            model_name=self.model_name,
        )
        if projected is None:
            if active_allowance.get() is not None:
                raise _OpenAIPreflightUnavailableError(
                    "OpenAI cost preflight requires the model tokenizer, which is unavailable; "
                    "the request was not sent"
                )
            reservation = budget.max_cost_usd
        else:
            projected += 128  # Conservative extra room for provider framing around the schema.
            if projected > budget.max_input_tokens:
                raise _OpenAIPreflightError(
                    BudgetExceeded(
                        which="input_tokens",
                        used=0,
                        limit=budget.max_input_tokens,
                        attempts=0,
                        projected_input_tokens=projected,
                    )
                )
            input_price = max(
                budget.pricing.input_per_million_usd,
                budget.pricing.cached_input_per_million_usd or Decimal(0),
                budget.pricing.cache_write_input_per_million_usd or Decimal(0),
            )
            reservation = (
                Decimal(projected) * input_price
                + Decimal(budget.max_output_tokens) * budget.pricing.output_per_million_usd
            ) / Decimal(1_000_000)
            if reservation > budget.max_cost_usd:
                raise _OpenAIPreflightError(
                    BudgetExceeded(
                        which="estimated_cost_usd",
                        used=0,
                        limit=budget.max_cost_usd,
                        attempts=0,
                    )
                )
        await reserve_openai(reservation)
        response = await self._client.responses.create(
            model=self.model_name,
            instructions=prompt.system,
            input=prompt.user,
            text={"format": strict_response_format(schema)},
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=budget.max_output_tokens,
            store=False,
        )
        output_text = getattr(response, "output_text", "")
        if not isinstance(output_text, str):
            output_text = ""
        (
            input_tokens,
            output_tokens,
            cached_input_tokens,
            cache_write_input_tokens,
            reasoning_tokens,
        ) = openai_usage(response)
        return RawProviderResponse(
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            reasoning_tokens=reasoning_tokens,
            request_id=getattr(response, "id", None),
            refusal=_openai_refusal(response),
        )
