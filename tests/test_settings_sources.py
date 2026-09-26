"""Dotenv-first application and release settings tests."""

import pytest

from app.config import Settings
from app.release.config import ReleaseSettings
from tests.support import load_settings


@pytest.mark.parametrize("settings_type", [Settings, ReleaseSettings])
def test_explicit_provider_settings_survive_revalidation(settings_type):
    """An explicit prod selection keeps its credential and blocks local inference."""
    values = {
        "environment": "prod",
        "openai_api_key_dev": "unused-local-key",
        "openai_api_key_prod": "selected-prod-key",
        "local_llm_base_url": "http://configured-model:11434",
    }
    if settings_type is ReleaseSettings:
        values["service_mode"] = "runtime"
    settings = load_settings(settings_type, env_file=None, **values)
    restored = load_settings(settings_type, env_file=None, **settings.model_dump())
    for current in (settings, restored):
        assert current.environment == "prod"
        assert current.openai_api_key is not None
        assert current.openai_api_key.get_secret_value() == "selected-prod-key"
        assert current.openai_key_slot == "prod"
        assert current.local_llm_enabled is False
        if isinstance(current, ReleaseSettings):
            assert current.openai_enabled is True


def test_process_environment_remains_the_fallback_without_dotenv(monkeypatch, tmp_path):
    """Read the exported key when the selected dotenv file is absent."""
    monkeypatch.setenv("OPENAI_API_KEY_LOCAL", "process-key")
    missing = tmp_path / "missing.env"

    settings = load_settings(Settings, env_file=missing)

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "process-key"


def test_mode_selects_the_environment_key_slot(monkeypatch, tmp_path):
    """Read the dev slot by default and the prod slot under MODE=prod, naming the slot."""
    monkeypatch.delenv("OPENAI_API_KEY_LOCAL", raising=False)
    slots = "OPENAI_API_KEY_LOCAL=dev-key\nOPENAI_API_KEY_PROD=prod-key\n"
    dotenv = tmp_path / ".env"
    dotenv.write_text(slots, encoding="utf-8")
    prod_dotenv = tmp_path / "prod.env"
    prod_dotenv.write_text(f"MODE=prod\n{slots}", encoding="utf-8")

    dev = load_settings(Settings, env_file=dotenv)
    prod = load_settings(Settings, env_file=prod_dotenv)
    release_dev = load_settings(ReleaseSettings, env_file=dotenv)
    release_prod = load_settings(ReleaseSettings, env_file=prod_dotenv)

    assert dev.openai_api_key is not None
    assert dev.openai_api_key.get_secret_value() == "dev-key"
    assert dev.openai_key_slot == "dev"
    assert prod.openai_api_key is not None
    assert prod.openai_api_key.get_secret_value() == "prod-key"
    assert prod.openai_key_slot == "prod"
    assert release_dev.openai_key_slot == "dev"
    assert release_prod.openai_key_slot == "prod"


def test_generic_keys_are_ignored_and_slots_never_cross_environments(monkeypatch, tmp_path):
    """Old generic credentials cannot override MODE or serve as a missing-slot fallback."""
    for name in ("OPENAI_API_KEY_LOCAL", "OPENAI_API_KEY_DEV", "OPENAI_API_KEY_PROD", "MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-process")
    monkeypatch.setenv("DOCREVIEW_OPENAI_API_KEY", "legacy-release")
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=legacy-file\nOPENAI_API_KEY_LOCAL=dev-key\n")
    for settings_type in (Settings, ReleaseSettings):
        monkeypatch.setenv("MODE", "dev")
        dev = load_settings(settings_type, env_file=dotenv)
        monkeypatch.setenv("MODE", "prod")
        prod = load_settings(settings_type, env_file=dotenv)
        assert dev.openai_api_key is not None
        assert dev.openai_api_key.get_secret_value() == "dev-key"
        assert dev.openai_key_slot == "dev"
        assert prod.openai_api_key is None
        assert prod.openai_key_slot is None


def test_runtime_settings_disable_the_local_engine_under_prod(monkeypatch, tmp_path):
    """Use MODE to disable local inference while preserving the configured endpoint."""
    for name in ("LOCAL_LLM_BASE_URL", "MODE"):
        monkeypatch.delenv(name, raising=False)
    pair = "LOCAL_LLM_BASE_URL=http://ollama:11434\n"
    dev = tmp_path / "dev.env"
    dev.write_text(f"MODE=dev\n{pair}", encoding="utf-8")
    prod = tmp_path / "prod.env"
    prod.write_text(f"MODE=prod\n{pair}", encoding="utf-8")

    assert load_settings(Settings, env_file=dev).local_llm_enabled is True
    disabled = load_settings(Settings, env_file=prod)
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
        "OPENAI_API_KEY_PROD=dotenv-secret\n"
    )
    monkeypatch.setenv("MODE", "prod")
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("DOCREVIEW_ADMIN_MODE", "readonly")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://process:11435")
    monkeypatch.setenv("LOCAL_LLM_PROTOCOL", "openai_responses")
    monkeypatch.setenv("OPENAI_API_KEY_PROD", "process-secret")
    for settings_type in (Settings, ReleaseSettings):
        settings = load_settings(settings_type, env_file=env_file)
        assert settings.environment == "prod"
        assert settings.local_llm_base_url == "https://process:11435"
        assert settings.local_llm_protocol == "openai_responses"
        assert settings.local_llm_source == "environment"
        assert settings.openai_api_key is not None
        assert settings.openai_api_key.get_secret_value() == "dotenv-secret"
    release = load_settings(ReleaseSettings, env_file=env_file)
    assert release.service_mode == "runtime"
    assert release.admin_mode == "readonly"


def test_local_endpoint_default_and_dotenv_provenance(tmp_path, monkeypatch):
    """Host execution has the standard Ollama default and records a supplied dotenv URL."""
    from app.config import Settings
    from app.release.config import ReleaseSettings

    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LOCAL_LLM_BASE_URL=http://dotenv:11434\n")
    for settings_type in (Settings, ReleaseSettings):
        default = load_settings(settings_type, env_file=None)
        assert default.local_llm_base_url == "http://127.0.0.1:11434"
        assert default.local_llm_source == "default"
        dotenv = load_settings(settings_type, env_file=env_file)
        assert dotenv.local_llm_base_url == "http://dotenv:11434"
        assert dotenv.local_llm_source == "dotenv"
