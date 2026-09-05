"""Request-scoped local model selection without database or inference side effects."""

import asyncio

import httpx
import pytest

from app.api.errors import ApiProblemError
from app.api.review_profile import ReviewSessionProfile
from app.api.runtime import RuntimeApiServices
from app.api.schemas import ReviewRequest
from app.llm.local_connection import LocalConnectionManager
from app.llm.local_engine import local_provider_budget
from app.llm.local_inventory import LocalModelInventory


def local_services(names: list[str]) -> RuntimeApiServices:
    """Build real provider selection over an explicitly controlled model inventory."""
    inventory = LocalModelInventory(
        base_url="http://host/v1",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"id": name} for name in names]})
        ),
    )
    return RuntimeApiServices(
        llm_providers={},
        provider_budgets={
            "local": local_provider_budget(max_input_tokens=1000, max_output_tokens=100)
        },
        local_inventory=inventory,
    )


def test_single_model_is_pinned_without_changing_the_requested_engine() -> None:
    """A single model is resolved once and cannot later switch to a replacement."""
    services = local_services(["answer"])
    profile = asyncio.run(services._local_profile(ReviewSessionProfile(engine="local")))
    assert profile.local_model == "answer"
    assert profile.engine == "local"
    other = local_services(["replacement"])
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(other._local_profile(profile))
    assert error.value.error.code == "local_model_unavailable"
    openai = ReviewSessionProfile()
    assert asyncio.run(services._local_profile(openai)) is openai


def test_multiple_models_require_a_choice_and_isolate_concurrent_requests() -> None:
    """Two conversations get separate providers and never mutate a global active model."""
    services = local_services(["first", "second"])
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(services._local_profile(ReviewSessionProfile(engine="local")))
    assert error.value.error.code == "local_model_required"

    async def resolve() -> list:
        """Resolve independent selections concurrently through the same runtime."""
        return await asyncio.gather(
            *(
                services._engine(
                    ReviewRequest(
                        query="question",
                        session_profile=ReviewSessionProfile(engine="local", local_model=name),
                    )
                )
                for name in ("first", "second")
            )
        )

    first, second = asyncio.run(resolve())
    assert first[0].model_name == "first"
    assert second[0].model_name == "second"
    assert first[0] is not second[0]


def test_empty_inventory_blocks_local_execution() -> None:
    """An explicitly chosen local engine never falls back to another provider."""
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(local_services([])._local_profile(ReviewSessionProfile(engine="local")))
    assert error.value.error.code == "local_model_unavailable"


def test_request_pins_endpoint_and_provider_across_connection_changes(tmp_path) -> None:
    """Running requests keep their endpoint and model while the next request uses a saved change."""
    manager = LocalConnectionManager(
        initial_base_url="http://first/v1",
        path=tmp_path / "connection.json",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"id": "answer"}]})
        ),
    )
    services = RuntimeApiServices(
        llm_providers={},
        provider_budgets={
            "local": local_provider_budget(max_input_tokens=1000, max_output_tokens=100)
        },
        local_connection=manager,
    )
    request = ReviewRequest(query="question", session_profile=ReviewSessionProfile(engine="local"))

    async def exercise() -> None:
        """Resolve stages before and after a switch, then enter another request boundary."""
        async with services._request_connection(request.session_profile):
            first, _ = await services._engine(request)
            assert first._base_url == "http://first/v1"
            await manager.connect("http://second/v1")
            later, _ = await services._engine(request)
            assert later is first
            assert later.model_name == "answer"
            assert not first._client.is_closed
        assert first._client.is_closed
        async with services._request_connection(request.session_profile):
            next_request, _ = await services._engine(request)
            assert next_request._base_url == "http://second/v1"
            assert next_request is not first
        assert next_request._client.is_closed

    asyncio.run(exercise())


def test_production_rejects_local_and_custom_controls_before_retrieval() -> None:
    """Even retrieval and deterministic chat must enforce the configured public limits."""
    from app.api.review_profile import PromptPolicy
    from app.api.schemas import RetrieveRequest

    services = RuntimeApiServices(allow_local_engine=False, allow_custom_prompt_policy=False)
    for profile in (
        ReviewSessionProfile(engine="local"),
        ReviewSessionProfile(prompt_policy=PromptPolicy(additional_instructions="changed")),
    ):
        with pytest.raises(ApiProblemError) as error:
            asyncio.run(services.retrieve(RetrieveRequest(query="hello", session_profile=profile)))
        assert error.value.status_code == 403
        with pytest.raises(ApiProblemError) as error:
            asyncio.run(services.review(ReviewRequest(query="hello", session_profile=profile)))
        assert error.value.status_code == 403


def test_resolved_scope_is_observed_before_retrieval_without_model_or_database_calls() -> None:
    """Emit real alias resolution before entering the database retrieval boundary."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages
    from app.retrieval.scope import ManifestScopeIndex

    events = []

    def stop_before_database():
        """Stop deliberately after routing to avoid database and inference side effects."""
        raise LookupError("retrieval boundary reached")

    async def observe(event) -> None:
        """Collect measured events from the real runtime resolver."""
        events.append(event)

    services = RuntimeApiServices(
        session_factory=stop_before_database,
        scope_index=ManifestScopeIndex.from_entries(
            (
                {
                    "registry": "dart",
                    "issuer": "005930",
                    "fiscal_year": 2024,
                    "form": "사업보고서",
                    "aliases": ["삼성전자", "Samsung Electronics"],
                },
            )
        ),
    )

    async def exercise() -> None:
        """Run normal runtime resolution until its injected database boundary."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await services.retrieve(
                RetrieveRequest(
                    query="삼성전자 매출",
                    session_profile=ReviewSessionProfile(fiscal_years=(2024,)),
                )
            )

    asyncio.run(exercise())
    assert [(event.node, event.phase) for event in events] == [
        ("route", "start"),
        ("route", "end"),
        ("retrieve", "start"),
        ("retrieve", "end"),
    ]
    scope = events[1].resolved_scope
    assert scope["source"] == "alias"
    assert scope["filters"]["registries"] == ["dart"]
    assert scope["filters"]["issuers"] == ["005930"]
    assert scope["filters"]["fiscal_years"] == [2024]
