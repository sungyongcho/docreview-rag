"""Async structured-output providers with one repair and fail-closed refusal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from decimal import Decimal
import json
import time
from typing import Any

from openai import AsyncOpenAI
from openai.types.responses import ResponseFormatTextJSONSchemaConfigParam
from pydantic import BaseModel, ValidationError

from app.llm.schemas import (
    BudgetExceeded,
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


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _validation_errors(error: ValidationError) -> tuple[str, ...]:
    messages = []
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"]) or "$"
        messages.append(f"{location}: {issue['msg']} [{issue['type']}]")
    return tuple(messages)


def _parse_output[OutputT: BaseModel](
    output_text: str,
    schema: type[OutputT],
) -> tuple[OutputT | None, tuple[str, ...]]:
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


def _budget_failure(
    budget: ProviderBudget,
    *,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: Decimal,
    attempts: int,
) -> BudgetExceeded | None:
    if input_tokens > budget.max_input_tokens:
        return BudgetExceeded(
            which="input_tokens",
            used=input_tokens,
            limit=budget.max_input_tokens,
            attempts=attempts,
        )
    if output_tokens > budget.max_output_tokens:
        return BudgetExceeded(
            which="output_tokens",
            used=output_tokens,
            limit=budget.max_output_tokens,
            attempts=attempts,
        )
    if estimated_cost_usd > budget.max_cost_usd:
        return BudgetExceeded(
            which="estimated_cost_usd",
            used=estimated_cost_usd,
            limit=budget.max_cost_usd,
            attempts=attempts,
        )
    return None


def _repair_budget_failure(
    budget: ProviderBudget,
    *,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: Decimal,
) -> BudgetExceeded | None:
    """Return why a validation repair cannot make another provider request."""
    if input_tokens >= budget.max_input_tokens:
        return BudgetExceeded(
            which="input_tokens",
            used=input_tokens,
            limit=budget.max_input_tokens,
            attempts=1,
        )
    if output_tokens >= budget.max_output_tokens:
        return BudgetExceeded(
            which="output_tokens",
            used=output_tokens,
            limit=budget.max_output_tokens,
            attempts=1,
        )
    priced = budget.pricing.input_per_million_usd > 0 or budget.pricing.output_per_million_usd > 0
    if priced and estimated_cost_usd >= budget.max_cost_usd:
        return BudgetExceeded(
            which="estimated_cost_usd",
            used=estimated_cost_usd,
            limit=budget.max_cost_usd,
            attempts=1,
        )
    return None


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
        """Validate, repair once after schema failure, then refuse explicitly."""
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

        for attempt in (1, 2):
            remaining = budget.model_copy(
                update={
                    "max_input_tokens": budget.max_input_tokens - total_input_tokens,
                    "max_output_tokens": budget.max_output_tokens - total_output_tokens,
                    "max_cost_usd": budget.max_cost_usd
                    - budget.pricing.estimate(total_input_tokens, total_output_tokens),
                }
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
                failure = ProviderRefusal(
                    status="provider_error",
                    message=f"{type(error).__name__}: {error}",
                    attempts=attempt,
                )
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
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
            estimated_cost = budget.pricing.estimate(
                total_input_tokens,
                total_output_tokens,
            )

            if raw.refusal is not None:
                failure = ProviderRefusal(
                    status="provider_refused",
                    message=raw.refusal,
                    attempts=attempt,
                )
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            if failure := _budget_failure(
                budget,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                estimated_cost_usd=estimated_cost,
                attempts=attempt,
            ):
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            parsed, errors = _parse_output(raw.output_text, schema)
            if parsed is None:
                if attempt == 1:
                    if failure := _repair_budget_failure(
                        budget,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        estimated_cost_usd=estimated_cost,
                    ):
                        return self._failed_result(
                            failure,
                            raw_outputs=raw_outputs,
                            request_ids=request_ids,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            request_time_ms=total_request_time_ms,
                            budget=budget,
                        )
                    current_prompt = _repair_prompt(prompt, raw.output_text, errors)
                    continue
                failure = SchemaRejected(errors=errors)
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            assert not errors
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

    def _failed_result[OutputT: BaseModel](
        self,
        failure: CompletionFailure,
        *,
        raw_outputs: Sequence[str],
        request_ids: Sequence[str],
        input_tokens: int,
        output_tokens: int,
        request_time_ms: float,
        budget: ProviderBudget,
    ) -> ProviderResult[OutputT]:
        metadata = self._metadata(
            raw_outputs=raw_outputs,
            request_ids=request_ids,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_time_ms,
            budget=budget,
        )
        return ProviderResult(
            status=failure.status,
            parsed=None,
            refusal=failure,
            metadata=metadata,
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
        del schema
        self._prompts.append(prompt)
        self._budgets.append(budget)
        if not self._responses:
            raise RuntimeError("deterministic provider response queue is empty")
        return self._responses.pop(0)


MockLLMProvider = DeterministicLLMProvider


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


def _openai_refusal(response: object) -> str | None:
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
