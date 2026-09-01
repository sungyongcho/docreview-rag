"""SSH-only corpus and evaluation experiment resources."""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.admin_deps import AdminServices
from app.api.admin_schemas import (
    CorpusOperationRequest,
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationResultDetailResponse,
    EvaluationRunRequest,
    GoldenSuiteResource,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    ReviewPreviewRequest,
    ReviewPreviewResponse,
    UsageResponse,
)
from app.api.errors import not_found, translate_runtime_errors
from app.api.schemas import ErrorResponse

router = APIRouter(prefix="/admin", tags=["admin"])
ResultId = Annotated[int, Query(gt=0)]


@router.get("/corpus", responses={503: {"model": ErrorResponse}})
async def corpus_snapshot(services: AdminServices) -> dict[str, Any]:
    """Return live corpus, schema, index, manifest, and document state."""
    async with translate_runtime_errors():
        return await services.corpus_snapshot()


@router.get("/documents/{doc_id}", responses={404: {"model": ErrorResponse}})
async def document_detail(doc_id: str, services: AdminServices) -> dict[str, Any]:
    """Return bounded metadata and chunk previews for one document."""
    async with translate_runtime_errors():
        detail = await services.document_detail(doc_id)
    if detail is None:
        raise not_found("document", doc_id)
    return detail


@router.post("/corpus/jobs", responses={400: {"model": ErrorResponse}})
async def enqueue_corpus(
    request: CorpusOperationRequest,
    services: AdminServices,
) -> dict[str, Any]:
    """Queue one safe corpus acquisition, ingest, or indexing operation."""
    async with translate_runtime_errors():
        return await services.enqueue_corpus(request)


@router.get("/corpus/jobs")
async def corpus_jobs(services: AdminServices) -> dict[str, Any]:
    """Return current corpus job queue and bounded history."""
    return await services.corpus_jobs()


@router.post("/corpus/jobs/{job_id}/retry", responses={400: {"model": ErrorResponse}})
async def retry_corpus(job_id: str, services: AdminServices) -> dict[str, Any]:
    """Retry one known failed corpus job."""
    async with translate_runtime_errors():
        return await services.retry_corpus(job_id)


@router.get("/evaluations/suites", response_model=tuple[GoldenSuiteResource, ...])
async def evaluation_suites(services: AdminServices) -> tuple[GoldenSuiteResource, ...]:
    """Return golden suite provenance and source readiness."""
    async with translate_runtime_errors():
        return await services.suites()


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


@router.get(
    "/jobs/{job_id}",
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
