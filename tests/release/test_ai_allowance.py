"""Exercise persistent public limits without provider or user-database calls."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from openai import AsyncOpenAI
import pytest

from app.release.ai_allowance import (
    SharedAIAllowance,
    active_allowance,
)
from app.retrieval.embedding.openai import OpenAIEmbeddingProvider
from tests.support import load_settings


def test_atomic_reservations_survive_recreation(tmp_path):
    """Competing instances cannot spend more than their shared durable cap."""

    async def scenario():
        """Race reservations from independent limiter objects."""
        path = tmp_path / "limits.sqlite3"
        first = SharedAIAllowance(path, Decimal("1"), 5, 25)
        second = SharedAIAllowance(path, Decimal("1"), 5, 25)
        outcomes = await asyncio.gather(
            *[(first if i % 2 else second).reserve_amount(Decimal("0.1")) for i in range(20)]
        )
        assert sum(row[0] for row in outcomes) == 10
        reopened = SharedAIAllowance(path, Decimal("1"), 5, 25)
        assert reopened.salt == first.salt
        remaining, reset = await reopened.status()
        assert remaining == 0
        assert reset.hour == 0 and reset.tzinfo == UTC

    asyncio.run(scenario())


def test_rolling_windows_are_persistent_and_independent(tmp_path, monkeypatch):
    """Rate windows survive restart and recover independently from the UTC budget."""
    now = [100000.0]
    monkeypatch.setattr("app.release.ai_allowance.time.time", lambda: now[0])

    async def scenario():
        """Move the clock through both rolling windows."""
        path = tmp_path / "limits.sqlite3"
        limiter = SharedAIAllowance(path, Decimal("1"), 2, 3)
        await limiter.admit("ip")
        now[0] += 10
        await limiter.admit("ip")
        reopened = SharedAIAllowance(path, Decimal("1"), 2, 3)
        refused = await reopened.admit("ip")
        assert not refused.allowed
        assert refused.retry_after_seconds == 50
        assert (await reopened.peek("another-ip")).remaining_day == 3
        now[0] += 50  # Exactly 60 seconds releases the first request.
        assert (await reopened.admit("ip")).allowed
        refused = await reopened.admit("ip")
        assert not refused.allowed
        assert refused.retry_after_seconds == 86340
        now[0] = 100000.0 + 86400  # Exactly 24 hours releases only the oldest request.
        assert (await reopened.peek("ip")).remaining_day == 1
        assert (await reopened.admit("ip")).allowed

    asyncio.run(scenario())


def test_utc_reset_does_not_reset_ip_window(tmp_path, monkeypatch):
    """Previous-day spend is excluded, while recent request timestamps remain."""

    now = [datetime(2026, 9, 27, 23, 59, 59, tzinfo=UTC).timestamp()]
    monkeypatch.setattr("app.release.ai_allowance.time.time", lambda: now[0])

    async def scenario():
        """Cross midnight with both a spent cost cap and a live request window."""
        ledger = SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 5, 25)
        await ledger.admit("ip")
        assert (await ledger.reserve_amount(Decimal("1")))[0]
        assert not (await ledger.reserve_amount(Decimal("0.01")))[0]
        now[0] += 1
        assert (await ledger.status())[0] == 1
        assert (await ledger.peek("ip")).remaining_day == 24
        assert (await ledger.peek("ip")).remaining_minute == 4

    asyncio.run(scenario())


def test_embedding_is_blocked_before_openai(tmp_path):
    """An exhausted allowance prevents even a query embedding from reaching its client."""

    async def scenario():
        """Use an injected local mock, never an external API."""
        ledger = SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 5, 25)
        await ledger.reserve_amount(Decimal("1"))
        create = AsyncMock()
        provider = OpenAIEmbeddingProvider(
            client=cast(AsyncOpenAI, SimpleNamespace(embeddings=SimpleNamespace(create=create)))
        )
        token = active_allowance.set(ledger)
        try:
            with pytest.raises(ValueError, match="Shared OpenAI allowance exhausted"):
                await provider.embed_query("test")
            create.assert_not_awaited()
        finally:
            active_allowance.reset(token)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_failed_or_cancelled_provider_keeps_reserved_cost(tmp_path, failure):
    """A dispatched call with an ambiguous outcome retains its conservative reservation."""

    async def scenario():
        """Inspect the actual embedding preflight before simulating failure or cancellation."""
        path = tmp_path / "failure.sqlite3"
        ledger = SharedAIAllowance(path, Decimal("1"), 10, 50)
        create = AsyncMock(side_effect=failure)
        provider = OpenAIEmbeddingProvider(
            client=cast(AsyncOpenAI, SimpleNamespace(embeddings=SimpleNamespace(create=create)))
        )
        token = active_allowance.set(ledger)
        try:
            with pytest.raises(failure):
                await provider.embed_query("A request with an uncertain provider outcome.")
        finally:
            active_allowance.reset(token)
        create.assert_awaited_once()
        remaining, _ = await ledger.status()
        assert Decimal(0) < remaining < Decimal("1")
        reopened = SharedAIAllowance(path, Decimal("1"), 10, 50)
        assert (await reopened.status())[0] == remaining

    asyncio.run(scenario())


def test_middleware_charges_lexical_requests_but_reserves_only_actual_ai_cost(tmp_path):
    """Every execution consumes a request slot, while only actual AI calls reserve dollars."""
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from app.release.ai_allowance import reserve_openai
    from app.release.middleware import ReleaseGuardMiddleware

    ledger = SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 10, 25)
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        allowance=ledger,
        trust_proxy_headers=False,
    )

    @app.post("/retrieve")
    async def retrieve(request: Request):
        """Stand in for provider calls without executing a network operation."""
        payload = await request.json()
        if payload.get("session_profile", {}).get("retrieval_preset") != "custom":
            await reserve_openai(Decimal("1"))
        return {"ok": True}

    lexical = {
        "query": "test",
        "session_profile": {
            "retrieval_preset": "custom",
            "custom_retrieval": {
                "strategy": "lexical",
                "k": 5,
                "candidate_k": 20,
                "rrf_k": 60,
                "lexical_ranker": "bm25",
                "bm25_k1": 1.2,
                "bm25_b": 0.75,
                "bm25_idf": "lucene",
                "route_by_language": False,
                "reranker": None,
            },
        },
    }
    with TestClient(app) as client:
        assert client.post("/retrieve", json=lexical).status_code == 200
        assert asyncio.run(ledger.status())[0] == 1
        assert client.post("/retrieve", json={"query": "test"}).status_code == 200
        denied = client.post("/retrieve", json={"query": "test"})
        assert denied.status_code == 429
        assert denied.json()["error"]["code"] == "daily_cost_limit"
        assert denied.json()["error"]["reset_at"]
        assert int(denied.headers["Retry-After"]) > 0
        assert client.post("/retrieve", json=lexical).status_code == 200
        assert denied.headers["X-RateLimit-Remaining-Day"] == "22"


def test_concurrent_request_admissions_are_atomic_and_persistent(tmp_path):
    """Independent workers admit at most the shared limit, including across restarts."""

    async def scenario():
        """Race request admission independently of all provider cost reservations."""
        path = tmp_path / "requests.sqlite3"
        first = SharedAIAllowance(path, Decimal("1"), 10, 50)
        second = SharedAIAllowance(path, Decimal("1"), 10, 50)
        decisions = await asyncio.gather(
            *[(first if i % 2 else second).admit("worker-ip") for i in range(30)]
        )
        assert sum(decision.allowed for decision in decisions) == 10
        reopened = SharedAIAllowance(path, Decimal("1"), 10, 50)
        assert reopened.salt == first.salt
        assert (await reopened.peek("worker-ip")).remaining_day == 40
        assert not (await reopened.admit("worker-ip")).allowed
        assert (await reopened.peek("worker-ip")).remaining_day == 40
        assert (await reopened.status())[0] == 1
        assert (await reopened.admit("different-worker-ip")).allowed

    asyncio.run(scenario())


def _fake_openai():
    """Use the actual provider boundary with an injected client that never opens a socket."""
    from app.llm.openai import OpenAILLMProvider
    from app.query.intent import RoutingClassification

    response = SimpleNamespace(
        output_text=RoutingClassification(
            intent="service_help",
            reason="A service question.",
            requested_issuers=(),
            target_scope="unclear",
        ).model_dump_json(),
        usage=SimpleNamespace(input_tokens=20, output_tokens=20),
        id="fake",
    )
    create = AsyncMock(return_value=response)
    provider = OpenAILLMProvider(
        model_name="gpt-5.6-luna",
        client=cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace(create=create))),
    )
    return provider, create


def test_lexical_classifier_and_pure_lexical_share_request_limit(tmp_path):
    """Run actual intent classification behind the lexical request guard without a database."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.errors import install_error_handlers
    from app.api.review.runtime import RuntimeApiServices
    from app.api.review.schemas import RetrieveRequest
    from app.release.config import ReleaseSettings
    from app.release.middleware import ReleaseGuardMiddleware
    from app.retrieval.embedding.provider import DeterministicEmbeddingProvider

    ledger = SharedAIAllowance(tmp_path / "lexical.sqlite3", Decimal("1"), 2, 2)
    provider, create = _fake_openai()
    runtime = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        intent_classifier_enabled=True,
    )
    runtime._scope.manifest_index_for_decision = AsyncMock(
        return_value=SimpleNamespace(match=lambda _: ())
    )
    runtime._conversation._followup_query = lambda request: (None, request.query)
    runtime._engines.resolve_engine = AsyncMock(
        return_value=(provider, load_settings(ReleaseSettings, env_file=None).provider_budget())
    )
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(
        ReleaseGuardMiddleware,
        allowance=ledger,
        trust_proxy_headers=False,
        public_read_only=True,
    )

    @app.post("/retrieve")
    async def retrieve(request: RetrieveRequest):
        """Execute the same pre-retrieval routing path as the runtime API."""
        decision, _ = await runtime._conversation.decide_path(request)
        return {"intent": decision.intent}

    payload = {
        "session_profile": {
            "retrieval_preset": "custom",
            "custom_retrieval": {"strategy": "lexical"},
        }
    }
    with TestClient(app) as client:
        pure = client.post("/retrieve", json={**payload, "query": "hello"})
        assert pure.status_code == 200
        assert create.await_count == 0
        assert (asyncio.run(ledger.status()))[0] == 1
        admitted = client.post("/retrieve", json={**payload, "query": "Could you elaborate?"})
        denied = client.post("/retrieve", json={**payload, "query": "Explain that distinction."})
        assert admitted.status_code == 200
        assert denied.status_code == 429
        assert denied.json()["error"]["code"] == "rate_limited"
        assert int(denied.headers["Retry-After"]) > 0
        assert create.await_count == 1
        assert client.post("/retrieve", json={**payload, "query": "hello"}).status_code == 429


def test_full_openai_input_and_output_cost_is_refused_before_dispatch(tmp_path):
    """A low dollar cap blocks a large legal token request before the client or ledger changes."""
    from app.llm.schemas import BudgetExceeded, Prompt
    from app.query.intent import RoutingClassification
    from app.release.config import ReleaseSettings

    async def scenario():
        """Reproduce the previous $0.001 reservation for a $0.0252 possible call."""
        ledger = SharedAIAllowance(tmp_path / "preflight.sqlite3", Decimal("0.001"), 5, 25)
        provider, create = _fake_openai()
        budget = (
            load_settings(ReleaseSettings, env_file=None)
            .provider_budget()
            .model_copy(update={"max_cost_usd": Decimal("0.001")})
        )
        token = active_allowance.set(ledger)
        try:
            result = await provider.complete(
                Prompt(system="Classify.", user="word " * 9000), RoutingClassification, budget
            )
        finally:
            active_allowance.reset(token)
        assert result.status == "budget_exceeded"
        assert isinstance(result.refusal, BudgetExceeded)
        assert result.refusal.which == "estimated_cost_usd"
        assert result.metadata.requests == 0
        create.assert_not_awaited()
        assert (await ledger.status())[0] == Decimal("0.001")

    asyncio.run(scenario())


def test_openai_preflight_includes_schema_and_allows_default_small_call(tmp_path):
    """Schema tokens participate in the input gate and a normal $0.01 call still fits."""
    from pydantic import BaseModel, Field

    from app.llm.schemas import BudgetExceeded, Prompt
    from app.query.intent import RoutingClassification
    from app.release.config import ReleaseSettings

    class LargeSchema(BaseModel):
        """Use a schema whose description materially exceeds a small input ceiling."""

        value: str = Field(description="schema description " * 1000)

    async def scenario():
        """Compare a normal classifier with a schema-heavy request without provider I/O."""
        provider, create = _fake_openai()
        budget = (
            load_settings(ReleaseSettings, env_file=None)
            .provider_budget()
            .model_copy(
                update={
                    "max_cost_usd": Decimal("0.01"),
                    "max_input_tokens": 12000,
                }
            )
        )
        token = active_allowance.set(
            SharedAIAllowance(tmp_path / "schema.sqlite3", Decimal("1"), 5, 25)
        )
        try:
            ordinary = await provider.complete(
                Prompt(system="Classify.", user="Explain it."), RoutingClassification, budget
            )
            refused = await provider.complete(
                Prompt(system="Classify.", user="Explain it."),
                LargeSchema,
                budget.model_copy(update={"max_input_tokens": 500}),
            )
        finally:
            active_allowance.reset(token)
        assert ordinary.status == "ok"
        assert refused.status == "budget_exceeded"
        assert isinstance(refused.refusal, BudgetExceeded)
        assert refused.refusal.which == "input_tokens"
        assert create.await_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("first_call", [True, False])
@pytest.mark.parametrize("failure", ["limit", "storage"])
def test_streamed_actual_call_denial_keeps_error_and_done(tmp_path, first_call, failure):
    """After SSE starts, limits or a failed ledger stop calls through error/done events."""
    from fastapi.testclient import TestClient

    from app.api.app import create_api_app
    from app.api.dependencies import get_api_services
    from app.release.ai_allowance import reserve_openai
    from app.release.middleware import ReleaseGuardMiddleware

    ledger = SharedAIAllowance(tmp_path / "stream.sqlite3", Decimal("0.1"), 5, 25)
    if first_call and failure == "limit":
        asyncio.run(ledger.reserve_amount(Decimal("0.1")))

    class Services:
        """Stand in for provider-bearing stream work without reads or writes to user state."""

        async def review(self, request, on_node):
            """Make the ledger deny a cost reservation before its provider dispatch."""
            if not first_call:
                await reserve_openai(Decimal("0.1"))
            if failure == "storage":
                ledger.path = tmp_path
            await reserve_openai(Decimal("0.1"))
            raise AssertionError("an exhausted call must not dispatch")

    app = create_api_app()
    app.dependency_overrides[get_api_services] = lambda: Services()
    app.add_middleware(
        ReleaseGuardMiddleware,
        allowance=ledger,
        trust_proxy_headers=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/review/stream",
            json={"query": "What was revenue?", "evidence_selection": {"candidate_token": "test"}},
        )
    assert response.status_code == 200
    assert "event: error" in response.text
    assert ("daily_cost_limit" if failure == "limit" else "allowance_unavailable") in response.text
    assert "Retry after" in response.text
    if failure == "limit":
        assert "Resets at" in response.text
    assert "event: done" in response.text
    assert "internal_error" not in response.text
    assert response.headers["X-RateLimit-Remaining-Day"] == "24"


def test_five_egress_ips_fit_two_three_call_requests_with_luna(tmp_path):
    """Five egress IPs can each make two bounded requests within the shared $0.10 cap."""
    from app.llm.schemas import Prompt
    from app.query.intent import RoutingClassification
    from app.release.config import ReleaseSettings

    async def scenario():
        """Exercise actual Luna preflight with maximum output reservations and fake responses."""
        settings = load_settings(ReleaseSettings, env_file=None, environment="prod")
        allowance = SharedAIAllowance(
            tmp_path / "visitors.sqlite3",
            settings.public_daily_cost_usd,
            settings.rate_limit_per_minute,
            settings.rate_limit_per_day,
        )
        provider, create = _fake_openai()
        budget = settings.provider_budget()
        token = active_allowance.set(allowance)
        try:
            for visitor in range(5):
                for _ in range(2):
                    assert (await allowance.admit(f"egress-{visitor}")).allowed
                    for _ in range(3):
                        result = await provider.complete(
                            Prompt(system="Classify.", user="Evidence " * 8000),
                            RoutingClassification,
                            budget,
                        )
                        assert result.status == "ok"
                assert (await allowance.peek(f"egress-{visitor}")).remaining_day == 48
                assert (await allowance.peek(f"egress-{visitor}")).remaining_minute == 8
        finally:
            active_allowance.reset(token)
        assert create.await_count == 30
        assert all(call.kwargs["model"] == "gpt-5.6-luna" for call in create.await_args_list)
        remaining, _ = await allowance.status()
        assert Decimal("0") < remaining < settings.public_daily_cost_usd

    asyncio.run(scenario())
