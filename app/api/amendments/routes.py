"""Administrator routes for weighing amended filings against their reports."""

from __future__ import annotations

from fastapi import APIRouter

from app.amendments.overview import ItemDecision, ReportPeriodView, amended_report_periods
from app.amendments.review import ItemEffect, ReviewError, clear_review, record_review
from app.api.dependencies import AdminDependency
from app.api.errors import ApiProblemError, bad_request, not_found, translate_runtime_errors
from app.api.review.schemas import ErrorResponse
from app.contracts.validation import NonBlank, StrictSchema

router = APIRouter(prefix="/admin", tags=["admin"])


class AmendedPeriodsResponse(StrictSchema):
    """Report periods that hold an amendment or more than one filing."""

    report_periods: tuple[ReportPeriodView, ...]


class AmendmentReviewRequest(StrictSchema):
    """One reviewer's decision for every Item of an indexed amendment."""

    reviewer: NonBlank
    rationale: NonBlank
    decisions: tuple[ItemDecision, ...]


def _review_problem(error: ReviewError, doc_id: str) -> ApiProblemError:
    """Answer a refused review with the status its cause calls for."""
    if error.code in {"not_indexed", "not_found"}:
        return not_found("amendment", doc_id)
    return bad_request(error.code, error.message)


async def _reviewed_period(services: AdminDependency, doc_id: str) -> ReportPeriodView:
    """Return the report period of a just-reviewed amendment as it stands now."""
    async with services.runtime.session_factory() as session:
        periods = await amended_report_periods(session, doc_id=doc_id)
    if not periods:
        raise not_found("amendment", doc_id)
    return periods[0]


@router.get("/amendments", response_model=AmendedPeriodsResponse)
async def amended_periods(services: AdminDependency) -> AmendedPeriodsResponse:
    """List report periods with an amendment or correction, and what holds them."""
    async with translate_runtime_errors():
        async with services.runtime.session_factory() as session:
            return AmendedPeriodsResponse(report_periods=await amended_report_periods(session))


@router.put(
    "/amendments/{doc_id}/review",
    response_model=ReportPeriodView,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def review_amendment(
    doc_id: str, request: AmendmentReviewRequest, services: AdminDependency
) -> ReportPeriodView:
    """Record what each Item of an indexed amendment does, replacing an earlier review."""
    async with translate_runtime_errors():
        try:
            async with services.runtime.session_factory() as session, session.begin():
                await record_review(
                    session,
                    doc_id,
                    reviewer=request.reviewer,
                    rationale=request.rationale,
                    effects=[
                        ItemEffect(decision.item, decision.action) for decision in request.decisions
                    ],
                )
        except ReviewError as error:
            raise _review_problem(error, doc_id) from error
        return await _reviewed_period(services, doc_id)


@router.delete(
    "/amendments/{doc_id}/review",
    response_model=ReportPeriodView,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def withdraw_amendment_review(doc_id: str, services: AdminDependency) -> ReportPeriodView:
    """Withdraw an amendment's review, which holds its report period again."""
    async with translate_runtime_errors():
        try:
            async with services.runtime.session_factory() as session, session.begin():
                await clear_review(session, doc_id)
        except ReviewError as error:
            raise _review_problem(error, doc_id) from error
        return await _reviewed_period(services, doc_id)
