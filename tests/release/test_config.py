"""Release configuration and cost-cap tests."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.release.config import ReleaseSettings
from tests.support import load_settings


def test_release_defaults_to_canned_without_provider_activation(monkeypatch) -> None:
    """Default to the offline read-only mode with the provider off and proxy headers untrusted,
    with a per-call cap that covers the largest default call."""
    for name in ("OPENAI_API_KEY", "DOCREVIEW_OPENAI_API_KEY", "OPENAI_API_KEY_LOCAL", "MODE"):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings(ReleaseSettings, env_file=None)

    assert settings.service_mode == "canned"
    assert settings.openai_api_key is None
    assert settings.openai_enabled is False
    assert settings.admin_mode == "readonly"
    assert settings.trust_proxy_headers is False
    budget = settings.provider_budget()
    largest_call = budget.pricing.estimate(budget.max_input_tokens, budget.max_output_tokens)
    assert largest_call <= budget.max_cost_usd


def test_canned_mode_keeps_the_provider_off_even_with_a_key(monkeypatch) -> None:
    """A configured key enables the provider only in the runtime mode and never renders."""
    secret = "sk-test-only"
    monkeypatch.setenv("OPENAI_API_KEY_LOCAL", secret)

    canned = load_settings(ReleaseSettings, env_file=None)
    runtime = load_settings(ReleaseSettings, service_mode="runtime", env_file=None)

    assert canned.openai_enabled is False
    assert runtime.openai_enabled is True
    assert secret not in repr(canned)
    assert secret not in repr(runtime)


def test_provider_budget_uses_explicit_caps_and_policy_prices() -> None:
    """Build explicit limits around the role-scoped policy price."""
    settings = load_settings(
        ReleaseSettings,
        env_file=None,
        openai_max_input_tokens=1_200,
        openai_max_output_tokens=300,
        openai_max_cost_usd=Decimal("0.01"),
    )

    budget = settings.provider_budget()

    assert budget.max_input_tokens == 1_200
    assert budget.max_output_tokens == 300
    assert budget.max_cost_usd == Decimal("0.01")
    assert budget.pricing.estimate(1_200, 300) == Decimal("0.0006")


@pytest.mark.parametrize(
    "values",
    [
        {"rate_limit_per_minute": 11, "rate_limit_per_day": 10},
        {"host": " "},
        {"openai_model": " "},
    ],
)
def test_invalid_release_settings_fail_closed(values) -> None:
    """Refuse a setting outside its range instead of falling back to a default."""
    with pytest.raises(ValidationError):
        load_settings(ReleaseSettings, env_file=None, **values)


def test_live_admin_requires_runtime_and_loopback() -> None:
    """Refuse a callable administrator surface on canned or remotely bound deployments."""
    with pytest.raises(ValidationError, match="DOCREVIEW_MODE=runtime"):
        load_settings(ReleaseSettings, env_file=None, admin_mode="live", host="127.0.0.1")
    with pytest.raises(ValidationError, match="loopback"):
        load_settings(
            ReleaseSettings,
            env_file=None,
            service_mode="runtime",
            admin_mode="live",
            host="0.0.0.0",
        )

    settings = load_settings(
        ReleaseSettings,
        env_file=None,
        service_mode="runtime",
        admin_mode="live",
        host="127.0.0.1",
    )

    assert settings.admin_mode == "live"


def test_admin_cors_origin_is_loopback_only() -> None:
    """Allow the tunneled local Next dev server but reject public browser origins."""
    settings = load_settings(
        ReleaseSettings,
        env_file=None,
        admin_cors_origin="http://127.0.0.1:3000",
    )

    assert settings.admin_cors_origin == "http://127.0.0.1:3000"
    with pytest.raises(ValidationError, match="loopback"):
        load_settings(ReleaseSettings, env_file=None, admin_cors_origin="https://sungyongcho.com")


def test_local_budgets_accept_blank_compose_substitutions(monkeypatch) -> None:
    """`${LOCAL_LLM_TIMEOUT_S:-}` reaches the app as an empty string, not as an absent key."""
    monkeypatch.delenv("MODE", raising=False)

    settings = load_settings(
        ReleaseSettings,
        env_file=None,
        LOCAL_LLM_TIMEOUT_S="",
        LOCAL_LLM_MAX_INPUT_TOKENS="",
        LOCAL_LLM_MAX_OUTPUT_TOKENS="",
    )

    assert settings.local_llm_timeout_s == 120.0
    assert settings.local_llm_max_input_tokens == 12_000
    assert settings.local_llm_max_output_tokens == 600


def test_production_requires_luna_but_retains_explicit_dev_terra() -> None:
    """A stale model override cannot silently spend Terra prices on the public server."""
    with pytest.raises(ValidationError, match="production text calls require gpt-5.6-luna"):
        load_settings(
            ReleaseSettings,
            env_file=None,
            environment="prod",
            openai_model="gpt-5.6-terra",
        )
    dev = load_settings(
        ReleaseSettings, env_file=None, environment="dev", openai_model="gpt-5.6-terra"
    )
    assert dev.provider_budget().pricing.output_per_million_usd == Decimal("12.00")
