"""Host-facing local launcher environment validation."""

from pathlib import Path

import pytest

from scripts.local_env import DEFAULTS, LocalEnvironmentError, load_local_environment


def _environment(tmp_path: Path, text: str = "", *, mode: str = "dev") -> dict[str, str]:
    """Write one isolated dotenv contract and load it."""
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return load_local_environment(path, mode=mode)


def test_defaults_are_complete_and_loopback_bound(tmp_path: Path) -> None:
    """Use the documented defaults when no dotenv values are present."""
    assert _environment(tmp_path) == DEFAULTS | {"MODE": "dev"}
    assert DEFAULTS["DOCREVIEW_LOCAL_HOST"] == "127.0.0.1"


def test_custom_dev_ports_and_host_are_preserved(tmp_path: Path) -> None:
    """Accept distinct custom host-facing values without coercing their text form."""
    values = _environment(
        tmp_path,
        "MODE=dev\nDOCREVIEW_LOCAL_HOST=localhost\nDB_PORT=15432\nAPP_PORT=18080\n"
        "DOCREVIEW_OPERATOR_WEB_PORT=13000\nDOCREVIEW_OPERATOR_PORT=18001\n",
    )

    assert values["DOCREVIEW_LOCAL_HOST"] == "localhost"
    assert values["DB_PORT"] == "15432"
    assert values["APP_PORT"] == "18080"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("DOCREVIEW_LOCAL_HOST=review.example.com\n", "must be an IP address or localhost"),
        ("APP_PORT=abc\n", "must be an integer"),
        ("APP_PORT=70000\n", "must be in 1..65535"),
        ("APP_PORT=5432\n", "host port collision"),
    ],
)
def test_invalid_mode_host_port_and_collision_fail_before_launch(
    tmp_path: Path, text: str, message: str
) -> None:
    """Reject every unsafe launcher contract before Compose can be invoked."""
    with pytest.raises(LocalEnvironmentError, match=message):
        _environment(tmp_path, text)


def test_prod_ignores_inactive_operator_port_collisions(tmp_path: Path) -> None:
    """Validate only bindings started together by the selected local mode."""
    values = _environment(
        tmp_path,
        "MODE=dev\nDOCREVIEW_OPERATOR_PORT=5432\n",
        mode="prod",
    )

    assert values["MODE"] == "prod"


def test_command_mode_ignores_dotenv_and_inherited_mode(tmp_path, monkeypatch) -> None:
    """Only the explicit launcher mode controls permissions and active bindings."""
    monkeypatch.setenv("MODE", "preview")
    assert _environment(tmp_path, "MODE=prod\n")["MODE"] == "dev"
    assert _environment(tmp_path, "MODE=dev\n", mode="prod")["MODE"] == "prod"
    with pytest.raises(LocalEnvironmentError, match="mode must be"):
        _environment(tmp_path, mode="preview")
