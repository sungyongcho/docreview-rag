"""Execution contracts retain actual settings and distinguish absent provider measurements."""

import asyncio
from decimal import Decimal

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
