"""M5.3 cross-lane HTTP, CLI, workflow, and runtime integration proofs."""

import asyncio
from decimal import Decimal
import json
from typing import cast

from fastapi.testclient import TestClient
from openai import OpenAIError
import pytest

from app import cli
from app.api.app import create_api_app
from app.api.review_profile import ReviewSessionProfile
from app.api.runtime import RuntimeApiServices, SessionFactory
from app.api.schemas import ReviewRequest
from app.llm.schemas import ProviderBudget, RawProviderResponse, TokenPricing
from app.observability.types import build_run_report
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.scope import ManifestScopeIndex
from app.retrieval.service import ComponentRankings, RetrievalResult
from app.workflow.types import NodeError, initial_state
from tests.ingestion.support import filing_document
from tests.llm.support import DeterministicLLMProvider


class FakeTransaction:
    """Minimal async transaction context for the runtime adapter test."""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.transaction_open = True
        return self.session

    async def __aexit__(self, error_type, error, traceback):
        self.session.transaction_open = False


class FakeSession:
    """Session context that records transaction ownership without database I/O."""

    def __init__(self):
        self.transaction_open = False
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, error_type, error, traceback):
        return None

    def in_transaction(self):
        """Report whether this fake session currently holds a transaction."""
        return self.transaction_open

    async def rollback(self):
        """Count the rollback and clear the transaction flag."""
        self.rollbacks += 1
        self.transaction_open = False

    def begin(self):
        """Open a transaction against this fake session."""
        return FakeTransaction(self)


def provider_budget() -> ProviderBudget:
    """Return an explicit zero-price budget for a no-call integration provider."""
    return ProviderBudget(
        max_input_tokens=1_000,
        max_output_tokens=1_000,
        max_cost_usd=Decimal("0"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0"),
            output_per_million_usd=Decimal("0"),
        ),
    )


def test_runtime_http_bridges_m2_retrieval_into_m4_review_and_persistence(
    hit,
    successful_run,
):
    """Carry one query through retrieval, the workflow, and persistence on one session."""
    sessions = []
    retrieval_calls = []
    workflow_calls = []
    persisted = []
    llm_provider = DeterministicLLMProvider(())

    def session_factory():
        """Hand out a fresh fake session and remember it."""
        session = FakeSession()
        sessions.append(session)
        return session

    async def retrieval_service(session, query, *, provider, k, filters, **plan):
        """Record the retrieval call and its plan, returning one hit on an open transaction."""
        session.transaction_open = True
        retrieval_calls.append((session, query, provider, k, filters, plan))
        return RetrievalResult(
            candidates=(hit,),
            hits=(hit,),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(hit.chunk_id,), lexical=()),
        )

    async def workflow_service(request, *, retriever, provider, on_node=None):
        """Record the workflow call and return the staged report."""
        result = await retriever(request.query, request.k, request.filters)
        assert sessions[-1].transaction_open is False
        workflow_calls.append((request, provider, result))
        if on_node is not None:
            await on_node(
                "retrieve",
                initial_state(request).model_copy(
                    update={
                        "retrieved_hits": result.hits,
                        "evidence": result.hits,
                    }
                ),
            )
        return successful_run.model_copy(update={"run_id": request.run_id})

    async def run_persister(session, run, traces):
        """Record the sanitized records that reached persistence."""
        persisted.append((session, run, tuple(traces)))
        return run

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, session_factory),
        llm_providers={"openai": llm_provider},
        provider_budgets={"openai": provider_budget()},
        retrieval_service=retrieval_service,
        workflow_service=workflow_service,
        run_persister=run_persister,
        run_id_factory=lambda: "run-integration",
        scope_index=ManifestScopeIndex.from_entries(
            (filing_document(issuer="ACME", document_id=hit.doc_id),)
        ),
    )
    explicit_profile = {
        "retrieval_preset": "custom",
        "custom_retrieval": {"k": 3, "route_by_language": True},
        "doc_ids": [hit.doc_id],
        "registries": ["sec"],
        "kinds": [hit.kind],
        "prompt_policy": {"max_context_chars": 10000, "workflow_budget": {"max_iterations": 4}},
    }

    with TestClient(create_api_app(services)) as client:
        retrieved = client.post(
            "/retrieve",
            json={"query": "Revenue?", "session_profile": explicit_profile},
        )
        reviewed = client.post(
            "/review",
            json={"query": "Revenue?", "session_profile": explicit_profile},
        )

    assert retrieved.status_code == 200
    assert retrieved.json()["results"][0]["chunk_id"] == hit.chunk_id
    assert reviewed.status_code == 200
    assert reviewed.json()["run_id"] == "run-integration"
    execution = reviewed.json()["execution"]
    assert execution["effective_settings"]["effective_provider_budget"]["max_input_tokens"] == 1000
    assert execution["stage_results"][0]["candidates"][0]["chunk_id"] == hit.chunk_id
    assert [call[1] for call in retrieval_calls] == ["Revenue?", "Revenue?"]
    assert all(isinstance(call[2], DeterministicEmbeddingProvider) for call in retrieval_calls)
    # The configured ranking plan reaches every retrieval, HTTP and workflow alike.
    assert all(call[5]["lexical_ranker"] == "ts_rank_cd" for call in retrieval_calls)
    assert all(call[5]["route_by_language"] is True for call in retrieval_calls)
    assert all(call[4].doc_ids == (hit.doc_id,) for call in retrieval_calls)
    assert all(call[4].registries == ("sec",) for call in retrieval_calls)
    assert all(call[4].kinds == (hit.kind,) for call in retrieval_calls)
    assert workflow_calls[0][0].k == 3
    assert workflow_calls[0][0].max_context_chars == 10000
    assert workflow_calls[0][0].budget.max_iterations == 4
    assert workflow_calls[0][0].run_id == "run-integration"
    assert workflow_calls[0][1] is llm_provider
    assert workflow_calls[0][2].hits == (hit,)
    assert persisted[0][1].run_id == "run-integration"
    assert persisted[0][0] is sessions[1]
    assert sessions[1].rollbacks == 1


def test_balanced_retrieve_does_not_require_an_answer_or_translation_provider(hit):
    """Keep provider-free evidence retrieval available when language routing is off."""

    async def retrieval_service(session, query, *, provider, k, filters, **plan):
        """Return one deterministic hit without touching an answer provider."""
        del session, query, provider, k, filters, plan
        return RetrievalResult(
            candidates=(hit,),
            hits=(hit,),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(), lexical=(hit.chunk_id,)),
        )

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, FakeSession),
        retrieval_service=retrieval_service,
        scope_index=ManifestScopeIndex.from_entries(
            (filing_document(issuer="ACME", document_id=hit.doc_id),)
        ),
        query_routing_enabled=True,
    )

    with TestClient(create_api_app(services)) as client:
        response = client.post("/retrieve", json={"query": "Revenue?"})

    assert response.status_code == 200
    assert response.json()["results"][0]["chunk_id"] == hit.chunk_id


@pytest.mark.parametrize("scope,languages", [("auto", []), ("sec", ["en"])])
def test_korean_preset_retrieval_uses_the_issuer_language_without_translation(
    hit, scope, languages
):
    """Keep an English NVIDIA query on SEC evidence without requiring a translation model."""
    observed = []

    async def retrieval_service(session, query, *, provider, k, filters, **plan):
        """Record the actual runtime filter and return one controlled candidate."""
        observed.append(filters)
        return RetrievalResult(
            candidates=(hit.model_copy(update={"doc_id": "NVDA-FY2024"}),),
            hits=(hit.model_copy(update={"doc_id": "NVDA-FY2024"}),),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(), lexical=(hit.chunk_id,)),
        )

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, FakeSession),
        retrieval_service=retrieval_service,
        query_routing_enabled=True,
        scope_index=ManifestScopeIndex.from_entries(
            [filing_document(issuer="NVDA", aliases=("NVDA", "NVIDIA"))]
        ),
    )
    with TestClient(create_api_app(services)) as client:
        response = client.post(
            "/retrieve",
            json={
                "query": "What drove NVIDIA data center revenue growth?",
                "session_profile": {
                    "retrieval_preset": "korean",
                    "corpus_scope": scope,
                    "languages": languages,
                },
            },
        )

    assert response.status_code == 200
    assert observed[0].registries == ("sec",)
    assert observed[0].issuers == ("NVDA",)
    assert observed[0].languages == ("en",)


@pytest.mark.parametrize(
    "preset,query,expected_variants",
    [
        ("korean", "What drove NVIDIA data center revenue growth?", {}),
        ("balanced", "NVIDIA 매출 증가 요인은 무엇인가요?", {}),
        (
            "korean",
            "NVIDIA 매출 증가 요인은 무엇인가요?",
            {"en": "What drove NVIDIA revenue growth?"},
        ),
    ],
)
def test_review_translation_respects_the_preset_and_actual_corpus_language(
    successful_run, preset, query, expected_variants
):
    """Translate only an enabled cross-language request before the workflow boundary."""
    responses = (
        (
            RawProviderResponse(
                output_text=json.dumps(
                    {
                        "translated_query": "What drove NVIDIA revenue growth?",
                        "target_language": "en",
                    }
                ),
                input_tokens=10,
                output_tokens=10,
            ),
        )
        if expected_variants
        else ()
    )
    provider = DeterministicLLMProvider(responses)
    observed = []

    async def workflow_service(request, *, retriever, provider, on_node=None):
        """Inspect runtime routing without generating an answer or accessing the database."""
        observed.append(request)
        return successful_run.model_copy(update={"run_id": request.run_id})

    async def run_persister(session, run, traces):
        """Keep this routing regression independent of persistence I/O."""
        return run

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, FakeSession),
        llm_providers={"openai": provider},
        provider_budgets={"openai": provider_budget()},
        workflow_service=workflow_service,
        run_persister=run_persister,
        query_routing_enabled=True,
        scope_index=ManifestScopeIndex.from_entries(
            [filing_document(issuer="NVDA", aliases=("NVDA", "NVIDIA"))]
        ),
    )
    asyncio.run(
        services.review(
            ReviewRequest(
                query=query, session_profile=ReviewSessionProfile(retrieval_preset=preset)
            )
        )
    )

    assert observed[0].query == query
    assert observed[0].filters.languages == ("en",)
    assert observed[0].routing_queries == expected_variants
    assert len(provider.prompts) == len(expected_variants)


def test_cli_and_http_use_the_same_public_evidence_shape(
    client_factory,
    services,
    hit,
):
    """Project evidence identically whether it leaves by the command line or HTTP."""
    services.hits = (hit,)

    response = client_factory(services).post("/retrieve", json={"query": "Revenue?"})

    assert response.status_code == 200
    assert cli._evidence_payload(hit) == response.json()["results"][0]
    assert "index_text" not in cli._evidence_payload(hit)


def test_default_runtime_is_live_but_review_is_fail_closed_without_provider():
    """Serve the surface while refusing review until a provider is injected."""
    services = RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())
    with TestClient(create_api_app(services), raise_server_exceptions=False) as client:
        review = client.post("/review", json={"query": "Revenue?"})
        openapi = client.get("/openapi.json")

    assert review.status_code == 503
    assert review.json()["error"] == {
        "code": "provider_unavailable",
        "message": "Review engine 'openai' is not configured.",
        "details": [],
    }
    assert "/retrieve" in openapi.json()["paths"]


def test_semantically_invalid_filters_are_a_typed_400():
    """Translate a domain ValueError into a client error instead of a 500."""

    async def rejecting_retrieval(session, query, *, provider, k, filters, **plan):
        """Raise the language-plan rejection the retrieval stack produces."""
        raise ValueError("lexical retrieval cannot span corpus languages")

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, FakeSession),
        retrieval_service=rejecting_retrieval,
    )

    with TestClient(create_api_app(services), raise_server_exceptions=False) as client:
        response = client.post(
            "/retrieve",
            json={"query": "revenue", "session_profile": {"languages": ["en", "ko"]}},
        )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "invalid_request",
        "message": "lexical retrieval cannot span corpus languages",
        "details": [],
    }


def test_runtime_maps_provider_exceptions_to_nonsecret_503():
    """Turn a provider failure into an unavailable answer that names no endpoint."""
    sessions = []

    def session_factory():
        """Hand out a fresh fake session and remember it."""
        session = FakeSession()
        sessions.append(session)
        return session

    async def unavailable_workflow(request, *, retriever, provider, on_node=None):
        """Raise the provider failure this exit is supposed to describe."""
        raise OpenAIError("secret provider endpoint")

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, session_factory),
        llm_providers={"openai": DeterministicLLMProvider(())},
        provider_budgets={"openai": provider_budget()},
        workflow_service=unavailable_workflow,
    )

    with TestClient(create_api_app(services), raise_server_exceptions=False) as client:
        response = client.post("/review", json={"query": "Revenue?"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "secret provider endpoint" not in response.text


def test_runtime_redacts_explicit_secrets_before_persisting_and_returning():
    """Keep a declared secret out of both the stored record and the response."""
    secret = "custom-sensitive-value"
    failure = NodeError(
        node="grade",
        error_type="RuntimeError",
        message=f"failed with {secret}",
    )
    raw_report = build_run_report(
        run_id="run-secret",
        status="error",
        total_time_seconds=0.1,
        system_prompt=f"Use {secret}",
        node_path=("retrieve", "grade"),
        steps=(),
        report={"reason": failure.model_dump(mode="json")},
    )
    persisted = []

    async def workflow_service(request, *, retriever, provider, on_node=None):
        """Record the workflow call and return the staged report."""
        return raw_report

    async def run_persister(session, run, traces):
        """Record the sanitized records that reached persistence."""
        persisted.append((run, tuple(traces)))
        return run

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, FakeSession),
        llm_providers={"openai": DeterministicLLMProvider(())},
        provider_budgets={"openai": provider_budget()},
        workflow_service=workflow_service,
        run_persister=run_persister,
        secret_values=(secret,),
    )

    result = asyncio.run(services.review(ReviewRequest(query="Revenue?")))

    persisted_run = persisted[0][0]
    assert secret not in repr(result)
    assert secret not in persisted_run.system_prompt
    assert secret not in json.dumps(persisted_run.report)
