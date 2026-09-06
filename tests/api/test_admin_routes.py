"""Administrator route injection and public-surface isolation."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from fastapi.testclient import TestClient

from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.admin_schemas import (
    AdminDocumentResource,
    CorpusJobResource,
    CorpusOperationRequest,
    DocumentFacetsResponse,
    DocumentFacetValue,
    DocumentInventoryResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationRunRequest,
    GoldenCanonicalResource,
    OperatorJobsResponse,
    UsageResponse,
)
from app.api.app import create_api_app


def _corpus_job(request: CorpusOperationRequest, job_id: str = "corpus-1") -> CorpusJobResource:
    """Return one complete shared job resource for route contract tests."""
    return CorpusJobResource(
        job_id=job_id,
        command=request,
        status="queued",
        stage="queued",
        current=0,
        total=None,
        message="Queued",
        detail_current=None,
        detail_total=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        started_at=None,
        finished_at=None,
        error_code=None,
        result_refs={},
    )


class FakeAdminServices:
    """Small route-level administrator service fixture."""

    async def corpus_snapshot(self):
        """Return one schema-compatible empty corpus."""
        return {
            "mode": "live",
            "status": {
                "schema_status": "compatible",
                "database_connected": True,
                "schema_message": "Compatible",
                "documents": 0,
                "chunks": 0,
                "embedded_chunks": 0,
                "pending_embeddings": 0,
                "bm25_ready": False,
                "writable": True,
                "provider": "deterministic",
            },
            "manifests": (),
            "documents": (),
        }

    document_filters = None

    async def document_detail(self, doc_id):
        """Return one structured detail fixture for the known document."""
        if doc_id != "ACME-FY2024":
            return None
        return {
            "document": {
                "doc_id": doc_id,
                "registry": "sec",
                "language": "en",
                "issuer": "ACME",
                "issuer_id": "123",
                "fiscal_year": 2024,
                "form": "10-K",
                "parse_status": "parsed",
                "filing_date": "2025-02-01",
                "report_period": "2024-12-31",
                "filing_id": "0000000123-25-000001",
                "source_url": "https://example.invalid/acme",
                "source_length": 1_000,
                "source_sha256": "d" * 64,
                "chunk_count": 2,
            },
            "chunks": (),
            "text_chunks": 1,
            "table_chunks": 1,
            "embedded_chunks": 2,
            "item_counts": ({"item": "7", "count": 2},),
            "embedding_identities": (
                {
                    "provider": "deterministic",
                    "model": "token-hash-384",
                    "dimensions": 384,
                    "tokenizer": "unicode-alnum:nfkc:casefold:v1",
                    "count": 2,
                },
            ),
            "snapshot_memberships": (),
        }

    async def documents(self, **filters):
        """Capture document filters and return one enriched inventory row."""
        self.document_filters = filters
        return DocumentInventoryResponse(
            documents=(
                AdminDocumentResource(
                    doc_id="ACME-FY2024",
                    registry="sec",
                    language="en",
                    issuer="ACME",
                    issuer_id="123",
                    fiscal_year=2024,
                    form="10-K",
                    filing_date="2025-02-01",
                    report_period="2024-12-31",
                    filing_id="0000000123-25-000001",
                    source_url="https://example.invalid/acme",
                    parse_status="parsed",
                    source_length=1_000,
                    source_sha256="d" * 64,
                    chunk_count=2,
                    embedded_chunks=2,
                    text_chunks=1,
                    table_chunks=1,
                    embedding_status="complete",
                    snapshot_count=1,
                ),
            ),
            total=1,
            next_cursor=None,
        )

    async def document_facets(self, registry=""):
        """Return all document facet families including index state."""
        self.facet_registry = registry
        one = (DocumentFacetValue(value="sec", count=1),)
        return DocumentFacetsResponse(
            registries=one,
            issuers=(DocumentFacetValue(value="ACME", count=1),),
            years=(DocumentFacetValue(value="2024", count=1),),
            languages=(DocumentFacetValue(value="en", count=1),),
            forms=(DocumentFacetValue(value="10-K", count=1),),
            parse_statuses=(DocumentFacetValue(value="parsed", count=1),),
            embedding_statuses=(DocumentFacetValue(value="complete", count=1),),
            snapshots=(DocumentFacetValue(value="3", count=1, label="Baseline · ready"),),
        )

    async def enqueue_corpus(self, request):
        """Echo one safe operation kind."""
        return _corpus_job(request)

    async def corpus_jobs(self):
        """Return an empty queue."""
        return {"active": None, "queued": (), "history": ()}

    async def retry_corpus(self, job_id):
        """Return one retry identity."""
        return _corpus_job(CorpusOperationRequest(kind="rebuild_bm25"), job_id)

    async def suites(self):
        """Return no suites for this route fixture."""
        return ()

    async def golden_canonical(self, suite_id):
        """Return one read-only canonical case collection."""
        return GoldenCanonicalResource(
            suite_id=suite_id,
            filename="retrieval.json",
            payload=(),
            sha256="a" * 64,
        )

    async def enqueue_evaluation(self, request: EvaluationRunRequest):
        """Return one queued evaluation."""
        return EvaluationJobResource(
            job_id="eval-1",
            request=request,
            status="queued",
            stage="queued",
            message="Queued",
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )

    async def evaluation_jobs(self):
        """Return an empty evaluation job list."""
        return EvaluationJobsResponse(jobs=())

    async def evaluation_job(self, job_id):
        """Return no job for this route fixture."""
        return None

    async def operator_job(self, job_id):
        """Return no persisted unified job for this route fixture."""
        return None

    async def operator_jobs(self):
        """Return one empty persistent unified job board."""
        return OperatorJobsResponse(jobs=(), active_count=0, queued_count=0)

    async def usage(self):
        """Return one empty local usage ledger."""
        return UsageResponse(
            runs=0,
            requests=0,
            input_tokens=0,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            estimated_cost_usd=Decimal("0"),
            latest_run_at=None,
            models=(),
        )

    async def compare(self, candidate_id, baseline_id):
        """Leave comparison unused in this focused route test."""
        raise AssertionError((candidate_id, baseline_id))

    async def retrieval_preview(self, request):
        """Leave preview unused in this focused route test."""
        raise AssertionError(request)

    async def review_preview(self, request):
        """Leave review unused in this focused route test."""
        raise AssertionError(request)


def test_admin_routes_are_absent_without_explicit_composition() -> None:
    """Keep the stable public OpenAPI surface free of administrator operations."""
    with TestClient(create_api_app()) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert not any(path.startswith("/admin") for path in paths)


def test_admin_routes_are_injected_and_typed() -> None:
    """Expose local routes only with one explicit administrator service override."""
    services = cast(RuntimeAdminApiServices, FakeAdminServices())
    with TestClient(create_api_app(admin_services=services)) as client:
        corpus = client.get("/admin/corpus")
        queued = client.post(
            "/admin/evaluations/runs",
            json={
                "suite_id": "sec-en",
                "mode": "quick",
                "profile": {},
                "target_tokens": [1024, 2048],
                "strategies": ["lexical", "vector", "hybrid"],
                "lexical_rankers": ["ts_rank_cd", "bm25"],
            },
        )
        corpus_job = client.post(
            "/admin/corpus/jobs",
            json={
                "kind": "acquire_edgar",
                "identifiers": ["NVDA"],
                "years": [2024],
            },
        )
        missing = client.get("/admin/jobs/missing")
        job_board = client.get("/admin/jobs")
        usage = client.get("/admin/usage")

    assert corpus.status_code == 200
    assert corpus.json()["status"]["schema_status"] == "compatible"
    assert queued.status_code == 200
    assert queued.json()["job_id"] == "eval-1"
    assert corpus_job.status_code == 200
    assert corpus_job.json()["command"]["kind"] == "acquire_edgar"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "operator_job_not_found"
    assert job_board.status_code == 200
    assert job_board.json() == {"jobs": [], "active_count": 0, "queued_count": 0}
    assert usage.status_code == 200
    assert usage.json()["estimated_cost_usd"] == "0"


def test_document_routes_expose_facets_coverage_and_structured_detail() -> None:
    """Forward document facets and return typed index and source detail."""
    fake = FakeAdminServices()
    services = cast(RuntimeAdminApiServices, fake)
    with TestClient(create_api_app(admin_services=services)) as client:
        page = client.get(
            "/admin/documents?issuer=ACME&embedding_status=complete&snapshot_id=3"
            "&sort=embedding_coverage&descending=true"
        )
        facets = client.get("/admin/documents/facets")
        scoped_facets = client.get("/admin/documents/facets?registry=sec")
        detail = client.get("/admin/documents/ACME-FY2024")

    assert page.status_code == 200
    assert page.json()["documents"][0]["embedding_status"] == "complete"
    assert page.json()["documents"][0]["snapshot_count"] == 1
    assert fake.document_filters == {
        "query": "",
        "registry": "",
        "issuer": "ACME",
        "fiscal_year": None,
        "language": "",
        "form": "",
        "parse_status": "",
        "embedding_status": "complete",
        "snapshot_id": 3,
        "sort": "embedding_coverage",
        "descending": True,
        "cursor": None,
        "limit": 50,
    }
    assert facets.json()["snapshots"][0]["label"] == "Baseline · ready"
    assert scoped_facets.status_code == 200 and fake.facet_registry == "sec"
    assert detail.status_code == 200
    assert detail.json()["document"]["filing_id"] == "0000000123-25-000001"
    assert detail.json()["item_counts"] == [{"item": "7", "count": 2}]


def test_golden_canonical_route_is_read_only_and_typed() -> None:
    """Expose canonical suite questions without implicitly creating a draft."""
    services = cast(RuntimeAdminApiServices, FakeAdminServices())
    with TestClient(create_api_app(admin_services=services)) as client:
        response = client.get("/admin/golden/sec-en/canonical")

    assert response.status_code == 200
    assert response.json()["filename"] == "retrieval.json"
    assert response.json()["sha256"] == "a" * 64


def test_ingestion_route_requires_and_forwards_explicit_selection():
    """Require selection identity in the shared corpus job request."""
    services = FakeAdminServices()
    received = []

    async def enqueue(request):
        """Record the validated operation without starting a worker."""
        received.append(request)
        return _corpus_job(request, "selection-job")

    services.enqueue_corpus = enqueue
    with TestClient(
        create_api_app(admin_services=cast(RuntimeAdminApiServices, services))
    ) as client:
        invalid = client.post(
            "/admin/corpus/jobs", json={"kind": "ingest_manifest", "manifest": "manifest.json"}
        )
        valid = client.post(
            "/admin/corpus/jobs",
            json={
                "kind": "ingest_manifest",
                "manifest": "manifest.json",
                "selection_id": "selected",
            },
        )
        schema = client.get("/openapi.json").json()
    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert received[0].selection_id == "selected"
    assert schema["paths"]["/admin/corpus"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("CorpusSnapshotResource")


def test_history_routes_validate_scope_and_translate_conflicts(tmp_path) -> None:
    """History routes retain typed confirmation, conflict and backup failures."""
    from app.operator.job_history import HistoryConflictError

    class HistoryServices(FakeAdminServices):
        """Expose predictable history outcomes without touching any user records."""

        async def job_history_summary(self):
            """Return explicit visible, archived and protected active counts."""
            return {"visible": 2, "archived": 1, "active": 3}

        async def manage_job_history(self, request):
            """Exercise route translation for conflict and backup errors."""
            if request.expected_count != 3:
                raise HistoryConflictError("Job history changed; refresh")
            if request.action == "delete":
                if request.confirmation != "DELETE JOB HISTORY":
                    raise ValueError("Type DELETE JOB HISTORY to confirm deletion")
                raise OSError("private filesystem details")
            return {
                "action": request.action,
                "changed_count": 3,
                "backup_id": None,
                "summary": {"visible": 3, "archived": 0, "active": 3},
            }

        def job_history_backup(self, backup_id):
            """Return only the known fixture and reject all other identities."""
            if backup_id != "known":
                raise ValueError("Invalid backup identifier")
            path = tmp_path / "backup.json"
            path.write_text('{"records": []}')
            return path

    services = cast(RuntimeAdminApiServices, HistoryServices())
    with TestClient(create_api_app(admin_services=services)) as client:
        assert client.get("/admin/jobs/history").json()["active"] == 3
        assert (
            client.post(
                "/admin/jobs/history", json={"action": "restore", "expected_count": 3}
            ).status_code
            == 200
        )
        conflict = client.post(
            "/admin/jobs/history", json={"action": "archive", "expected_count": 1}
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "history_changed"
        assert (
            client.post(
                "/admin/jobs/history", json={"action": "delete", "expected_count": 3}
            ).status_code
            == 400
        )
        failure = client.post(
            "/admin/jobs/history",
            json={"action": "delete", "expected_count": 3, "confirmation": "DELETE JOB HISTORY"},
        )
        assert failure.status_code == 503
        assert "private filesystem details" not in failure.text
        assert client.get("/admin/jobs/history/backups/unknown").status_code == 404
        assert client.get("/admin/jobs/history/backups/known").json() == {"records": []}
    with TestClient(create_api_app()) as client:
        assert client.get("/admin/jobs/history/backups/known").status_code == 404
