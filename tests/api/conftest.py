"""Deterministic service fixtures for the HTTP boundary tests."""

from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app.api.app import create_api_app
from app.api.review_profile import resolve_retrieval_profile
from app.api.schemas import EvidenceHit, RetrieveResponse
from app.ingestion.seed import SeedResult
from app.observability.types import StepTrace, build_run_report
from app.retrieval.types import ChunkHit
from app.workflow.types import EvidenceCitation, ProviderFailure, WorkflowReport

SOURCE_SHA256 = "d" * 64


@pytest.fixture
def hit() -> ChunkHit:
    """Return one complete source-cited retrieval hit."""
    context = "ACME FY2024 - Item 7"
    body = "Revenue increased by ten percent."
    return ChunkHit(
        chunk_id=7,
        doc_id="ACME-FY2024",
        item="7",
        kind="text",
        citation=context,
        start_char=100,
        end_char=180,
        source_sha256=SOURCE_SHA256,
        body=body,
        context_header=context,
        index_text=f"{context}\n\n{body}",
        score=1.0,
    )


@pytest.fixture
def trace() -> StepTrace:
    """Return one deterministic provider trace with raw output."""
    return StepTrace(
        step=1,
        node="grade",
        model_name="deterministic-mock",
        api_url="deterministic://local",
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=Decimal("0"),
        request_time_ms=1.0,
        llm_output='{"grades":[]}',
        retries=0,
        error=None,
    )


@pytest.fixture
def successful_run(hit):
    """Return one successful supported run report."""
    report = WorkflowReport(
        label="SUPPORTED",
        answer="Revenue increased by ten percent.",
        citations=(
            EvidenceCitation(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                citation=hit.citation,
                start_char=hit.start_char,
                end_char=hit.end_char,
                source_sha256=hit.source_sha256,
            ),
        ),
        rationale="The cited filing chunk states the increase.",
        reasons=(),
    )
    return build_run_report(
        run_id="run-supported",
        status="ok",
        total_time_seconds=0.1,
        system_prompt="Use only filing evidence.",
        node_path=("retrieve", "grade", "check", "report"),
        steps=(),
        report=report.model_dump(mode="json"),
    )


@pytest.fixture
def budget_run():
    """Return one structured pre-node budget refusal."""
    return build_run_report(
        run_id="run-budget",
        status="budget_exceeded",
        total_time_seconds=0.0,
        system_prompt="Use only filing evidence.",
        node_path=(),
        steps=(),
        report={
            "reason": {
                "code": "budget_exceeded",
                "resource": "iterations",
                "limit": 0,
                "observed": 0,
                "blocked_node": "retrieve",
            }
        },
    )


@pytest.fixture
def schema_rejected_run(trace):
    """Return one schema-rejected run retaining its raw trace."""
    failure = ProviderFailure(
        node="grade",
        status="schema_rejected",
        attempts=2,
        details=("grades field is required",),
    )
    return build_run_report(
        run_id="run-schema",
        status="schema_rejected",
        total_time_seconds=0.1,
        system_prompt="Use only filing evidence.",
        node_path=("retrieve", "grade"),
        steps=(trace,),
        report={"reason": failure.model_dump(mode="json")},
    )


class FakeApiServices:
    """Configurable in-memory service implementation with no live dependencies."""

    def __init__(self):
        self.hits = ()
        self.documents = ()
        self.seed_result = SeedResult(documents=0, chunks=0)
        self.review_result = None
        self.stream_states: tuple[tuple[str, object], ...] = ()
        self.runs = {}
        self.traces = {}
        self.eval_results = ()
        self.snapshots = ()
        self.snapshot_comparison = None
        self.retrieve_error = None
        self.ingest_error = None
        self.review_error = None
        self.last_retrieve_request = None
        self.last_ingest_request = None
        self.last_review_request = None
        self.last_eval_limit = None

    async def retrieve(self, request):
        """Record the request and return the configured hits, or raise the staged error."""
        self.last_retrieve_request = request
        if self.retrieve_error is not None:
            raise self.retrieve_error
        hits = tuple(self.hits)
        return RetrieveResponse(
            query=request.query,
            results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in hits),
            candidates=(),
            candidate_token="test-candidate",
            candidate_expires_at=2_000_000_000,
            score_stage="rrf",
            component_rankings={"vector": [hit.chunk_id for hit in hits], "lexical": []},
            resolved_profile=resolve_retrieval_profile(request.session_profile),
            resolved_scope=None,
        )

    async def list_documents(self):
        """Return the configured document collection."""
        return self.documents

    async def ingest(self, request):
        """Record the request and return the seed result, or raise the staged error."""
        self.last_ingest_request = request
        if self.ingest_error is not None:
            raise self.ingest_error
        return self.seed_result

    async def review(self, request, on_node=None):
        """Replay staged node states when observed, then return the configured report."""
        self.last_review_request = request
        if self.review_error is not None:
            raise self.review_error
        if self.review_result is None:
            raise RuntimeError("review fixture is not configured")
        if on_node is not None:
            for node, state in self.stream_states:
                await on_node(node, state)
        return self.review_result

    async def get_run(self, run_id):
        """Return the run resource for this identity, or None when absent."""
        return self.runs.get(run_id)

    async def get_traces(self, run_id):
        """Return the traces recorded for this run, or None when absent."""
        return self.traces.get(run_id)

    async def list_eval_results(self, limit):
        """Record the requested limit and return that many results."""
        self.last_eval_limit = limit
        return self.eval_results[:limit]

    async def list_snapshots(self, *, public_only):
        """Return configured immutable snapshots."""
        assert public_only is True
        return self.snapshots

    async def compare_snapshots(self, baseline_id, candidate_id):
        """Return one configured read-only snapshot comparison."""
        assert (baseline_id, candidate_id) == (1, 2)
        return self.snapshot_comparison


@pytest.fixture
def services() -> FakeApiServices:
    """Return a fresh fake service boundary for every route test."""
    return FakeApiServices()


@pytest.fixture
def client_factory():
    """Build a no-network TestClient around an injected service implementation."""

    def build(services=None) -> TestClient:
        """Build a client over the given services, or over none at all."""
        return TestClient(create_api_app(services), raise_server_exceptions=False)

    return build
