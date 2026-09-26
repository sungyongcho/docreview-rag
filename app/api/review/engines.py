"""Resolve each request's review engine and pin a local one for the whole request."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.api.errors import bad_request, unavailable
from app.api.review.profiles import ReviewSessionProfile
from app.api.review.schemas import RetrieveRequest, ReviewRequest
from app.llm.completion import LLMProvider
from app.llm.local.connection import LocalConnectionManager
from app.llm.local.inventory import LocalModelInventory
from app.llm.local.provider import LocalLLMProvider
from app.llm.openai_limits import OpenAILimitsManager
from app.llm.schemas import ProviderBudget


@dataclass
class _LocalRequest:
    """Hold one endpoint and provider for a complete request across asynchronous stages."""

    inventory: LocalModelInventory | None
    provider: LocalLLMProvider | None = None
    model: str | None = None
    model_digest: str | None = None


class ReviewEngines:
    """Resolve the provider and budget of each request's review engine.

    A local engine is pinned per request: the endpoint discovered when the request starts,
    the model it selects and the provider it opens stay fixed across every asynchronous
    stage, so a connection saved mid-request only affects the next request.

    Parameters
    ----------
    llm_providers : dict[str, LLMProvider]
        Configured provider per remote engine name.
    provider_budgets : dict[str, ProviderBudget]
        Explicit budget per engine name, including ``local`` when discovery is enabled.
    local_connection : LocalConnectionManager | None
        Saved local connection whose current inventory each new request pins.
    openai_limits : OpenAILimitsManager | None
        Working per-call OpenAI cap that replaces the configured OpenAI budget.
    allow_local_engine : bool
        Whether this deployment serves the local engine at all.
    local_timeout_s : float
        Request timeout for a local provider opened by a request.
    """

    def __init__(
        self,
        *,
        llm_providers: dict[str, LLMProvider],
        provider_budgets: dict[str, ProviderBudget],
        local_connection: LocalConnectionManager | None,
        openai_limits: OpenAILimitsManager | None,
        allow_local_engine: bool,
        local_timeout_s: float,
    ) -> None:
        self._llm_providers = llm_providers
        self._provider_budgets = provider_budgets
        self._local_connection = local_connection
        self._openai_limits = openai_limits
        self._allow_local_engine = allow_local_engine
        self._local_timeout_s = local_timeout_s
        self._local_request: ContextVar[_LocalRequest | None] = ContextVar(
            "local_request", default=None
        )

    @property
    def local_inventory(self) -> LocalModelInventory | None:
        """Resolve the connection inventory before each request pins its own revision."""
        if not self._allow_local_engine or self._local_connection is None:
            return None
        return self._local_connection.current.inventory

    @asynccontextmanager
    async def pin_request(self) -> AsyncIterator[None]:
        """Pin the current local endpoint for one request and close what the request opened.

        The endpoint is captured before the request's first await, so a connection saved
        while the request runs cannot switch it to another server halfway through.
        """
        context = _LocalRequest(self.local_inventory)
        token = self._local_request.set(context)
        try:
            yield
        finally:
            self._local_request.reset(token)
            if context.provider is not None:
                await context.provider.aclose()

    def pinned_inventory(self) -> LocalModelInventory | None:
        """Return the endpoint this request pinned, or current discovery outside a request."""
        context = self._local_request.get()
        return context.inventory if context is not None else self.local_inventory

    def pinned_model_digest(self) -> str | None:
        """Return the digest of the model this request pinned, if it pinned one."""
        context = self._local_request.get()
        return context.model_digest if context is not None else None

    async def pin_local_model(self, profile: ReviewSessionProfile) -> ReviewSessionProfile:
        """Pin one discovered model without replacing an explicit unavailable selection."""
        if profile.engine != "local":
            return profile
        context = self._local_request.get()
        if context is not None and context.model is not None:
            return profile.model_copy(update={"local_model": context.model})
        inventory = self.pinned_inventory()
        if inventory is None:
            raise unavailable("local_model_unavailable", "The local model server is disconnected.")
        snapshot = await inventory.snapshot()
        available = snapshot.available_models
        if snapshot.reason is not None or not available:
            raise unavailable(
                "local_model_unavailable", "No answer model is available on the local server."
            )
        selected = profile.local_model
        if selected is None:
            if len(available) != 1:
                raise bad_request(
                    "local_model_required", "Choose a local answer model before sending a question."
                )
            selected = available[0]
        if selected not in available:
            raise unavailable(
                "local_model_unavailable", "The selected local model is no longer available."
            )
        if context is not None:
            context.model = selected
            context.model_digest = inventory.model_digest(selected)
        return profile.model_copy(update={"local_model": selected})

    async def resolve_engine(
        self, request: ReviewRequest | RetrieveRequest
    ) -> tuple[LLMProvider, ProviderBudget]:
        """Resolve a request-specific provider without changing any other conversation."""
        profile = await self.pin_local_model(request.session_profile)
        engine = profile.engine
        budget = self._provider_budgets.get(engine)
        if engine == "openai" and budget is not None and self._openai_limits is not None:
            # Dev may lower the per-call cap below the .env ceiling without a restart.
            budget = self._openai_limits.effective()
        inventory = self.pinned_inventory()
        if engine == "local" and inventory is not None and budget is not None:
            return self._local_provider(profile.local_model, inventory, budget), budget
        provider = self._llm_providers.get(engine)
        if provider is None or budget is None:
            raise unavailable(
                "provider_unavailable",
                f"Review engine {engine!r} is not configured.",
            )
        return provider, budget

    def _local_provider(
        self, model: str | None, inventory: LocalModelInventory, budget: ProviderBudget
    ) -> LocalLLMProvider:
        """Reuse the provider this request opened, or open one for its pinned model.

        Every stage of a request must talk to the same endpoint and model, so the first
        provider is kept on the request and ``pin_request`` closes it when the request ends.
        """
        context = self._local_request.get()
        if context is not None and context.provider is not None:
            return context.provider
        assert model is not None
        provider = LocalLLMProvider(
            base_url=inventory.base_url,
            model_name=model,
            protocol=inventory.protocol,
            api_key=inventory.api_key,
            timeout_s=self._local_timeout_s,
            context_window=budget.max_input_tokens + budget.max_output_tokens,
        )
        if context is not None:
            context.provider = provider
        return provider
