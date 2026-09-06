"""Readiness for the optional local engine, including the production kill switch."""

import asyncio

import httpx
import pytest

from app.release.app import _local_engine_readiness
from app.release.config import ReleaseSettings


def settings_for(monkeypatch: pytest.MonkeyPatch, environment: str) -> ReleaseSettings:
    """Build runtime settings with a complete local pair under the given MODE."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("MODE", environment)
    return ReleaseSettings(
        _env_file=None,
        LOCAL_LLM_BASE_URL="http://ollama:11434",
        LOCAL_LLM_MODEL="gemma4:e4b",
    )


def test_production_names_the_reason_and_never_probes_the_endpoint(monkeypatch) -> None:
    """A published build must not reach out to a model host it is forbidden to use."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a production build probed the local model endpoint")

    monkeypatch.setattr(httpx.AsyncClient, "get", refuse)

    result = asyncio.run(_local_engine_readiness(settings_for(monkeypatch, "prod")))

    assert result == {"enabled": False, "reason": "disabled_in_prod"}


def test_an_unconfigured_build_reports_the_original_reason(monkeypatch) -> None:
    """Absent configuration keeps saying so; the production reason is a separate state."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("MODE", "prod")

    result = asyncio.run(_local_engine_readiness(ReleaseSettings(_env_file=None)))

    assert result == {"enabled": False, "reason": "not_configured"}


def test_development_probes_and_reports_the_model_it_found(monkeypatch) -> None:
    """A development build asks the host which models it actually holds."""

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"models": [{"name": "gemma4:e4b"}]})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient.__init__

    def with_transport(self: httpx.AsyncClient, **kwargs: object) -> None:
        original(self, transport=transport, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", with_transport)

    result = asyncio.run(_local_engine_readiness(settings_for(monkeypatch, "dev")))

    assert result == {"enabled": True, "model": "gemma4:e4b", "protocol": "ollama"}
    assert seen == ["http://ollama:11434/api/tags"]
