"""Bounded structured completion with cumulative provider accounting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
import time

from pydantic import BaseModel

from app.llm.decoding import _parse_output, _repair_prompt
from app.llm.estimate import estimate_prompt_tokens
from app.llm.schemas import (
    BudgetExceeded,
    CompletionFailure,
    LocalModelTiming,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    ProviderResult,
    RawProviderResponse,
    SchemaRejected,
)
from app.observability.stages import record_model_call
from app.release.ai_allowance import AIAllowanceError

type Clock = Callable[[], int]


class BilledAttemptAllowanceError(AIAllowanceError):
    """A shared-allowance denial of a repair after the call's first attempt was billed.

    It is an ``AIAllowanceError`` with the original code, message, retry delay and reset,
    so every caller keeps its retry mapping. ``metadata`` describes the attempt already
    sent exactly as a typed failure after that attempt would, so a caller can trace what
    was billed.
    """

    def __init__(self, error: AIAllowanceError, metadata: ProviderMetadata) -> None:
        super().__init__(error.code, str(error), error.retry_after, error.reset)
        self.metadata = metadata


class _OpenAIPreflightError(ValueError):
    """Return a structured budget refusal without counting an unsent provider call."""

    def __init__(self, failure: BudgetExceeded):
        """Retain the preflight resource and conservative projected bound."""
        super().__init__("OpenAI request exceeds its configured preflight allowance")
        self.failure = failure


class _OpenAIPreflightUnavailableError(ValueError):
    """Refuse before dispatch because a local precondition of the preflight is missing.

    Nothing was sent, so the refusal counts no request and carries no raw output; the
    message names the precondition rather than a provider fault.
    """


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
        ValueError
            If the injected clock moves backwards.
        AIAllowanceError
            If the shared OpenAI allowance denies the call before dispatch; propagated so
            the API can answer 429. A denied repair raises ``BilledAttemptAllowanceError``,
            which carries the metadata of the first attempt that was already billed.

        Notes
        -----
        Provider exceptions become typed results. Only a non-monotonic clock and a
        denied shared allowance escape this boundary.
        """
        current_prompt = prompt
        raw_outputs: list[str] = []
        local_timings: list[LocalModelTiming] = []
        request_ids: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_input_tokens = 0
        total_cache_write_input_tokens = 0
        total_reasoning_tokens = 0
        total_request_time_ms = 0.0

        def sent_metadata(projected: int | None = None) -> ProviderMetadata:
            """Describe the attempts sent so far as this completion's trace metadata."""
            return self._metadata(
                raw_outputs=raw_outputs,
                local_timings=local_timings,
                request_ids=request_ids,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cached_input_tokens=total_cached_input_tokens,
                cache_write_input_tokens=total_cache_write_input_tokens,
                reasoning_tokens=total_reasoning_tokens,
                request_time_ms=total_request_time_ms,
                budget=budget,
                projected_input_tokens=projected,
            )

        def failed(
            failure: CompletionFailure, *, projected: int | None = None
        ) -> ProviderResult[OutputT]:
            """Close the completion over whatever evidence has accumulated so far."""
            return ProviderResult(
                status=failure.status,
                parsed=None,
                refusal=failure,
                metadata=sent_metadata(projected),
            )

        repair_errors: tuple[str, ...] = ()
        for attempt in (1, 2):
            remaining = ProviderBudget(
                max_input_tokens=budget.max_input_tokens - total_input_tokens,
                max_output_tokens=budget.max_output_tokens - total_output_tokens,
                max_cost_usd=budget.max_cost_usd
                - budget.pricing.estimate(
                    total_input_tokens,
                    total_output_tokens,
                    cached_input_tokens=total_cached_input_tokens,
                    cache_write_input_tokens=total_cache_write_input_tokens,
                ),
                pricing=budget.pricing,
            )
            # Fail before paying: a prompt that cannot fit the remaining input allowance is
            # refused here, including the larger repair prompt of a second attempt. Only a
            # projection strictly over the allowance is refused: estimation uncertainty is
            # not turned into extra budget, and because the fallback encoding undercounts,
            # a projection that slips through is still caught by the post-hoc usage check.
            projected = estimate_prompt_tokens(current_prompt, model_name=self.model_name)
            if projected is not None and projected > remaining.max_input_tokens:
                # Nothing is sent, so nothing is fabricated: the refusal reports how many
                # requests actually went out (none on the first attempt, one before a repair).
                return failed(
                    BudgetExceeded(
                        which="input_tokens",
                        used=total_input_tokens,
                        limit=budget.max_input_tokens,
                        attempts=len(raw_outputs),
                        schema_errors=repair_errors,
                        projected_input_tokens=projected,
                    ),
                    projected=projected,
                )
            started = self._clock()
            try:
                raw = await self._request(current_prompt, schema, remaining)
            except AIAllowanceError as error:
                if not raw_outputs:
                    # Nothing of this completion was sent, so nothing was billed.
                    raise
                # Only the repair was denied: the first attempt was sent and billed, so it
                # leaves with the denial and the caller can trace it like any paid attempt.
                raise BilledAttemptAllowanceError(error, sent_metadata()) from error
            except _OpenAIPreflightError as error:
                # The adapter's stricter projection refused the call; the metadata carries
                # the same projection so model_calls and the failure details agree.
                return failed(
                    error.failure.model_copy(
                        update={
                            "attempts": len(raw_outputs),
                            "schema_errors": repair_errors,
                            "used": total_input_tokens
                            if error.failure.which == "input_tokens"
                            else budget.pricing.estimate(
                                total_input_tokens,
                                total_output_tokens,
                                cached_input_tokens=total_cached_input_tokens,
                                cache_write_input_tokens=total_cache_write_input_tokens,
                            ),
                            "limit": budget.max_input_tokens
                            if error.failure.which == "input_tokens"
                            else budget.max_cost_usd,
                        }
                    ),
                    projected=error.failure.projected_input_tokens,
                )
            except _OpenAIPreflightUnavailableError as error:
                # A local precondition failed before dispatch: no request went out, so no
                # empty raw output and no request time are recorded against the provider.
                return failed(
                    ProviderRefusal(
                        status="provider_error",
                        message=str(error),
                        attempts=len(raw_outputs),
                    )
                )
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
            if raw.local_timing is not None:
                local_timings.append(raw.local_timing.model_copy(update={"attempt": attempt}))
            if raw.request_id is not None:
                request_ids.append(raw.request_id)
            total_input_tokens += raw.input_tokens
            total_output_tokens += raw.output_tokens
            total_cached_input_tokens += raw.cached_input_tokens
            total_cache_write_input_tokens += raw.cache_write_input_tokens
            total_reasoning_tokens += raw.reasoning_tokens
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
                cached_input_tokens=total_cached_input_tokens,
                cache_write_input_tokens=total_cache_write_input_tokens,
                attempts=attempt,
            ):
                return failed(failure)

            parsed, errors = _parse_output(raw.output_text, schema)
            if parsed is None:
                if attempt == 1:
                    if failure := budget.exhausted_by(
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        cached_input_tokens=total_cached_input_tokens,
                        cache_write_input_tokens=total_cache_write_input_tokens,
                        attempts=1,
                        inclusive=True,
                        schema_errors=errors,
                    ):
                        return failed(failure)
                    current_prompt = _repair_prompt(prompt, raw.output_text, errors)
                    repair_errors = tuple(errors)
                    continue
                return failed(SchemaRejected(errors=errors))

            metadata = self._metadata(
                raw_outputs=raw_outputs,
                local_timings=local_timings,
                request_ids=request_ids,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cached_input_tokens=total_cached_input_tokens,
                cache_write_input_tokens=total_cache_write_input_tokens,
                reasoning_tokens=total_reasoning_tokens,
                request_time_ms=total_request_time_ms,
                budget=budget,
            )
            return ProviderResult(status="ok", parsed=parsed, refusal=None, metadata=metadata)

        raise AssertionError("completion attempt loop ended unexpectedly")

    def _metadata(
        self,
        *,
        raw_outputs: Sequence[str],
        local_timings: Sequence[LocalModelTiming],
        request_ids: Sequence[str],
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int,
        cache_write_input_tokens: int,
        reasoning_tokens: int,
        request_time_ms: float,
        budget: ProviderBudget,
        projected_input_tokens: int | None = None,
    ) -> ProviderMetadata:
        """Build trace-ready metadata from accumulated attempts."""
        metadata = ProviderMetadata(
            provider=self.provider_name,
            model_name=self.model_name,
            api_url=self.api_url,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            reasoning_tokens=reasoning_tokens,
            estimated_cost_usd=budget.pricing.estimate(
                input_tokens,
                output_tokens,
                cached_input_tokens=cached_input_tokens,
                cache_write_input_tokens=cache_write_input_tokens,
            ),
            request_time_ms=request_time_ms,
            retries=max(len(raw_outputs) - 1, 0),
            request_ids=tuple(request_ids),
            llm_output=raw_outputs[-1] if raw_outputs else "",
            raw_outputs=tuple(raw_outputs),
            local_timings=tuple(local_timings),
            requests=len(raw_outputs),
            projected_input_tokens=projected_input_tokens,
        )

        record_model_call(metadata)
        return metadata
