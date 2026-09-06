"""Canned-default release application and runtime composition tests."""

from fastapi.testclient import TestClient

from app.llm import DeterministicLLMProvider, RawProviderResponse
from app.release.app import build_runtime_services, create_release_app
from app.release.config import ReleaseSettings


def test_release_app_is_canned_healthy_and_nonsecret(monkeypatch) -> None:
    secret = "sk-must-not-render"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    with TestClient(create_release_app()) as client:
        health = client.get("/health")
        release = client.get("/release")
        home = client.get("/")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "mode": "canned"}
    assert release.status_code == 200
    assert release.json()["openai_enabled"] is False
    assert release.json()["key_persisted"] is False
    assert release.json()["max_cost_usd"] == "0.01"
    assert secret not in release.text
    assert home.status_code == 200
    assert "Document Review Evidence Demo" in home.text


def test_release_app_blocks_ingest_and_rate_limits_post_requests() -> None:
    settings = ReleaseSettings(rate_limit_per_minute=1, rate_limit_per_day=1)
    request = {"query": "What revenue was reported?", "k": 1, "filters": {}}

    with TestClient(create_release_app(settings)) as client:
        ingest = client.post("/ingest", json={})
        unavailable = client.post("/retrieve", json=request)
        limited = client.post("/retrieve", json=request)

    assert ingest.status_code == 403
    assert ingest.headers["x-content-type-options"] == "nosniff"
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "service_unavailable"
    assert limited.status_code == 429
    assert limited.headers["x-content-type-options"] == "nosniff"


def test_runtime_composition_passes_key_only_to_provider_and_redaction(monkeypatch) -> None:
    secret = "sk-runtime-only"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    captured: dict[str, str] = {}

    def provider_factory(*, model_name: str, api_key: str):
        captured["model_name"] = model_name
        captured["api_key"] = api_key
        return DeterministicLLMProvider(
            [RawProviderResponse(output_text="{}", input_tokens=0, output_tokens=0)]
        )

    services = build_runtime_services(
        ReleaseSettings(mode="runtime"),
        provider_factory=provider_factory,
    )

    assert captured == {"model_name": "gpt-4.1-mini", "api_key": secret}
    assert services._secret_values == (secret,)
    assert secret not in repr(services)


def test_runtime_without_key_keeps_review_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCREVIEW_OPENAI_API_KEY", raising=False)

    services = build_runtime_services(ReleaseSettings(mode="runtime"))

    assert services._llm_provider is None
    assert services._provider_budget is None
