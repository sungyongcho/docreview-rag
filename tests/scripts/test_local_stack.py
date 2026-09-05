"""Explicit mode selection and host lifecycle coordination."""

from unittest.mock import Mock

import pytest

from scripts.local_env import LocalEnvironmentError
from scripts.local_stack import compose_command, compose_environment, run


def test_selected_mode_overrides_stale_flags_and_keeps_other_environment(monkeypatch) -> None:
    """Inherited settings cannot select permissions or route requests to another API."""
    monkeypatch.setenv("MODE", "dev")
    monkeypatch.setenv("DOCREVIEW_ADMIN_MODE", "live")
    monkeypatch.setenv("NEXT_PUBLIC_ADMIN_MODE", "live")
    monkeypatch.setenv("COMPOSE_FILE", "unrelated.yml")
    monkeypatch.setenv("OPENAI_API_KEY", "test-existing-explicit-key")
    environment = compose_environment("prod", {"MODE": "prod"})
    assert environment["MODE"] == "prod"
    assert environment["DOCREVIEW_ADMIN_MODE"] == "readonly"
    assert environment["NEXT_PUBLIC_ADMIN_MODE"] == "canned"
    assert environment["NEXT_PUBLIC_API_BASE_URL"] == "/docreview-rag-agent/api"
    assert environment["OPENAI_API_KEY"] == "test-existing-explicit-key"
    assert "COMPOSE_FILE" not in environment
    assert environment["NEXT_PUBLIC_OPERATOR_TOKEN"] == ""


def test_compose_arguments_target_the_repository_from_another_directory(tmp_path) -> None:
    """Explicit files and project directory prevent aliases from affecting another stack."""
    command = compose_command(tmp_path, "prod", ["logs", "-f"])
    assert command[command.index("--project-directory") + 1] == str(tmp_path)
    assert str(tmp_path / "docker-compose.prod.yml") in command
    assert command[-2:] == ["logs", "-f"]


def test_prod_start_stops_owned_operations_before_compose(tmp_path, monkeypatch) -> None:
    """A public preview cannot retain a host Operations token or server."""
    events = []
    operator = Mock()
    operator.stop.side_effect = lambda: events.append("stop")
    monkeypatch.setattr("scripts.local_stack.LocalOperator", lambda root: operator)
    execute = Mock(
        side_effect=lambda *args, **kwargs: events.append("compose") or Mock(returncode=0)
    )
    monkeypatch.setattr("scripts.local_stack.subprocess.run", execute)
    assert run("prod", ["up", "-d"], root=tmp_path) == 0
    assert events == ["stop", "compose"]
    assert execute.call_args.kwargs["env"]["NEXT_PUBLIC_OPERATOR_TOKEN"] == ""
    operator.start.assert_not_called()


def test_failed_detached_start_cleans_up_only_new_operations(tmp_path, monkeypatch) -> None:
    """A failing Compose start does not leave its newly launched host daemon running."""
    operator = Mock()
    operator.environment.return_value = {"NEXT_PUBLIC_OPERATOR_TOKEN": ""}
    operator.start.return_value = {"NEXT_PUBLIC_OPERATOR_TOKEN": "new-test-token"}
    monkeypatch.setattr("scripts.local_stack.LocalOperator", lambda root: operator)
    monkeypatch.setattr("scripts.local_stack.subprocess.run", Mock(return_value=Mock(returncode=1)))
    assert run("dev", ["up", "-d"], root=tmp_path) == 1
    operator.stop.assert_called_once()


def test_down_wrapper_never_deletes_volumes(tmp_path) -> None:
    """The convenience command cannot silently remove the corpus database volume."""
    with pytest.raises(LocalEnvironmentError, match="preserves data"):
        run("dev", ["down", "-v"], root=tmp_path)
