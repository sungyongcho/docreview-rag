"""OpenAI per-call cap routes: Dev edits below the ceiling, production keeps the ceiling."""

import asyncio
from decimal import Decimal

from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest

from app.api.review_profile import ReviewSessionProfile
from app.api.runtime import RuntimeApiServices
from app.api.schemas import ReviewRequest
from app.llm.openai_limits import CEILING_ENV_KEYS, OpenAILimitsManager
from app.llm.provider import LLMProvider, RawProviderResponse
from app.llm.schemas import Prompt, ProviderBudget, TokenPricing
from app.release.app import create_release_app
from app.release.config import ReleaseSettings
from app.retrieval.embeddings import DeterministicEmbeddingProvider


class _StubProvider(LLMProvider):
    """Register an OpenAI engine without letting any test reach a network."""

    provider_name = "openai"
    model_name = "stub"
    api_url = "http://stub"

    async def _request[OutputT: BaseModel](
        self, prompt: Prompt, schema: type[OutputT], budget: ProviderBudget
    ) -> RawProviderResponse:
        """No test in this module completes a prompt."""
        raise AssertionError("per-call cap tests never call the provider")


EXPECTED_KEYS = {
    "max_input_tokens",
    "max_output_tokens",
    "max_cost_usd",
    "ceiling_max_input_tokens",
    "ceiling_max_output_tokens",
    "ceiling_max_cost_usd",
    "source",
    "editable",
    "error",
    "ceiling_env_keys",
    "file_path",
}


def ceiling() -> ProviderBudget:
    """Mirror the .env-derived cap used by the release composition."""
    return ProviderBudget(
        max_input_tokens=12_000,
        max_output_tokens=600,
        max_cost_usd=Decimal("0.04"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("1"), output_per_million_usd=Decimal("2")
        ),
    )


def limits_app(tmp_path, environment="dev", admin_mode="live", admin_cors_origin=None):
    """Build real routes around a fake OpenAI provider and a temporary settings file."""
    manager = OpenAILimitsManager(
        ceiling(), path=tmp_path / "openai-limits.json", enabled=environment == "dev"
    )
    runtime = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        llm_providers={"openai": _StubProvider()},
        provider_budgets={"openai": ceiling()},
        openai_limits=manager,
        allow_local_engine=environment == "dev",
    )
    settings = ReleaseSettings(
        _env_file=None,
        DOCREVIEW_ENVIRONMENT=environment,
        mode="runtime",
        host="127.0.0.1",
        admin_mode=admin_mode,
        admin_cors_origin=admin_cors_origin,
    )
    return create_release_app(settings, services=runtime), runtime, manager


def test_routes_read_save_and_reset_within_the_ceiling(tmp_path) -> None:
    """The web receives one stable contract and a saved value drives the next review."""
    app, runtime, manager = limits_app(tmp_path)
    with TestClient(app) as client:
        initial = client.get("/admin/openai/limits")
        assert initial.status_code == 200
        assert set(initial.json()) == EXPECTED_KEYS
        assert initial.json()["source"] == "ceiling"
        assert initial.json()["editable"] is True
        assert initial.json()["ceiling_env_keys"] == CEILING_ENV_KEYS
        saved = client.post(
            "/admin/openai/limits",
            json={"max_input_tokens": 6_000, "max_output_tokens": 300, "max_cost_usd": "0.02"},
        )
        assert saved.status_code == 200
        assert saved.json()["source"] == "saved"
        assert saved.json()["max_output_tokens"] == 300
        assert saved.json()["ceiling_max_output_tokens"] == 600
        assert manager.effective().max_output_tokens == 300
        reset = client.post("/admin/openai/limits/reset")
        assert reset.status_code == 200
        assert reset.json()["source"] == "ceiling"
        assert manager.effective() == ceiling()


def test_review_requests_use_the_saved_per_call_cap(tmp_path) -> None:
    """The provider budget handed to a review equals the working value, not the ceiling."""
    _, runtime, manager = limits_app(tmp_path)

    async def exercise():
        await manager.save(
            max_input_tokens=5_000, max_output_tokens=200, max_cost_usd=Decimal("0.01")
        )
        request = ReviewRequest(query="What is disclosed?", session_profile=ReviewSessionProfile())
        _, budget = await runtime._engine(request)
        return budget

    budget = asyncio.run(exercise())
    assert budget.max_input_tokens == 5_000
    assert budget.max_output_tokens == 200
    assert budget.max_cost_usd == Decimal("0.01")
    assert budget.pricing == ceiling().pricing


def test_values_above_the_ceiling_are_rejected_with_the_env_key(tmp_path) -> None:
    """A 422 names the key that raises the ceiling; nothing is saved."""
    app, _, manager = limits_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/admin/openai/limits",
            json={"max_input_tokens": 12_001, "max_output_tokens": 300, "max_cost_usd": "0.02"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "openai_limits_above_ceiling"
    assert CEILING_ENV_KEYS["max_input_tokens"] in response.json()["error"]["message"]
    assert manager.effective() == ceiling()
    assert not (tmp_path / "openai-limits.json").exists()


def test_production_reports_the_ceiling_read_only_and_refuses_edits(tmp_path) -> None:
    """Readiness still shows the caps in production, but every admin route is 403."""
    app, _, _ = limits_app(tmp_path, environment="prod")
    with TestClient(app) as client:
        assert client.get("/admin/openai/limits").status_code == 403
        assert client.post("/admin/openai/limits/reset").status_code == 403
        ready = client.get("/ready")
    assert ready.json()["openai_call_limits"]["editable"] is False
    assert ready.json()["openai_call_limits"]["source"] == "ceiling"
    assert ready.json()["openai_call_limits"]["max_output_tokens"] == 600


@pytest.mark.parametrize("path", ["/admin/openai/limits", "/admin/openai/limits/reset"])
def test_browser_origins_cannot_mutate_per_call_caps(tmp_path, path) -> None:
    """Cross-origin browser mutations are refused like every other admin write."""
    app, _, manager = limits_app(tmp_path, admin_cors_origin="http://127.0.0.1:9000")
    with TestClient(app, base_url="http://app:8000") as client:
        response = client.post(
            path,
            content="",
            headers={
                "origin": "https://unrelated.example",
                "content-type": "text/plain",
                "x-forwarded-host": "localhost:9001",
                "x-forwarded-proto": "http",
            },
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    assert manager.effective() == ceiling()


def test_public_surface_readiness_marks_caps_not_editable(tmp_path) -> None:
    """The public header hides editability without hiding the non-secret caps."""
    app, _, _ = limits_app(tmp_path)
    with TestClient(app) as client:
        private = client.get("/ready").json()["openai_call_limits"]
        public = client.get("/ready", headers={"x-docreview-public": "true"}).json()[
            "openai_call_limits"
        ]
    assert private["editable"] is True
    assert public["editable"] is False
    assert public["max_input_tokens"] == private["max_input_tokens"]
