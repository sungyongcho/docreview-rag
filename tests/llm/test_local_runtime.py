"""Local connection and zero-cost budget composition shared by both entry points."""

from decimal import Decimal

import pytest

from app.llm.local_runtime import build_local_runtime


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_local_runtime_only_provisions_a_budget_in_dev(environment, tmp_path, monkeypatch):
    """Preserve endpoint identity and local token limits without enabling production discovery."""
    monkeypatch.chdir(tmp_path)
    connection, budget = build_local_runtime(
        environment=environment,
        base_url="http://local-model:11434",
        protocol="ollama",
        source="environment",
        api_key="test-local-key",
        max_input_tokens=2048,
        max_output_tokens=256,
    )
    assert connection.enabled is (environment == "dev")
    if environment == "prod":
        assert budget is None
        assert connection.current.inventory is None
        assert connection.current.source == "disabled"
    else:
        assert connection.current.base_url == "http://local-model:11434"
        assert connection.current.source == "environment"
        inventory = connection.current.inventory
        assert inventory is not None
        assert inventory.protocol == "ollama"
        assert inventory.api_key == "test-local-key"
        assert budget is not None
        assert budget.max_input_tokens == 2048
        assert budget.max_output_tokens == 256
        assert budget.max_cost_usd == Decimal("0")
