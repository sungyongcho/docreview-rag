"""Execution contracts retain actual settings and distinguish absent provider measurements."""

import asyncio
from decimal import Decimal

import pytest

from app.api.runtime import RuntimeApiServices
from app.api.schemas import ReviewRequest, RunResponse
from app.llm.provider import DeterministicLLMProvider
from app.llm.schemas import ProviderBudget, TokenPricing
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_effective_budget_exposes_the_limiting_source_and_chat_exclusion():
    """The 60k workflow default cannot hide a smaller configured provider allowance."""
    service = RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())
    budget = ProviderBudget(
        max_input_tokens=2500,
        max_output_tokens=600,
        max_cost_usd=Decimal("0"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0"), output_per_million_usd=Decimal("0")
        ),
    )
    provider = DeterministicLLMProvider(())
    request = ReviewRequest(query="Revenue?")
    context = asyncio.run(service._execution_context(provider, budget, request))
    settings = context["effective_settings"]
    assert settings["run_limits"]["max_input_tokens"] == 60000
    assert settings["effective_provider_budget"]["max_input_tokens"] == 2500
    assert settings["budget_sources"]["max_input_tokens"] == "provider_budget"
    assert settings["run_limits_source"] == "application_default"
    overridden = ReviewRequest.model_validate(
        {
            "query": "Revenue?",
            "session_profile": {"prompt_policy": {"workflow_budget": {"max_input_tokens": 1000}}},
        }
    )
    settings = asyncio.run(service._execution_context(provider, budget, overridden))[
        "effective_settings"
    ]
    assert settings["effective_provider_budget"]["max_input_tokens"] == 1000
    assert settings["budget_sources"]["max_input_tokens"] == "run_limits"
    assert settings["run_limits_source"] == "request"
    chat = asyncio.run(service._execution_context(provider, budget, request, chat_only=True))
    assert chat["effective_settings"]["retrieval_applicable"] is False
    assert chat["effective_settings"]["run_limits"] is None
    assert chat["effective_settings"]["effective_provider_budget"]["max_input_tokens"] == 2500


def test_terminal_contract_preserves_stage_outputs_and_explicit_missing_timing(successful_run):
    """Live and persisted projections retain details while historical absence stays unknown."""
    fields = {
        "routing_queries": {"en": "Revenue?"},
        "resolved_scope": {"source": "issuer_alias"},
        "stage_results": [{"node": "grade", "kept_chunk_ids": [7], "rejected_chunk_ids": [8]}],
        "model_calls": [
            {
                "step": 1,
                "node": "grade",
                "model": "gpt-example",
                "attempts": 1,
                "elapsed_ms": 4.0,
                "input_tokens": 9,
                "output_tokens": 2,
                "provider": "openai_responses",
                "local": False,
                "credential_slot": "OPENAI_API_KEY_LOCAL",
            }
        ],
    }
    response = RunResponse.from_run_report(
        successful_run.model_copy(update={"request_context": fields})
    )
    execution = response.model_dump(mode="json")["execution"]
    assert execution["routing_queries"] == fields["routing_queries"]
    assert execution["stage_results"][0]["rejected_chunk_ids"] == [8]
    assert execution["model_calls"][0]["provider_timing"] is None
    assert (
        execution["model_calls"][0]["timing_unavailable_reason"]
        == "provider_does_not_report_timing"
    )
    from app.observability.persistence import records_to_report, report_to_records

    stored, traces = report_to_records(
        successful_run.model_copy(update={"request_context": fields})
    )
    restored = RunResponse.from_run_report(records_to_report(stored, traces)).model_dump(
        mode="json"
    )
    assert restored["execution"] == execution
    historical = RunResponse.from_run_report(successful_run).model_dump(mode="json")["execution"]
    assert historical["stage_results"] is None
    assert historical["effective_settings"] is None


@pytest.mark.parametrize(
    ("tag_digest", "loaded_digest", "expected_speed"),
    [("v1", "v1", 10), ("v2", "v1", None), ("v2", "v2", None), ("v1", None, None)],
)
def test_local_execution_publishes_measured_cpu_speed_to_readiness(
    monkeypatch, tag_digest, loaded_digest, expected_speed
):
    """Terminal context updates the same inventory consumed by the next readiness check."""
    import httpx

    from app.llm.local import LocalLLMProvider
    from app.llm.local_engine import local_provider_budget
    from app.llm.local_inventory import LocalModelInventory
    from app.observability.stages import record_stages

    monkeypatch.setattr("app.llm.local_inventory.CACHE_TTL_S", 0)
    state = {"tag_digest": "v1", "loaded_digest": "v1"}

    def respond(request):
        """Allow metadata inspection without invoking a model or database."""
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "cpu",
                        "digest": state["tag_digest"]
                        if request.url.path == "/api/tags"
                        else state["loaded_digest"],
                        "size": 100,
                        "size_vram": 0,
                    }
                ]
            },
        )

    inventory = LocalModelInventory(
        base_url="http://local.test", transport=httpx.MockTransport(respond)
    )
    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        local_inventory=inventory,
        llm_providers={},
        provider_budgets={
            "local": local_provider_budget(max_input_tokens=12000, max_output_tokens=600)
        },
    )

    async def exercise():
        """Use the actual runtime-to-inventory path and preserve its execution evidence."""
        await inventory.snapshot()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = LocalLLMProvider(
                base_url="http://local.test", model_name="cpu", protocol="ollama", client=client
            )
            request = ReviewRequest.model_validate(
                {"query": "Revenue?", "session_profile": {"engine": "local"}}
            )
            async with service._request_connection(request.session_profile):
                await service._local_profile(request.session_profile)
                state.update(tag_digest=tag_digest, loaded_digest=loaded_digest)
                await inventory.snapshot()
                with record_stages() as recorder:
                    recorder.model_calls.append(
                        {
                            "model": "cpu",
                            "provider": "ollama",
                            "local": True,
                            "local_timings": [{"eval_count": 100, "eval_duration_ms": 10000}],
                        }
                    )
                    result = await service._execution_context(provider, None, request)
                placement = result["local_placement"]
                assert isinstance(placement, dict) and placement["placement"] == "cpu"
                assert result["model_calls"] == recorder.model_calls
                sample = (await inventory.snapshot()).models[0].cpu_performance
                if expected_speed is None:
                    assert sample is None
                else:
                    assert sample is not None and sample.tokens_per_second == expected_speed

    asyncio.run(exercise())
