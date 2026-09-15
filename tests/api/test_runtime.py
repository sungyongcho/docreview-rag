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


def test_public_runtime_admits_bounded_custom_retrieval_and_rejects_oversized_depth() -> None:
    """Apply the same public retrieval ceilings inside the service as the release guard."""
    from app.api.review_profile import CustomRetrievalProfile

    services = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        allow_custom_prompt_policy=False,
    )
    bounded = ReviewSessionProfile(
        retrieval_preset="custom",
        custom_retrieval=CustomRetrievalProfile(k=10, candidate_k=50),
    )
    services._validate_session_profile(bounded)

    oversized = ReviewSessionProfile(
        retrieval_preset="custom",
        custom_retrieval=CustomRetrievalProfile(k=5, candidate_k=51),
    )
    with pytest.raises(ApiProblemError) as error:
        services._validate_session_profile(oversized)
    assert error.value.status_code == 403
    assert error.value.error.code == "capability_disabled"
    assert "custom_retrieval.candidate_k" in error.value.error.message


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
        ("What about Samsung Electronics?", "005930", 2023),
        ("그럼 2024년은?", "NVDA", 2024),
        ("그럼 2024년 매출은?", "NVDA", 2024),
        ("방금 이야기해준거 한글로 다시 설명해줄래", "NVDA", 2023),
        ("Please explain that again in Korean", "NVDA", 2023),
    ],
)
def test_followups_reach_retrieval_with_replaced_scope(classified_service, query, issuer, year):
    """Clear continuations inherit or replace filing scope without a provider call."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages
    from app.workflow.gate import ConversationTurn

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run the real retrieval entry point using bounded conversation history."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await service.retrieve(
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
    assert path["intent"] == "document_review"
    assert path["source"] == "deterministic"
    assert path["matched_rule"] == "filing_followup"
    assert path["history_turns"] == 2
    assert "data center revenue" in path["retrieval_query"]
    assert path["resolved_scope"]["filters"]["issuers"] == [issuer]
    assert path["resolved_scope"]["filters"]["fiscal_years"] == [year]
    assert path["model_call_count"] == 0
    assert prompts == []


@pytest.mark.parametrize("endpoint", ["retrieve", "review"])
@pytest.mark.parametrize(
    "query,issuer",
    [
        ("Nvidia revenue", "NVDA"),
        ("What drove NVIDIA data center revenue growth?", "NVDA"),
        ("삼성전자 매출", "005930"),
        ("삼성전자 메모리 사업의 주요 위험은 무엇인가요?", "005930"),
    ],
)
def test_known_company_questions_reach_retrieval_without_classifier(
    classified_service, endpoint, query, issuer
):
    """Fully covered filing questions resolve their scope without a provider call."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run the real entry point and stop at the existing retrieval boundary."""
        request_type = RetrieveRequest if endpoint == "retrieve" else ReviewRequest
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await getattr(service, endpoint)(request_type(query=query))

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["intent"] == "document_review"
    assert path["source"] == "deterministic"
    assert path["retrieval_query"] == query
    assert path["resolved_scope"]["filters"]["issuers"] == [issuer]
    assert path["model_call_count"] == 0
    assert prompts == []


@pytest.mark.parametrize("query", ["hello", "안녕하세요", "help"])
def test_exact_greetings_use_fixed_guidance_without_classifier(classified_service, query):
    """Exact casual intents return fixed guidance at the gate with no provider call."""
    from app.api.schemas import RetrieveRequest

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    prepared = asyncio.run(service.retrieve(RetrieveRequest(query=query)))
    path = prepared.path_decision
    assert path["intent"] == "service_help"
    assert path["source"] == "deterministic"
    assert path["scope_outcome"] == "not_applicable"
    assert path["model_call_count"] == 0
    assert prompts == []


def test_korean_restatement_keeps_prior_filing_scope(classified_service):
    """A Korean restatement keeps the prior issuer and year without a provider call."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages
    from app.workflow.gate import ConversationTurn

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run retrieval on top of a prior NVDA 2024 filing turn."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await service.retrieve(
                RetrieveRequest(
                    query="방금 이야기해준거 한글로 다시 설명해줄래",
                    conversation_history=(
                        ConversationTurn(role="user", text="Nvidia revenue 2024"),
                        ConversationTurn(role="assistant", text="Prior filing answer."),
                    ),
                )
            )

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["intent"] == "document_review"
    assert path["source"] == "deterministic"
    assert path["matched_rule"] == "filing_followup"
    assert path["resolved_scope"]["filters"]["issuers"] == ["NVDA"]
    assert path["resolved_scope"]["filters"]["fiscal_years"] == [2024]
    assert path["model_call_count"] == 0
    assert prompts == []


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


def test_zero_history_bound_prevents_implicit_inheritance(classified_service):
    """A zero-turn allowance rejects an elliptical question instead of inheriting scope."""
    from app.api.review_profile import PromptPolicy
    from app.api.schemas import RetrieveRequest
    from app.workflow.gate import ConversationTurn

    service, responses, prompts = classified_service
    assert service._intent_classifier_enabled is True
    responses.append(
        {
            "intent": "document_review",
            "reason": "Elliptical question without an eligible anchor.",
            "requested_issuers": [],
            "target_scope": "unclear",
        }
    )
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query="그럼 2024년은?",
                    session_profile=ReviewSessionProfile(
                        prompt_policy=PromptPolicy(history_turns=0)
                    ),
                    conversation_history=(ConversationTurn(role="user", text="NVDA revenue 2023"),),
                )
            )
        )
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == "ambiguous_issuer"
    assert error.path_decision["stopping_stage"] == "gate"
    assert error.path_decision["history_turns"] == 0
    assert error.path_decision["retrieval_query"] == "그럼 2024년은?"
    assert error.path_decision["matched_rule"] != "filing_followup"
    assert len(prompts) == 1
    assert prompts[0]["history"] == []


@pytest.mark.parametrize("query", ["hello", "What about the weather?", "삼성전자 농담은?"])
def test_casual_input_does_not_inherit_filing_scope(routing_service, query):
    """Clear casual topics never acquire a prior filing issuer or question."""
    from app.workflow.gate import ConversationTurn

    request = ReviewRequest(
        query=query, conversation_history=(ConversationTurn(role="user", text="NVDA revenue"),)
    )
    try:
        _, path = asyncio.run(routing_service._path_decision(request))
    except ApiProblemError as failure:
        assert failure.error.code == "unsupported_request"
        rejected = failure.error.path_decision
        assert rejected["retrieval_query"] == query
        assert rejected["matched_rule"] != "filing_followup"
        return
    assert path["retrieval_query"] == query
    assert path["matched_rule"] != "filing_followup"
    if query == "hello":
        assert path["intent"] == "service_help"
        assert path["scope_outcome"] == "not_applicable"


@pytest.mark.parametrize(
    "profile,code",
    [
        (ReviewSessionProfile(corpus_scope="dart"), "query_scope_conflict"),
        (ReviewSessionProfile(fiscal_years=(2099,)), "query_scope_empty"),
        (ReviewSessionProfile(doc_ids=("not-a-provided-document",)), "query_scope_empty"),
        (ReviewSessionProfile(forms=("20-F",)), "query_scope_empty"),
    ],
)
def test_scope_stops_before_retrieval_with_action(classified_service, profile, code):
    """Conflicts and empty scopes retain the path decision and an actionable correction."""
    from app.api.schemas import RetrieveRequest

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(RetrieveRequest(query="NVDA revenue", session_profile=profile))
        )
    error = failure.value.error
    assert error.code == code
    assert error.path_decision["stopping_reason"] == code
    assert error.path_decision["suggested_scope"] == (
        "auto" if code == "query_scope_conflict" else None
    )
    assert error.path_decision["stopping_stage"] == "gate"
    assert error.path_decision["selected_scope"] == profile.corpus_scope
    assert error.path_decision["source"] == "deterministic"
    assert error.path_decision["model_call_count"] == 0
    assert prompts == []


@pytest.mark.parametrize(
    "profile,query,issuer,registry,language",
    [
        (
            ReviewSessionProfile(corpus_scope="sec", issuers=("NVDA",)),
            "revenue?",
            "NVDA",
            "sec",
            "en",
        ),
        (
            ReviewSessionProfile(corpus_scope="dart", issuers=("005930",)),
            "매출은?",
            "005930",
            "dart",
            "ko",
        ),
        (
            ReviewSessionProfile(doc_ids=("NVDA-FY2023", "NVDA-FY2024")),
            "revenue?",
            "NVDA",
            "sec",
            "en",
        ),
        (
            ReviewSessionProfile(doc_ids=("005930-FY2024",)),
            "매출은?",
            "005930",
            "dart",
            "ko",
        ),
        (
            ReviewSessionProfile(doc_ids=("005930-FY2024",)),
            "revenue?",
            "005930",
            "dart",
            "ko",
        ),
        (
            ReviewSessionProfile(doc_ids=("NVDA-FY2024",)),
            "매출은?",
            "NVDA",
            "sec",
            "en",
        ),
    ],
)
def test_unique_company_selection_anchors_short_finance_questions(
    classified_service, profile, query, issuer, registry, language
):
    """A selection narrowed to one company anchors a short question with no provider call."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run retrieval with a session profile that selects a single issuer."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await service.retrieve(RetrieveRequest(query=query, session_profile=profile))

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["intent"] == "document_review"
    assert path["source"] == "deterministic"
    resolved_scope = path["resolved_scope"]
    assert resolved_scope["source"] == "explicit"
    assert resolved_scope["filters"]["issuers"] == [issuer]
    assert resolved_scope["filters"]["registries"] == [registry]
    assert resolved_scope["filters"]["languages"] == [language]
    assert path["model_call_count"] == 0
    assert prompts == []


def test_explicit_language_filter_still_empties_anchored_document_scope(classified_service):
    """An explicit language filter is kept and empties a conflicting anchored scope."""
    from app.api.schemas import RetrieveRequest

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query="revenue?",
                    session_profile=ReviewSessionProfile(
                        doc_ids=("005930-FY2024",), languages=("en",)
                    ),
                )
            )
        )
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == "query_scope_empty"
    assert error.path_decision["stopping_stage"] == "gate"
    assert error.path_decision["model_call_count"] == 0
    assert prompts == []


def test_vague_question_with_multiple_selected_companies_is_rejected(classified_service):
    """A vague finance question spanning several companies must not search all of them."""
    from app.api.schemas import RetrieveRequest

    service, responses, prompts = classified_service
    assert service._intent_classifier_enabled is True
    responses.append(
        {
            "intent": "document_review",
            "reason": "No issuer named and the selection holds several companies.",
            "requested_issuers": [],
            "target_scope": "unclear",
        }
    )
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query="revenue?",
                    session_profile=ReviewSessionProfile(doc_ids=("NVDA-FY2024", "005930-FY2024")),
                )
            )
        )
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == "ambiguous_issuer"
    assert error.path_decision["stopping_stage"] == "gate"
    assert error.path_decision["suggested_scope"] is None
    assert len(prompts) <= 1


def test_unknown_selected_document_id_cannot_establish_a_unique_anchor(classified_service):
    """A partially unknown document selection must not collapse to the known issuer."""
    from app.api.schemas import RetrieveRequest

    service, responses, prompts = classified_service
    assert service._intent_classifier_enabled is True
    responses.append(
        {
            "intent": "document_review",
            "reason": "The selection cannot anchor a single issuer.",
            "requested_issuers": [],
            "target_scope": "context",
        }
    )
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query="revenue?",
                    session_profile=ReviewSessionProfile(
                        doc_ids=("NVDA-FY2024", "not-a-provided-document")
                    ),
                )
            )
        )
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code in ("query_scope_empty", "ambiguous_issuer")
    assert error.path_decision["stopping_stage"] == "gate"
    assert len(prompts) <= 1


def test_classifier_history_and_service_guidance_are_recorded_once(routing_service):
    """Stream preparation reuses classification and never generates a free-form answer."""
    from contextlib import asynccontextmanager
    import json

    from app.api.schemas import RetrieveRequest, RunResponse
    from app.llm.local import LocalLLMProvider
    from app.observability.stages import record_stages
    from app.workflow.gate import ConversationTurn

    prompts = []
    saved = []

    def respond(request):
        """Return structured routing through the real usage-recording adapter."""
        payload = json.loads(request.content)
        prompts.append(json.loads(payload["messages"][1]["content"]))
        assert len(prompts) == 1, "service guidance must not generate a model answer"
        content = {
            "intent": "service_help",
            "reason": "A service usage question.",
            "requested_issuers": [],
            "target_scope": "unclear",
        }
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
                query="How do I ask questions in DocReview?",
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
    assert prepared.path_decision["intent"] == "service_help"
    assert len(prompts) == 1
    assert prompts[0]["history"] == [{"role": "user", "text": "NVDA revenue"}]
    assert [call.node for call in result.execution.model_calls] == ["gate"]
    assert result.report.response_source == "canned"
    assert result.execution.path_decision["source"] == "classifier"
    assert saved[0].request_context["path_decision"]["scope_outcome"] == "not_applicable"


def classifier_wiring(service):
    """Wire a recording single-response classifier transport into the given service."""
    import json

    from app.llm.local import LocalLLMProvider

    responses = []
    prompts = []

    def respond(request):
        """Consume exactly one planned classifier response per request."""
        payload = json.loads(request.content)
        prompts.append(json.loads(payload["messages"][1]["content"]))
        assert responses, "unexpected answer generation or classifier retry"
        content = responses.pop(0)
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(content)},
                "prompt_eval_count": 8,
                "eval_count": 3,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    service._llm_providers = {
        "openai": LocalLLMProvider(
            base_url="http://test", model_name="test", protocol="ollama", client=client
        )
    }
    service._provider_budgets = {
        "openai": local_provider_budget(max_input_tokens=10000, max_output_tokens=1000)
    }
    service._intent_classifier_enabled = True
    return responses, prompts, client


@pytest.fixture
def classified_service(routing_service):
    """Exercise structured provider parsing while forbidding unplanned provider calls."""
    responses, prompts, client = classifier_wiring(routing_service)
    yield routing_service, responses, prompts
    asyncio.run(client.aclose())


@pytest.mark.parametrize("allow_custom_policy", [False, True])
def test_review_preserves_original_question_across_search_rewriting(
    classified_service, monkeypatch, allow_custom_policy
):
    """Public and DEV workflows receive the original question without another model call."""
    from app.api import runtime as runtime_module
    from app.workflow.types import WorkflowRequest

    service, _, prompts = classified_service
    service._allow_custom_prompt_policy = allow_custom_policy
    request = ReviewRequest(query="NVIDIA의 2024년 매출 성장 요인은?")
    captured = []

    def capture_request(**kwargs):
        """Validate the real workflow payload and stop before database or inference access."""
        captured.append(WorkflowRequest(**kwargs))
        raise LookupError("workflow request captured")

    async def exercise():
        """Use the real scope resolver with a separately rewritten retrieval question."""
        _, path = await service._path_decision(request)
        path = {**path, "retrieval_query": "What drove NVIDIA revenue growth in 2024?"}
        await service._review(request, on_node=None, retrieval_override=None, path=path)

    monkeypatch.setattr(runtime_module, "WorkflowRequest", capture_request)
    with pytest.raises(LookupError, match="workflow request captured"):
        asyncio.run(exercise())
    assert len(captured) == 1
    assert captured[0].original_query == request.query
    assert captured[0].query == "What drove NVIDIA revenue growth in 2024?"
    assert "same language as the Original question JSON" in captured[0].system_prompt
    assert prompts == []


def test_hbm_outlook_question_stays_deterministic_with_local_index():
    """A natural-language outlook question resolves its issuer without a provider call."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages
    from app.retrieval.scope import ManifestScopeIndex

    def stop_before_database():
        """Prove successful routing enters retrieval without using the user's database."""
        raise LookupError("retrieval boundary reached")

    service = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        session_factory=stop_before_database,
        scope_index=ManifestScopeIndex.from_entries(
            (
                filing_document(
                    registry="dart",
                    issuer="000660",
                    fiscal_year=2024,
                    aliases=("SK하이닉스", "SK hynix"),
                ),
            )
        ),
    )
    responses, prompts, client = classifier_wiring(service)
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run retrieval against the test-local SK hynix corpus index."""
        try:
            with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
                await service.retrieve(RetrieveRequest(query="SK하이닉스 HBM 전망은?"))
        finally:
            await client.aclose()

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["intent"] == "document_review"
    assert path["source"] == "deterministic"
    assert path["resolved_scope"]["filters"]["issuers"] == ["000660"]
    assert path["model_call_count"] == 0
    assert prompts == []
    assert not responses


@pytest.mark.parametrize("endpoint", ["retrieve", "review"])
@pytest.mark.parametrize(
    "query,intent,names,target,code,stage,calls",
    [
        (
            "샌디스크 성장 요인",
            "document_review",
            ["샌디스크"],
            "explicit",
            "unknown_issuer",
            "gate",
            1,
        ),
        (
            "SanDisk growth drivers",
            "document_review",
            ["SanDisk"],
            "explicit",
            "unknown_issuer",
            "gate",
            1,
        ),
        (
            "Compare Nvidia and SanDisk",
            "document_review",
            ["Nvidia", "SanDisk"],
            "explicit",
            "unknown_issuer",
            "gate",
            1,
        ),
        (
            "Nvidia and UnknownCorp revenue",
            "document_review",
            ["Nvidia", "UnknownCorp"],
            "explicit",
            "unknown_issuer",
            "gate",
            1,
        ),
        (
            "Nvidia and NvidiaAI revenue",
            "document_review",
            ["Nvidia", "NvidiaAI"],
            "explicit",
            "unknown_issuer",
            "gate",
            1,
        ),
        (
            "그 회사의 성장 요인은?",
            "document_review",
            [],
            "unclear",
            "ambiguous_issuer",
            "gate",
            1,
        ),
        ("Nvidia revenue 2099", None, [], None, "query_scope_empty", "gate", 0),
        (
            "Nvidia or another company?",
            "document_review",
            [],
            "unclear",
            "ambiguous_issuer",
            "gate",
            1,
        ),
        ("고양이와 대화하기", None, [], None, "unsupported_request", "path", 0),
        ("Pretend you are a cat", None, [], None, "unsupported_request", "path", 0),
    ],
)
def test_routing_stops_before_search_and_answer(
    classified_service, endpoint, query, intent, names, target, code, stage, calls
):
    """Both entry points reject unsupported targets without searching or generating answers."""
    from app.api.schemas import RetrieveRequest

    service, responses, prompts = classified_service
    if calls:
        responses.append(
            {
                "intent": intent,
                "reason": "Classified request.",
                "requested_issuers": names,
                "target_scope": target,
            }
        )
    request_type = RetrieveRequest if endpoint == "retrieve" else ReviewRequest
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(getattr(service, endpoint)(request_type(query=query)))
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == code
    assert error.path_decision["stopping_stage"] == stage
    assert error.path_decision["stopping_reason"] == code
    assert error.path_decision["suggested_scope"] is None
    assert error.path_decision["model_call_count"] == calls
    assert error.path_decision["source"] == ("classifier" if calls else "deterministic")
    if code == "unknown_issuer":
        assert error.path_decision["missing_issuers"] == [names[-1]]
    assert len(prompts) == calls
    if calls:
        assert prompts[0]["message"] == query
    assert not responses


@pytest.mark.parametrize(
    "query,names,target,prior,calls",
    [
        ("Nvidia growth drivers", None, None, None, 0),
        ("Compare all available companies", None, None, None, 0),
        ("Compare all available companies' revenue", None, None, None, 0),
        ("그럼 2024년은?", None, None, "NVDA revenue 2023", 0),
        (
            "NVIDIA 10-K sexual harassment risk disclosure",
            ["Nvidia"],
            "explicit",
            None,
            1,
        ),
        (
            "삼성전자 사업보고서의 성희롱 관련 위험",
            ["삼성전자"],
            "explicit",
            None,
            1,
        ),
    ],
)
def test_supported_questions_reach_search(classified_service, query, names, target, prior, calls):
    """Deterministic filing questions and classified targets both reach actual retrieval."""
    from app.api.schemas import RetrieveRequest
    from app.workflow.gate import ConversationTurn

    service, responses, prompts = classified_service
    if calls:
        responses.append(
            {
                "intent": "document_review",
                "reason": "A filing question.",
                "requested_issuers": names,
                "target_scope": target,
            }
        )
    history = (ConversationTurn(role="user", text=prior),) if prior else ()
    with pytest.raises(LookupError, match="retrieval boundary reached"):
        asyncio.run(service.retrieve(RetrieveRequest(query=query, conversation_history=history)))
    assert len(prompts) <= calls


@pytest.mark.parametrize("endpoint", ["retrieve", "review"])
@pytest.mark.parametrize(
    "query",
    [
        "Compare all available companies' revenue",
        "모든 회사의 매출을 비교해줘",
    ],
)
def test_explicit_corpus_wide_scope_keeps_every_language(classified_service, endpoint, query):
    """A confirmed all-corpus request is never narrowed by its own query language."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run the real entry point and stop at the existing retrieval boundary."""
        request_type = RetrieveRequest if endpoint == "retrieve" else ReviewRequest
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await getattr(service, endpoint)(request_type(query=query))

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["intent"] == "document_review"
    assert path["source"] == "deterministic"
    assert path["matched_rule"] == "corpus_wide_comparison"
    assert path["target_scope"] == "all"
    resolved_scope = path["resolved_scope"]
    assert resolved_scope["source"] == "explicit"
    assert resolved_scope["filters"]["registries"] == []
    assert resolved_scope["filters"]["languages"] == []
    assert resolved_scope["filters"]["issuers"] == []
    assert path["model_call_count"] == 0
    assert prompts == []


@pytest.mark.parametrize("language", ["en", "ko"])
def test_corpus_wide_scope_preserves_explicit_language_filter(classified_service, language):
    """A user-chosen language filter still narrows an all-corpus request."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages

    service, _, prompts = classified_service
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Run a corpus-wide question carrying an explicit language selection."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await service.retrieve(
                RetrieveRequest(
                    query="Compare all available companies' revenue",
                    session_profile=ReviewSessionProfile(languages=(language,)),
                )
            )

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["target_scope"] == "all"
    resolved_scope = path["resolved_scope"]
    assert resolved_scope["source"] == "explicit"
    assert resolved_scope["filters"]["languages"] == [language]
    assert path["model_call_count"] == 0
    assert prompts == []


def test_corpus_wide_followup_restatement_carries_all_scope(classified_service):
    """A restatement of a rule-confirmed all-corpus turn stays corpus-wide."""
    from app.api.schemas import RetrieveRequest
    from app.observability.stages import record_stages
    from app.workflow.gate import ConversationTurn

    service, _, prompts = classified_service
    events = []

    async def observe(event):
        """Collect the actual server scope before the database boundary."""
        events.append(event)

    async def exercise():
        """Continue a confirmed corpus-wide question with a bounded restatement."""
        with record_stages(observe), pytest.raises(LookupError, match="retrieval boundary"):
            await service.retrieve(
                RetrieveRequest(
                    query="Please explain that again for 2024",
                    conversation_history=(
                        ConversationTurn(
                            role="user", text="Compare all available companies' revenue"
                        ),
                        ConversationTurn(role="assistant", text="Prior answer."),
                    ),
                )
            )

    asyncio.run(exercise())
    path = next(
        event.path_decision for event in events if event.node == "route" and event.phase == "end"
    )
    assert path["intent"] == "document_review"
    assert path["source"] == "deterministic"
    assert path["matched_rule"] == "filing_followup"
    assert path["target_scope"] == "all"
    assert "Compare all available companies" in path["retrieval_query"]
    resolved_scope = path["resolved_scope"]
    assert resolved_scope["filters"]["languages"] == []
    assert resolved_scope["filters"]["issuers"] == []
    assert resolved_scope["filters"]["fiscal_years"] == [2024]
    assert path["model_call_count"] == 0
    assert prompts == []


def test_mixed_prior_turn_cannot_anchor_a_followup(classified_service):
    """A prior turn the gate never resolved cannot seed follow-up scope."""
    from app.api.schemas import RetrieveRequest
    from app.workflow.gate import ConversationTurn

    service, responses, prompts = classified_service
    assert service._intent_classifier_enabled is True
    responses.append(
        {
            "intent": "document_review",
            "reason": "The prior turn never resolved to a filing scope.",
            "requested_issuers": [],
            "target_scope": "unclear",
        }
    )
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query="그럼 2024년은?",
                    conversation_history=(
                        ConversationTurn(
                            role="user", text="Compare Nvidia to all companies' revenue"
                        ),
                        ConversationTurn(role="assistant", text="Prior answer."),
                    ),
                )
            )
        )
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == "ambiguous_issuer"
    assert error.path_decision["stopping_stage"] == "gate"
    assert error.path_decision["retrieval_query"] == "그럼 2024년은?"
    assert error.path_decision["matched_rule"] != "filing_followup"
    assert len(prompts) == 1


@pytest.mark.parametrize("endpoint", ["retrieve", "review"])
def test_classifier_all_without_corpus_wide_cue_is_clarified(classified_service, endpoint):
    """A model-expanded all scope without an explicit cue never reaches search."""
    from app.api.schemas import RetrieveRequest

    service, responses, prompts = classified_service
    assert service._intent_classifier_enabled is True
    responses.append(
        {
            "intent": "document_review",
            "reason": "Treat the question as a corpus-wide comparison.",
            "requested_issuers": [],
            "target_scope": "all",
        }
    )
    request_type = RetrieveRequest if endpoint == "retrieve" else ReviewRequest
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(getattr(service, endpoint)(request_type(query="SanDisk growth drivers")))
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == "ambiguous_issuer"
    assert error.path_decision["stopping_stage"] == "gate"
    assert error.path_decision["stopping_reason"] == "ambiguous_issuer"
    assert error.path_decision["target_scope"] == "all"
    assert error.path_decision["model_call_count"] == 1
    assert len(prompts) == 1
    assert not responses


def test_roleplay_overrides_previous_filing_context(classified_service):
    """A clear roleplay request after a filing turn is rejected without a provider call."""
    from app.api.schemas import RetrieveRequest
    from app.workflow.gate import ConversationTurn

    service, _, prompts = classified_service
    assert service._intent_classifier_enabled is True
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query="Pretend Nvidia is a cat and talk to me",
                    conversation_history=(ConversationTurn(role="user", text="NVDA revenue"),),
                )
            )
        )
    error = failure.value.error
    assert error.code == "unsupported_request"
    assert error.path_decision["stopping_stage"] == "path"
    assert error.path_decision["source"] == "deterministic"
    assert error.path_decision["model_call_count"] == 0
    assert error.path_decision["retrieval_query"] == "Pretend Nvidia is a cat and talk to me"
    assert prompts == []


def test_restatement_after_unresolved_prior_cannot_inherit_scope(classified_service):
    """A restatement of an unresolved multi-target turn gets clarification, not retrieval."""
    from app.api.schemas import RetrieveRequest
    from app.workflow.gate import ConversationTurn

    service, responses, prompts = classified_service
    assert service._intent_classifier_enabled is True
    responses.append(
        {
            "intent": "document_review",
            "reason": "The prior turn never resolved all of its targets.",
            "requested_issuers": [],
            "target_scope": "unclear",
        }
    )
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query="Please explain that again in Korean",
                    conversation_history=(
                        ConversationTurn(role="user", text="Nvidia and UnknownCorp revenue"),
                        ConversationTurn(role="assistant", text="Prior answer."),
                    ),
                )
            )
        )
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == "ambiguous_issuer"
    assert error.path_decision["stopping_stage"] == "gate"
    assert len(prompts) <= 1


@pytest.mark.parametrize(
    "query",
    [
        "Explain UnknownCorp revenue again in Korean",
        "다시 UnknownCorp 매출을 설명해줘",
    ],
)
def test_restatement_with_new_unknown_target_never_inherits_prior_issuer(classified_service, query):
    """A restatement naming a new issuer must not silently reuse the prior company."""
    from app.api.schemas import RetrieveRequest
    from app.workflow.gate import ConversationTurn

    service, responses, prompts = classified_service
    assert service._intent_classifier_enabled is True
    responses.append(
        {
            "intent": "document_review",
            "reason": "A new explicit target replaces the prior scope.",
            "requested_issuers": ["UnknownCorp"],
            "target_scope": "explicit",
        }
    )
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(
            service.retrieve(
                RetrieveRequest(
                    query=query,
                    conversation_history=(
                        ConversationTurn(role="user", text="Nvidia revenue 2024"),
                        ConversationTurn(role="assistant", text="Prior filing answer."),
                    ),
                )
            )
        )
    assert failure.value.status_code == 422
    error = failure.value.error
    assert error.code == "unknown_issuer"
    assert error.path_decision["stopping_stage"] == "gate"
    assert error.path_decision["missing_issuers"] == ["UnknownCorp"]
    assert len(prompts) == 1
    assert not responses


def test_invalid_classification_is_a_technical_failure(classified_service):
    """Missing routing fields cannot silently become a broad search or canned success."""
    from app.api.schemas import RetrieveRequest

    service, responses, _ = classified_service
    responses.extend([{"intent": "document_review", "reason": "Incomplete."}] * 3)
    with pytest.raises(ApiProblemError) as failure:
        asyncio.run(service.retrieve(RetrieveRequest(query="SanDisk growth")))
    assert failure.value.status_code == 503
    assert failure.value.error.code == "provider_unavailable"
