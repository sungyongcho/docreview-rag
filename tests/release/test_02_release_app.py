"""Canned-default release application and runtime composition tests."""

from fastapi.testclient import TestClient

from app.api.runtime import RuntimeApiServices
from app.llm.provider import DeterministicLLMProvider
from app.llm.schemas import RawProviderResponse
from app.release.app import build_runtime_services, create_release_app
from app.release.config import ReleaseSettings
from app.release.middleware import ReleaseGuardMiddleware


def test_release_app_is_canned_healthy_and_nonsecret(monkeypatch, tmp_path) -> None:
    """Serve the offline mode with its limits published and no secret in the response."""
    secret = "sk-must-not-render"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    (tmp_path / "index.html").write_text(
        "<title>DocReview</title><p>Evidence-first SEC and DART filing review</p>",
        encoding="utf-8",
    )

    with TestClient(create_release_app(static_dir=tmp_path)) as client:
        health = client.get("/health")
        release = client.get("/release")
        home = client.get("/")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "mode": "canned"}
    assert release.status_code == 200
    assert release.json()["openai_enabled"] is False
    assert release.json()["admin_mode"] == "readonly"
    assert release.json()["key_persisted"] is False
    assert release.json()["max_cost_usd"] == "0.01"
    assert secret not in release.text
    assert home.status_code == 200
    assert "Evidence-first SEC and DART filing review" in home.text
    assert release.json()["frontend"] == "next-static"


def test_release_app_blocks_ingest_and_rate_limits_post_requests() -> None:
    """Block ingestion, refuse an unconfigured review, and rate limit, all with headers set."""
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
    """Give the key to the provider and the redaction list, and nowhere else."""
    secret = "sk-runtime-only"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    captured: dict[str, str] = {}

    def provider_factory(*, model_name: str, api_key: str):
        """Capture the arguments the provider was built with."""
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
    """Leave the provider and its budget unset when no key was configured."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCREVIEW_OPENAI_API_KEY", raising=False)

    services = build_runtime_services(ReleaseSettings(mode="runtime"))

    assert services._llm_provider is None
    assert services._provider_budget is None


def test_release_admin_modes_hide_or_enable_the_local_surface() -> None:
    """Expose administrator routes only in explicit loopback live mode."""
    with TestClient(create_release_app(ReleaseSettings(admin_mode="off"))) as client:
        hidden_paths = set(client.get("/openapi.json").json()["paths"])

    live_settings = ReleaseSettings(mode="runtime", admin_mode="live", host="127.0.0.1")
    with TestClient(create_release_app(live_settings, services=RuntimeApiServices())) as client:
        live_paths = set(client.get("/openapi.json").json()["paths"])

    assert not any(path.startswith("/admin") for path in hidden_paths)
    assert "/admin/corpus" in live_paths
    assert "/admin/evaluations/runs" in live_paths


def test_live_operator_disables_only_public_request_limits() -> None:
    """Wire loopback live mode without public rate or daily-cost enforcement."""
    settings = ReleaseSettings(mode="runtime", admin_mode="live", host="127.0.0.1")
    application = create_release_app(settings, services=RuntimeApiServices())
    guard = next(
        middleware
        for middleware in application.user_middleware
        if middleware.cls is ReleaseGuardMiddleware
    )

    assert guard.kwargs["enforce_rate_limit"] is False
    assert guard.kwargs["cost_limiter"] is None
    assert guard.kwargs["allow_ingest"] is False
