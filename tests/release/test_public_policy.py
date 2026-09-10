"""Published limits follow the policy and effective provider ceilings used by requests."""

from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app.api.review_profile import PromptPolicy
from app.api.runtime import RuntimeApiServices
from app.llm.openai_limits import OpenAILimitsManager
from app.release.app import create_release_app
from app.release.config import ReleaseSettings
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_limits_expose_public_policy_without_consuming_allowance() -> None:
    """The public workflow contract comes from the same model required by the guard."""
    with TestClient(create_release_app()) as client:
        first = client.get("/limits").json()
        second = client.get("/limits").json()
    assert first["prompt_policy"] == PromptPolicy().model_dump(mode="json")
    assert first["per_call"]["editable"] is False
    assert first["remaining_minute"] == second["remaining_minute"]


def test_limits_expose_effective_runtime_call_caps(tmp_path) -> None:
    """A DEV preview reports lower runtime caps rather than the configured ceiling."""
    ceiling = (
        ReleaseSettings()
        .provider_budget()
        .model_copy(
            update={
                "max_input_tokens": 1400,
                "max_output_tokens": 250,
                "max_cost_usd": Decimal("0.01"),
            }
        )
    )
    manager = OpenAILimitsManager(ceiling, path=tmp_path / "limits.json", enabled=False)
    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(), openai_limits=manager
    )
    with TestClient(create_release_app(ReleaseSettings(), services=services)) as client:
        response = client.get("/limits").json()
    assert response["per_call"]["max_input_tokens"] == 1400
    assert response["per_call"]["max_output_tokens"] == 250
    assert response["per_call"]["max_cost_usd"] == "0.01"


@pytest.mark.parametrize("public_header", [False, True])
def test_production_blocks_admin_even_with_retained_live_configuration(tmp_path, public_header):
    """Production cannot regain administrator execution through SSH or a missing header."""
    settings = ReleaseSettings(
        _env_file=None,
        DOCREVIEW_ENVIRONMENT="prod",
        mode="runtime",
        admin_mode="live",
        host="127.0.0.1",
        allow_ingest=True,
        public_allowance_path=tmp_path / "limits.sqlite3",
    )
    services = RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())
    with TestClient(create_release_app(settings, services=services)) as client:
        headers = {"x-docreview-public": "true"} if public_header else {}
        assert client.get("/admin/corpus", headers=headers).status_code == 403
        assert client.post("/ingest", json={}, headers=headers).status_code == 403
        capabilities = client.get("/capabilities", headers=headers).json()
        assert capabilities["can_change_custom_retrieval"] is True
        assert not any(
            value
            for key, value in capabilities.items()
            if key.startswith("can_")
            and key not in {"can_change_custom_retrieval", "can_compare_published_snapshots"}
        )
        assert client.get("/release").json()["admin_mode"] == "readonly"
        limits = client.get("/limits").json()
        assert (limits["per_minute"], limits["per_day"]) == (2, 5)
        assert limits["daily_cost_usd"] == "0.10"
        assert limits["per_call"]["max_cost_usd"] == "0.005"
        assert '"supportedSubmitMethods": []' in client.get("/docs").text
        paths = client.get("/openapi.json").json()["paths"]
        assert "/admin/corpus" in paths and "/review" in paths and "/limits" in paths
