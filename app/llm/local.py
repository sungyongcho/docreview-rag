"""Fail-closed OpenAI-compatible and Ollama native local LLM adapters."""

from __future__ import annotations

import time
from typing import Literal

import httpx
from pydantic import BaseModel

from app.llm.local_diagnostics import failure_kind
from app.llm.provider import Clock, LLMProvider, RawProviderResponse, strict_response_format
from app.llm.schemas import LocalModelTiming, Prompt, ProviderBudget

LocalLlmProtocol = Literal["openai_responses", "ollama"]


def openai_compatible_root(base_url: str) -> str:
    """Return the server root of an OpenAI-compatible base URL, dropping a ``/v1`` suffix.

    Operators configure either the server root or its ``/v1`` API prefix; request paths
    are built from the root so both spellings reach the same ``/v1/...`` endpoints.
    """
    return base_url.removesuffix("/v1")


def _responses_output(payload: dict[str, object]) -> tuple[str | None, str | None]:
    """Read the message text and refusal one Responses object carries in ``output``.

    The wire format carries text only as ``output[].content[]`` parts of type
    ``output_text``; a top-level ``output_text`` is a convenience of the OpenAI SDK, not
    a JSON field, so it is read only when the items carry no text.

    Parameters
    ----------
    payload : dict[str, object]
        Decoded ``POST /v1/responses`` body.

    Returns
    -------
    tuple[str | None, str | None]
        Joined message text, or ``None`` when no text part was present, and the first
        nonblank ``refusal`` part, in that order.
    """
    texts: list[str] = []
    refusal: str | None = None
    output = payload.get("output")
    for item in output if isinstance(output, list) else ():
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        for part in content if isinstance(content, list) else ():
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if part.get("type") == "output_text" and isinstance(text, str):
                texts.append(text)
            declined = part.get("refusal")
            if part.get("type") == "refusal" and isinstance(declined, str) and declined.strip():
                refusal = refusal or declined
    if texts:
        return "".join(texts), refusal
    top_level = payload.get("output_text")
    return (top_level if isinstance(top_level, str) else None), refusal


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
        context_window: int | None = None,
    ) -> None:
        if not base_url.strip() or not model_name.strip():
            raise ValueError("local LLM base URL and model must be nonblank")
        if protocol not in {"openai_responses", "ollama"}:
            raise ValueError("unsupported local LLM protocol")
        if timeout_s <= 0:
            raise ValueError("local LLM timeout must be positive")
        if context_window is not None and context_window <= 0:
            raise ValueError("local LLM context window must be positive")
        super().__init__(clock=clock)
        self.model_name = model_name.strip()
        self.protocol = protocol
        local_kind = "openai-compatible" if protocol == "openai_responses" else "ollama"
        self.api_url = f"local://{local_kind}"
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout_s)
        self._owned_client = self._client if client is None else None
        #: Window requested from Ollama for every call of a run. The remaining budget
        #: shrinks after each call, and Ollama reloads the model whenever the requested
        #: window changes, which cost 10-12 s per call on CPU; a fixed window avoids that.
        self._context_window = context_window

    async def aclose(self) -> None:
        """Close only the HTTP client owned by this provider."""
        if self._owned_client is not None:
            await self._owned_client.aclose()

    async def _post_json(self, url: str, body: dict[str, object]) -> object:
        """POST ``body`` to ``url`` and decode the reply, naming a failure by its kind only.

        ``httpx`` writes the request URL into ``HTTPStatusError`` text, and a refusal
        message travels into the public failure details and the persisted trace. The
        server address is an admin-only setting, so a transport or status failure is
        reported through :func:`failure_kind` (``http_503``, ``timeout``, ``refused``)
        and never through the exception text.
        """
        headers = {"authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            response = await self._client.post(url, headers=headers, json=body)
            response.raise_for_status()
        except httpx.HTTPError as error:
            kind = failure_kind(error)
            raise ValueError(f"local model server request failed: {kind}") from error
        return response.json()

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        """Call the configured local protocol and require authoritative token usage."""
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
        payload = await self._post_json(
            f"{openai_compatible_root(self._base_url)}/v1/responses",
            {
                "model": self.model_name,
                "instructions": prompt.system,
                "input": prompt.user,
                "text": {"format": strict_response_format(schema)},
                "max_output_tokens": budget.max_output_tokens,
                "store": False,
            },
        )
        if not isinstance(payload, dict):
            raise ValueError("local Responses payload was not a JSON object")
        usage = payload.get("usage")
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("local Responses payload did not include token usage")
        output_text, refusal = _responses_output(payload)
        if output_text is None and refusal is None:
            raise ValueError("local Responses payload did not include output text")
        request_id = payload.get("id")
        return RawProviderResponse(
            output_text=output_text or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=request_id if isinstance(request_id, str) else None,
            refusal=refusal,
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
        payload = await self._post_json(
            f"{self._base_url}/api/chat",
            {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                "format": schema.model_json_schema(),
                "stream": False,
                # Thinking models such as gemma4 otherwise spend the whole output allowance
                # on hidden reasoning and return an empty structured answer; the prompts
                # already state their rules, so only the visible JSON is paid for.
                "think": False,
                "options": {
                    "num_predict": budget.max_output_tokens,
                    "num_ctx": max(
                        self._context_window or 0,
                        budget.max_input_tokens + budget.max_output_tokens,
                    ),
                    "temperature": 0,
                },
            },
        )
        if not isinstance(payload, dict):
            raise ValueError("Ollama response was not a JSON object")
        message = payload.get("message")
        output_text = message.get("content") if isinstance(message, dict) else None
        input_tokens = payload.get("prompt_eval_count")
        output_tokens = payload.get("eval_count")
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
