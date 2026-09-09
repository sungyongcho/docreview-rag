"""Published limits follow the policy and effective provider ceilings used by requests."""

from decimal import Decimal

from fastapi.testclient import TestClient

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
