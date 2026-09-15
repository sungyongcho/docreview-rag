"""Verify explicit mode command routing without using the user's services or data."""

from unittest.mock import Mock

import pytest

from scripts.stack import __main__ as stack, cli, fresh, quickstart


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_no_command_only_shows_help(mode, monkeypatch, capsys):
    """A bare mode command never creates or starts resources."""
    dispatch = Mock(side_effect=AssertionError("Help must not execute operations"))
    monkeypatch.setattr(cli, "dispatch", dispatch)
    assert cli.main([mode]) == 0
    assert f"rag-{mode}" in capsys.readouterr().out
    dispatch.assert_not_called()


@pytest.mark.parametrize(
    "values,expected",
    [
        (["prod", "status"], ["ps", "--all"]),
        (["dev", "stop"], ["stop"]),
        (["prod", "restart"], ["up", "-d", "--force-recreate"]),
        (["dev", "logs", "app", "-f", "--tail", "12"], ["logs", "--tail", "12", "--follow", "app"]),
        (["prod", "compose", "ps", "--all"], ["ps", "--all"]),
    ],
)
def test_lifecycle_commands_preserve_mode_and_arguments(values, expected, monkeypatch, tmp_path):
    """Restart enforces the desired mode instead of restarting an opposite-mode container."""
    run = Mock(return_value=0)
    monkeypatch.setattr(stack, "run", run)
    assert cli.main(values, root=tmp_path) == 0
    run.assert_called_once_with(values[0], expected, root=tmp_path)


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_start_uses_guided_non_destructive_setup(mode, monkeypatch, tmp_path):
    """Start selects its environment and does not request any reset."""
    start = Mock(return_value=0)
    monkeypatch.setattr(quickstart, "quickstart", start)
    assert cli.main([mode, "start", "--timeout", "45"], root=tmp_path) == 0
    start.assert_called_once_with(tmp_path, mode=mode, timeout=45)


@pytest.mark.parametrize(
    "values",
    [
        ["dev", "start", "--ready"],
        ["prod", "start", "--ready"],
        ["prod", "reset", "data", "--local"],
        ["dev", "reset", "environment", "--local"],
        ["dev", "reset", "data", "--local", "--all-modes"],
        ["prod", "corpus", "ingest_manifest"],
    ],
)
def test_unconnected_or_unsafe_operations_do_not_dispatch(values, monkeypatch, tmp_path):
    """Pending workflows and invalid scopes cannot silently restore, reset or start."""
    forbidden = Mock(side_effect=AssertionError("No mutation allowed"))
    monkeypatch.setattr(cli, "module", forbidden)
    monkeypatch.setattr(stack, "run", forbidden)
    monkeypatch.setattr(quickstart, "quickstart", forbidden)
    monkeypatch.setattr(fresh, "start_fresh", forbidden)
    assert cli.main(values, root=tmp_path) == 2
    forbidden.assert_not_called()


@pytest.mark.parametrize("action", ["prepare", "reset"])
def test_data_mutations_require_local_flag(action):
    """A missing locality choice fails in parsing, before service inspection."""
    values = ["prod", action] + (["environment", "--all-modes"] if action == "reset" else [])
    with pytest.raises(SystemExit) as error:
        cli.main(values)
    assert error.value.code == 2


def test_environment_reset_only_removes_runtime_and_never_starts(monkeypatch, tmp_path):
    """Both mode names route a whole-checkout reset with source and environment preservation."""
    reset = Mock(return_value=0)
    monkeypatch.setattr(fresh, "start_fresh", reset)
    assert cli.main(["prod", "reset", "environment", "--local", "--all-modes"], root=tmp_path) == 0
    reset.assert_called_once_with(tmp_path, no_start=True, runtime_only=True)


def test_data_reset_checks_actual_mode_and_stays_stopped(monkeypatch, tmp_path):
    """DEV data reset uses the existing stop-after-recreate operation, not quickstart."""
    guard = Mock()
    invoke = Mock(return_value=0)
    monkeypatch.setattr(cli, "require_running_mode", guard)
    monkeypatch.setattr(cli, "module", invoke)
    assert cli.main(["dev", "reset", "data", "--local", "--keep-sources"], root=tmp_path) == 0
    guard.assert_called_once_with(tmp_path, "dev")
    invoke.assert_called_once_with(tmp_path, "scripts.schema", ["recreate", "--keep-sources"])


def test_opposite_running_mode_blocks_data_reset(monkeypatch, tmp_path):
    """A DEV command cannot clear the shared database while PROD is running."""
    invoke = Mock()
    monkeypatch.setattr(cli, "module", invoke)
    monkeypatch.setattr(cli, "require_running_mode", Mock(side_effect=ValueError("Not DEV")))
    assert cli.main(["dev", "reset", "data", "--local"], root=tmp_path) == 2
    invoke.assert_not_called()


def test_dev_corpus_flags_are_passed_without_reinterpretation(monkeypatch, tmp_path):
    """Document selection remains literal when moved under the DEV root command."""
    invoke = Mock(return_value=0)
    monkeypatch.setattr(cli, "module", invoke)
    assert (
        cli.main(["dev", "corpus", "ingest_manifest", "--selection", "tutorial"], root=tmp_path)
        == 0
    )
    invoke.assert_called_once_with(
        tmp_path, "scripts.stack.commands", ["corpus", "ingest_manifest", "--selection", "tutorial"]
    )


@pytest.mark.parametrize("old_action", ["up", "down", "start-fresh", "start-quick"])
def test_retired_top_level_commands_are_not_forwarded(old_action):
    """Explicit command errors replace silent backward-compatible dispatch."""
    with pytest.raises(SystemExit) as error:
        cli.parser("dev").parse_args([old_action])
    assert error.value.code == 2
