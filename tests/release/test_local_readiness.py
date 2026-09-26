"""Readiness for the optional local engine, including the production kill switch."""

import asyncio

import httpx
import pytest

from app.llm.local.connection import LocalConnectionManager
from app.release.config import ReleaseSettings
from app.release.status import _local_engine_readiness
from tests.support import load_settings


def settings_for(monkeypatch: pytest.MonkeyPatch, environment: str) -> ReleaseSettings:
    """Build runtime settings using only a server URL under the given MODE."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    monkeypatch.setenv("MODE", environment)
    return load_settings(
        ReleaseSettings,
        env_file=None,
        LOCAL_LLM_BASE_URL="http://ollama:11434",
    )


@pytest.mark.parametrize(
    ("environment", "public_request", "reason"),
    [
        ("prod", False, "disabled_in_prod"),
        ("prod", True, "disabled_in_prod"),
        ("dev", True, "public_surface"),
    ],
)
def test_public_readiness_never_probes_a_local_endpoint(
    monkeypatch, tmp_path, environment, public_request, reason
) -> None:
    """PROD and proxy-marked DEV requests refuse discovery even with an enabled connection."""

    def refuse(request: httpx.Request) -> httpx.Response:
        """Fail if a public request reaches any local inventory endpoint."""
        raise AssertionError("a public request probed the local model endpoint")

    connection = LocalConnectionManager(
        initial_base_url="http://ollama:11434",
        path=tmp_path / "connection.json",
        transport=httpx.MockTransport(refuse),
    )
    result = asyncio.run(
        _local_engine_readiness(
            settings_for(monkeypatch, environment), connection, public_request=public_request
        )
    )

    assert result == {"enabled": False, "reason": reason}


def test_development_probes_and_reports_the_model_it_found(monkeypatch, tmp_path) -> None:
    """A development build asks the host which models it actually holds."""

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Expose installed model metadata through the native discovery endpoints."""
        seen.append(str(request.url))
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        return httpx.Response(200, json={"models": [{"name": "gemma4:e4b"}]})

    connection = LocalConnectionManager(
        initial_base_url="http://ollama:11434",
        path=tmp_path / "connection.json",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(_local_engine_readiness(settings_for(monkeypatch, "dev"), connection))

    assert result["enabled"] is True
    assert result["model"] == "gemma4:e4b"
    assert result["protocol"] == "ollama"
    assert result["checked_at"]
    models = result["models"]
    assert isinstance(models, tuple)
    assert models[0]["capabilities"] == ("completion",)
    assert set(seen) == {
        "http://ollama:11434/api/tags",
        "http://ollama:11434/api/show",
        "http://ollama:11434/api/ps",
    }
