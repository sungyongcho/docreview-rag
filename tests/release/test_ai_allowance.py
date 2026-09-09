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
