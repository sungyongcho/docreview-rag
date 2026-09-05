"""Shared local connection and budget composition for API and release entry points."""

from app.llm.local_connection import ConnectionSource, LocalConnectionManager, LocalProtocol
from app.llm.local_engine import local_provider_budget
from app.llm.schemas import ProviderBudget
from app.settings_sources import Environment


def build_local_runtime(
    *,
    environment: Environment,
    base_url: str | None,
    protocol: LocalProtocol,
    source: ConnectionSource,
    api_key: str | None,
    max_input_tokens: int,
    max_output_tokens: int,
) -> tuple[LocalConnectionManager, ProviderBudget | None]:
    """Configure discovery without probing; production receives no local token budget."""
    enabled = environment != "prod"
    connection = LocalConnectionManager(
        initial_base_url=base_url,
        initial_protocol=protocol,
        initial_source=source,
        api_key=api_key,
        enabled=enabled,
    )
    budget = (
        local_provider_budget(
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
        )
        if enabled
        else None
    )
    return connection, budget
