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
        ready = client.get("/ready")
        home = client.get("/")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "mode": "canned"}
    assert release.status_code == 200
    assert release.json()["openai_enabled"] is False
    assert release.json()["admin_mode"] == "readonly"
    assert release.json()["key_persisted"] is False
    assert release.json()["max_cost_usd"] == "0.04"
    assert ready.status_code == 200
    assert ready.json()["corpus"]["availability"] == "not_applicable"
    assert ready.json()["models"]["agent"]["default"] == "gpt-5.6-terra"
    assert secret not in release.text
    assert home.status_code == 200
    assert "Evidence-first SEC and DART filing review" in home.text
    assert release.json()["frontend"] == "next-static"


def test_runtime_readiness_returns_typed_200_or_503_without_provider_calls(monkeypatch) -> None:
    """Separate live corpus readiness from provider availability and liveness."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def ready_probe():
        """Return one compatible populated corpus snapshot."""
        return {
            "status": {
                "database_connected": True,
                "schema_status": "compatible",
                "schema_message": "compatible",
                "documents": 2,
                "chunks": 20,
                "embedded_chunks": 20,
                "pending_embeddings": 0,
                "bm25_ready": True,
                "writable": True,
            }
        }

    async def degraded_probe():
        """Return schema drift without mutating the database."""
        return {
            "status": {
                "database_connected": True,
                "schema_status": "drifted",
                "schema_message": "traces is missing columns",
                "documents": 0,
                "chunks": 0,
                "embedded_chunks": 0,
                "pending_embeddings": 0,
                "bm25_ready": False,
                "writable": False,
            }
        }

    settings = ReleaseSettings(mode="runtime", host="127.0.0.1", _env_file=None)
    with TestClient(
        create_release_app(
            settings,
            services=RuntimeApiServices(),
            readiness_probe=ready_probe,
        )
    ) as client:
        ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["review_enabled"] is False

    with TestClient(
        create_release_app(
            settings,
            services=RuntimeApiServices(),
            readiness_probe=degraded_probe,
        )
    ) as client:
        degraded = client.get("/ready")
    assert degraded.status_code == 503
    assert degraded.json()["status"] == "degraded"
    assert degraded.json()["corpus"]["schema_status"] == "drifted"


def test_release_app_blocks_ingest_and_rate_limits_post_requests() -> None:
    """Block ingestion, refuse an unconfigured review, and rate limit, all with headers set."""
    settings = ReleaseSettings(
        _env_file=None,
        rate_limit_per_minute=1,
        rate_limit_per_day=1,
    )
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
        ReleaseSettings(mode="runtime", _env_file=None),
        provider_factory=provider_factory,
    )

    assert captured == {"model_name": "gpt-5.6-terra", "api_key": secret}
    assert services._secret_values == (secret,)
    assert secret not in repr(services)


def test_runtime_without_key_keeps_review_fail_closed(monkeypatch) -> None:
    """Leave the provider and its budget unset when no key was configured."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCREVIEW_OPENAI_API_KEY", raising=False)

    services = build_runtime_services(ReleaseSettings(mode="runtime", _env_file=None))

    assert services._llm_provider is None
    assert services._provider_budget is None


def test_release_admin_modes_hide_or_enable_the_local_surface() -> None:
    """Expose administrator routes only in explicit loopback live mode."""
    with TestClient(
        create_release_app(ReleaseSettings(admin_mode="off", _env_file=None))
    ) as client:
        hidden_paths = set(client.get("/openapi.json").json()["paths"])

    live_settings = ReleaseSettings(
        mode="runtime",
        admin_mode="live",
        host="127.0.0.1",
        _env_file=None,
    )
    with TestClient(create_release_app(live_settings, services=RuntimeApiServices())) as client:
        live_paths = set(client.get("/openapi.json").json()["paths"])

    assert not any(path.startswith("/admin") for path in hidden_paths)
    assert "/admin/corpus" in live_paths
    assert "/admin/evaluations/runs" in live_paths


def test_live_operator_disables_only_public_request_limits() -> None:
    """Wire loopback live mode without public rate or daily-cost enforcement."""
    settings = ReleaseSettings(
        mode="runtime",
        admin_mode="live",
        host="127.0.0.1",
        _env_file=None,
    )
    application = create_release_app(settings, services=RuntimeApiServices())
    guard = next(
        middleware
        for middleware in application.user_middleware
        if middleware.cls is ReleaseGuardMiddleware
    )

    assert guard.kwargs["enforce_rate_limit"] is False
    assert guard.kwargs["cost_limiter"] is None
    assert guard.kwargs["allow_ingest"] is False


def test_capabilities_and_limit_peek_reflect_release_mode_without_consuming_slots() -> None:
    """Expose mode controls and inspect allowance without spending it."""
    settings = ReleaseSettings(
        rate_limit_per_minute=2,
        rate_limit_per_day=3,
        _env_file=None,
    )
    with TestClient(create_release_app(settings)) as client:
        capabilities = client.get("/capabilities")
        first = client.get("/limits")
        second = client.get("/limits")

    assert capabilities.json()["can_edit_prompt_policy"] is False
    assert capabilities.json()["can_compare_published_snapshots"] is True
    assert first.json()["remaining_minute"] == 2
    assert second.json()["remaining_day"] == 3
    assert first.json()["retry_after_seconds"] == 0
    assert first.json()["minute_reset_seconds"] == 0
    assert first.json()["day_reset_seconds"] == 0
    assert first.json()["daily_cost_reset_at_utc"].endswith(("Z", "+00:00"))


def test_live_capabilities_enable_developer_controls() -> None:
    """Enable experiment controls only on explicit loopback live mode."""
    settings = ReleaseSettings(
        mode="runtime",
        admin_mode="live",
        host="127.0.0.1",
        _env_file=None,
    )
    with TestClient(create_release_app(settings, services=RuntimeApiServices())) as client:
        capabilities = client.get("/capabilities").json()

    assert capabilities["can_edit_prompt_policy"] is True
    assert capabilities["can_run_evaluation"] is True
