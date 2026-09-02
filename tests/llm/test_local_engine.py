"""Protocol resolution and budget construction for the optional local engine."""

import asyncio
from decimal import Decimal

import pytest

from app.llm.local_engine import (
    DEFAULT_LOCAL_TIMEOUT_S,
    build_local_provider,
    local_provider_budget,
    resolve_local_protocol,
)


@pytest.mark.parametrize(
    ("base_url", "configured", "expected"),
    [
        ("http://ollama:11434", "auto", "ollama"),
        ("http://ollama:11434/", "auto", "ollama"),
        ("http://host:8000/v1", "auto", "openai_responses"),
        ("http://host:8000/v1/", "auto", "openai_responses"),
        ("http://ollama:11434", "openai_responses", "openai_responses"),
        ("http://host:8000/v1", "ollama", "ollama"),
    ],
)
def test_auto_reads_the_v1_suffix_and_an_explicit_protocol_always_wins(
    base_url: str, configured: str, expected: str
) -> None:
    """The `/v1` suffix is the only signal `auto` has, and it never overrides a choice."""
    assert resolve_local_protocol(base_url, configured) == expected


def test_local_budget_is_priced_at_zero_and_keeps_its_own_token_limits() -> None:
    """The local budget is its own definition, not the OpenAI one with prices cleared."""
    budget = local_provider_budget(max_input_tokens=4_096, max_output_tokens=512)

    assert budget.max_input_tokens == 4_096
    assert budget.max_output_tokens == 512
    assert budget.max_cost_usd == Decimal("0")
    assert budget.pricing.input_per_million_usd == Decimal("0")
    assert budget.pricing.output_per_million_usd == Decimal("0")


def test_provider_carries_the_configured_timeout_and_refuses_a_nonpositive_one() -> None:
    """A CPU-hosted model needs a caller-chosen deadline, and zero is not one."""
    provider = build_local_provider(
        base_url="http://ollama:11434",
        model_name="gemma4:e4b",
        protocol="auto",
        api_key=None,
        timeout_s=45.0,
    )
    try:
        assert provider.protocol == "ollama"
        assert provider.api_url == "local://ollama"
    finally:
        asyncio.run(provider.aclose())

    with pytest.raises(ValueError, match="timeout must be positive"):
        build_local_provider(
            base_url="http://ollama:11434",
            model_name="gemma4:e4b",
            protocol="auto",
            api_key=None,
            timeout_s=0,
        )


def test_default_timeout_leaves_room_for_a_slow_first_token() -> None:
    """30 seconds was not enough for structured output on a CPU host; the default is not that."""
    assert DEFAULT_LOCAL_TIMEOUT_S >= 120.0
