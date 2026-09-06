"""M5.3 cross-lane HTTP, CLI, workflow, and runtime integration proofs."""

from decimal import Decimal

from fastapi.testclient import TestClient

from app import cli
from app.llm import DeterministicLLMProvider, ProviderBudget, TokenPricing
from app.main import create_app
from app.retrieval import (
    ComponentRankings,
    DeterministicEmbeddingProvider,
    RetrievalResult,
)
from tests.support import need


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
        return self.transaction_open

    async def rollback(self):
        self.rollbacks += 1
        self.transaction_open = False

    def begin(self):
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
    A,
    hit,
    successful_run,
):
    need(A, "RuntimeApiServices")
    sessions = []
    retrieval_calls = []
    workflow_calls = []
    persisted = []
    llm_provider = DeterministicLLMProvider(())

    def session_factory():
        session = FakeSession()
        sessions.append(session)
        return session

    async def retrieval_service(session, query, *, provider, k, filters):
        retrieval_calls.append((session, query, provider, k, filters))
        return RetrievalResult(
            hits=(hit,),
            component_rankings=ComponentRankings(vector=(hit.chunk_id,), lexical=()),
        )

    async def workflow_service(request, *, retriever, provider, on_node=None):
        result = await retriever(request.query, request.k, request.filters)
        workflow_calls.append((request, provider, result))
        return successful_run.model_copy(update={"run_id": request.run_id})

    async def run_persister(session, report, *, secret_values):
        persisted.append((session, report, tuple(secret_values)))
        return object()

    services = A.RuntimeApiServices(
        session_factory=session_factory,
        llm_provider=llm_provider,
        provider_budget=provider_budget(),
        retrieval_service=retrieval_service,
        workflow_service=workflow_service,
        run_persister=run_persister,
        run_id_factory=lambda: "run-integration",
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
    assert workflow_calls[0][0].run_id == "run-integration"
    assert workflow_calls[0][1] is llm_provider
    assert workflow_calls[0][2].hits == (hit,)
    assert persisted[0][1].run_id == "run-integration"
    assert persisted[0][0] is sessions[1]


def test_cli_and_http_use_the_same_public_evidence_shape(
    client_factory,
    services,
    hit,
):
    services.hits = (hit,)

    response = client_factory(services).post("/retrieve", json={"query": "Revenue?"})

    assert response.status_code == 200
    assert cli._evidence_payload(hit) == response.json()["results"][0]
    assert "index_text" not in cli._evidence_payload(hit)


def test_default_runtime_is_live_but_review_is_fail_closed_without_provider():
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
