"""Readiness for the optional local engine, including the production kill switch."""

import asyncio

import httpx
import pytest

from app.llm.local_inventory import LocalModelInventory
from app.release.app import _local_engine_readiness
from app.release.config import ReleaseSettings


def settings_for(monkeypatch: pytest.MonkeyPatch, environment: str) -> ReleaseSettings:
    """Build runtime settings using only a server URL under the given MODE."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("MODE", environment)
    return ReleaseSettings(
        _env_file=None,
        LOCAL_LLM_BASE_URL="http://ollama:11434",
    )


def test_production_names_the_reason_and_never_probes_the_endpoint(monkeypatch) -> None:
    """A published build must not reach out to a model host it is forbidden to use."""

    def refuse(*args: object, **kwargs: object) -> None:
        """Fail if production attempts any local inventory request."""
        raise AssertionError("a production build probed the local model endpoint")

    monkeypatch.setattr(httpx.AsyncClient, "get", refuse)

    result = asyncio.run(_local_engine_readiness(settings_for(monkeypatch, "prod")))

    assert result == {"enabled": False, "reason": "disabled_in_prod"}


def test_production_blocks_the_default_endpoint(monkeypatch) -> None:
    """Production does not probe even when the local endpoint now has a default."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("MODE", "prod")

    result = asyncio.run(_local_engine_readiness(ReleaseSettings(_env_file=None)))

    assert result == {"enabled": False, "reason": "disabled_in_prod"}


def test_development_probes_and_reports_the_model_it_found(monkeypatch) -> None:
    """A development build asks the host which models it actually holds."""

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Expose installed model metadata through the native discovery endpoints."""
        seen.append(str(request.url))
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        return httpx.Response(200, json={"models": [{"name": "gemma4:e4b"}]})

    inventory = LocalModelInventory(
        base_url="http://ollama:11434", transport=httpx.MockTransport(handler)
    )
    result = asyncio.run(_local_engine_readiness(settings_for(monkeypatch, "dev"), inventory))

    assert result["enabled"] is True
    assert result["model"] == "gemma4:e4b"
    assert result["protocol"] == "ollama"
    assert result["checked_at"]
    assert result["models"][0]["capabilities"] == ("completion",)
    assert set(seen) == {
        "http://ollama:11434/api/tags",
        "http://ollama:11434/api/show",
        "http://ollama:11434/api/ps",
    }
