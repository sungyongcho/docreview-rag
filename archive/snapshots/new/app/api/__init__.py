"""Strict, injected synchronous HTTP boundary for M5."""

from app.api.app import create_api_app
from app.api.deps import ApiServices, get_api_services
from app.api.errors import ApiProblemError, bad_request, install_error_handlers, not_found
from app.api.routes import api_router
from app.api.runtime import RuntimeApiServices
from app.api.schemas import (
    ApiError,
    BudgetLimitFailure,
    DocumentListResponse,
    DocumentResource,
    ErrorResponse,
    EvalListResponse,
    EvalResultResource,
    EvidenceHit,
    IngestRequest,
    IngestResponse,
    RetrieveRequest,
    RetrieveResponse,
    ReviewRequest,
    RunResponse,
    TraceListResponse,
    ValidationIssue,
)

router = api_router

__all__ = [
    "ApiError",
    "ApiProblemError",
    "ApiServices",
    "BudgetLimitFailure",
    "DocumentListResponse",
    "DocumentResource",
    "ErrorResponse",
    "EvalListResponse",
    "EvalResultResource",
    "EvidenceHit",
    "IngestRequest",
    "IngestResponse",
    "RetrieveRequest",
    "RetrieveResponse",
    "ReviewRequest",
    "RuntimeApiServices",
    "RunResponse",
    "TraceListResponse",
    "ValidationIssue",
    "api_router",
    "bad_request",
    "create_api_app",
    "get_api_services",
    "install_error_handlers",
    "not_found",
    "router",
]
