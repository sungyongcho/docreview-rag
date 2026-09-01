"""Dotenv-first application and release settings tests."""

from app.config import Settings
from app.release.config import ReleaseSettings


def test_dotenv_openai_key_wins_over_process_environment(monkeypatch, tmp_path):
    """Use the checkout dotenv key first while retaining environment fallback."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")

    application = Settings(_env_file=dotenv)
    release = ReleaseSettings(_env_file=dotenv)

    assert application.openai_api_key is not None
    assert application.openai_api_key.get_secret_value() == "dotenv-key"
    assert release.openai_api_key is not None
    assert release.openai_api_key.get_secret_value() == "dotenv-key"


def test_process_environment_remains_the_fallback_without_dotenv(monkeypatch, tmp_path):
    """Read the exported key when the selected dotenv file is absent."""
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    missing = tmp_path / "missing.env"

    settings = Settings(_env_file=missing)

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "process-key"
