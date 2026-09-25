"""Protocol resolution and the zero-cost budget for the optional local model engine.

The runtime API and the release app both resolve the local wire protocol and build the
local budget here from their own settings objects, which stops the two paths from
drifting, as when the release path once borrowed the OpenAI token limits while the
runtime path used the local ones.
"""

from __future__ import annotations

from decimal import Decimal

from app.llm.local import LocalLlmProtocol
from app.llm.schemas import ProviderBudget, TokenPricing

ConfiguredLocalProtocol = LocalLlmProtocol | str


def resolve_local_protocol(base_url: str, configured: ConfiguredLocalProtocol) -> LocalLlmProtocol:
    """Pick the wire protocol, treating a `/v1` suffix as the OpenAI-compatible marker.

    Parameters
    ----------
    base_url:
        Configured local endpoint.
    configured:
        `auto`, or an explicit protocol that always wins.

    Returns
    -------
    LocalLlmProtocol
        The protocol the provider should speak.
    """
    if configured in {"openai_responses", "ollama"}:
        return configured  # type: ignore[return-value]
    return "openai_responses" if base_url.rstrip("/").endswith("/v1") else "ollama"


def local_provider_budget(*, max_input_tokens: int, max_output_tokens: int) -> ProviderBudget:
    """Build the local budget, which is priced at zero because nothing is billed.

    Notes
    -----
    The cost cap stays zero rather than unset so the shared budget guard still runs and
    a local run can never be mistaken for a billable one in the usage ledger.
    """
    return ProviderBudget(
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_cost_usd=Decimal("0"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0"),
            output_per_million_usd=Decimal("0"),
        ),
    )
