# M5.1 Tutorial 2 — Non-leaking errors and the injection seam

The schemas are ready. Now two things get built — the channel failure leaves through, and the channel the domain arrives through.

**Prerequisite:** `api/schemas.py` from tutorial 1 is written. Its tests run together in tutorial 3.

### A stack trace must not ride in a response

FastAPI's default behavior for an unhandled exception is a 500 plus a server log. But depending on configuration, **the exception message can end up in the response body.**

There is no knowing what is in that message. A database URL, a file path, an internal class name. So one last handler exists — whatever explodes leaves as a single `internal_error`.

The cause goes to the log and **not to the response.** Separating those two is the point.

### The only channel routes use to reach the domain

`ApiServices` is a `Protocol`. Routes call only its methods, and what it actually is gets decided in M5.2.

The same shape as M4.2 accepting a provider through a `Protocol`. **The dependency flows one way** — routes import no M2 or M4.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `ApiProblemError` | **Write the record declaration** | The value that moves a domain failure into HTTP |
| `install_error_handlers` | **Implement** the four handlers yourself | What the last handler blocks |
| `ApiServices` | **Review the design decision** | The dependency direction a protocol preserves |
| `get_api_services` | **Define the structure** | A default that fails before assembly |

### 1. Moving a domain failure into HTTP

#### Create `app/api/errors.py` — module header

**Learning action — define the structure:** no domain module is among the imports.

```python
"""Stable typed error handling for malformed and failed API requests."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import ApiError, ErrorResponse, ValidationIssue

```

#### Extend `app/api/errors.py` — problem exception and response conversion

**Learning action — write the record declaration:** note why `bad_request` and `not_found` are functions.

<!-- src: app/api/errors.py::ApiProblemError,_validation_issue -->
```python
class ApiProblemError(Exception):
    """An expected HTTP failure with a stable machine code."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ValidationIssue] = (),
    ) -> None:
        super().__init__(message)
        if not 400 <= status_code <= 599:
            raise ValueError("API problem status must be between 400 and 599")
        self.status_code = status_code
        self.error = ApiError(code=code, message=message, details=tuple(details))


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


def _response(status_code: int, error: ApiError) -> JSONResponse:
    body = ErrorResponse(error=error)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _validation_issue(error: dict[str, object]) -> ValidationIssue:
    raw_location = error.get("loc", ())
    if not isinstance(raw_location, tuple | list):
        raw_location = (str(raw_location),)
    location = tuple(value if isinstance(value, int) else str(value) for value in raw_location)
    return ValidationIssue(
        location=location,
        message=str(error.get("msg", "Invalid request.")),
        error_type=str(error.get("type", "validation_error")),
    )
```

**What to look for in the code**

- `ApiProblemError` carries the status code together with an `ApiError`. Domain code can raise this one exception without knowing HTTP.
- `bad_request` and `not_found` are factory functions. Status codes do not scatter across call sites.
- `_validation_issue` moves FastAPI's error dictionary into our schema. Unfiltered here, internal type names would reach the response.

### 2. What the last handler blocks

#### Complete `app/api/errors.py` — installing the error handlers

**Learning action — implement the handlers:** implement all four yourself, and consider whether registration order matters.

<!-- src: app/api/errors.py::install_error_handlers -->
```python
def install_error_handlers(app: FastAPI) -> None:
    """Install non-leaking error envelopes on one FastAPI application."""

    @app.exception_handler(ApiProblemError)
    async def api_problem_handler(request: Request, error: ApiProblemError) -> JSONResponse:
        return _response(error.status_code, error.error)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
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
        code = "route_not_found" if error.status_code == 404 else "http_error"
        message = str(error.detail) if isinstance(error.detail, str) else "HTTP request failed."
        return _response(error.status_code, ApiError(code=code, message=message))

    @app.exception_handler(Exception)
    async def internal_handler(request: Request, error: Exception) -> JSONResponse:
        return _response(
            500,
            ApiError(
                code="internal_error",
                message="The request could not be completed.",
            ),
        )
```

**What to look for in the code**

- `@app.exception_handler(Exception)` is the final net. Whatever it catches **has its message discarded entirely** — `str(error)` never enters the response.
- Only 404 gets its own `route_not_found` code. A client can tell a wrong path from another HTTP error.
- `RequestValidationError` leaves as 422, not 400 — the request is syntactically fine and semantically wrong.
- Every handler goes through `_response`. The envelope is constructed in exactly one place.

### 3. The dependency direction a protocol preserves

#### Create `app/api/deps.py` — module header

**Learning action — define the structure:** this file does import domain types. It is the **seam**, not a route.

```python
"""Injected application-service seam for the synchronous HTTP boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.api.errors import ApiProblemError
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.ingestion.seed import SeedResult
from app.observability import RunReport, StepTrace
from app.retrieval import ChunkHit, RetrievalResult

```

#### Complete `app/api/deps.py` — the service protocol

**Learning action — review the design decision:** map each of the seven methods to its route.

<!-- src: app/api/deps.py::ApiServices,get_api_services -->
```python
class ApiServices(Protocol):
    """All domain operations required by the seven HTTP resources."""

    async def retrieve(
        self,
        request: RetrieveRequest,
    ) -> RetrievalResult | Sequence[ChunkHit]:
        """Return ranked evidence without performing HTTP work."""
        ...

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return document resources in deterministic order."""
        ...

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Run one synchronous local-manifest ingestion operation."""
        ...

    async def review(self, request: ReviewRequest) -> RunReport:
        """Run and persist one complete evidence-checked workflow."""
        ...

    async def review_stream(
        self,
        request: ReviewRequest,
        on_node: NodeObserver,
    ) -> RunReport:
        """Run one reviewed workflow while reporting each completed node."""
        ...

    async def get_run(self, run_id: str) -> RunReport | None:
        """Return one persisted run or null when it does not exist."""
        ...

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Return ordered traces or null when the parent run does not exist."""
        ...

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Return the newest persisted evaluation resources."""
        ...


def get_api_services() -> ApiServices:
    """Require production composition or a test override to inject services."""
    raise ApiProblemError(
        status_code=503,
        code="service_unavailable",
        message="API services are not configured.",
    )
```

**What to look for in the code**

- Being a `Protocol`, an implementation declares no inheritance. M5.2's `RuntimeApiServices` only has to match the shape.
- Every method is `async`. A synchronous implementation is possible, but adding I/O later will not change the signature.
- The default `get_api_services` **raises.** An unassembled app fails on the first request instead of running quietly.

#### Create `app/api/__init__.py` — package surface

**Learning action — define the structure:** what M5.1 publishes.

```python
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
```

### What you should be able to explain now

- **Why does the final exception handler discard the message?**
  - **Answer:** An unexpected exception may contain database URLs, file paths, or other internal details, so only a generic error is safe to return.
- **Why is a validation failure 422 rather than 400?**
  - **Answer:** The request is syntactically valid HTTP and JSON, but its values violate the declared semantic schema.
- **Which dependency direction is preserved by `ApiServices` being a `Protocol`?**
  - **Answer:** `ApiServices` makes routes call a transport-owned service interface, while the runtime adapter implements it with domain code. It does not remove every route-to-domain import: `retrieve.py` still imports `RetrievalResult` for response projection.
- **Why does the default `get_api_services` raise?**
  - **Answer:** An application that has not been assembled must fail on its first request instead of appearing to run with missing services.
- **Why does `deps.py` import the domain while routes do not?**
  - **Answer:** The premise is only partly true. Service calls cross the protocol in `deps.py`, but `retrieve.py` imports `RetrievalResult` directly to project it into an API response. The seam isolates execution, not every domain type used for projection.

---

[← Previous: API schemas](01-schemas.md) · [Module overview](../03-build.md) · [Next: Routes →](03-routes.md)
