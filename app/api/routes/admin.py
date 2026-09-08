"""SSH-only corpus and evaluation experiment resources."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.api.admin_deps import AdminServices
from app.api.admin_schemas import (
    CorpusJobResource,
    CorpusJobsResource,
    CorpusOperationRequest,
    CorpusSnapshotResource,
    DocumentDetailResponse,
    DocumentEmbeddingStatus,
    DocumentFacetsResponse,
    DocumentInventoryResponse,
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationResultDetailResponse,
    EvaluationRunRequest,
    GoldenCanonicalResource,
    GoldenCaseUpdateRequest,
    GoldenDraftRequest,
    GoldenRevisionActionRequest,
    GoldenRevisionResource,
    GoldenSuiteId,
    GoldenSuiteResource,
    JobHistoryRequest,
    JobHistoryResultResource,
    JobHistorySummaryResource,
    LocalConnectionRequest,
    LocalConnectionResponse,
    LocalDiagnosticsRequest,
    LocalDiagnosticsResponse,
    LocalServerRequest,
    LocalServerSelectionRequest,
    OperatorJobResource,
    OperatorJobsResponse,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    ReviewPreviewRequest,
    ReviewPreviewResponse,
    SnapshotCreateRequest,
    SnapshotVisibilityRequest,
    UsageResponse,
)
from app.api.errors import ApiProblemError, not_found, translate_runtime_errors
from app.api.preset_store import PresetCatalog, StoredPreset, preset_store
from app.api.schemas import ErrorResponse, SnapshotComparisonResponse, SnapshotResource
from app.config import get_settings
from app.operator.job_history import HistoryConflictError

router = APIRouter(prefix="/admin", tags=["admin"])
ResultId = Annotated[int, Query(gt=0)]


@router.get(
    "/corpus", response_model=CorpusSnapshotResource, responses={503: {"model": ErrorResponse}}
)
async def corpus_snapshot(services: AdminServices) -> CorpusSnapshotResource:
    """Return live corpus, schema, index, manifest, and document state."""
    async with translate_runtime_errors():
        return await services.corpus_snapshot()


@router.get("/documents", response_model=DocumentInventoryResponse)
async def document_inventory(
    services: AdminServices,
    query: str = "",
    registry: str = "",
    issuer: str = "",
    fiscal_year: int | None = None,
    language: str = "",
    form: str = "",
    parse_status: str = "",
    embedding_status: DocumentEmbeddingStatus | None = None,
    snapshot_id: Annotated[int | None, Query(gt=0)] = None,
    sort: Literal[
        "doc_id",
        "issuer",
        "fiscal_year",
        "filing_date",
        "chunk_count",
        "embedding_coverage",
    ] = "doc_id",
    descending: bool = False,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DocumentInventoryResponse:
    """Return one filtered and sortable live document page."""
    async with translate_runtime_errors():
        return await services.documents(
            query=query,
            registry=registry,
            issuer=issuer,
            fiscal_year=fiscal_year,
            language=language,
            form=form,
            parse_status=parse_status,
            embedding_status=embedding_status,
            snapshot_id=snapshot_id,
            sort=sort,
            descending=descending,
            cursor=cursor,
            limit=limit,
        )


@router.get("/documents/facets", response_model=DocumentFacetsResponse)
async def document_facets(services: AdminServices, registry: str = "") -> DocumentFacetsResponse:
    """Return live registry, issuer, year, language, form, and status facets."""
    async with translate_runtime_errors():
        return await services.document_facets(registry=registry)


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
async def document_detail(doc_id: str, services: AdminServices) -> DocumentDetailResponse:
    """Return bounded metadata and chunk previews for one document."""
    async with translate_runtime_errors():
        detail = await services.document_detail(doc_id)
    if detail is None:
        raise not_found("document", doc_id)
    return DocumentDetailResponse.model_validate(detail)


@router.post(
    "/corpus/jobs", response_model=CorpusJobResource, responses={400: {"model": ErrorResponse}}
)
async def enqueue_corpus(
    request: CorpusOperationRequest,
    services: AdminServices,
) -> dict[str, Any]:
    """Queue one safe corpus acquisition, ingest, or indexing operation."""
    async with translate_runtime_errors():
        return await services.enqueue_corpus(request)


@router.get("/corpus/jobs", response_model=CorpusJobsResource)
async def corpus_jobs(services: AdminServices) -> dict[str, Any]:
    """Return current corpus job queue and bounded history."""
    return await services.corpus_jobs()


@router.post(
    "/corpus/jobs/{job_id}/retry",
    response_model=CorpusJobResource,
    responses={400: {"model": ErrorResponse}},
)
async def retry_corpus(job_id: str, services: AdminServices) -> dict[str, Any]:
    """Retry one known failed corpus job."""
    async with translate_runtime_errors():
        return await services.retry_corpus(job_id)


@router.get("/evaluations/suites", response_model=tuple[GoldenSuiteResource, ...])
async def evaluation_suites(services: AdminServices) -> tuple[GoldenSuiteResource, ...]:
    """Return golden suite provenance and source readiness."""
    async with translate_runtime_errors():
        return await services.suites()


@router.get(
    "/golden/{suite_id}/canonical",
    response_model=GoldenCanonicalResource,
)
async def golden_canonical(
    suite_id: GoldenSuiteId, services: AdminServices
) -> GoldenCanonicalResource:
    """Return validated read-only canonical cases for one suite."""
    async with translate_runtime_errors():
        return await services.golden_canonical(suite_id)


@router.get(
    "/golden/{suite_id}/revisions",
    response_model=tuple[GoldenRevisionResource, ...],
)
async def golden_revisions(
    suite_id: GoldenSuiteId, services: AdminServices
) -> tuple[GoldenRevisionResource, ...]:
    """Return newest-first revisions for one golden suite."""
    async with translate_runtime_errors():
        return await services.golden_revisions(suite_id)


@router.post("/golden/{suite_id}/drafts", response_model=GoldenRevisionResource)
async def create_golden_draft(
    suite_id: GoldenSuiteId,
    request: GoldenDraftRequest,
    services: AdminServices,
) -> GoldenRevisionResource:
    """Create a draft from canonical JSON or one selected parent."""
    async with translate_runtime_errors():
        return await services.create_golden_draft(suite_id, request.parent_id)


@router.put(
    "/golden/revisions/{revision_id}/cases/{case_id}",
    response_model=GoldenRevisionResource,
)
async def replace_golden_case(
    revision_id: int,
    case_id: str,
    request: GoldenCaseUpdateRequest,
    services: AdminServices,
) -> GoldenRevisionResource:
    """Replace one case using an expected draft digest."""
    async with translate_runtime_errors():
        return await services.replace_golden_case(
            revision_id,
            case_id,
            expected_sha256=request.expected_sha256,
            payload=request.case,
        )


@router.post(
    "/golden/revisions/{revision_id}/validate",
    response_model=GoldenRevisionResource,
)
async def validate_golden_revision(
    revision_id: int,
    request: GoldenRevisionActionRequest,
    services: AdminServices,
) -> GoldenRevisionResource:
    """Validate one exact draft against corpus source bytes."""
    async with translate_runtime_errors():
        return await services.validate_golden_revision(revision_id, request.expected_sha256)


@router.post(
    "/golden/revisions/{revision_id}/publish",
    response_model=GoldenRevisionResource,
)
async def publish_golden_revision(
    revision_id: int,
    request: GoldenRevisionActionRequest,
    services: AdminServices,
) -> GoldenRevisionResource:
    """Atomically publish one validated revision."""
    async with translate_runtime_errors():
        return await services.publish_golden_revision(revision_id, request.expected_sha256)


@router.get("/snapshots", response_model=tuple[SnapshotResource, ...])
async def list_admin_snapshots(services: AdminServices) -> tuple[SnapshotResource, ...]:
    """Return public and private local snapshots."""
    async with translate_runtime_errors():
        return await services.snapshots()


@router.post("/snapshots", response_model=SnapshotResource)
async def create_snapshot(
    request: SnapshotCreateRequest, services: AdminServices
) -> SnapshotResource:
    """Create one immutable snapshot from a persisted eval result."""
    async with translate_runtime_errors():
        return await services.create_snapshot(request)


@router.put("/snapshots/{snapshot_id}/visibility", response_model=SnapshotResource)
async def set_snapshot_visibility(
    snapshot_id: int,
    request: SnapshotVisibilityRequest,
    services: AdminServices,
) -> SnapshotResource:
    """Publish or hide one ready snapshot without changing its identity."""
    async with translate_runtime_errors():
        return await services.set_snapshot_visibility(snapshot_id, request)


@router.get("/snapshots/compare", response_model=SnapshotComparisonResponse)
async def compare_admin_snapshots(
    services: AdminServices,
    baseline_id: ResultId,
    candidate_id: ResultId,
) -> SnapshotComparisonResponse:
    """Compare any two local snapshots without executing evaluation work."""
    async with translate_runtime_errors():
        return await services.compare_snapshot_results(baseline_id, candidate_id)


@router.post("/evaluations/runs", response_model=EvaluationJobResource)
async def enqueue_evaluation(
    request: EvaluationRunRequest,
    services: AdminServices,
) -> EvaluationJobResource:
    """Queue one quick live-index or isolated matrix evaluation."""
    async with translate_runtime_errors():
        return await services.enqueue_evaluation(request)


@router.get("/evaluations/runs", response_model=EvaluationJobsResponse)
async def evaluation_runs(services: AdminServices) -> EvaluationJobsResponse:
    """Return newest-first evaluation job state."""
    return await services.evaluation_jobs()


@router.get("/usage", response_model=UsageResponse)
async def provider_usage(services: AdminServices) -> UsageResponse:
    """Return locally persisted token and estimated-cost totals."""
    async with translate_runtime_errors():
        return await services.usage()


@router.get("/jobs/history", response_model=JobHistorySummaryResource)
async def job_history_summary(services: AdminServices) -> JobHistorySummaryResource:
    """Read protected active and terminal history counts."""
    async with translate_runtime_errors():
        return await services.job_history_summary()


@router.post("/jobs/history", response_model=JobHistoryResultResource)
async def manage_job_history(
    request: JobHistoryRequest, services: AdminServices
) -> JobHistoryResultResource:
    """Apply one explicitly confirmed terminal-history operation."""
    try:
        async with translate_runtime_errors():
            return await services.manage_job_history(request)
    except HistoryConflictError as error:
        raise ApiProblemError(
            status_code=409, code="history_changed", message=str(error)
        ) from error
    except OSError as error:
        raise ApiProblemError(
            status_code=503,
            code="history_backup_failed",
            message="The history backup could not be written; deletion was not completed.",
        ) from error


@router.get("/jobs/history/backups/{backup_id}", response_class=FileResponse)
async def job_history_backup(backup_id: str, services: AdminServices) -> FileResponse:
    """Download an owned backup without exposing arbitrary filesystem paths."""
    try:
        path = services.job_history_backup(backup_id)
    except (ValueError, OSError) as error:
        raise not_found("job_history_backup", backup_id) from error
    return FileResponse(
        path, media_type="application/json", filename=f"job-history-{backup_id}.json"
    )


@router.get("/jobs", response_model=OperatorJobsResponse)
async def operator_jobs(services: AdminServices) -> OperatorJobsResponse:
    """Return the persistent unified corpus and evaluation job board."""
    async with translate_runtime_errors():
        return await services.operator_jobs()


@router.get(
    "/jobs/{job_id}",
    response_model=OperatorJobResource,
    responses={404: {"model": ErrorResponse}},
)
async def operator_job(job_id: str, services: AdminServices) -> OperatorJobResource:
    """Return one persisted operator job by identity."""
    job = await services.operator_job(job_id)
    if job is None:
        raise not_found("operator_job", job_id)
    return job


@router.post("/jobs/{job_id}/retry", response_model=OperatorJobResource)
async def retry_operator_job(job_id: str, services: AdminServices) -> OperatorJobResource:
    """Create a new queued job from failed or interrupted request provenance."""
    async with translate_runtime_errors():
        return await services.retry_operator_job(job_id)


@router.post("/jobs/{job_id}/cancel", response_model=OperatorJobResource)
async def cancel_operator_job(job_id: str, services: AdminServices) -> OperatorJobResource:
    """Cancel queued work or cooperatively cancel a supported running corpus job."""
    async with translate_runtime_errors():
        return await services.cancel_operator_job(job_id)


@router.get(
    "/evaluations/jobs/{job_id}",
    response_model=EvaluationJobResource,
    responses={404: {"model": ErrorResponse}},
)
async def evaluation_job(job_id: str, services: AdminServices) -> EvaluationJobResource:
    """Return one evaluation job by its public identifier."""
    job = await services.evaluation_job(job_id)
    if job is None:
        raise not_found("evaluation_job", job_id)
    return job


@router.get(
    "/evaluations/results/{result_id}",
    response_model=EvaluationResultDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
async def evaluation_result(
    result_id: int,
    services: AdminServices,
) -> EvaluationResultDetailResponse:
    """Return absolute metrics and bounded case details for one result."""
    async with translate_runtime_errors():
        detail = await services.evaluation_result(result_id)
    if detail is None:
        raise not_found("evaluation_result", str(result_id))
    return detail


@router.get("/evaluations/compare", response_model=EvaluationComparisonResponse)
async def compare_evaluations(
    services: AdminServices,
    candidate_id: ResultId,
    baseline_id: ResultId,
) -> EvaluationComparisonResponse:
    """Return metrics and per-case changes between compatible artifacts."""
    async with translate_runtime_errors():
        return await services.compare(candidate_id, baseline_id)


@router.post("/retrieval/preview", response_model=RetrievalPreviewResponse)
async def retrieval_preview(
    request: RetrievalPreviewRequest,
    services: AdminServices,
) -> RetrievalPreviewResponse:
    """Execute one query through an explicit session-scoped retrieval profile."""
    async with translate_runtime_errors():
        return await services.retrieval_preview(request)


@router.post("/review/preview", response_model=ReviewPreviewResponse)
async def review_preview(
    request: ReviewPreviewRequest,
    services: AdminServices,
) -> ReviewPreviewResponse:
    """Run one evidence-checked review through an explicit retrieval profile."""
    async with translate_runtime_errors():
        return await services.review_preview(request)


@router.get("/local-llm/connection", response_model=LocalConnectionResponse)
async def local_connection_state(services: AdminServices) -> dict[str, Any]:
    """Return private connection settings without changing the selected endpoint."""
    async with translate_runtime_errors():
        return await services.local_connection_state()


@router.post("/local-llm/connection", response_model=LocalConnectionResponse)
async def connect_local_llm(
    request: LocalConnectionRequest,
    services: AdminServices,
) -> dict[str, Any]:
    """Verify and save a replacement endpoint, leaving the old one active on failure."""
    async with translate_runtime_errors():
        return await services.update_local_connection("connect", request.base_url, request.protocol)


@router.post("/local-llm/disconnect", response_model=LocalConnectionResponse)
async def disconnect_local_llm(services: AdminServices) -> dict[str, Any]:
    """Save explicit disconnection so environment defaults cannot reactivate it."""
    async with translate_runtime_errors():
        return await services.update_local_connection("disconnect")


@router.post("/local-llm/servers", response_model=LocalConnectionResponse)
async def register_local_server(
    request: LocalServerRequest, services: AdminServices
) -> dict[str, Any]:
    """Register and select a verified named server while preserving prior choices on failure."""
    async with translate_runtime_errors():
        return await services.update_local_connection(
            "add", request.base_url, request.protocol, name=request.name
        )


@router.post("/local-llm/select", response_model=LocalConnectionResponse)
async def select_local_server(
    request: LocalServerSelectionRequest, services: AdminServices
) -> dict[str, Any]:
    """Verify and select a saved endpoint or Default without accepting a new URL."""
    async with translate_runtime_errors():
        return await services.update_local_connection("select", server_id=request.server_id)


@router.post("/local-llm/diagnostics", response_model=LocalDiagnosticsResponse)
async def diagnose_local_server(
    request: LocalDiagnosticsRequest, services: AdminServices
) -> dict[str, Any]:
    """Inspect bounded metadata without modifying the active connection or loading a model."""
    async with translate_runtime_errors():
        return await services.diagnose_local_connection(
            server_id=request.server_id, base_url=request.base_url, protocol=request.protocol
        )


@router.post("/local-llm/reset", response_model=LocalConnectionResponse)
async def reset_local_llm(services: AdminServices) -> dict[str, Any]:
    """Restore the endpoint selected by environment, dotenv, or startup defaults."""
    async with translate_runtime_errors():
        return await services.update_local_connection("reset")


def _require_preset_dev() -> None:
    """Keep file resources unavailable even if admin composition is enabled in PROD."""
    if get_settings().environment == "prod":
        raise not_found("presets", "directory")


@router.get("/presets", response_model=PresetCatalog)
def list_presets(services: AdminServices, version: str | None = None) -> PresetCatalog:
    """Read a debounced catalog or return only its unchanged version."""
    _require_preset_dev()
    return preset_store.catalog(version)


@router.put("/presets", response_model=StoredPreset)
def put_preset(preset: StoredPreset, services: AdminServices) -> StoredPreset:
    """Atomically create or update one custom DEV preset."""
    _require_preset_dev()
    try:
        return preset_store.save(preset)
    except ValueError as error:
        raise ApiProblemError(status_code=400, code="invalid_preset", message=str(error)) from error
    except OSError as error:
        raise ApiProblemError(
            status_code=503, code="preset_write_failed", message="Could not write the preset file."
        ) from error


@router.delete("/presets", response_model=PresetCatalog)
def delete_preset(services: AdminServices, id: str = Query(min_length=1)) -> PresetCatalog:
    """Delete one custom DEV preset after the UI obtains confirmation."""
    _require_preset_dev()
    try:
        preset_store.delete(id)
    except ValueError as error:
        raise ApiProblemError(status_code=400, code="invalid_preset", message=str(error)) from error
    except FileNotFoundError as error:
        raise not_found("preset", id) from error
    except OSError as error:
        raise ApiProblemError(
            status_code=503, code="preset_write_failed", message="Could not delete the preset file."
        ) from error
    return preset_store.catalog()
