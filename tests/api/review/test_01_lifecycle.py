"""HTTP review execution across retrieval, providers, workflow, and persistence."""

import asyncio
from decimal import Decimal
import json
from typing import cast

from fastapi.testclient import TestClient
import httpx
from openai import OpenAIError
import pytest

from app.api.app import create_api_app
from app.api.review.profiles import ReviewSessionProfile
from app.api.review.runtime import RuntimeApiServices
from app.api.review.schemas import ReviewRequest
from app.db.session_factory import SessionFactory
from app.llm.local.provider import LocalLLMProvider
from app.llm.schemas import ProviderBudget, RawProviderResponse, TokenPricing
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.search.service import ComponentRankings, RetrievalResult
from tests.api.support import MemorySession, write_scope_manifest
from tests.ingestion.support import filing_document
from tests.llm.support import DeterministicLLMProvider, raw


def provider_budget() -> ProviderBudget:
    """Return an explicit zero-price allowance for offline provider responses."""
    return ProviderBudget(
        max_input_tokens=1_000,
        max_output_tokens=1_000,
        max_cost_usd=Decimal("0"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0"),
            output_per_million_usd=Decimal("0"),
        ),
    )


def test_http_review_grades_evidence_and_persists_the_returned_report(tmp_path, hit):
    """Run real provider parsing and workflow guards between offline I/O boundaries."""
    unrelated_body = "The board met in June."
    unrelated = hit.model_copy(
        update={
            "chunk_id": 8,
            "body": unrelated_body,
            "index_text": f"{hit.context_header}\n\n{unrelated_body}",
            "start_char": 200,
            "end_char": 230,
        }
    )
    sessions = []
    retrieval_calls = []
    model_calls = []
    persisted = []
    replies = [
        {
            "grades": [
                {"chunk_id": hit.chunk_id, "relevant": True, "reason": "States revenue growth."},
                {"chunk_id": unrelated.chunk_id, "relevant": False, "reason": "Board meeting."},
            ]
        },
        {
            "label": "SUPPORTED",
            "answer": hit.body,
            "citation_chunk_ids": [hit.chunk_id],
            "reason": "The filing states the increase.",
        },
    ]

    def session_factory():
        """Track request sessions so model calls can check transaction ownership."""
        session = MemorySession()
        sessions.append(session)
        return session

    async def retrieval_service(session, query, *, provider, k, filters, plan, **options):
        """Simulate retrieval opening a database transaction and returning ranked evidence."""
        session.transaction_open = True
        retrieval_calls.append({"query": query, "filters": filters, "plan": plan})
        return RetrievalResult(
            candidates=(hit, unrelated),
            hits=(hit, unrelated),
            score_stage="rrf",
            component_rankings=ComponentRankings(
                vector=(hit.chunk_id, unrelated.chunk_id), lexical=()
            ),
        )

    def respond(request):
        """Answer the actual adapter without keeping retrieval's transaction open."""
        assert sessions[-1].transaction_open is False
        model_calls.append(json.loads(request.content))
        assert replies, "unexpected model retry or additional workflow call"
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(replies.pop(0))},
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )

    async def run_persister(session, run, traces):
        """Capture real sanitized records while the runtime owns the write transaction."""
        assert session.transaction_open is True
        persisted.append((session, run, tuple(traces)))
        return run

    profile = {
        "retrieval_preset": "custom",
        "custom_retrieval": {"k": 3, "route_by_language": True},
        "doc_ids": [hit.doc_id],
        "registries": ["sec"],
        "kinds": [hit.kind],
        "prompt_policy": {"max_context_chars": 10000, "workflow_budget": {"max_iterations": 4}},
    }

    async def exercise():
        """Use in-process HTTP for both evidence preview and the resulting review."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as provider_client:
            provider = LocalLLMProvider(
                base_url="http://model.test",
                model_name="test-model",
                protocol="ollama",
                client=provider_client,
            )
            services = RuntimeApiServices(
                embedding_provider=DeterministicEmbeddingProvider(),
                session_factory=cast(SessionFactory, session_factory),
                llm_providers={"openai": provider},
                provider_budgets={"openai": provider_budget()},
                retrieval_service=retrieval_service,
                run_persister=run_persister,
                corpus_root=write_scope_manifest(
                    tmp_path, (filing_document(issuer="ACME", document_id=hit.doc_id),)
                ),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_api_app(services)),
                base_url="http://api.test",
            ) as client:
                request = {"query": "Revenue?", "session_profile": profile}
                return await client.post("/retrieve", json=request), await client.post(
                    "/review", json=request
                )

    retrieved, reviewed = asyncio.run(exercise())

    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["query"] == "Revenue?"
    assert retrieved.json()["results"][0] == {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "item": "7",
        "section_title": "Management's Discussion and Analysis",
        "kind": "text",
        "citation": hit.citation,
        "start_char": hit.start_char,
        "end_char": hit.end_char,
        "source_sha256": hit.source_sha256,
        "body": hit.body,
        "context_header": hit.context_header,
        "score": hit.score,
    }
    assert retrieved.json()["resolved_profile"]["k"] == 3
    assert [item["chunk_id"] for item in retrieved.json()["results"]] == [hit.chunk_id, 8]
    assert reviewed.status_code == 200, reviewed.text
    result = reviewed.json()
    assert result["report"]["answer"] == hit.body
    assert result["report"]["label"] == "SUPPORTED"
    assert result["report"]["citations"] == [
        {
            "chunk_id": hit.chunk_id,
            "doc_id": hit.doc_id,
            "citation": hit.citation,
            "start_char": hit.start_char,
            "end_char": hit.end_char,
            "source_sha256": hit.source_sha256,
        }
    ]
    execution = result["execution"]
    assert execution["effective_settings"]["effective_provider_budget"]["max_input_tokens"] == 1000
    assert execution["effective_settings"]["max_context_chars"] == 10000
    assert execution["effective_settings"]["run_limits"]["max_iterations"] == 4
    stages = execution["stage_results"]
    grade = next(stage for stage in stages if stage["node"] == "grade")
    assert grade["kept_chunk_ids"] == [hit.chunk_id]
    assert grade["rejected_chunk_ids"] == [unrelated.chunk_id]
    assert [call["node"] for call in execution["model_calls"]] == ["grade", "check"]
    assert sum(call["input_tokens"] for call in execution["model_calls"]) == 20
    assert not replies
    assert hit.body in model_calls[0]["messages"][1]["content"]
    assert unrelated.body in model_calls[0]["messages"][1]["content"]
    assert hit.body in model_calls[1]["messages"][1]["content"]
    assert unrelated.body not in model_calls[1]["messages"][1]["content"]
    assert [call["query"] for call in retrieval_calls] == ["Revenue?", "Revenue?"]
    for call in retrieval_calls:
        assert call["plan"].lexical_ranker == "ts_rank_cd"
        assert call["plan"].route_by_language is True
        assert call["filters"].doc_ids == (hit.doc_id,)
        assert call["filters"].registries == ("sec",)
        assert call["filters"].kinds == (hit.kind,)
    ((session, run, traces),) = persisted
    assert run.run_id == result["run_id"]
    assert run.report == result["report"]
    assert [trace.node for trace in traces] == ["grade", "check"]
    assert session is sessions[1]
    assert session.rollbacks == 1
    assert session.transaction_open is False


def test_balanced_retrieve_does_not_require_an_answer_or_translation_provider(tmp_path, hit):
    """Keep provider-free evidence retrieval available when language routing is off."""

    async def retrieval_service(session, query, *, provider, k, filters, plan, **options):
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
        session_factory=cast(SessionFactory, MemorySession),
        retrieval_service=retrieval_service,
        corpus_root=write_scope_manifest(
            tmp_path, (filing_document(issuer="ACME", document_id=hit.doc_id),)
        ),
        query_routing_enabled=True,
    )

    with TestClient(create_api_app(services)) as client:
        response = client.post(
            "/retrieve",
            json={"query": "Revenue?", "session_profile": {"issuers": ["ACME"]}},
        )

    assert response.status_code == 200
    assert response.json()["results"][0]["chunk_id"] == hit.chunk_id


@pytest.mark.parametrize("scope,languages", [("auto", []), ("sec", ["en"])])
def test_korean_preset_retrieval_uses_the_issuer_language_without_translation(
    tmp_path, hit, scope, languages
):
    """Keep an English NVIDIA query on SEC evidence without requiring a translation model."""
    observed = []

    async def retrieval_service(session, query, *, provider, k, filters, plan, **options):
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
        session_factory=cast(SessionFactory, MemorySession),
        retrieval_service=retrieval_service,
        query_routing_enabled=True,
        corpus_root=write_scope_manifest(
            tmp_path, [filing_document(issuer="NVDA", aliases=("NVDA", "NVIDIA"))]
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
@pytest.mark.parametrize("entrypoint", ["review", "preview"])
def test_review_translation_respects_the_preset_and_actual_corpus_language(
    tmp_path, preset, query, expected_variants, entrypoint
):
    """Pass enabled corpus-language variants through the runner into retrieval."""
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

    async def retrieval_service(session, query, *, provider, k, filters, plan, **options):
        """Observe the actual retrieval input; empty evidence needs no answer model."""
        observed.append((query, filters, options["query_variants"]))
        return RetrievalResult(
            candidates=(),
            hits=(),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(), lexical=()),
        )

    async def run_persister(session, run, traces):
        """Keep this routing regression independent of persistence I/O."""
        return run

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, MemorySession),
        llm_providers={"openai": provider},
        provider_budgets={"openai": provider_budget()},
        retrieval_service=retrieval_service,
        run_persister=run_persister,
        query_routing_enabled=True,
        corpus_root=write_scope_manifest(
            tmp_path, [filing_document(issuer="NVDA", aliases=("NVDA", "NVIDIA"))]
        ),
    )
    session_profile = ReviewSessionProfile(retrieval_preset=preset)
    if entrypoint == "preview":
        from types import SimpleNamespace

        from app.api.review.previews import ReviewPreviewRequest, _review_preview
        from app.api.review.profiles import resolve_retrieval_profile
        from app.retrieval.search.profiles import RetrievalProfile

        profile = resolve_retrieval_profile(session_profile, services.bm25_parameters)
        asyncio.run(
            _review_preview(
                SimpleNamespace(runtime=services),
                ReviewPreviewRequest(
                    query=query,
                    profile=RetrievalProfile.model_validate(
                        profile.model_dump(exclude={"name", "preset"})
                    ),
                ),
            )
        )
    else:
        asyncio.run(services.review(ReviewRequest(query=query, session_profile=session_profile)))

    ((retrieved_query, filters, variants),) = observed
    assert retrieved_query == query
    assert filters.languages == ("en",)
    assert variants == (expected_variants or None)
    assert len(provider.prompts) == len(expected_variants)


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


@pytest.mark.parametrize(
    "failure,status,code,message",
    [
        (
            ValueError("lexical retrieval cannot span corpus languages"),
            400,
            "invalid_request",
            "lexical retrieval cannot span corpus languages",
        ),
        (
            OpenAIError("private embedding provider endpoint"),
            503,
            "provider_unavailable",
            "Provider is unavailable (OpenAIError).",
        ),
    ],
)
def test_retrieval_failures_are_typed_and_hide_provider_details(failure, status, code, message):
    """Translate retrieval-domain rejection and embedding-provider failure at the HTTP boundary."""

    async def rejecting_retrieval(session, query, *, provider, k, filters, plan, **options):
        """Fail where the retrieval plan or its embedding provider rejects the request."""
        raise failure

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, MemorySession),
        retrieval_service=rejecting_retrieval,
    )

    with TestClient(create_api_app(services), raise_server_exceptions=False) as client:
        response = client.post(
            "/retrieve",
            json={
                "query": "revenue",
                "session_profile": {"issuers": ["NVDA"], "languages": ["en", "ko"]},
            },
        )

    assert response.status_code == status
    assert response.json()["error"] == {
        "code": code,
        "message": message,
        "details": [],
    }
    assert "private embedding provider endpoint" not in response.text


def test_provider_failure_is_recorded_and_redacted_before_http_response(tmp_path, hit):
    """A real provider failure leaves a typed 503 and a safe persisted run."""
    secret = "custom-sensitive-value"
    persisted = []

    class UnavailableProvider(DeterministicLLMProvider):
        """Fail at dispatch so the real provider and workflow failure handling run."""

        async def _request(self, prompt, schema, budget):
            """Model an upstream failure carrying a configured secret."""
            raise RuntimeError(f"provider unavailable: {secret}")

    async def retrieval_service(session, query, *, provider, k, filters, plan, **options):
        """Supply evidence so the workflow must attempt its grade call."""
        return RetrievalResult(
            candidates=(hit,),
            hits=(hit,),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(hit.chunk_id,), lexical=()),
        )

    async def run_persister(session, run, traces):
        """Retain the sanitized records generated by the failed workflow."""
        persisted.append((run, tuple(traces)))
        return run

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, MemorySession),
        llm_providers={"openai": UnavailableProvider(())},
        provider_budgets={"openai": provider_budget()},
        retrieval_service=retrieval_service,
        run_persister=run_persister,
        secret_values=(secret,),
        corpus_root=write_scope_manifest(
            tmp_path, (filing_document(issuer="ACME", document_id=hit.doc_id),)
        ),
    )
    with TestClient(create_api_app(services)) as client:
        response = client.post(
            "/review",
            json={
                "query": "Revenue?",
                "session_profile": {
                    "issuers": ["ACME"],
                    "prompt_policy": {"additional_instructions": f"Use {secret}"},
                },
            },
        )

    assert response.status_code == 503
    result = response.json()
    assert result["status"] == "error"
    assert result["failure"]["code"] == "provider_failure"
    assert result["failure"]["status"] == "provider_error"
    assert result["failure"]["node"] == "grade"
    assert result["failure"]["attempts"] == 1
    assert secret not in response.text
    ((run, traces),) = persisted
    assert run.run_id == result["run_id"]
    assert run.report["reason"] == result["failure"]
    assert secret not in run.system_prompt
    assert secret not in json.dumps(run.request_context)
    assert secret not in json.dumps(run.report)
    assert len(traces) == 1 and traces[0].node == "grade"
    assert secret not in str(traces[0].error)


def test_allowance_denial_after_a_billed_call_keeps_the_run_on_record(tmp_path, hit):
    """A check call the shared allowance denies after the grade call was billed still
    persists the billed run, and the caller still receives the denial for its 429."""
    from app.release.ai_allowance import AIAllowanceError
    from app.workflow.runner import BilledRunAllowanceError

    grade = json.dumps(
        {"grades": [{"chunk_id": hit.chunk_id, "relevant": True, "reason": "Direct evidence."}]}
    )

    class CappedProvider(DeterministicLLMProvider):
        """Deny the second request before it is sent, as the allowance reservation does."""

        async def _request(self, prompt, schema, budget):
            """Serve the grade call, then refuse the check call."""
            if self.prompts:
                raise AIAllowanceError("public_daily_limit", "Daily AI allowance reached.", 60)
            return await super()._request(prompt, schema, budget)

    async def retrieval_service(session, query, *, provider, k, filters, plan, **options):
        """Return the one staged hit."""
        del session, query, provider, k, filters, plan
        return RetrievalResult(
            candidates=(hit,),
            hits=(hit,),
            score_stage="rrf",
            component_rankings=ComponentRankings(vector=(hit.chunk_id,), lexical=()),
        )

    persisted = []

    async def run_persister(session, run, traces):
        """Record the sanitized records that reached persistence."""
        persisted.append((run, tuple(traces)))
        return run

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=cast(SessionFactory, MemorySession),
        llm_providers={"openai": CappedProvider([raw(grade, input_tokens=900, output_tokens=40)])},
        provider_budgets={"openai": provider_budget()},
        retrieval_service=retrieval_service,
        run_persister=run_persister,
        corpus_root=write_scope_manifest(
            tmp_path, (filing_document(issuer="ACME", document_id=hit.doc_id),)
        ),
    )
    request = ReviewRequest.model_validate(
        {"query": "Revenue?", "session_profile": {"issuers": ["ACME"]}}
    )

    with pytest.raises(BilledRunAllowanceError) as raised:
        asyncio.run(services.review(request))

    assert (raised.value.code, raised.value.retry_after) == ("public_daily_limit", 60)
    ((run, traces),) = persisted
    assert run.run_id == raised.value.report.run_id
    assert run.status == "budget_exceeded"
    assert [trace.node for trace in traces] == ["grade"]
    assert run.report["reason"]["details"][0] == "public_daily_limit"
