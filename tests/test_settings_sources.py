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


def test_mode_selects_the_environment_key_slot(monkeypatch, tmp_path):
    """Read the dev slot by default and the prod slot under MODE=prod, naming the slot."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    slots = "OPENAI_API_KEY_LOCAL=dev-key\nOPENAI_API_KEY_PROD=prod-key\n"
    dotenv = tmp_path / ".env"
    dotenv.write_text(slots, encoding="utf-8")
    prod_dotenv = tmp_path / "prod.env"
    prod_dotenv.write_text(f"MODE=prod\n{slots}", encoding="utf-8")

    dev = Settings(_env_file=dotenv)
    prod = Settings(_env_file=prod_dotenv)
    release_dev = ReleaseSettings(_env_file=dotenv)
    release_prod = ReleaseSettings(_env_file=prod_dotenv)

    assert dev.openai_api_key is not None
    assert dev.openai_api_key.get_secret_value() == "dev-key"
    assert dev.openai_key_slot == "dev"
    assert prod.openai_api_key is not None
    assert prod.openai_api_key.get_secret_value() == "prod-key"
    assert prod.openai_key_slot == "prod"
    assert release_dev.openai_key_slot == "dev"
    assert release_prod.openai_key_slot == "prod"


def test_explicit_key_wins_and_blank_explicit_falls_back_to_the_slot(monkeypatch, tmp_path):
    """Prefer an explicit key over the slot and treat a blank explicit key as unset."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "OPENAI_API_KEY=explicit-key\nOPENAI_API_KEY_LOCAL=dev-key\n", encoding="utf-8"
    )
    blank = tmp_path / "blank.env"
    blank.write_text("OPENAI_API_KEY=\nOPENAI_API_KEY_LOCAL=dev-key\n", encoding="utf-8")
    empty = tmp_path / "empty.env"
    empty.write_text("MODE=prod\nOPENAI_API_KEY_LOCAL=dev-key\n", encoding="utf-8")

    explicit = ReleaseSettings(_env_file=dotenv)
    fallback = ReleaseSettings(_env_file=blank)
    unmatched = Settings(_env_file=empty)

    assert explicit.openai_api_key is not None
    assert explicit.openai_api_key.get_secret_value() == "explicit-key"
    assert explicit.openai_key_slot == "explicit"
    assert fallback.openai_api_key is not None
    assert fallback.openai_api_key.get_secret_value() == "dev-key"
    assert fallback.openai_key_slot == "dev"
    assert unmatched.openai_api_key is None
    assert unmatched.openai_key_slot is None


def test_runtime_settings_disable_the_local_engine_under_prod(monkeypatch, tmp_path):
    """Use MODE to disable local inference while preserving the configured endpoint."""
    for name in ("LOCAL_LLM_BASE_URL", "MODE"):
        monkeypatch.delenv(name, raising=False)
    pair = "LOCAL_LLM_BASE_URL=http://ollama:11434\n"
    dev = tmp_path / "dev.env"
    dev.write_text(f"MODE=dev\n{pair}", encoding="utf-8")
    prod = tmp_path / "prod.env"
    prod.write_text(f"MODE=prod\n{pair}", encoding="utf-8")

    assert Settings(_env_file=dev).local_llm_enabled is True
    disabled = Settings(_env_file=prod)
    assert disabled.local_llm_enabled is False
    assert disabled.local_llm_base_url == "http://ollama:11434"


def test_process_mode_and_connection_override_dotenv_without_changing_key_order(
    tmp_path, monkeypatch
):
    """Command controls and endpoints win over stale dotenv while OpenAI stays dotenv-first."""
    from app.config import Settings
    from app.release.config import ReleaseSettings

    env_file = tmp_path / ".env"
    env_file.write_text(
        "MODE=dev\nDOCREVIEW_MODE=canned\nDOCREVIEW_ADMIN_MODE=live\n"
        "LOCAL_LLM_BASE_URL=http://dotenv:11434\nLOCAL_LLM_PROTOCOL=ollama\n"
        "OPENAI_API_KEY=dotenv-secret\n"
    )
    monkeypatch.setenv("MODE", "prod")
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("DOCREVIEW_ADMIN_MODE", "readonly")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://process:11435")
    monkeypatch.setenv("LOCAL_LLM_PROTOCOL", "openai_responses")
    monkeypatch.setenv("OPENAI_API_KEY", "process-secret")
    for settings_type in (Settings, ReleaseSettings):
        settings = settings_type(_env_file=env_file)
        assert settings.environment == "prod"
        assert settings.local_llm_base_url == "https://process:11435"
        assert settings.local_llm_protocol == "openai_responses"
        assert settings.local_llm_source == "environment"
        assert settings.openai_api_key.get_secret_value() == "dotenv-secret"
    release = ReleaseSettings(_env_file=env_file)
    assert release.mode == "runtime"
    assert release.admin_mode == "readonly"


def test_local_endpoint_default_and_dotenv_provenance(tmp_path, monkeypatch):
    """Host execution has the standard Ollama default and records a supplied dotenv URL."""
    from app.config import Settings
    from app.release.config import ReleaseSettings

    for key in ("LOCAL_LLM_BASE_URL", "DOCREVIEW_LOCAL_LLM_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LOCAL_LLM_BASE_URL=http://dotenv:11434\n")
    for settings_type in (Settings, ReleaseSettings):
        default = settings_type(_env_file=None)
        assert default.local_llm_base_url == "http://127.0.0.1:11434"
        assert default.local_llm_source == "default"
        dotenv = settings_type(_env_file=env_file)
        assert dotenv.local_llm_base_url == "http://dotenv:11434"
        assert dotenv.local_llm_source == "dotenv"
