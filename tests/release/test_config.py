"""Release configuration and cost-cap tests."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.release.config import ReleaseSettings


def test_release_defaults_to_canned_without_provider_activation(monkeypatch) -> None:
    """Default to the offline mode with ingestion, proxy trust and the provider all off."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCREVIEW_OPENAI_API_KEY", raising=False)

    settings = ReleaseSettings()

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
    ) == Decimal("0.00576")
    assert Decimal("0.00576") <= budget.max_cost_usd


def test_operator_key_is_secret_and_only_enables_explicit_runtime(monkeypatch) -> None:
    """Enable the provider only in the runtime mode, keeping the key out of every rendering."""
    secret = "sk-test-server-only"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    canned = ReleaseSettings()
    runtime = ReleaseSettings(mode="runtime")

    assert canned.openai_enabled is False
    assert runtime.openai_enabled is True
    assert runtime.openai_api_key is not None
    assert runtime.openai_api_key.get_secret_value() == secret
    assert secret not in repr(runtime)
    assert secret not in str(runtime)


def test_provider_budget_uses_all_explicit_release_caps() -> None:
    """Build the budget from the declared caps rather than any implicit default."""
    settings = ReleaseSettings(
        openai_max_input_tokens=1_200,
        openai_max_output_tokens=300,
        openai_max_cost_usd=Decimal("0.005"),
        openai_input_per_million_usd=Decimal("0.40"),
        openai_output_per_million_usd=Decimal("1.60"),
    )

    budget = settings.provider_budget()

    assert budget.max_input_tokens == 1_200
    assert budget.max_output_tokens == 300
    assert budget.max_cost_usd == Decimal("0.005")
    assert budget.pricing.estimate(1_200, 300) == Decimal("0.00096")


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
        ReleaseSettings(**values)


def test_live_admin_requires_runtime_and_loopback() -> None:
    """Refuse a callable administrator surface on canned or remotely bound deployments."""
    with pytest.raises(ValidationError, match="DOCREVIEW_MODE=runtime"):
        ReleaseSettings(admin_mode="live", host="127.0.0.1")
    with pytest.raises(ValidationError, match="loopback"):
        ReleaseSettings(mode="runtime", admin_mode="live", host="0.0.0.0")

    settings = ReleaseSettings(mode="runtime", admin_mode="live", host="127.0.0.1")

    assert settings.admin_mode == "live"


def test_admin_cors_origin_is_loopback_only() -> None:
    """Allow the tunneled local Next dev server but reject public browser origins."""
    settings = ReleaseSettings(admin_cors_origin="http://127.0.0.1:3000")

    assert settings.admin_cors_origin == "http://127.0.0.1:3000"
    with pytest.raises(ValidationError, match="loopback"):
        ReleaseSettings(admin_cors_origin="https://sungyongcho.com")
