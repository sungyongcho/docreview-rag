"""Role-scoped OpenAI model policy: resolution, allowlist enforcement and the public snapshot."""

import pytest

from app.openai_models import (
    _ALLOWED,
    _DEFAULTS,
    POLICY_REVISION,
    OpenAIModelPolicyError,
    openai_policy_snapshot,
    resolve_openai_model,
)


def test_resolution_uses_the_role_default_and_prices_the_selected_model():
    """An omitted model resolves to the role default, and each model carries its own price."""
    for role, default in _DEFAULTS.items():
        implicit = resolve_openai_model(role)
        explicit = resolve_openai_model(role, f"  {default}  ")
        assert implicit == explicit
        assert implicit.model == default
    luna = resolve_openai_model("review", "gpt-5.6-luna")
    terra = resolve_openai_model("review", "gpt-5.6-terra")
    assert terra.pricing.output_per_million_usd > luna.pricing.output_per_million_usd
    assert resolve_openai_model("embedding").dimensions == 384
    assert all(
        resolve_openai_model(role).dimensions is None for role in _DEFAULTS if role != "embedding"
    )


@pytest.mark.parametrize(
    "model",
    [
        pytest.param("gpt-5.6-sol", id="sibling-outside-the-allowlist"),
        pytest.param("", id="blank-selection"),
    ],
)
def test_policy_rejects_models_outside_the_role_allowlist(model):
    """Reject a sibling model outside the allowlist and a blank selection before any client."""
    with pytest.raises(OpenAIModelPolicyError, match="allowed"):
        resolve_openai_model("agent", model)


def test_snapshot_mirrors_the_resolved_policy_for_every_role():
    """The public snapshot is a projection of the resolver, so the UIs can never drift from it."""
    snapshot = openai_policy_snapshot()

    roles = snapshot["roles"]
    assert snapshot["revision"] == POLICY_REVISION
    assert isinstance(roles, dict)
    assert set(roles) == set(_DEFAULTS)
    for role, projected in roles.items():
        selection = resolve_openai_model(role)
        assert projected == {
            "default": selection.model,
            "allowed": list(_ALLOWED[role]),
            "reasoning_effort": selection.reasoning_effort,
            "dimensions": selection.dimensions,
        }
