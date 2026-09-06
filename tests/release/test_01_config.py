"""Release configuration and cost-cap tests."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.release.config import ReleaseSettings


def test_release_defaults_to_canned_without_provider_activation(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCREVIEW_OPENAI_API_KEY", raising=False)

    settings = ReleaseSettings()

    assert settings.mode == "canned"
    assert settings.openai_api_key is None
    assert settings.openai_enabled is False
    assert settings.allow_ingest is False
    assert settings.trust_proxy_headers is False
    budget = settings.provider_budget()
    assert budget.pricing.estimate(
        budget.max_input_tokens,
        budget.max_output_tokens,
    ) == Decimal("0.00576")
    assert Decimal("0.00576") <= budget.max_cost_usd


def test_operator_key_is_secret_and_only_enables_explicit_runtime(monkeypatch) -> None:
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
    with pytest.raises(ValidationError):
        ReleaseSettings(**values)
