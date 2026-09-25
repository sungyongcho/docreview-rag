"""Shared offline LLM provider double and structured-output schema for deterministic tests."""

from collections.abc import Callable, Sequence
import time

from pydantic import BaseModel

from app.llm.provider import Clock, LLMProvider
from app.llm.schemas import NonBlank, Prompt, ProviderBudget, RawProviderResponse, StrictSchema


class ChatReply(StrictSchema):
    """One concise retrieval-free conversational answer."""

    answer: NonBlank


class DeterministicLLMProvider(LLMProvider):
    """Queue-backed offline provider for deterministic tests."""

    provider_name = "deterministic"
    api_url = "deterministic://local"

    def __init__(
        self,
        responses: Sequence[RawProviderResponse],
        *,
        model_name: str = "deterministic-mock",
        clock: Clock = time.perf_counter_ns,
        projected_input_tokens: Callable[[Prompt], int] | None = None,
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
        self._projection = projected_input_tokens

    def _projected_input_tokens(self, prompt: Prompt) -> int | None:
        """Project only when a test injected a projection; fixtures otherwise report usage alone."""
        return None if self._projection is None else self._projection(prompt)

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
