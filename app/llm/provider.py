"""Async structured-output providers with one repair and fail-closed refusal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from functools import cache
import json
import time
from typing import Any, Protocol, cast

from openai import AsyncOpenAI
from openai.types.responses import ResponseFormatTextJSONSchemaConfigParam
from pydantic import BaseModel, ValidationError

from app.llm.schemas import (
    CompletionFailure,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    ProviderResult,
    RawProviderResponse,
    SchemaRejected,
)

type Clock = Callable[[], int]


class _ResponsesAPI(Protocol):
    """Injected Responses surface used by the OpenAI adapter and offline fakes."""

    def create(self, **kwargs: object) -> Awaitable[object]:
        """Send one request to the Responses API."""
        ...

    def parse(self, **kwargs: object) -> Awaitable[object]:
        """Send one request whose output the SDK parses into a schema."""
        ...


class _OpenAIClient(Protocol):
    """Minimum client shape needed by ``OpenAILLMProvider``."""

    @property
    def responses(self) -> _ResponsesAPI:
        """Expose the Responses surface the adapter calls."""
        ...


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object, rejecting a repeated key instead of merging it."""
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _invalid_json_constant(value: str) -> None:
    """Reject the non-finite JSON constants a strict schema cannot carry."""
    raise ValueError(f"non-finite JSON number: {value}")


def _validation_errors(error: ValidationError) -> tuple[str, ...]:
    """Render validation failures as repair instructions the model can act on."""
    messages = []
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"]) or "$"
        messages.append(f"{location}: {issue['msg']} [{issue['type']}]")
    return tuple(messages)


def _parse_output[OutputT: BaseModel](
    output_text: str,
    schema: type[OutputT],
) -> tuple[OutputT | None, tuple[str, ...]]:
    """Parse one strict JSON object into the requested output schema.

    Parameters
    ----------
    output_text : str
        Raw provider output.
    schema : type[OutputT]
        Pydantic model required by the caller.

    Returns
    -------
    tuple[OutputT | None, tuple[str, ...]]
        Parsed value with no errors, or ``None`` with stable validation messages.

    Notes
    -----
    The JSON round trip rejects duplicate keys and non-finite numbers while retaining
    JSON-mode strict validation, including array-to-tuple handling.
    """
    try:
        value = json.loads(
            output_text,
            object_pairs_hook=_json_object,
            parse_constant=_invalid_json_constant,
        )
        canonical = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        return schema.model_validate_json(canonical, strict=True), ()
    except ValidationError as error:
        return None, _validation_errors(error)
    except json.JSONDecodeError as error:
        message = f"$: {error.msg} at line {error.lineno} column {error.colno} [json_invalid]"
        return None, (message,)
    except ValueError as error:
        return None, (f"$: {error} [json_invalid]",)


def _repair_prompt(prompt: Prompt, raw_output: str, errors: Sequence[str]) -> Prompt:
    """Extend one prompt with its validation errors and the output that failed."""
    details = "\n".join(f"- {error}" for error in errors)
    return Prompt(
        system=prompt.system,
        user=(
            f"{prompt.user}\n\n"
            "Your previous structured output failed validation. Repair it once and return "
            "only an object that matches the required schema.\n"
            f"Validation errors:\n{details}\n"
            f"Previous output:\n{raw_output}"
        ),
    )


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
        """Validate one completion, repair once, and return a typed result.

        Parameters
        ----------
        prompt : Prompt
            Strict system and user prompt.
        schema : type[OutputT]
            Required structured-output model.
        budget : ProviderBudget
            Cumulative allowance shared by both possible attempts.

        Returns
        -------
        ProviderResult[OutputT]
            Parsed output or a typed schema, budget, refusal, or provider failure.

        Raises
        ------
        TypeError
            If the boundary values do not use the declared strict types.
        ValueError
            If the injected clock moves backwards.

        Notes
        -----
        Provider exceptions become typed results. Only invalid caller contracts and a
        non-monotonic clock escape this boundary.
        """
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

        def failed(failure: CompletionFailure) -> ProviderResult[OutputT]:
            """Close the completion over whatever evidence has accumulated so far."""
            return ProviderResult(
                status=failure.status,
                parsed=None,
                refusal=failure,
                metadata=self._metadata(
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                ),
            )

        for attempt in (1, 2):
            remaining = ProviderBudget(
                max_input_tokens=budget.max_input_tokens - total_input_tokens,
                max_output_tokens=budget.max_output_tokens - total_output_tokens,
                max_cost_usd=budget.max_cost_usd
                - budget.pricing.estimate(total_input_tokens, total_output_tokens),
                pricing=budget.pricing,
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
                return failed(
                    ProviderRefusal(
                        status="provider_error",
                        message=f"{type(error).__name__}: {error}",
                        attempts=attempt,
                    )
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
            if raw.refusal is not None:
                return failed(
                    ProviderRefusal(
                        status="provider_refused",
                        message=raw.refusal,
                        attempts=attempt,
                    )
                )

            if failure := budget.exhausted_by(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                attempts=attempt,
            ):
                return failed(failure)

            parsed, errors = _parse_output(raw.output_text, schema)
            if parsed is None:
                if attempt == 1:
                    if failure := budget.exhausted_by(
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        attempts=1,
                        inclusive=True,
                        schema_errors=errors,
                    ):
                        return failed(failure)
                    current_prompt = _repair_prompt(prompt, raw.output_text, errors)
                    continue
                return failed(SchemaRejected(errors=errors))

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
        """Build trace-ready metadata from accumulated attempts."""
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
        """Record the request boundary and return the next queued response."""
        del schema
        self._prompts.append(prompt)
        self._budgets.append(budget)
        if not self._responses:
            raise RuntimeError("deterministic provider response queue is empty")
        return self._responses.pop(0)


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


@cache
def _strict_schema_json(schema: type[BaseModel]) -> str:
    """Build one strict JSON schema, cached per model class.

    ``model_json_schema`` is neither cached by pydantic nor cheap, and every request
    rebuilds the same payload for the same class. Caching the serialized form rather
    than the dictionary keeps each caller's copy independent of the cache entry. Key
    order is preserved because ``required`` is a positional copy of ``properties``.
    """
    json_schema = schema.model_json_schema()
    _strict_schema(json_schema, "$")
    return json.dumps(json_schema, allow_nan=False, ensure_ascii=False)


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
    return {
        "type": "json_schema",
        "name": schema.__name__,
        "schema": json.loads(_strict_schema_json(schema)),
        "strict": True,
    }


def _openai_refusal(response: object) -> str | None:
    """Return the refusal text an OpenAI response carries, or ``None``."""
    for output in getattr(response, "output", ()):
        for content in getattr(output, "content", ()):
            if getattr(content, "type", None) == "refusal":
                refusal = getattr(content, "refusal", None)
                if isinstance(refusal, str) and refusal.strip():
                    return refusal
    return None


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
        client: object | None = None,
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
        self._owned_client = AsyncOpenAI(api_key=api_key) if client is None else None
        client_value: object = client if client is not None else self._owned_client
        self._client = cast(_OpenAIClient, client_value)

    async def aclose(self) -> None:
        """Close the HTTP client this provider opened for itself.

        An injected client belongs to its caller and is left untouched, so a test fake
        needs no shutdown surface. Without this the connection pool of every provider
        built from an api key survives until interpreter exit.
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
            Pydantic output schema bound through strict or legacy SDK decoding.
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
