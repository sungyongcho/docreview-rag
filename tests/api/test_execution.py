"""Execution contracts retain actual settings and distinguish absent provider measurements."""

import asyncio
from decimal import Decimal

from pydantic import JsonValue
import pytest

from app.api.runtime import RuntimeApiServices
from app.api.schemas import ReviewRequest, RunResponse
from app.llm.schemas import ProviderBudget, TokenPricing
from app.observability.types import JsonObject
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.llm.support import DeterministicLLMProvider


def json_object(value: JsonValue) -> JsonObject:
    """Narrow one JSON value that the execution contract defines as an object."""
    assert isinstance(value, dict)
    return value


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
    settings = json_object(context["effective_settings"])
    assert json_object(settings["run_limits"])["max_input_tokens"] == 60000
    assert json_object(settings["effective_provider_budget"])["max_input_tokens"] == 2500
    assert json_object(settings["budget_sources"])["max_input_tokens"] == "provider_budget"
    assert settings["run_limits_source"] == "application_default"
    overridden = ReviewRequest.model_validate(
        {
            "query": "Revenue?",
            "session_profile": {"prompt_policy": {"workflow_budget": {"max_input_tokens": 1000}}},
        }
    )
    context = asyncio.run(service._execution_context(provider, budget, overridden))
    settings = json_object(context["effective_settings"])
    assert json_object(settings["effective_provider_budget"])["max_input_tokens"] == 1000
    assert json_object(settings["budget_sources"])["max_input_tokens"] == "run_limits"
    assert settings["run_limits_source"] == "request"
    chat = asyncio.run(service._execution_context(provider, budget, request, chat_only=True))
    chat_settings = json_object(chat["effective_settings"])
    assert chat_settings["retrieval_applicable"] is False
    assert chat_settings["run_limits"] is None
    assert json_object(chat_settings["effective_provider_budget"])["max_input_tokens"] == 2500


def test_terminal_contract_preserves_stage_outputs_and_explicit_missing_timing(successful_run):
    """Live and persisted projections retain current measurements and optional timing."""
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
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "reasoning_tokens": 0,
                "estimated_cost_usd": "0.000001",
                "provider": "openai_responses",
                "local": False,
                "credential_slot": "OPENAI_API_KEY_LOCAL",
                "local_timings": [],
                "projected_input_tokens": None,
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
    provider_free = RunResponse.from_run_report(successful_run).execution
    assert provider_free is not None
    assert provider_free.model_calls == []
    assert provider_free.stage_results is None
    assert provider_free.effective_settings is None


@pytest.mark.parametrize("context", [None, {}, {"model_calls": None}, {"model_calls": {}}])
def test_execution_rejects_missing_call_records_instead_of_rebuilding_traces(
    schema_rejected_run, context
):
    """A billed trace cannot make an unsupported execution context look current."""
    with pytest.raises(ValueError, match="recorded model calls must be a list"):
        RunResponse.from_run_report(
            schema_rejected_run.model_copy(update={"request_context": context})
        )


@pytest.mark.parametrize(
    ("tag_digest", "loaded_digest", "expected_speed"),
    [("v1", "v1", 10), ("v2", "v1", None)],
)
def test_local_execution_publishes_measured_cpu_speed_to_readiness(
    tmp_path, tag_digest, loaded_digest, expected_speed
):
    """Terminal context updates the same inventory consumed by the next readiness check."""
    import httpx

    from app.llm.local import LocalLLMProvider
    from app.llm.local_connection import LocalConnectionManager
    from app.llm.local_engine import local_provider_budget
    from app.llm.schemas import Prompt
    from app.observability.stages import record_stages, stage
    from tests.llm.support import ChatReply

    state = {"tag_digest": "v1", "loaded_digest": "v1"}

    def respond(request):
        """Return Ollama inventory and measured completion data without external I/O."""
        if request.url.path == "/api/chat":
            return httpx.Response(
                200,
                json={
                    "message": {"content": '{"answer":"Revenue increased."}'},
                    "prompt_eval_count": 10,
                    "eval_count": 100,
                    "eval_duration": 10_000_000_000,
                },
            )
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

    connection = LocalConnectionManager(
        initial_base_url="http://local.test",
        path=tmp_path / "connection.json",
        transport=httpx.MockTransport(respond),
    )
    inventory = connection.current.inventory
    assert inventory is not None
    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        local_connection=connection,
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
                await service._engines.pin_local_model(request.session_profile)
                state.update(tag_digest=tag_digest, loaded_digest=loaded_digest)
                inventory.invalidate()
                await inventory.snapshot()
                with record_stages() as recorder:
                    async with stage("check"):
                        completion = await provider.complete(
                            Prompt(system="Return the requested JSON.", user="Revenue?"),
                            ChatReply,
                            local_provider_budget(max_input_tokens=12000, max_output_tokens=600),
                        )
                    assert completion.status == "ok"
                    result = await service._execution_context(provider, None, request)
                placement = result["local_placement"]
                assert isinstance(placement, dict) and placement["placement"] == "cpu"
                assert result["model_calls"] == recorder.model_calls
                assert len(recorder.model_calls) == 1
                assert recorder.model_calls[0]["output_tokens"] == 100
                sample = (await inventory.snapshot()).models[0].cpu_performance
                if expected_speed is None:
                    assert sample is None
                else:
                    assert sample is not None and sample.tokens_per_second == expected_speed

    asyncio.run(exercise())
