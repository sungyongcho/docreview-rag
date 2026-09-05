"""Release configuration and cost-cap tests."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.release.config import ReleaseSettings


def test_release_defaults_to_canned_without_provider_activation(monkeypatch) -> None:
    """Default to the offline mode with ingestion, proxy trust and the provider all off."""
    for name in ("OPENAI_API_KEY", "DOCREVIEW_OPENAI_API_KEY", "OPENAI_API_KEY_LOCAL", "MODE"):
        monkeypatch.delenv(name, raising=False)

    settings = ReleaseSettings(_env_file=None)

    assert settings.mode == "canned"
    assert settings.openai_api_key is None
    assert settings.openai_enabled is False
    assert settings.allow_ingest is False
    assert settings.admin_mode == "readonly"
    assert settings.rate_limit_per_minute == 5
    assert settings.rate_limit_per_day == 25
    assert settings.public_daily_cost_usd == Decimal("1.00")
    assert settings.trust_proxy_headers is False
    budget = settings.provider_budget()
    assert budget.pricing.estimate(
        budget.max_input_tokens,
        budget.max_output_tokens,
    ) == Decimal("0.0312")
    assert Decimal("0.0312") <= budget.max_cost_usd


def test_operator_key_is_secret_and_only_enables_explicit_runtime(monkeypatch) -> None:
    """Enable the provider only in the runtime mode, keeping the key out of every rendering."""
    secret = "sk-test-server-only"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    canned = ReleaseSettings(_env_file=None)
    runtime = ReleaseSettings(mode="runtime", _env_file=None)

    assert canned.openai_enabled is False
    assert runtime.openai_enabled is True
    assert runtime.openai_api_key is not None
    assert runtime.openai_api_key.get_secret_value() == secret
    assert secret not in repr(runtime)
    assert secret not in str(runtime)


def test_environment_slot_enables_runtime_without_an_explicit_key(monkeypatch) -> None:
    """Enable the provider from the MODE-selected slot and report the slot, not the key."""
    secret = "sk-dev-slot-only"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCREVIEW_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_PROD", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY_LOCAL", secret)

    dev = ReleaseSettings(mode="runtime", _env_file=None)
    monkeypatch.setenv("MODE", "prod")
    prod = ReleaseSettings(mode="runtime", _env_file=None)

    assert dev.openai_enabled is True
    assert dev.openai_key_slot == "dev"
    assert dev.openai_api_key is not None
    assert dev.openai_api_key.get_secret_value() == secret
    assert secret not in repr(dev)
    assert prod.openai_enabled is False
    assert prod.openai_key_slot is None


def test_provider_budget_uses_explicit_caps_and_policy_prices() -> None:
    """Build explicit limits around the role-scoped policy price."""
    settings = ReleaseSettings(
        _env_file=None,
        openai_max_input_tokens=1_200,
        openai_max_output_tokens=300,
        openai_max_cost_usd=Decimal("0.01"),
    )

    budget = settings.provider_budget()

    assert budget.max_input_tokens == 1_200
    assert budget.max_output_tokens == 300
    assert budget.max_cost_usd == Decimal("0.01")
    assert budget.pricing.estimate(1_200, 300) == Decimal("0.006")


def test_manual_release_prices_are_rejected() -> None:
    """Fail rather than silently diverging from the model policy price."""
    with pytest.raises(ValidationError, match="policy owns prices"):
        ReleaseSettings(_env_file=None, openai_input_per_million_usd=Decimal("0.40"))


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
        ReleaseSettings(_env_file=None, **values)


def test_live_admin_requires_runtime_and_loopback() -> None:
    """Refuse a callable administrator surface on canned or remotely bound deployments."""
    with pytest.raises(ValidationError, match="DOCREVIEW_MODE=runtime"):
        ReleaseSettings(_env_file=None, admin_mode="live", host="127.0.0.1")
    with pytest.raises(ValidationError, match="loopback"):
        ReleaseSettings(
            _env_file=None,
            mode="runtime",
            admin_mode="live",
            host="0.0.0.0",
        )

    settings = ReleaseSettings(
        _env_file=None,
        mode="runtime",
        admin_mode="live",
        host="127.0.0.1",
    )

    assert settings.admin_mode == "live"


def test_admin_cors_origin_is_loopback_only() -> None:
    """Allow the tunneled local Next dev server but reject public browser origins."""
    settings = ReleaseSettings(
        _env_file=None,
        admin_cors_origin="http://127.0.0.1:3000",
    )

    assert settings.admin_cors_origin == "http://127.0.0.1:3000"
    with pytest.raises(ValidationError, match="loopback"):
        ReleaseSettings(_env_file=None, admin_cors_origin="https://sungyongcho.com")


def test_prod_disables_the_local_engine_even_with_a_complete_endpoint_pair(monkeypatch) -> None:
    """Disable local models in production without rejecting retained developer settings."""
    for name in ("OPENAI_API_KEY", "DOCREVIEW_OPENAI_API_KEY", "OPENAI_API_KEY_LOCAL"):
        monkeypatch.delenv(name, raising=False)
    # `mode` resolves through its DOCREVIEW_ alias, so it has to arrive as an env var.
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    local = {"LOCAL_LLM_BASE_URL": "http://ollama:11434"}

    monkeypatch.setenv("MODE", "dev")
    assert ReleaseSettings(_env_file=None, **local).local_llm_enabled is True

    monkeypatch.setenv("MODE", "prod")
    prod = ReleaseSettings(_env_file=None, **local)
    assert prod.local_llm_enabled is False
    assert prod.local_llm_base_url == "http://ollama:11434"


def test_local_budgets_accept_blank_compose_substitutions(monkeypatch) -> None:
    """`${LOCAL_LLM_TIMEOUT_S:-}` reaches the app as an empty string, not as an absent key."""
    monkeypatch.delenv("MODE", raising=False)

    settings = ReleaseSettings(
        _env_file=None,
        LOCAL_LLM_TIMEOUT_S="",
        LOCAL_LLM_MAX_INPUT_TOKENS="",
        LOCAL_LLM_MAX_OUTPUT_TOKENS="",
    )

    assert settings.local_llm_timeout_s == 120.0
    assert settings.local_llm_max_input_tokens == 12_000
    assert settings.local_llm_max_output_tokens == 600
