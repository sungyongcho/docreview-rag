"""Request-scoped local model selection without database or inference side effects."""

import asyncio

import httpx
import pytest

from app.api.errors import ApiProblemError
from app.api.review_profile import ReviewSessionProfile
from app.api.runtime import RuntimeApiServices
from app.api.schemas import ReviewRequest
from app.llm.local_connection import LocalConnectionManager
from app.llm.local_engine import local_provider_budget
from app.llm.local_inventory import LocalModelInventory
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.ingestion.support import filing_document


def local_services(names: list[str]) -> RuntimeApiServices:
    """Build real provider selection over an explicitly controlled model inventory."""
    inventory = LocalModelInventory(
        base_url="http://host/v1",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"id": name} for name in names]})
        ),
    )
    return RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        llm_providers={},
        provider_budgets={
            "local": local_provider_budget(max_input_tokens=1000, max_output_tokens=100)
        },
        local_inventory=inventory,
    )


def test_single_model_is_pinned_without_changing_the_requested_engine() -> None:
    """A single model is resolved once and cannot later switch to a replacement."""
    services = local_services(["answer"])
    profile = asyncio.run(services._local_profile(ReviewSessionProfile(engine="local")))
    assert profile.local_model == "answer"
    assert profile.engine == "local"
    other = local_services(["replacement"])
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(other._local_profile(profile))
    assert error.value.error.code == "local_model_unavailable"
    openai = ReviewSessionProfile()
    assert asyncio.run(services._local_profile(openai)) is openai


def test_multiple_models_require_a_choice_and_isolate_concurrent_requests() -> None:
    """Two conversations get separate providers and never mutate a global active model."""
    services = local_services(["first", "second"])
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(services._local_profile(ReviewSessionProfile(engine="local")))
    assert error.value.error.code == "local_model_required"

    async def resolve() -> list:
        """Resolve independent selections concurrently through the same runtime."""
        return await asyncio.gather(
            *(
                services._engine(
                    ReviewRequest(
                        query="question",
                        session_profile=ReviewSessionProfile(engine="local", local_model=name),
                    )
                )
                for name in ("first", "second")
            )
        )

    first, second = asyncio.run(resolve())
    assert first[0].model_name == "first"
    assert second[0].model_name == "second"
    assert first[0] is not second[0]


def test_empty_inventory_blocks_local_execution() -> None:
    """An explicitly chosen local engine never falls back to another provider."""
    with pytest.raises(ApiProblemError) as error:
        asyncio.run(local_services([])._local_profile(ReviewSessionProfile(engine="local")))
    assert error.value.error.code == "local_model_unavailable"


def test_request_pins_endpoint_and_provider_across_connection_changes(tmp_path) -> None:
    """Running requests keep their endpoint and model while the next request uses a saved change."""
    manager = LocalConnectionManager(
        initial_base_url="http://first/v1",
        path=tmp_path / "connection.json",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"id": "answer"}]})
        ),
    )
    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        llm_providers={},
        provider_budgets={
            "local": local_provider_budget(max_input_tokens=1000, max_output_tokens=100)
        },
        local_connection=manager,
    )
    request = ReviewRequest(query="question", session_profile=ReviewSessionProfile(engine="local"))

    async def exercise() -> None:
        """Resolve stages before and after a switch, then enter another request boundary."""
        async with services._request_connection(request.session_profile):
            first, _ = await services._engine(request)
            assert first._base_url == "http://first/v1"
            await manager.connect("http://second/v1")
            later, _ = await services._engine(request)
            assert later is first
            assert later.model_name == "answer"
            assert not first._client.is_closed
        assert first._client.is_closed
        async with services._request_connection(request.session_profile):
            next_request, _ = await services._engine(request)
            assert next_request._base_url == "http://second/v1"
            assert next_request is not first
        assert next_request._client.is_closed

    asyncio.run(exercise())


def test_production_rejects_local_and_custom_controls_before_retrieval() -> None:
    """Even retrieval and deterministic chat must enforce the configured public limits."""
    from app.api.review_profile import PromptPolicy
    from app.api.schemas import RetrieveRequest

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        allow_local_engine=False,
        allow_custom_prompt_policy=False,
    )
    for profile in (
        ReviewSessionProfile(engine="local"),
        ReviewSessionProfile(prompt_policy=PromptPolicy(additional_instructions="changed")),
    ):
        with pytest.raises(ApiProblemError) as error:
            asyncio.run(services.retrieve(RetrieveRequest(query="hello", session_profile=profile)))
        assert error.value.status_code == 403
        with pytest.raises(ApiProblemError) as error:
            asyncio.run(services.review(ReviewRequest(query="hello", session_profile=profile)))
        assert error.value.status_code == 403


def test_resolved_scope_is_observed_before_retrieval_without_model_or_database_calls() -> None:
    """Emit real alias resolution before entering the database retrieval boundary."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages
    from app.retrieval.scope import ManifestScopeIndex

    events = []

    def stop_before_database():
        """Stop deliberately after routing to avoid database and inference side effects."""
        raise LookupError("retrieval boundary reached")

    async def observe(event) -> None:
        """Collect measured events from the real runtime resolver."""
        events.append(event)

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=stop_before_database,
        scope_index=ManifestScopeIndex.from_entries(
            (
                filing_document(
                    registry="dart",
                    issuer="005930",
                    fiscal_year=2024,
                    aliases=("삼성전자", "Samsung Electronics"),
                ),
            )
        ),
    )

    async def exercise() -> None:
        """Run normal runtime resolution until its injected database boundary."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await services.retrieve(
                RetrieveRequest(
                    query="삼성전자 매출",
                    session_profile=ReviewSessionProfile(fiscal_years=(2024,)),
                )
            )

    asyncio.run(exercise())
    assert [(event.node, event.phase) for event in events] == [
        ("gate", "start"),
        ("gate", "end"),
        ("route", "start"),
        ("route", "end"),
        ("retrieve", "start"),
        ("retrieve", "end"),
    ]
    assert events[1].path_decision["intent"] == "document_review"
    scope = events[3].resolved_scope
    assert scope["source"] == "alias"
    assert scope["filters"]["registries"] == ["dart"]
    assert scope["filters"]["issuers"] == ["005930"]
    assert scope["filters"]["fiscal_years"] == [2024]


def test_missing_candidate_metadata_is_an_explicit_failure(hit):
    """Never guess filing metadata from legacy-looking or opaque document identifiers."""
    from app.retrieval.scope import ManifestScopeIndex
    from app.retrieval.service import ComponentRankings, RetrievalResult

    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        scope_index=ManifestScopeIndex.from_entries(()),
    )
    result = RetrievalResult(
        candidates=(hit,),
        hits=(hit,),
        score_stage="rrf",
        component_rankings=ComponentRankings(vector=(), lexical=()),
    )
    with pytest.raises(ApiProblemError) as failure:
        service._candidate_resource(hit, rank=1, result=result)
    assert failure.value.status_code == 503
    assert failure.value.error.code == "evidence_metadata_unavailable"


def test_ingest_forwards_selection_and_model_planning_provider(tmp_path, monkeypatch):
    """Pass the selected source set and actual embedding provider through the thread boundary."""
    from contextlib import asynccontextmanager

    import app.api.runtime as runtime_module
    from app.api.schemas import IngestRequest
    from app.ingestion.seed import SeedResult
    from app.retrieval.embeddings import DeterministicEmbeddingProvider
    from tests.ingestion.seed.support import sample_batch

    provider = DeterministicEmbeddingProvider()
    batch = sample_batch()
    manifest = tmp_path / "manifest.json"

    @asynccontextmanager
    async def sessions():
        """Keep this argument-contract check free of database calls."""
        yield object()

    def load(path, *, selection_id, embedding_provider, expected_documents):
        """Inspect the actual model-aware planning arguments."""
        assert path == manifest
        assert selection_id == "selected"
        assert embedding_provider is provider
        return batch

    async def persist(session, received, *, chunk_batch_size):
        """Preserve the prepared batch at the persistence boundary."""
        assert received is batch
        return SeedResult(documents=1, chunks=2)

    monkeypatch.setattr(runtime_module, "load_seed_batch", load)
    monkeypatch.setattr(runtime_module, "persist_seed_batch_with_stats", persist)
    service = RuntimeApiServices(
        session_factory=sessions, embedding_provider=provider, corpus_root=tmp_path
    )
    result = asyncio.run(
        service.ingest(
            IngestRequest(
                manifest_path="manifest.json", selection_id="selected", create_schema=False
            )
        )
    )
    assert result.documents == 1 and result.chunks == 2


@pytest.fixture
def routing_service():
    """Use a two-registry manifest and stop at the actual retrieval boundary."""
    from app.retrieval.scope import ManifestScopeIndex

    def stop_before_database():
        """Prove successful routing enters retrieval without using the user's database."""
        raise LookupError("retrieval boundary reached")

    return RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=stop_before_database,
        scope_index=ManifestScopeIndex.from_entries(
            (
                filing_document(
                    registry="sec", issuer="NVDA", fiscal_year=2023, aliases=("NVDA", "Nvidia")
                ),
                filing_document(
                    registry="sec", issuer="NVDA", fiscal_year=2024, aliases=("NVDA", "Nvidia")
                ),
                filing_document(
                    registry="dart",
                    issuer="005930",
                    fiscal_year=2023,
                    aliases=("삼성전자", "Samsung Electronics"),
                ),
                filing_document(
                    registry="dart",
                    issuer="005930",
                    fiscal_year=2024,
                    aliases=("삼성전자", "Samsung Electronics"),
                ),
            )
        ),
    )


@pytest.mark.parametrize(
    "query,issuer,year",
    [
        ("삼성전자는?", "005930", 2023),
        ("그럼 2024년은?", "NVDA", 2024),
        ("그럼 2024년 매출은?", "NVDA", 2024),
    ],
)
def test_followups_reach_retrieval_with_replaced_scope(routing_service, query, issuer, year):
    """Follow-up retrieval preserves the topic and replaces only newly specified scope."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages
    from app.workflow.gate import ConversationTurn

    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run the real retrieval entry point using bounded conversation history."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await routing_service.retrieve(
                RetrieveRequest(
                    query=query,
                    conversation_history=(
                        ConversationTurn(role="user", text="NVDA data center revenue 2023"),
                        ConversationTurn(role="assistant", text="Prior filing answer."),
                    ),
                )
            )

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["matched_rule"] == "filing_followup"
    assert path["history_turns"] == 2
    assert "data center revenue" in path["retrieval_query"]
    assert path["resolved_scope"]["filters"]["issuers"] == [issuer]
    assert path["resolved_scope"]["filters"]["fiscal_years"] == [year]


@pytest.mark.parametrize("limit,expected", [(0, 0), (1, 1), (2, 2)])
def test_server_enforces_history_bounds(routing_service, limit, expected):
    """A client cannot restore excluded filing context through an oversized allowed history."""
    from app.api.review_profile import PromptPolicy
    from app.workflow.gate import ConversationTurn

    request = ReviewRequest(
        query="그럼 2024년은?",
        session_profile=ReviewSessionProfile(prompt_policy=PromptPolicy(history_turns=limit)),
        conversation_history=(
            ConversationTurn(role="user", text="NVDA revenue 2023"),
            ConversationTurn(role="assistant", text="Prior answer"),
        ),
    )
    _, path = asyncio.run(routing_service._path_decision(request))
    assert path["history_turns"] == expected
    assert (path["matched_rule"] == "filing_followup") is (limit == 2)
    if limit < 2:
        assert path["retrieval_query"] == request.query


@pytest.mark.parametrize("query", ["hello", "What about the weather?", "삼성전자 농담은?"])
def test_casual_input_does_not_inherit_filing_scope(routing_service, query):
    """Clear casual topics never acquire a prior filing issuer or question."""
    from app.workflow.gate import ConversationTurn

    request = ReviewRequest(
        query=query, conversation_history=(ConversationTurn(role="user", text="NVDA revenue"),)
    )
    _, path = asyncio.run(routing_service._path_decision(request))
    assert path["retrieval_query"] == query
    assert path["matched_rule"] != "filing_followup"
    if query == "hello":
        assert path["intent"] == "casual_chat"
        assert path["scope_outcome"] == "not_applicable"


@pytest.mark.parametrize(
    "profile,code",
    [
        (ReviewSessionProfile(corpus_scope="dart"), "query_scope_conflict"),
        (ReviewSessionProfile(fiscal_years=(2099,)), "query_scope_empty"),
    ],
)
def test_scope_stops_before_retrieval_with_action(routing_service, profile, code):
    """Conflicts and empty scopes retain the path decision and an actionable correction."""
    from app.api.schemas import RetrieveRequest

    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            routing_service.retrieve(RetrieveRequest(query="NVDA revenue", session_profile=profile))
        )
    error = failure.value.error
    assert error.code == code
    assert error.path_decision["stopping_reason"] == code
    assert error.path_decision["suggested_scope"] == "auto"
    assert error.path_decision["selected_scope"] == profile.corpus_scope


def test_classifier_history_and_chat_calls_are_recorded_once(routing_service):
    """Stream preparation reuses its classification and counts the actual classifier/chat calls."""
    from contextlib import asynccontextmanager
    import json

    from app.api.schemas import RetrieveRequest, RunResponse
    from app.llm.local import LocalLLMProvider
    from app.observability.stages import record_stages
    from app.workflow.gate import ConversationTurn

    prompts = []
    saved = []

    def respond(request):
        """Return structured classifier/chat results through the real usage-recording adapter."""
        payload = json.loads(request.content)
        prompts.append(json.loads(payload["messages"][1]["content"]))
        content = (
            {"intent": "casual_chat", "reason": "A casual topic."}
            if len(prompts) == 1
            else {"answer": "Nice weather."}
        )
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(content)},
                "prompt_eval_count": 8,
                "eval_count": 3,
            },
        )

    @asynccontextmanager
    async def transaction():
        """Provide only the transaction lifetime required by the injected persister."""
        yield

    class Session:
        """Transaction-only stand-in; any unexpected database access fails."""

        begin = staticmethod(transaction)

    @asynccontextmanager
    async def sessions():
        """Isolate persistence from the user's corpus database."""
        yield Session()

    async def persist(session, run, traces):
        """Capture the actual records created by the runtime."""
        saved.append(run)

    async def exercise():
        """Execute the same preparation/review pair used by the SSE endpoint."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = LocalLLMProvider(
                base_url="http://test", model_name="test", protocol="ollama", client=client
            )
            routing_service._llm_providers = {"openai": provider}
            routing_service._provider_budgets = {
                "openai": local_provider_budget(max_input_tokens=10000, max_output_tokens=1000)
            }
            routing_service._intent_classifier_enabled = True
            routing_service._session_factory = sessions
            routing_service._run_persister = persist
            request = ReviewRequest(
                query="What about the weather?",
                conversation_history=(ConversationTurn(role="user", text="NVDA revenue"),),
            )
            with record_stages():
                prepared = await routing_service.retrieve(
                    RetrieveRequest(
                        query=request.query, conversation_history=request.conversation_history
                    )
                )
                report = await routing_service.review(request)
            return prepared, RunResponse.from_run_report(report)

    prepared, result = asyncio.run(exercise())
    assert prepared.path_decision["intent"] == "casual_chat"
    assert len(prompts) == 2
    assert prompts[0]["history"] == [{"role": "user", "text": "NVDA revenue"}]
    assert [call.node for call in result.execution.model_calls] == ["gate", "chat"]
    assert result.execution.path_decision["source"] == "classifier"
    assert saved[0].request_context["path_decision"]["scope_outcome"] == "not_applicable"
