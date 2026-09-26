"""Evaluation preparation, job submission, and golden dataset editing routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.composition import AdminServices
from app.api.dependencies import AdminDependency
from app.api.errors import ApiProblemError, not_found, translate_runtime_errors
from app.api.review.schemas import ErrorResponse, ValidationIssue
from app.db.models import EvalResult
from app.evals.admin.service import EvaluationAlreadyQueuedError, EvaluationNotReadyError
from app.evals.contracts import (
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationPreparationResource,
    EvaluationResultDetailResponse,
    EvaluationResultSummaryResource,
    EvaluationRunRequest,
    GoldenCanonicalResource,
    GoldenCaseUpdateRequest,
    GoldenDraftRequest,
    GoldenRevisionActionRequest,
    GoldenRevisionResource,
    GoldenSuiteId,
    GoldenSuiteResource,
)
from app.evals.golden.models import DraftConflictError, DraftInputError

router = APIRouter(prefix="/admin", tags=["admin"])
ResultId = Annotated[int, Query(gt=0)]


async def _enqueue_evaluation(
    dependencies: AdminServices, request: EvaluationRunRequest
) -> EvaluationJobResource:
    """Queue one quick or matrix evaluation."""
    try:
        return await dependencies.evaluations.enqueue(request)
    except EvaluationNotReadyError as error:
        raise ApiProblemError(
            status_code=409,
            code="evaluation_not_ready",
            message=str(error),
            detail=error.preparation.state,
        ) from error
    except EvaluationAlreadyQueuedError as error:
        raise ApiProblemError(
            status_code=409, code="evaluation_already_queued", message=str(error)
        ) from error


async def _evaluation_jobs(dependencies: AdminServices) -> EvaluationJobsResponse:
    """Return newest-first evaluation job state."""
    board = await dependencies.evaluations.jobs()
    ids = {result_id for job in board.jobs for result_id in job.result_ids}
    if not ids:
        return board
    async with dependencies.runtime.session_factory() as session:
        rows = tuple(await session.scalars(select(EvalResult).where(EvalResult.id.in_(ids))))
    summaries = {
        row.id: EvaluationResultSummaryResource(
            result_id=row.id, created_at=row.created_at, config=row.config
        )
        for row in rows
    }
    return board.model_copy(
        update={
            "jobs": tuple(
                job.model_copy(
                    update={
                        "result_summaries": tuple(
                            summaries[result_id]
                            for result_id in job.result_ids
                            if result_id in summaries
                        )
                    }
                )
                for job in board.jobs
            )
        }
    )


@router.post("/evaluations/preparation", response_model=EvaluationPreparationResource)
async def evaluation_preparation(
    request: EvaluationRunRequest, services: AdminDependency
) -> EvaluationPreparationResource:
    """Check source and retrieval prerequisites without queueing or generating anything."""
    async with translate_runtime_errors():
        return await services.evaluations.preparation(request)


@router.get("/evaluations/suites", response_model=tuple[GoldenSuiteResource, ...])
async def evaluation_suites(services: AdminDependency) -> tuple[GoldenSuiteResource, ...]:
    """Return golden suite provenance and source readiness."""
    async with translate_runtime_errors():
        return await services.evaluations.suites()


@router.get("/golden/{suite_id}/canonical", response_model=GoldenCanonicalResource)
async def golden_canonical(
    suite_id: GoldenSuiteId, services: AdminDependency
) -> GoldenCanonicalResource:
    """Return validated read-only canonical cases for one suite."""
    async with translate_runtime_errors():
        return services.golden.canonical(suite_id)


@router.get("/golden/{suite_id}/revisions", response_model=tuple[GoldenRevisionResource, ...])
async def golden_revisions(
    suite_id: GoldenSuiteId, services: AdminDependency
) -> tuple[GoldenRevisionResource, ...]:
    """Return newest-first revisions for one golden suite."""
    async with translate_runtime_errors():
        return await services.golden.list(suite_id)


@router.post("/golden/{suite_id}/drafts", response_model=GoldenRevisionResource)
async def create_golden_draft(
    suite_id: GoldenSuiteId, request: GoldenDraftRequest, services: AdminDependency
) -> GoldenRevisionResource:
    """Create a draft from canonical JSON or one selected parent."""
    async with translate_runtime_errors():
        return await services.golden.create_draft(
            suite_id, parent_id=request.parent_id, filename=request.filename, empty=request.empty
        )


@asynccontextmanager
async def golden_input_errors() -> AsyncIterator[None]:
    """Expose bounded field errors without echoing authored text."""
    try:
        yield
    except DraftConflictError as error:
        raise ApiProblemError(
            status_code=409, code="golden_draft_conflict", message=str(error)
        ) from error
    except DraftInputError as error:
        raise ApiProblemError(
            status_code=422,
            code="golden_input_invalid",
            message="Check the indicated question fields.",
            details=tuple(
                ValidationIssue(
                    location=issue.location, message=issue.message, error_type=issue.code
                )
                for issue in error.issues
            ),
        ) from error


@router.put(
    "/golden/revisions/{revision_id}/cases/{case_id}", response_model=GoldenRevisionResource
)
async def replace_golden_case(
    revision_id: int, case_id: str, request: GoldenCaseUpdateRequest, services: AdminDependency
) -> GoldenRevisionResource:
    """Replace one case using an expected draft digest."""
    async with translate_runtime_errors(), golden_input_errors():
        return await services.golden.replace_case(
            revision_id, case_id, expected_sha256=request.expected_sha256, payload=request.case
        )


@router.post(
    "/golden/revisions/{revision_id}/cases/{case_id}/delete", response_model=GoldenRevisionResource
)
async def delete_golden_case(
    revision_id: int, case_id: str, request: GoldenRevisionActionRequest, services: AdminDependency
) -> GoldenRevisionResource:
    """Remove one question from a draft using an expected draft digest."""
    async with translate_runtime_errors(), golden_input_errors():
        return await services.golden.delete_case(
            revision_id, case_id, expected_sha256=request.expected_sha256
        )


@router.post("/golden/revisions/{revision_id}/delete", response_model=GoldenRevisionResource)
async def delete_golden_revision(
    revision_id: int, request: GoldenRevisionActionRequest, services: AdminDependency
) -> GoldenRevisionResource:
    """Delete one user dataset file using an expected draft digest."""
    async with translate_runtime_errors(), golden_input_errors():
        return await services.golden.delete_draft(
            revision_id, expected_sha256=request.expected_sha256
        )


@router.post("/golden/revisions/{revision_id}/validate", response_model=GoldenRevisionResource)
async def validate_golden_revision(
    revision_id: int, request: GoldenRevisionActionRequest, services: AdminDependency
) -> GoldenRevisionResource:
    """Validate one exact draft against corpus source bytes."""
    async with translate_runtime_errors(), golden_input_errors():
        return await services.golden.validate(revision_id, expected_sha256=request.expected_sha256)


@router.post("/evaluations/runs", response_model=EvaluationJobResource)
async def enqueue_evaluation(
    request: EvaluationRunRequest, services: AdminDependency
) -> EvaluationJobResource:
    """Queue one quick live-index or isolated matrix evaluation."""
    async with translate_runtime_errors():
        return await _enqueue_evaluation(services, request)


@router.get("/evaluations/runs", response_model=EvaluationJobsResponse)
async def evaluation_runs(services: AdminDependency) -> EvaluationJobsResponse:
    """Return newest-first evaluation job state."""
    return await _evaluation_jobs(services)


@router.get(
    "/evaluations/results/{result_id}",
    response_model=EvaluationResultDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
async def evaluation_result(
    result_id: int, services: AdminDependency
) -> EvaluationResultDetailResponse:
    """Return absolute metrics and bounded case details for one result."""
    async with translate_runtime_errors():
        detail = await services.evaluations.result_detail(result_id)
    if detail is None:
        raise not_found("evaluation_result", str(result_id))
    return detail


@router.get("/evaluations/compare", response_model=EvaluationComparisonResponse)
async def compare_evaluations(
    services: AdminDependency, candidate_id: ResultId, baseline_id: ResultId
) -> EvaluationComparisonResponse:
    """Return metrics and per-case changes between compatible artifacts."""
    async with translate_runtime_errors():
        return await services.evaluations.compare(candidate_id, baseline_id)
