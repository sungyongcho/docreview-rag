"""Exercise persistent public limits without provider or user-database calls."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.release.ai_allowance import SharedAIAllowance, active_allowance
from app.retrieval.embeddings import OpenAIEmbeddingProvider


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
        await limiter.check("ip")
        now[0] += 10
        await limiter.check("ip")
        reopened = SharedAIAllowance(path, Decimal("1"), 2, 3)
        assert (await reopened.check("ip")).retry_after_seconds == 50
        assert (await reopened.peek("another-ip")).remaining_day == 3
        now[0] += 51
        assert (await reopened.check("ip")).allowed
        assert not (await reopened.check("ip")).allowed
        now[0] += 86400
        assert (await reopened.peek("ip")).remaining_day == 3

    asyncio.run(scenario())


def test_utc_reset_does_not_reset_ip_window(tmp_path):
    """Previous-day spend is excluded, while recent request timestamps remain."""

    async def scenario():
        """Seed a previous UTC reservation without touching real service state."""
        ledger = SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 5, 25)
        yesterday = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(seconds=1)
        with ledger._connect() as connection:
            connection.execute(
                "INSERT INTO calls VALUES (?, 'openai', NULL, 1000000)", (yesterday.timestamp(),)
            )
        await ledger.check("ip")
        assert (await ledger.status())[0] == 1
        assert (await ledger.peek("ip")).remaining_day == 24

    asyncio.run(scenario())


def test_embedding_is_blocked_before_openai(tmp_path):
    """An exhausted allowance prevents even a query embedding from reaching its client."""

    async def scenario():
        """Use an injected local mock, never an external API."""
        ledger = SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 5, 25)
        await ledger.reserve_amount(Decimal("1"))
        create = AsyncMock()
        provider = OpenAIEmbeddingProvider(
            client=SimpleNamespace(embeddings=SimpleNamespace(create=create))
        )
        token = active_allowance.set(ledger)
        try:
            with pytest.raises(ValueError, match="Shared OpenAI allowance exhausted"):
                await provider.embed_query("test")
            create.assert_not_awaited()
        finally:
            active_allowance.reset(token)

    asyncio.run(scenario())


def test_middleware_exempts_lexical_and_reports_server_reset(tmp_path):
    """Only OpenAI-bearing paths consume persistent capacity; exhaustion has retry metadata."""
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from app.release.ai_allowance import reserve_openai
    from app.release.middleware import ReleaseGuardMiddleware

    ledger = SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 10, 25)
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=ledger,
        shared_allowance=ledger,
        trust_proxy_headers=False,
        allow_ingest=False,
        salt=ledger.salt,
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


def test_concurrent_calls_share_one_request_admission_and_denials_do_not_spend(tmp_path):
    """One request shares its admission; another denied IP request cannot reserve dollars."""
    from app.release.ai_allowance import AIAllowanceError, RequestAIAllowance

    async def scenario():
        """Race calls within one request and inspect atomic refusal of a second request."""
        ledger = SharedAIAllowance(tmp_path / "atomic.sqlite3", Decimal("1"), 1, 1)
        first = RequestAIAllowance(ledger, "ip")
        assert all(
            row[0]
            for row in await asyncio.gather(
                *[first.reserve_amount(Decimal("0.1")) for _ in range(5)]
            )
        )
        assert (await ledger.peek("ip")).remaining_day == 0
        assert (await ledger.status())[0] == Decimal("0.5")
        with pytest.raises(AIAllowanceError, match="request limit"):
            await RequestAIAllowance(ledger, "ip").reserve_amount(Decimal("0.1"))
        assert (await ledger.status())[0] == Decimal("0.5")
        empty = SharedAIAllowance(tmp_path / "empty.sqlite3", Decimal("0.01"), 1, 1)
        assert not (await RequestAIAllowance(empty, "ip").reserve_amount(Decimal("0.1")))[0]
        assert (await empty.peek("ip")).remaining_day == 1

    asyncio.run(scenario())


def _fake_openai():
    """Use the actual provider boundary with an injected client that never opens a socket."""
    from app.llm.provider import OpenAILLMProvider
    from app.workflow.gate import IntentClassification

    response = SimpleNamespace(
        output_parsed=IntentClassification(intent="casual_chat", reason="Synthetic response"),
        output_text="",
        usage=SimpleNamespace(input_tokens=20, output_tokens=20),
        id="fake",
    )
    create = AsyncMock(return_value=response)
    provider = OpenAILLMProvider(
        model_name="gpt-5.6-luna", client=SimpleNamespace(responses=SimpleNamespace(create=create))
    )
    return provider, create


def test_lexical_classifier_is_metered_but_pure_lexical_is_free(tmp_path):
    """Run actual intent classification behind the lexical request guard without a database."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.errors import install_error_handlers
    from app.api.runtime import RuntimeApiServices
    from app.api.schemas import RetrieveRequest
    from app.release.config import ReleaseSettings
    from app.release.middleware import ReleaseGuardMiddleware
    from app.retrieval.embeddings import DeterministicEmbeddingProvider

    ledger = SharedAIAllowance(tmp_path / "lexical.sqlite3", Decimal("1"), 1, 1)
    provider, create = _fake_openai()
    runtime = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        intent_classifier_enabled=True,
    )
    runtime._scope_index_for_decision = AsyncMock(return_value=SimpleNamespace(match=lambda _: ()))
    runtime._followup_query = lambda request: (None, request.query)
    runtime._engine = AsyncMock(
        return_value=(provider, ReleaseSettings(_env_file=None).provider_budget())
    )
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=ledger,
        shared_allowance=ledger,
        trust_proxy_headers=False,
        allow_ingest=False,
        public_read_only=True,
        salt=ledger.salt,
    )

    @app.post("/retrieve")
    async def retrieve(request: RetrieveRequest):
        """Execute the same pre-retrieval routing path as the runtime API."""
        decision, _ = await runtime._path_decision(request)
        return {"intent": decision.intent}

    payload = {
        "session_profile": {
            "retrieval_preset": "custom",
            "custom_retrieval": {"strategy": "lexical"},
        }
    }
    with TestClient(app) as client:
        pure = client.post("/retrieve", json={**payload, "query": "What was revenue?"})
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
        assert (
            client.post("/retrieve", json={**payload, "query": "What was revenue?"}).status_code
            == 200
        )


def test_full_openai_input_and_output_cost_is_refused_before_dispatch(tmp_path):
    """A low dollar cap blocks a large legal token request before the client or ledger changes."""
    from app.llm.schemas import Prompt
    from app.release.config import ReleaseSettings
    from app.workflow.gate import IntentClassification

    async def scenario():
        """Reproduce the previous $0.001 reservation for a $0.0252 possible call."""
        ledger = SharedAIAllowance(tmp_path / "preflight.sqlite3", Decimal("0.001"), 5, 25)
        provider, create = _fake_openai()
        budget = (
            ReleaseSettings(_env_file=None)
            .provider_budget()
            .model_copy(update={"max_cost_usd": Decimal("0.001")})
        )
        token = active_allowance.set(ledger)
        try:
            result = await provider.complete(
                Prompt(system="Classify.", user="word " * 9000), IntentClassification, budget
            )
        finally:
            active_allowance.reset(token)
        assert result.status == "budget_exceeded"
        assert result.refusal.which == "estimated_cost_usd"
        assert result.metadata.requests == 0
        create.assert_not_awaited()
        assert (await ledger.status())[0] == Decimal("0.001")

    asyncio.run(scenario())


def test_openai_preflight_includes_schema_and_allows_default_small_call(tmp_path):
    """Schema tokens participate in the input gate and a normal $0.01 call still fits."""
    from pydantic import BaseModel, Field

    from app.llm.schemas import Prompt
    from app.release.config import ReleaseSettings
    from app.workflow.gate import IntentClassification

    class LargeSchema(BaseModel):
        """Use a schema whose description materially exceeds a small input ceiling."""

        value: str = Field(description="schema description " * 1000)

    async def scenario():
        """Compare a normal classifier with a schema-heavy request without provider I/O."""
        provider, create = _fake_openai()
        budget = (
            ReleaseSettings(_env_file=None)
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
                Prompt(system="Classify.", user="Explain it."), IntentClassification, budget
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
        assert refused.refusal.which == "input_tokens"
        assert create.await_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("first_call", [True, False])
def test_streamed_actual_call_denial_keeps_error_and_done(tmp_path, first_call):
    """Deny the first or a later streamed call through structured error/done events."""
    from fastapi.testclient import TestClient

    from app.api.app import create_api_app
    from app.api.deps import get_api_services
    from app.release.ai_allowance import reserve_openai
    from app.release.middleware import ReleaseGuardMiddleware

    ledger = SharedAIAllowance(tmp_path / "stream.sqlite3", Decimal("0.1"), 5, 25)
    if first_call:
        asyncio.run(ledger.reserve_amount(Decimal("0.1")))

    class Services:
        """Stand in for provider-bearing stream work without reads or writes to user state."""

        async def review(self, request, on_node):
            """The second reservation fails after a first call used the remaining allowance."""
            await reserve_openai(Decimal("0.1"))
            await reserve_openai(Decimal("0.1"))
            raise AssertionError("an exhausted call must not dispatch")

    app = create_api_app()
    app.dependency_overrides[get_api_services] = lambda: Services()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=ledger,
        shared_allowance=ledger,
        trust_proxy_headers=False,
        allow_ingest=False,
        salt=ledger.salt,
    )
    with TestClient(app) as client:
        response = client.post("/review/stream", json={"query": "What was revenue?"})
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "daily_cost_limit" in response.text
    assert "Retry after" in response.text
    assert "Resets at" in response.text
    assert "event: done" in response.text
    assert "internal_error" not in response.text


def test_five_visitors_fit_two_three_call_questions_with_luna(tmp_path):
    """Five visitors can each make two bounded questions within the $0.10 reservation cap."""
    from app.llm.schemas import Prompt
    from app.release.ai_allowance import RequestAIAllowance, active_request_allowance
    from app.release.config import ReleaseSettings
    from app.workflow.gate import IntentClassification

    async def scenario():
        """Exercise actual Luna preflight with maximum output reservations and fake responses."""
        settings = ReleaseSettings(_env_file=None, DOCREVIEW_ENVIRONMENT="prod")
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
                    request_token = active_request_allowance.set(
                        RequestAIAllowance(allowance, f"visitor-{visitor}")
                    )
                    try:
                        for _ in range(3):
                            result = await provider.complete(
                                Prompt(system="Classify.", user="Evidence " * 8000),
                                IntentClassification,
                                budget,
                            )
                            assert result.status == "ok"
                    finally:
                        active_request_allowance.reset(request_token)
                assert (await allowance.peek(f"visitor-{visitor}")).remaining_day == 3
                assert (await allowance.peek(f"visitor-{visitor}")).remaining_minute == 0
        finally:
            active_allowance.reset(token)
        assert create.await_count == 30
        assert all(call.kwargs["model"] == "gpt-5.6-luna" for call in create.await_args_list)
        remaining, _ = await allowance.status()
        assert Decimal("0") < remaining < settings.public_daily_cost_usd

    asyncio.run(scenario())
