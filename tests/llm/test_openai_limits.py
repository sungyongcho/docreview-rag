"""Persisted per-call caps that never exceed the deploy-time ceiling."""

import asyncio
from decimal import Decimal
import json
import stat

import pytest

from app.llm.openai_limits import CEILING_ENV_KEYS, OpenAILimitsError, OpenAILimitsManager
from app.llm.schemas import ProviderBudget, TokenPricing


def ceiling() -> ProviderBudget:
    """Build the .env-derived cap that bounds every saved value."""
    return ProviderBudget(
        max_input_tokens=12_000,
        max_output_tokens=600,
        max_cost_usd=Decimal("0.04"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("1"), output_per_million_usd=Decimal("2")
        ),
    )


def test_saved_caps_survive_restart_and_reset_restores_the_ceiling(tmp_path) -> None:
    """A lower working value persists across managers; reset deletes it again."""
    path = tmp_path / "local-settings/openai-limits.json"
    manager = OpenAILimitsManager(ceiling(), path=path)
    assert manager.state().source == "ceiling"
    saved = asyncio.run(
        manager.save(max_input_tokens=8_000, max_output_tokens=300, max_cost_usd=Decimal("0.01"))
    )
    assert saved.source == "saved"
    assert saved.max_output_tokens == 300
    assert saved.ceiling_max_output_tokens == 600
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert json.loads(path.read_text()) == {
        "version": 1,
        "max_input_tokens": 8_000,
        "max_output_tokens": 300,
        "max_cost_usd": "0.01",
    }
    restarted = OpenAILimitsManager(ceiling(), path=path)
    assert restarted.effective().max_input_tokens == 8_000
    assert restarted.effective().max_cost_usd == Decimal("0.01")
    assert restarted.effective().pricing == ceiling().pricing
    reset = asyncio.run(restarted.reset())
    assert reset.source == "ceiling"
    assert not path.exists()
    assert restarted.effective() == ceiling()


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_input_tokens", 12_001), ("max_output_tokens", 601), ("max_cost_usd", Decimal("0.05"))],
)
def test_values_above_the_ceiling_are_refused_and_name_the_env_key(tmp_path, field, value) -> None:
    """The web can only lower a cap; the message tells where the ceiling is raised."""
    manager = OpenAILimitsManager(ceiling(), path=tmp_path / "openai-limits.json")
    values = {"max_input_tokens": 1_000, "max_output_tokens": 100, "max_cost_usd": Decimal("0.01")}
    values[field] = value
    with pytest.raises(OpenAILimitsError, match=CEILING_ENV_KEYS[field]) as error:
        asyncio.run(manager.save(**values))
    assert error.value.code == "openai_limits_above_ceiling"
    assert manager.effective() == ceiling()
    assert not (tmp_path / "openai-limits.json").exists()


def test_corrupt_or_excessive_file_falls_back_to_the_ceiling(tmp_path) -> None:
    """Editing the file by hand cannot raise a cap or break startup."""
    path = tmp_path / "openai-limits.json"
    path.write_text("{not json")
    invalid = OpenAILimitsManager(ceiling(), path=path)
    assert invalid.state().source == "invalid"
    assert invalid.effective() == ceiling()
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "max_input_tokens": 50_000,
                "max_output_tokens": 100,
                "max_cost_usd": "0.01",
            }
        )
    )
    excessive = OpenAILimitsManager(ceiling(), path=path)
    assert excessive.state().source == "invalid"
    assert CEILING_ENV_KEYS["max_input_tokens"] in (excessive.state().error or "")
    assert excessive.effective() == ceiling()


def test_production_never_reads_the_file_or_accepts_edits(tmp_path) -> None:
    """Production keeps the ceiling even when a lower saved file exists."""
    path = tmp_path / "openai-limits.json"
    path.write_text(
        json.dumps(
            {"version": 1, "max_input_tokens": 100, "max_output_tokens": 10, "max_cost_usd": "0.01"}
        )
    )
    manager = OpenAILimitsManager(ceiling(), path=path, enabled=False)
    assert manager.effective() == ceiling()
    assert manager.state().editable is False
    with pytest.raises(OpenAILimitsError, match="only in Dev"):
        asyncio.run(
            manager.save(max_input_tokens=100, max_output_tokens=10, max_cost_usd=Decimal("0.01"))
        )


def test_unwritable_directory_keeps_the_active_caps(tmp_path) -> None:
    """A failed save leaves the previous effective budget untouched."""
    manager = OpenAILimitsManager(ceiling(), path=tmp_path / "openai-limits.json")
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(OpenAILimitsError, match="not writable"):
            asyncio.run(
                manager.save(
                    max_input_tokens=100, max_output_tokens=10, max_cost_usd=Decimal("0.01")
                )
            )
    finally:
        tmp_path.chmod(0o700)
    assert manager.effective() == ceiling()
    assert manager.state().source == "ceiling"
