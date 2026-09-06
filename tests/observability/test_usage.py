"""Provider classification and persisted review/embedding usage share one honest ledger."""

import asyncio
from decimal import Decimal
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.admin_runtime import RuntimeAdminApiServices
from app.db.models import Base, OperatorJob
from app.observability.persistence import persist_run_report
from app.observability.usage import (
    USAGE_KEY,
    merge_usage,
    persist_embedding_usage,
    provider_identity,
    review_usage,
    usage_record,
)
from tests.observability.support import run_report, step_trace


@pytest.mark.parametrize(
    "url, expected, local",
    [
        ("local://ollama", "ollama", True),
        ("local://openai-compatible", "openai_compatible", True),
        ("deterministic://local", "deterministic", True),
        ("https://api.openai.com/v1/responses", "openai_responses", False),
        ("http://127.0.0.1:11434/api/chat", "ollama", True),
    ],
)
def test_historical_identity_uses_url_without_inventing_a_key_slot(url, expected, local):
    """Actual historical trace URL schemes retain provider and locality."""
    assert provider_identity(api_url=url) == {
        "provider": expected,
        "local": local,
        "credential_slot": "unknown",
    }


def test_identity_only_exposes_approved_slot_names():
    """Provider identity never turns an arbitrary key value into a displayed slot."""
    assert (
        provider_identity(provider="openai_responses", local=False, credential_slot="dev")[
            "credential_slot"
        ]
        == "OPENAI_API_KEY_LOCAL"
    )
    assert provider_identity(credential_slot="sk-not-a-slot")["credential_slot"] == "unknown"
    assert "sk-not-a-slot" not in repr(
        provider_identity(provider="sk-not-a-slot", credential_slot="sk-not-a-slot")
    )


def test_model_calls_include_gate_without_double_counting_the_same_trace():
    """New call records are authoritative; matching traces only fill historical missing fields."""
    trace = step_trace(
        node="report",
        model_name="review",
        input_tokens=20,
        output_tokens=3,
        estimated_cost_usd=Decimal("0.02"),
    )
    context = {
        "provider_identity": provider_identity(
            provider="openai_responses", local=False, credential_slot="dev"
        ),
        "model_calls": [
            {
                "node": "gate",
                "model": "review",
                "attempts": 1,
                "input_tokens": 10,
                "output_tokens": 1,
                "estimated_cost_usd": "0.01",
            },
            {
                "node": "report",
                "model": "review",
                "attempts": 1,
                "input_tokens": 20,
                "output_tokens": 3,
            },
        ],
    }
    rows = merge_usage(review_usage(context, [trace]))
    assert sum(row["requests"] for row in rows) == 2
    assert sum(row["input_tokens"] for row in rows) == 30
    assert sum(Decimal(row["estimated_cost_usd"]) for row in rows) == Decimal("0.03")
    assert {row["role"] for row in rows} == {"gate", "report"}
    assert all(row["credential_slot"] == "OPENAI_API_KEY_LOCAL" for row in rows)


def test_old_unpriced_calls_and_local_estimates_remain_explicit():
    """Missing billed usage does not become reported zero tokens or a free external request."""
    rows = review_usage(
        {
            "model_calls": [
                {
                    "node": "gate",
                    "model": "unknown",
                    "attempts": 1,
                    "input_tokens": 10,
                    "output_tokens": 2,
                }
            ]
        },
        [],
    )
    assert rows[0]["unreported_cost_requests"] == 1
    local = usage_record(
        identity=provider_identity(provider="sbert", local=True, credential_slot="none"),
        model_name="local-embedding",
        role="embedding",
        estimated_input_tokens=12,
        estimated_cost_usd=Decimal(0),
    )
    assert local["input_tokens"] == 0 and local["estimated_input_tokens"] == 12
    assert local["unreported_input_requests"] == 1 and local["unreported_cost_requests"] == 0


@pytest.mark.live_postgres
def test_live_usage_includes_archived_cli_batches_and_matches_provider_subtotals():
    """Exercise actual JSONB persistence and aggregation only in an explicitly isolated server."""
    url = os.environ.get("USAGE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("USAGE_TEST_DATABASE_URL must point to the isolated fixture server")

    async def scenario():
        """Own only connection-local temporary tables, preserving every external table."""
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            metadata = MetaData()
            for name in ("runs", "traces", "operator_jobs"):
                Base.metadata.tables[name].to_metadata(metadata, schema="pg_temp")
            await connection.run_sync(lambda sync: metadata.create_all(sync, checkfirst=False))
            await connection.commit()
            factory = async_sessionmaker(connection, expire_on_commit=False)
            async with factory() as session, session.begin():
                await persist_run_report(
                    session,
                    run_report(
                        steps=[
                            step_trace(
                                node="report", model_name="review", input_tokens=20, output_tokens=3
                            )
                        ],
                        request_context={
                            "provider_identity": provider_identity(
                                provider="openai_responses", local=False, credential_slot="dev"
                            ),
                            "model_calls": [
                                {
                                    "node": "gate",
                                    "model": "review",
                                    "attempts": 1,
                                    "input_tokens": 10,
                                    "output_tokens": 1,
                                    "estimated_cost_usd": "0.01",
                                },
                                {
                                    "node": "report",
                                    "model": "review",
                                    "attempts": 1,
                                    "input_tokens": 20,
                                    "output_tokens": 3,
                                    "estimated_cost_usd": "0.02",
                                },
                            ],
                        },
                    ),
                )
            record = usage_record(
                identity=provider_identity(
                    provider="openai_embeddings", local=False, credential_slot="prod"
                ),
                model_name="text-embedding-3-large",
                role="embedding",
                input_tokens=100,
                estimated_cost_usd=Decimal("0.000013"),
            )
            async with factory() as session:
                await persist_embedding_usage(session, record)
                ledger = (await session.execute(select(OperatorJob))).scalar_one()
                assert ledger.kind == "embedding_usage"
                assert ledger.result_refs["__history_archived"] is True
                assert ledger.result_refs[USAGE_KEY][0]["input_tokens"] == 100
            service = object.__new__(RuntimeAdminApiServices)
            service._runtime = SimpleNamespace(session_factory=factory)
            usage = await service.usage()
            assert usage.runs == 1 and usage.requests == 3 and usage.input_tokens == 130
            assert usage.estimated_cost_usd == Decimal("0.030013")
            assert sum(group.requests for group in usage.providers) == usage.requests
            assert sum(group.input_tokens for group in usage.providers) == usage.input_tokens
            assert (
                sum(group.estimated_cost_usd for group in usage.providers)
                == usage.estimated_cost_usd
            )
            assert {group.credential_slot for group in usage.providers} == {
                "OPENAI_API_KEY_LOCAL",
                "OPENAI_API_KEY_PROD",
            }
        await engine.dispose()

    asyncio.run(scenario())


def test_partial_model_calls_keep_unmatched_historical_traces():
    """A partial model-call list must not erase separately persisted charged traces."""
    report = step_trace(
        node="report",
        model_name="review",
        input_tokens=20,
        output_tokens=3,
        estimated_cost_usd=Decimal("0.02"),
    )
    grade = step_trace(
        step=2,
        node="grade",
        model_name="review",
        input_tokens=7,
        output_tokens=2,
        estimated_cost_usd=Decimal("0.007"),
    )
    records = merge_usage(
        review_usage(
            {
                "model_calls": [
                    {
                        "node": "report",
                        "model": "review",
                        "attempts": 1,
                        "input_tokens": 20,
                        "output_tokens": 3,
                    }
                ]
            },
            [report, grade],
        )
    )
    assert sum(row["requests"] for row in records) == 2
    assert sum(row["input_tokens"] for row in records) == 27
    assert sum(Decimal(row["estimated_cost_usd"]) for row in records) == Decimal("0.027")
    assert {row["role"] for row in records} == {"report", "grade"}


@pytest.mark.live_postgres
def test_direct_backfill_keeps_charged_cli_usage_when_vector_storage_fails(monkeypatch):
    """The CLI's shared backfill path commits response usage before a later vector-write failure."""
    import hashlib

    from app.retrieval import embeddings

    url = os.environ.get("USAGE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("USAGE_TEST_DATABASE_URL must point to the isolated fixture server")

    async def scenario():
        """Use one temporary ledger and a fake SDK response; never download or embed user data."""
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            metadata = MetaData()
            Base.metadata.tables["operator_jobs"].to_metadata(metadata, schema="pg_temp")
            await connection.run_sync(lambda sync: metadata.create_all(sync, checkfirst=False))
            await connection.commit()
            factory = async_sessionmaker(connection, expire_on_commit=False)

            async def missing(*args, **kwargs):
                """Provide one synthetic pending input without reading a user's corpus."""
                return [
                    embeddings.PendingEmbedding(
                        1, "fixture", hashlib.sha256(b"fixture").hexdigest()
                    )
                ]

            async def reject_store(*args):
                """Fail after the provider response to verify independent usage durability."""
                raise ValueError("fixture vector write rejected")

            async def create(**kwargs):
                """Return one fake provider response with explicit reported token usage."""
                return SimpleNamespace(
                    data=[SimpleNamespace(index=0, embedding=[1.0] * 384)],
                    usage=SimpleNamespace(prompt_tokens=17),
                )

            monkeypatch.setattr(embeddings, "_missing_batch", missing)
            monkeypatch.setattr(embeddings, "_store_batch", reject_store)
            provider = embeddings.OpenAIEmbeddingProvider(
                client=SimpleNamespace(embeddings=SimpleNamespace(create=create)),
                credential_slot="dev",
            )
            async with factory() as session:
                with pytest.raises(ValueError, match="vector write"):
                    await embeddings.embed_missing_chunks(session, provider, batch_size=1)
            async with factory() as session:
                row = (await session.execute(select(OperatorJob))).scalar_one()
                assert (
                    row.kind == "embedding_usage" and row.result_refs["__history_archived"] is True
                )
                assert row.result_refs[USAGE_KEY][0]["input_tokens"] == 17
                assert row.result_refs[USAGE_KEY][0]["unreported_input_requests"] == 0
        await engine.dispose()

    asyncio.run(scenario())
