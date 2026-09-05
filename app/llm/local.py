"""Fail-closed OpenAI-compatible and Ollama native local LLM adapters."""

from __future__ import annotations

import time
from typing import Literal

import httpx
from pydantic import BaseModel

from app.llm.provider import Clock, LLMProvider, RawProviderResponse, strict_response_format
from app.llm.schemas import LocalModelTiming, Prompt, ProviderBudget

LocalLlmProtocol = Literal["openai_responses", "ollama"]


class LocalLLMProvider(LLMProvider):
    """Normalize two local structured-output protocols without exposing their endpoint."""

    provider_name = "local"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        protocol: LocalLlmProtocol,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        client: httpx.AsyncClient | None = None,
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not base_url.strip() or not model_name.strip():
            raise ValueError("local LLM base URL and model must be nonblank")
        if protocol not in {"openai_responses", "ollama"}:
            raise ValueError("unsupported local LLM protocol")
        if timeout_s <= 0:
            raise ValueError("local LLM timeout must be positive")
        super().__init__(clock=clock)
        self.model_name = model_name.strip()
        self.protocol = protocol
        local_kind = "openai-compatible" if protocol == "openai_responses" else "ollama"
        self.api_url = f"local://{local_kind}"
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owned_client = httpx.AsyncClient(timeout=timeout_s) if client is None else None
        self._client = client or self._owned_client

    async def aclose(self) -> None:
        """Close only the HTTP client owned by this provider."""
        if self._owned_client is not None:
            await self._owned_client.aclose()

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        """Call the configured local protocol and require authoritative token usage."""
        if self._client is None:
            raise RuntimeError("local provider client is closed")
        return (
            await self._openai_request(prompt, schema, budget)
            if self.protocol == "openai_responses"
            else await self._ollama_request(prompt, schema, budget)
        )

    async def _openai_request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        """Call an OpenAI Responses-compatible local endpoint."""
        base = self._base_url[:-3] if self._base_url.endswith("/v1") else self._base_url
        headers = {"authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        response = await self._client.post(
            f"{base}/v1/responses",
            headers=headers,
            json={
                "model": self.model_name,
                "instructions": prompt.system,
                "input": prompt.user,
                "text": {"format": strict_response_format(schema)},
                "max_output_tokens": budget.max_output_tokens,
                "store": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage") if isinstance(payload, dict) else None
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("local Responses payload did not include token usage")
        output_text = payload.get("output_text")
        if not isinstance(output_text, str):
            raise ValueError("local Responses payload did not include output_text")
        return RawProviderResponse(
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
        )

    async def _ollama_request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        """Call Ollama native chat with a Pydantic JSON schema.

        Notes
        -----
        `num_ctx` is sent explicitly. Ollama otherwise loads the model with its own
        default window, commonly 4096 tokens, and silently drops whatever does not fit.
        A truncated evidence prompt would produce an answer about filings the model never
        saw, which is the one failure this system must not hide, so the window is asked
        to match the budget the caller already enforces.
        """
        headers = {"authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        response = await self._client.post(
            f"{self._base_url}/api/chat",
            headers=headers,
            json={
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                "format": schema.model_json_schema(),
                "stream": False,
                "options": {
                    "num_predict": budget.max_output_tokens,
                    "num_ctx": budget.max_input_tokens + budget.max_output_tokens,
                    "temperature": 0,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") if isinstance(payload, dict) else None
        output_text = message.get("content") if isinstance(message, dict) else None
        input_tokens = payload.get("prompt_eval_count") if isinstance(payload, dict) else None
        output_tokens = payload.get("eval_count") if isinstance(payload, dict) else None
        if not isinstance(output_text, str):
            raise ValueError("Ollama response did not include message content")
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("Ollama response did not include token usage")
        timings: dict[str, int | float] = {}
        for name in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
            value = payload.get(name)
            if type(value) is int and value >= 0:
                timings[f"{name}_ms"] = value / 1_000_000
        for name in ("prompt_eval_count", "eval_count"):
            value = payload.get(name)
            if type(value) is int and value >= 0:
                timings[name] = value
        return RawProviderResponse(
            local_timing=LocalModelTiming.model_validate(timings) if timings else None,
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
