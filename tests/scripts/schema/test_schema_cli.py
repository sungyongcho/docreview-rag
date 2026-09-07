"""The schema package CLI keeps help offline and targets only its checkout database."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.schema import __main__ as command


def test_help_does_not_load_configuration_or_connect(monkeypatch, capsys):
    """Printing the consolidated command guide cannot read local configuration or touch data."""
    forbidden = Mock(side_effect=AssertionError("help must be read-only"))
    monkeypatch.setattr("sys.argv", ["scripts.schema", "--help"])
    monkeypatch.setattr(command, "load_local_environment", forbidden)
    monkeypatch.setattr(command, "schema_status", forbidden)
    with pytest.raises(SystemExit) as exit_status:
        command.main()
    assert exit_status.value.code == 0
    assert "{check,prepare,recover,recreate}" in capsys.readouterr().out
    forbidden.assert_not_called()


@pytest.mark.parametrize("action", ["check", "prepare"])
def test_schema_action_uses_the_checkout_port(monkeypatch, capsys, action):
    """Both actions retain the local-only target after moving the entry point one level deeper."""
    root = Path(__file__).resolve().parents[3]
    environment = Mock(return_value={"DB_PORT": "38432"})
    inspect = AsyncMock(return_value={"schema_status": "compatible", "created": False})
    monkeypatch.setattr("sys.argv", ["scripts.schema", action])
    monkeypatch.setenv("DATABASE_URL", "postgresql://external.example/never-touch")
    monkeypatch.setattr(command, "load_local_environment", environment)
    monkeypatch.setattr(command, "schema_status", inspect)
    assert command.main() == 0
    environment.assert_called_once_with(root / ".env", mode="dev")
    inspect.assert_awaited_once_with(
        "postgresql+asyncpg://filing:filing@127.0.0.1:38432/filing", prepare=action == "prepare"
    )
    assert "127.0.0.1:38432/filing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "outcome,expected", [("cancelled", 0), ("succeeded", 0), ("incomplete", 1)]
)
def test_recreate_cli_maps_explicit_outcomes_without_planning_restart(
    monkeypatch, outcome, expected
):
    """Standalone schema recreation distinguishes partial failure and leaves restart to the user."""
    from scripts.schema import recreate

    root = Path(__file__).resolve().parents[3]
    run = Mock(return_value=outcome)
    forbidden = Mock(side_effect=AssertionError("no secondary schema operation"))
    monkeypatch.setattr("sys.argv", ["scripts.schema", "recreate", "--keep-sources"])
    monkeypatch.setattr(recreate, "run", run)
    monkeypatch.setattr(command, "load_local_environment", forbidden)
    monkeypatch.setattr(command, "schema_status", forbidden)
    assert command.main() == expected
    run.assert_called_once_with(root, keep_sources=True, sample=False)
    forbidden.assert_not_called()
