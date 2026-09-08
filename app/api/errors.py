"""Stable typed error handling for malformed and failed API requests."""

from collections.abc import AsyncIterator, Mapping, Sequence
import contextlib
import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import ApiError, ErrorResponse, ValidationIssue
from app.observability.types import JsonObject

logger = logging.getLogger(__name__)


class ApiProblemError(Exception):
    """An expected HTTP failure with a stable machine code."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ValidationIssue] = (),
        path_decision: JsonObject | None = None,
        detail: str | None = None,
        path: str | None = None,
        cause: Literal[
            "missing_file", "invalid_json", "invalid_manifest", "alias_conflict", "permission"
        ]
        | None = None,
        corpus_job: JsonObject | None = None,
        failed_stage: Literal["path", "gate"] | None = None,
    ) -> None:
        super().__init__(message)
        if not 400 <= status_code <= 599:
            raise ValueError("API problem status must be between 400 and 599")
        self.status_code = status_code
        self.error = ApiError(
            code=code,
            message=message,
            details=tuple(details),
            path_decision=path_decision,
            detail=detail,
            path=path,
            cause=cause,
            corpus_job=corpus_job,
            failed_stage=failed_stage,
        )


def bad_request(code: str, message: str) -> ApiProblemError:
    """Build one typed client-input failure."""
    return ApiProblemError(status_code=400, code=code, message=message)


def not_found(resource: str, identity: str) -> ApiProblemError:
    """Build one typed missing-resource failure."""
    return ApiProblemError(
        status_code=404,
        code=f"{resource}_not_found",
        message=f"{resource} {identity} was not found.",
    )


def unavailable(code: str, message: str) -> ApiProblemError:
    """Build the typed 503 an unconfigured or unreachable dependency answers with."""
    return ApiProblemError(status_code=503, code=code, message=message)


@contextlib.asynccontextmanager
async def translate_runtime_errors() -> AsyncIterator[None]:
    """Translate every expected infrastructure and domain failure exactly once.

    One boundary owns the mapping so a new operation cannot forget a family: domain
    ``ValueError`` (semantically invalid input the schemas cannot express) becomes a
    typed 400, provider and database outages become typed 503s, and an already-typed
    problem passes through unchanged.
    """
    try:
        yield
    except ApiProblemError:
        raise
    except ValueError as error:
        raise bad_request("invalid_request", str(error)) from error
    except OpenAIError as error:
        raise unavailable(
            "provider_unavailable",
            f"Provider is unavailable ({type(error).__name__}).",
        ) from error
    except SQLAlchemyError as error:
        raise unavailable(
            "database_unavailable",
            f"Database is unavailable ({type(error).__name__}).",
        ) from error


def _response(
    status_code: int,
    error: ApiError,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Serialize one typed error into the single envelope every failure uses."""
    body = ErrorResponse(error=error)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def _validation_issue(error: dict[str, object]) -> ValidationIssue:
    """Narrow one pydantic error dictionary to the typed issue clients receive."""
    raw_location = error.get("loc", ())
    if not isinstance(raw_location, tuple | list):
        raw_location = (str(raw_location),)
    location = tuple(value if isinstance(value, int) else str(value) for value in raw_location)
    return ValidationIssue(
        location=location,
        message=str(error.get("msg", "Invalid request.")),
        error_type=str(error.get("type", "validation_error")),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Install non-leaking error envelopes on one FastAPI application.

    Parameters
    ----------
    app : FastAPI
        Application receiving the exception handlers.

    Notes
    -----
    Client-safe 4xx detail and transport headers are preserved. Every 5xx response
    uses a fixed public message while unexpected exceptions retain server-side logs.
    """

    @app.exception_handler(ApiProblemError)
    async def api_problem_handler(request: Request, error: ApiProblemError) -> JSONResponse:
        """Return the status and envelope the raised domain problem already carries."""
        return _response(error.status_code, error.error)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        """Report every rejected field as a typed issue instead of a traceback."""
        details = tuple(_validation_issue(issue) for issue in error.errors())
        return _response(
            422,
            ApiError(
                code="request_validation_failed",
                message="Request validation failed.",
                details=details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        """Keep client-safe 4xx detail and headers while 5xx detail stays server-side."""
        if error.status_code >= 500:
            code = "internal_error"
            message = "The request could not be completed."
        else:
            code = "route_not_found" if error.status_code == 404 else "http_error"
            message = str(error.detail) if isinstance(error.detail, str) else "HTTP request failed."
        return _response(
            error.status_code,
            ApiError(code=code, message=message),
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def internal_handler(request: Request, error: Exception) -> JSONResponse:
        """Log the unexpected failure in full and answer with a fixed public message."""
        logger.error(
            "Unhandled API error on %s",
            request.url.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return _response(
            500,
            ApiError(
                code="internal_error",
                message="The request could not be completed.",
            ),
        )
