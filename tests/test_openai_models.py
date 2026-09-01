"""Role-scoped OpenAI model policy tests."""

from decimal import Decimal

import pytest

from app.openai_models import (
    OpenAIModelPolicyError,
    allowed_openai_models,
    default_openai_model,
    openai_policy_snapshot,
    resolve_openai_model,
)


def test_policy_defaults_are_role_scoped_and_price_exact_models():
    """Keep model identity, reasoning, dimensions, and prices in one policy."""
    agent = resolve_openai_model("agent")
    translation = resolve_openai_model("translation")
    embedding = resolve_openai_model("embedding")

    assert agent.model == "gpt-5.6-terra" and agent.reasoning_effort == "medium"
    assert agent.pricing.cache_write_input_per_million_usd == Decimal("2.50")
    assert translation.model == "gpt-5.6-luna" and translation.reasoning_effort == "low"
    assert embedding.model == "text-embedding-3-large" and embedding.dimensions == 384
    assert embedding.pricing.input_per_million_usd == Decimal("0.13")


@pytest.mark.parametrize("model", ["gpt-5-mini", "gpt-4.1-mini", "gpt-5.6-sol", "other"])
def test_policy_rejects_models_outside_the_role_allowlist(model):
    """Reject legacy, expensive, and arbitrary models before provider construction."""
    with pytest.raises(OpenAIModelPolicyError, match="allowed"):
        resolve_openai_model("agent", model)


def test_translation_allows_only_luna_and_terra_and_snapshot_is_public():
    """Expose a deterministic non-secret policy snapshot for both UIs."""
    assert allowed_openai_models("translation") == ("gpt-5.6-luna", "gpt-5.6-terra")
    assert default_openai_model("review") == "gpt-5.6-terra"
    snapshot = openai_policy_snapshot()
    assert snapshot["revision"] == "2026-09-01"
    assert snapshot["roles"]["embedding"]["dimensions"] == 384
