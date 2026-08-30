"""M5.3 cross-lane HTTP, CLI, workflow, and runtime integration proofs."""

import asyncio
from decimal import Decimal
import json
import threading
from typing import cast

from fastapi.testclient import TestClient
from openai import OpenAIError

from app import cli
from app.api.errors import ApiProblemError
import app.api.runtime as runtime_module
from app.api.runtime import RuntimeApiServices, SessionFactory, build_runtime_services
from app.api.schemas import IngestRequest, ReviewRequest
from app.config import Settings, get_settings
from app.ingestion.seed import SeedResult
from app.llm.provider import DeterministicLLMProvider, OpenAILLMProvider
from app.llm.schemas import ProviderBudget, TokenPricing
from app.main import create_app
from app.observability.types import build_run_report
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.service import ComponentRankings, RetrievalResult
from app.workflow.types import NodeError


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
            hits=(hit,),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(hit.chunk_id,), lexical=()),
        )

    async def workflow_service(request, *, retriever, provider, on_node=None):
        """Record the workflow call and return the staged report."""
        result = await retriever(request.query, request.k, request.filters)
        assert sessions[-1].transaction_open is False
        workflow_calls.append((request, provider, result))
        return successful_run.model_copy(update={"run_id": request.run_id})

    async def run_persister(session, run, traces):
        """Record the sanitized records that reached persistence."""
        persisted.append((session, run, tuple(traces)))
        return run

    services = RuntimeApiServices(
        session_factory=cast(SessionFactory, session_factory),
        llm_provider=llm_provider,
        provider_budget=provider_budget(),
        retrieval_service=retrieval_service,
        workflow_service=workflow_service,
        run_persister=run_persister,
        run_id_factory=lambda: "run-integration",
        lexical_ranker="bm25",
        route_by_language=True,
    )

    with TestClient(create_app(services)) as client:
        retrieved = client.post("/retrieve", json={"query": "Revenue?", "k": 3})
        reviewed = client.post("/review", json={"query": "Revenue?", "k": 3})

    assert retrieved.status_code == 200
    assert retrieved.json()["results"][0]["chunk_id"] == hit.chunk_id
    assert reviewed.status_code == 200
    assert reviewed.json()["run_id"] == "run-integration"
    assert [call[1] for call in retrieval_calls] == ["Revenue?", "Revenue?"]
    assert all(isinstance(call[2], DeterministicEmbeddingProvider) for call in retrieval_calls)
    # The configured ranking plan reaches every retrieval, HTTP and workflow alike.
    assert all(call[5]["lexical_ranker"] == "bm25" for call in retrieval_calls)
    assert all(call[5]["route_by_language"] is True for call in retrieval_calls)
    assert workflow_calls[0][0].run_id == "run-integration"
    assert workflow_calls[0][1] is llm_provider
    assert workflow_calls[0][2].hits == (hit,)
    assert persisted[0][1].run_id == "run-integration"
    assert persisted[0][0] is sessions[1]
    assert sessions[1].rollbacks == 1


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
    """Serve the surface by default while refusing review until a provider is injected."""
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        health = client.get("/health")
        review = client.post("/review", json={"query": "Revenue?"})
        openapi = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert review.status_code == 503
    assert review.json()["error"] == {
        "code": "provider_unavailable",
        "message": "Review requires an explicitly configured LLM provider and budget.",
        "details": [],
    }
    assert "/health" in openapi.json()["paths"]
    assert "/retrieve" in openapi.json()["paths"]


def test_build_runtime_services_composes_from_settings():
    """Wire the embedder, lexical plan, review provider, and secrets from Settings."""
    settings = Settings.model_validate(
        {
            **get_settings().model_dump(),
            "embedding_provider": "deterministic",
            "lexical_ranker": "bm25",
            "query_language_routing": True,
            "bm25_k1": 1.4,
            "openai_api_key": "sk-review-test-key",
            "review_model": "gpt-5-mini",
            "review_input_price_per_million_usd": Decimal("0.25"),
            "review_output_price_per_million_usd": Decimal("2.0"),
        }
    )

    services = build_runtime_services(settings)

    assert isinstance(services._embedding_provider, DeterministicEmbeddingProvider)
    assert services._lexical_ranker == "bm25"
    assert services._route_by_language is True
    assert services._bm25_k1 == 1.4
    assert isinstance(services._llm_provider, OpenAILLMProvider)
    assert services._llm_provider.model_name == "gpt-5-mini"
    assert services._provider_budget is not None
    assert services._provider_budget.pricing.output_per_million_usd == Decimal("2.0")
    assert "sk-review-test-key" in services._secret_values
    assert services._corpus_root == settings.corpus_dir


def test_semantically_invalid_filters_are_a_typed_400():
    """Translate a domain ValueError into a client error instead of a 500."""

    async def rejecting_retrieval(session, query, *, provider, k, filters, **plan):
        """Raise the language-plan rejection the retrieval stack produces."""
        raise ValueError("lexical retrieval cannot span corpus languages")

    services = RuntimeApiServices(
        session_factory=cast(SessionFactory, FakeSession),
        retrieval_service=rejecting_retrieval,
    )

    with TestClient(create_app(services), raise_server_exceptions=False) as client:
        response = client.post(
            "/retrieve",
            json={"query": "revenue", "filters": {"languages": ["en", "ko"]}},
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
        session_factory=cast(SessionFactory, session_factory),
        llm_provider=DeterministicLLMProvider(()),
        provider_budget=provider_budget(),
        workflow_service=unavailable_workflow,
    )

    with TestClient(create_app(services), raise_server_exceptions=False) as client:
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
        session_factory=cast(SessionFactory, FakeSession),
        llm_provider=DeterministicLLMProvider(()),
        provider_budget=provider_budget(),
        workflow_service=workflow_service,
        run_persister=run_persister,
        secret_values=(secret,),
    )

    result = asyncio.run(services.review(ReviewRequest(query="Revenue?")))

    persisted_run = persisted[0][0]
    assert secret not in repr(result)
    assert secret not in persisted_run.system_prompt
    assert secret not in json.dumps(persisted_run.report)


def test_runtime_prepares_ingestion_off_the_event_loop(monkeypatch, tmp_path):
    """Prepare the corpus on another thread, leaving the event loop free."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]", encoding="utf-8")
    caller_thread = threading.get_ident()
    preparation_threads = []
    bootstraps = []

    def prepare(path, *, expected_documents):
        """Record which thread prepared the batch."""
        preparation_threads.append(threading.get_ident())
        return object()

    async def bootstrap(engine):
        """Record that schema bootstrap ran."""
        bootstraps.append(engine)

    async def persist(session, batch, *, chunk_batch_size):
        """Stand in for persistence, returning an empty seed result."""
        return SeedResult(documents=0, chunks=0)

    monkeypatch.setattr(runtime_module, "load_seed_batch", prepare)
    monkeypatch.setattr(runtime_module, "bootstrap_schema", bootstrap)
    monkeypatch.setattr(runtime_module, "persist_seed_batch_with_stats", persist)
    services = RuntimeApiServices(
        session_factory=cast(SessionFactory, FakeSession),
        database_engine=object(),  # pyright: ignore[reportArgumentType]
        corpus_root=tmp_path,
    )

    result = asyncio.run(
        services.ingest(
            IngestRequest(
                manifest_path="manifest.json",
                expected_documents=1,
            )
        )
    )

    assert result == SeedResult(documents=0, chunks=0)
    assert len(preparation_threads) == 1
    assert preparation_threads[0] != caller_thread
    # Schema DDL is opt-in: without create_schema no bootstrap runs; with it, one does.
    assert bootstraps == []
    asyncio.run(
        services.ingest(
            IngestRequest(
                manifest_path="manifest.json",
                expected_documents=1,
                create_schema=True,
            )
        )
    )
    assert len(bootstraps) == 1


def test_ingest_confines_manifests_to_the_corpus_directory(tmp_path):
    """Reject absolute and relative escapes from the configured corpus root."""
    services = RuntimeApiServices(
        session_factory=cast(SessionFactory, FakeSession),
        corpus_root=tmp_path,
    )

    for escape in ("/etc/passwd", "../outside.json"):
        try:
            asyncio.run(services.ingest(IngestRequest(manifest_path=escape, expected_documents=1)))
        except ApiProblemError as error:
            assert error.status_code == 400
            assert error.error.code == "manifest_outside_corpus"
        else:
            raise AssertionError(f"escape was accepted: {escape}")
