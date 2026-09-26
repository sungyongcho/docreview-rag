"""Canned-default release application and runtime composition tests."""

from dataclasses import asdict
from decimal import Decimal
from typing import cast

from fastapi.testclient import TestClient
import pytest

from app.api.deps import get_api_services
from app.api.review_profile import PromptPolicy, ServerBM25
from app.api.runtime import RuntimeApiServices
from app.corpus_admin import CorpusStatus, RuntimeCorpusAdminService
from app.llm.schemas import RawProviderResponse
from app.observability.types import RunReport, build_run_report
from app.release.ai_allowance import SharedAIAllowance, reserve_openai
from app.release.app import build_runtime_services, create_release_app
from app.release.config import ReleaseSettings
from app.release.middleware import ReleaseGuardMiddleware
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingClient,
    OpenAIEmbeddingProvider,
)
from app.workflow.types import WorkflowReport
from tests.llm.support import DeterministicLLMProvider


def _run_report() -> RunReport:
    """Build one terminal report the synchronous review route can project."""
    report = WorkflowReport(
        label="NOT_IN_DOCS",
        answer="NOT_IN_DOCS",
        citations=(),
        rationale="No evidence.",
        reasons=(),
    )
    return build_run_report(
        run_id="run-metered",
        status="ok",
        total_time_seconds=0.0,
        system_prompt="Use only filing evidence.",
        node_path=("retrieve",),
        steps=(),
        report=report.model_dump(mode="json"),
    )


def _guard_kwargs(app) -> dict[str, object]:
    """Return the keyword arguments the release app handed to its request guard."""
    guard = next(
        middleware for middleware in app.user_middleware if middleware.cls is ReleaseGuardMiddleware
    )
    return guard.kwargs


class _MeteredReview:
    """Stand in for the runtime with reviews that reserve through the provider hook."""

    def __init__(self, calls_per_review: int, amount: Decimal) -> None:
        self.calls_per_review = calls_per_review
        self.amount = amount
        self.calls = 0

    async def review(self, request, on_node=None):
        """Reserve one provider call at a time, skipping the ``free`` query entirely."""
        if request.query != "free":
            for _ in range(self.calls_per_review):
                await reserve_openai(self.amount)
                self.calls += 1
        return _run_report()


def test_release_app_is_canned_healthy_and_nonsecret(monkeypatch, tmp_path) -> None:
    """Serve the offline mode with its limits published and no secret in the response."""
    secret = "sk-must-not-render"
    monkeypatch.setenv("OPENAI_API_KEY_LOCAL", secret)
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
    assert release.json()["max_cost_usd"] == "0.005"
    assert ready.status_code == 200
    assert ready.json()["corpus"]["availability"] == "not_applicable"
    assert ready.json()["models"]["agent"]["default"] == "gpt-5.6-luna"
    assert secret not in release.text
    assert home.status_code == 200
    assert "Evidence-first SEC and DART filing review" in home.text
    assert release.json()["frontend"] == "next-static"


@pytest.mark.parametrize(
    "environment,admin_mode,headers,public,ready",
    [
        ("prod", "readonly", {}, True, True),
        ("prod", "readonly", {}, True, False),
        ("dev", "readonly", {}, True, True),
        ("dev", "live", {"x-docreview-public": "true"}, True, True),
        ("dev", "live", {}, False, True),
    ],
)
def test_public_readiness_publishes_counts_and_withholds_only_write_access(
    environment, admin_mode, headers, public, ready
) -> None:
    """Public views receive corpus totals and health evidence; only write access stays private."""
    status = {
        "database_connected": True,
        "schema_status": "compatible" if ready else "drifted",
        "schema_message": "Schema fixture",
        "documents": 30,
        "chunks": 900,
        "embedded_chunks": 900 if ready else 800,
        "pending_embeddings": 0 if ready else 100,
        "bm25_ready": ready,
        "writable": True,
    }

    async def probe():
        """Supply private corpus status without accessing a database or provider."""
        return {"status": status, "documents": [{"issuer_name": "PRIVATE_COMPANY_FIXTURE"}]}

    settings = ReleaseSettings(
        _env_file=None,
        DOCREVIEW_ENVIRONMENT=environment,
        admin_mode=admin_mode,
        mode="runtime",
        host="127.0.0.1",
    )
    with TestClient(
        create_release_app(
            settings,
            services=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
            readiness_probe=probe,
        )
    ) as client:
        response = client.get("/ready", headers=headers)
    assert response.status_code == (200 if ready else 503)
    payload = response.json()
    assert payload["status"] == ("ready" if ready else "degraded")
    corpus = payload["corpus"]
    assert corpus["writable"] == (None if public else status["writable"])
    for field in (
        "documents",
        "chunks",
        "embedded_chunks",
        "pending_embeddings",
        "database_connected",
        "schema_status",
        "schema_message",
        "bm25_ready",
    ):
        assert corpus[field] == status[field]
    assert corpus["availability"] == ("ready" if ready else "degraded")
    assert "PRIVATE_COMPANY_FIXTURE" not in response.text


def test_canned_mode_refuses_an_unconfigured_review_with_headers_set(monkeypatch, tmp_path) -> None:
    """Answer a provider route with a typed 503 and the security headers when no runtime exists."""
    monkeypatch.chdir(tmp_path)
    request = {"query": "What revenue was reported?", "k": 1, "filters": {}}

    with TestClient(create_release_app(ReleaseSettings())) as client:
        unavailable = client.post("/retrieve", json=request)

    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "service_unavailable"
    assert unavailable.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("mode", "environment"),
    [("canned", "dev"), ("runtime", "dev"), ("runtime", "prod")],
)
def test_every_mode_guards_with_the_shared_allowance(
    monkeypatch, tmp_path, mode, environment
) -> None:
    """Build one allowance type in every mode so metering cannot differ between them."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODE", environment)
    settings = ReleaseSettings(mode=mode, host="127.0.0.1")
    services = (
        RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())
        if mode == "runtime"
        else None
    )

    kwargs = _guard_kwargs(create_release_app(settings, services=services))

    assert isinstance(kwargs["allowance"], SharedAIAllowance)
    assert kwargs["allowance"].path == settings.public_allowance_path


def test_public_review_meters_every_provider_call_against_the_day_cap(
    monkeypatch, tmp_path
) -> None:
    """Charge each actual provider call of one admitted review to the UTC-day cost cap."""
    monkeypatch.chdir(tmp_path)
    settings = ReleaseSettings(
        mode="runtime",
        public_daily_cost_usd=Decimal("0.03"),
        openai_max_cost_usd=Decimal("0.01"),
    )
    app = create_release_app(
        settings, services=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())
    )
    review = _MeteredReview(calls_per_review=3, amount=Decimal("0.01"))
    app.dependency_overrides[get_api_services] = lambda: review

    with TestClient(app) as client:
        first = client.post("/review", json={"query": "What was revenue?"})
        calls_after_first = review.calls
        limits = client.get("/limits").json()
        second = client.post("/review", json={"query": "What was revenue?"})

    assert first.status_code == 200
    assert calls_after_first == 3
    assert Decimal(limits["remaining_daily_cost_usd"]) == 0
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "daily_cost_limit"
    assert review.calls * review.amount <= settings.public_daily_cost_usd


def test_public_ai_routes_are_rate_limited_while_exempt_requests_pass(
    monkeypatch, tmp_path
) -> None:
    """Rate limit public provider-bearing requests, leaving the operator and free work alone."""
    monkeypatch.chdir(tmp_path)
    settings = ReleaseSettings(
        mode="runtime",
        admin_mode="live",
        host="127.0.0.1",
        rate_limit_per_minute=1,
        rate_limit_per_day=1,
    )
    app = create_release_app(
        settings, services=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())
    )
    app.dependency_overrides[get_api_services] = lambda: _MeteredReview(1, Decimal("0.001"))
    public = {"x-docreview-public": "true"}
    metered = {"query": "What was revenue?"}

    with TestClient(app) as client:
        private = [client.post("/review", json=metered) for _ in range(2)]
        free = client.post("/review", json={"query": "free"}, headers=public)
        untouched = client.get("/limits", headers=public).json()
        admitted = client.post("/review", json=metered, headers=public)
        denied = client.post("/review", json=metered, headers=public)
        free_after = client.post("/review", json={"query": "free"}, headers=public)
        private_after = client.post("/review", json=metered)

    assert [response.status_code for response in private] == [200, 200]
    assert all("x-ratelimit-remaining-minute" not in response.headers for response in private)
    assert free.status_code == 200
    assert "x-ratelimit-remaining-minute" not in free.headers
    assert untouched["remaining_minute"] == 1
    assert admitted.status_code == 200
    assert admitted.headers["x-ratelimit-remaining-minute"] == "0"
    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "rate_limited"
    assert int(denied.headers["retry-after"]) > 0
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert free_after.status_code == 200
    assert private_after.status_code == 200


def test_runtime_composition_passes_key_only_to_provider_and_redaction(monkeypatch) -> None:
    """Give the key to the provider and the redaction list, and nowhere else."""
    secret = "sk-runtime-only"
    monkeypatch.setenv("OPENAI_API_KEY_LOCAL", secret)
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

    assert captured == {"model_name": "gpt-5.6-luna", "api_key": secret}
    assert services._secret_values == (secret,)
    assert secret not in repr(services)


def test_runtime_without_key_keeps_review_fail_closed(monkeypatch, tmp_path) -> None:
    """Leave the provider and its budget unset when no key was configured."""
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_API_KEY", "DOCREVIEW_OPENAI_API_KEY", "OPENAI_API_KEY_LOCAL", "MODE"):
        monkeypatch.delenv(name, raising=False)

    services = build_runtime_services(ReleaseSettings(mode="runtime", _env_file=None))

    assert "openai" not in services._llm_providers
    assert "openai" not in services._provider_budgets


def test_runtime_composition_serves_the_configured_bm25_settings(monkeypatch, tmp_path) -> None:
    """Hand BM25_* settings to the served runtime and keep the built-in defaults otherwise."""
    monkeypatch.chdir(tmp_path)
    for name in ("BM25_K1", "BM25_B", "BM25_IDF"):
        monkeypatch.delenv(name, raising=False)
    default = build_runtime_services(ReleaseSettings(mode="runtime"))
    monkeypatch.setenv("BM25_K1", "1.6")
    monkeypatch.setenv("BM25_B", "0.5")
    monkeypatch.setenv("BM25_IDF", "robertson")
    configured = build_runtime_services(ReleaseSettings(mode="runtime"))

    assert default.bm25_parameters == ServerBM25(1.2, 0.75, "lucene")
    assert configured.bm25_parameters == ServerBM25(1.6, 0.5, "robertson")


def test_release_admin_modes_hide_or_enable_the_local_surface() -> None:
    """Expose administrator routes and developer controls, and lift only the public request
    limits, in explicit loopback live mode."""
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
    live = create_release_app(
        live_settings,
        services=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
    )
    guard = _guard_kwargs(live)
    with TestClient(live) as client:
        live_paths = set(client.get("/openapi.json").json()["paths"])
        capabilities = client.get("/capabilities").json()

    assert not any(path.startswith("/admin") for path in hidden_paths)
    assert "/admin/corpus" in live_paths
    assert "/admin/evaluations/runs" in live_paths
    assert capabilities["can_edit_prompt_policy"] is True
    assert capabilities["can_run_evaluation"] is True
    assert guard["enforce_rate_limit"] is False
    assert isinstance(guard["allowance"], SharedAIAllowance)
    assert guard["public_read_only"] is False


def test_capabilities_and_limit_peek_reflect_release_mode_without_consuming_slots() -> None:
    """Expose mode controls, the public policy and the allowance without spending it."""
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
    assert capabilities.json()["can_change_custom_retrieval"] is True
    assert capabilities.json()["can_compare_published_snapshots"] is True
    assert first.json()["prompt_policy"] == PromptPolicy().model_dump(mode="json")
    assert first.json()["per_call"]["editable"] is False
    assert first.json()["remaining_minute"] == 2
    assert second.json()["remaining_day"] == 3
    assert first.json()["retry_after_seconds"] == 0
    assert first.json()["minute_reset_seconds"] == 0
    assert first.json()["day_reset_seconds"] == 0
    assert first.json()["daily_cost_reset_at_utc"].endswith(("Z", "+00:00"))


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_release_uses_configured_embedding_identity_and_credential_slot(
    monkeypatch, tmp_path, environment
) -> None:
    """Use the indexed provider identity and the release's explicit credential slot."""
    import app.release.app as release_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("MODE", environment)
    selected = OpenAIEmbeddingProvider(client=cast(EmbeddingClient, object()))
    captured = {}

    def embedding_factory(settings):
        """Capture composition without submitting an embedding request."""
        captured["provider"] = settings.embedding_provider
        captured["model"] = settings.embedding_model
        captured["key"] = settings.openai_api_key.get_secret_value()
        return selected

    monkeypatch.setattr(release_app, "get_embedding_provider", embedding_factory)
    services = build_runtime_services(
        ReleaseSettings(
            mode="runtime",
            MODE=environment,
            OPENAI_API_KEY_LOCAL="sk-development-fixture",
            OPENAI_API_KEY_PROD="sk-production-fixture",
            _env_file=None,
        )
    )

    assert services.embedding_provider is selected
    assert captured == {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "key": "sk-development-fixture" if environment == "dev" else "sk-production-fixture",
    }
    # Review calls must record the same slot as embeddings, not "unknown".
    assert services._credential_slot == environment


def test_runtime_readiness_default_probe_shares_admin_status_and_keeps_the_payload(
    monkeypatch,
) -> None:
    """The default probe reads the memoized administrator status, matches an injected probe,
    and reports corpus readiness separately from provider availability."""
    for name in ("OPENAI_API_KEY", "OPENAI_API_KEY_LOCAL", "OPENAI_API_KEY_DEV", "MODE"):
        monkeypatch.delenv(name, raising=False)
    status = CorpusStatus(
        database_connected=True,
        schema_status="compatible",
        schema_message="compatible",
        documents=2,
        chunks=20,
        embedded_chunks=20,
        pending_embeddings=0,
        bm25_ready=True,
        writable=True,
        provider="deterministic",
    )
    ages: list[float] = []

    async def fake_status(self, *, max_age_s: float = 0.0) -> CorpusStatus:
        """Serve the fixed status and record the reuse window the caller allowed."""
        ages.append(max_age_s)
        return status

    monkeypatch.setattr(RuntimeCorpusAdminService, "status", fake_status)

    async def injected_probe():
        """Return the same status through the injection seam."""
        return {"status": asdict(status)}

    settings = ReleaseSettings(mode="runtime", admin_mode="live", host="127.0.0.1", _env_file=None)
    with TestClient(
        create_release_app(
            settings,
            services=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
        )
    ) as client:
        default = client.get("/ready")
    with TestClient(
        create_release_app(
            settings,
            services=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
            readiness_probe=injected_probe,
        )
    ) as client:
        injected = client.get("/ready")

    assert ages == [2.0]
    assert default.status_code == injected.status_code == 200
    assert default.text == injected.text
    assert default.json()["status"] == "ready"
    assert default.json()["review_enabled"] is False
    assert default.json()["review_engines"]["openai"]["key_slot"] is None


def test_bm25_missing_is_normal_preparation_after_embeddings_finish():
    """Expose BM25 preparation as degraded without misreporting schema or database failure."""

    async def probe():
        """Report a populated vector index whose BM25 stage has not yet run."""
        return {
            "status": {
                "database_connected": True,
                "schema_status": "compatible",
                "schema_message": "ok",
                "documents": 1,
                "chunks": 10,
                "embedded_chunks": 10,
                "pending_embeddings": 0,
                "bm25_ready": False,
                "bm25_rebuild_recorded": True,
                "writable": True,
            }
        }

    settings = ReleaseSettings(mode="runtime", admin_mode="live", host="127.0.0.1", _env_file=None)
    with TestClient(
        create_release_app(
            settings,
            services=RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider()),
            readiness_probe=probe,
        )
    ) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["corpus"]["availability"] == "degraded"
    assert response.json()["corpus"]["schema_status"] == "compatible"
    assert response.json()["corpus"]["database_connected"] is True
    assert response.json()["corpus"]["bm25_rebuild_recorded"] is True


def test_readiness_reports_update_without_hiding_existing_counts():
    """An active writer overrides cached ready counts and clears when the update ends."""
    import asyncio

    import httpx

    async def exercise():
        """Use the same event loop for the application and its admission gate."""
        runtime = RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())

        async def probe():
            """Return a populated, previously ready corpus without database calls."""
            return {
                "status": {
                    "database_connected": True,
                    "schema_status": "compatible",
                    "documents": 1,
                    "chunks": 2,
                    "embedded_chunks": 2,
                    "pending_embeddings": 0,
                    "bm25_ready": True,
                }
            }

        app = create_release_app(
            ReleaseSettings(mode="runtime", host="127.0.0.1", _env_file=None),
            services=runtime,
            readiness_probe=probe,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            async with runtime.corpus_access.update():
                response = await client.get("/ready")
                assert response.status_code == 503
                assert response.json()["corpus"]["updating"] is True
                assert response.json()["corpus"]["database_connected"] is True
            response = await client.get("/ready")
            assert response.status_code == 200
            assert response.json()["corpus"]["updating"] is False

    asyncio.run(exercise())
