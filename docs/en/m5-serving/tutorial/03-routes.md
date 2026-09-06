# M5.1 Tutorial 3 — Seven thin routes

Schemas and the seam are ready. Now the routes. **All seven files together are 146 lines.**

That shortness is the point. A route growing longer means domain logic has leaked in.

**Prerequisite:** `api/errors.py` and `deps.py` are written through tutorial 2.

### The shape of one route

They all share the same three-step structure.

1. FastAPI parses the request into a strict model. 2. One injected service method is called. 3. The result is projected into a response schema.

`retrieve.py` has one extra line — the one distinguishing a `RetrievalResult` from a sequence, because `ApiServices` declared that a service may return either.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| The seven routes | **Define the structure** | Why a route has to stay short |
| `routes/__init__.py` | **Define the structure** | Router registration order |
| `create_api_app` | **Review the design decision** | Why a factory beats a global app |

### 1. Retrieve, documents, ingest

#### Create `app/api/routes/retrieve.py` — the retrieve route

**Learning action — define the structure:** note what the `Services` alias does. All seven files repeat that line.

```python
"""Retrieve resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import EvidenceHit, RetrieveRequest, RetrieveResponse
from app.retrieval import RetrievalResult

router = APIRouter(tags=["retrieve"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_evidence(request: RetrieveRequest, services: Services) -> RetrieveResponse:
    """Return source-cited ranked evidence for one validated query."""
    result = await services.retrieve(request)
    hits = result.hits if isinstance(result, RetrievalResult) else tuple(result)
    return RetrieveResponse(
        query=request.query,
        results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in hits),
    )
```

**What to look for in the code**

- `Services = Annotated[ApiServices, Depends(get_api_services)]` makes injection one line. The type hint is the dependency declaration.
- The route imports `RetrievalResult`, but only **to project it**. It never touches domain logic.
- `EvidenceHit.from_chunk_hit` performs the conversion. The route does not move fields by hand.

#### Create `app/api/routes/documents.py` — document listing

```python
"""Document collection resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import DocumentListResponse

router = APIRouter(tags=["documents"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(services: Services) -> DocumentListResponse:
    """Return the deterministic collection of ingested filings."""
    documents = tuple(await services.list_documents())
    return DocumentListResponse(documents=documents)
```

#### Create `app/api/routes/ingest.py` — ingestion

```python
"""Synchronous ingestion resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.post("/ingest", response_model=IngestResponse)
async def ingest_manifest(request: IngestRequest, services: Services) -> IngestResponse:
    """Parse and persist one explicit local manifest before responding."""
    result = await services.ingest(request)
    return IngestResponse(documents=result.documents, chunks=result.chunks)
```

**What to look for in the code**

- Ingestion is a POST and synchronous. No queue, no background task — M5 builds only the **synchronous boundary**.
- Both routes are three lines. Putting what the service returned into a response schema is all they do.

### 2. Review, runs, traces, evaluations

#### Create `app/api/routes/review.py` — running the workflow

**Learning action — define the structure:** note how M4's four terminal states become one response.

```python
"""Synchronous evidence-review resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ReviewRequest, RunResponse

router = APIRouter(tags=["review"])
Services = Annotated[ApiServices, Depends(get_api_services)]
STATUS_CODES = {
    "ok": 200,
    "budget_exceeded": 429,
    "schema_rejected": 502,
    "error": 503,
}


@router.post("/review", response_model=RunResponse)
async def review_query(
    request: ReviewRequest,
    response: Response,
    services: Services,
) -> RunResponse:
    """Complete one guarded workflow and return its terminal run resource."""
    result = RunResponse.from_run_report(await services.review(request))
    response.status_code = STATUS_CODES[result.status]
    return result
```

#### Create `app/api/routes/runs.py` — run lookup

```python
"""Persisted workflow run resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ApiServices, get_api_services
from app.api.errors import not_found
from app.api.schemas import RunResponse

router = APIRouter(tags=["runs"])
Services = Annotated[ApiServices, Depends(get_api_services)]
RunPath = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: RunPath, services: Services) -> RunResponse:
    """Return one persisted run without executing it again."""
    result = await services.get_run(run_id)
    if result is None:
        raise not_found("run", run_id)
    return RunResponse.from_run_report(result)
```

#### Create `app/api/routes/traces.py` — trace lookup

```python
"""Persisted provider trace collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ApiServices, get_api_services
from app.api.errors import not_found
from app.api.schemas import TraceListResponse

router = APIRouter(tags=["traces"])
Services = Annotated[ApiServices, Depends(get_api_services)]
RunPath = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


@router.get("/runs/{run_id}/traces", response_model=TraceListResponse)
async def list_traces(run_id: RunPath, services: Services) -> TraceListResponse:
    """Return ordered raw provider traces for one persisted run."""
    traces = await services.get_traces(run_id)
    if traces is None:
        raise not_found("run", run_id)
    return TraceListResponse(run_id=run_id, traces=tuple(traces))
```

#### Create `app/api/routes/eval.py` — evaluation lookup

```python
"""Persisted evaluation result collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import EvalListResponse

router = APIRouter(tags=["eval"])
Services = Annotated[ApiServices, Depends(get_api_services)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/eval", response_model=EvalListResponse)
async def list_eval_results(
    services: Services,
    limit: Limit = 20,
) -> EvalListResponse:
    """Return the newest persisted retrieval evaluation results."""
    results = tuple(await services.list_eval_results(limit))
    return EvalListResponse(results=results)
```

**What to look for in the code**

- `review` returns 200 even on failure. The `status` inside `RunResponse` states the outcome — a budget overrun is not an HTTP error.
- All three lookup routes receive `not_found` from the service. The route does not decide whether something exists.
- `eval.py` runs no evaluation. It only reads what M3 stored.

### 3. Router registration and the app factory

#### Create `app/api/routes/__init__.py` — the router collection

**Learning action — define the structure:** note that registration order is not filename order.

```python
"""Resource-oriented M5 route collection."""

from fastapi import APIRouter

from app.api.routes import documents, eval, ingest, retrieve, review, runs, traces

api_router = APIRouter()
for module in (retrieve, documents, ingest, review, runs, traces, eval):
    api_router.include_router(module.router)

__all__ = ["api_router"]
```

**What to look for in the code**

- The order is `retrieve, documents, ingest, review, runs, traces, eval`. That is the order the OpenAPI document lists, so it is arranged in the order a reader understands.

#### Create `app/api/app.py` — the application factory

**Learning action — review the design decision:** work out why a factory rather than a module-level `app = FastAPI()`.

```python
"""FastAPI application factory with explicit service injection."""

from fastapi import FastAPI

from app.api.deps import ApiServices, get_api_services
from app.api.errors import install_error_handlers
from app.api.routes import api_router


def create_api_app(services: ApiServices | None = None) -> FastAPI:
    """Create the synchronous M5 HTTP application without starting external services."""
    app = FastAPI(title="Document Review RAG API", version="0.1.0")
    install_error_handlers(app)
    app.include_router(api_router)
    if services is not None:
        app.dependency_overrides[get_api_services] = lambda: services
    return app
```

**What to look for in the code**

- It is a factory function. A module-level `app` means **importing alone builds the app** — which is exactly the next document's subject.
- `services=None` is the default. Called with no argument, the default `get_api_services` remains and the first request fails.
- Injection goes through `dependency_overrides`. How a test inserts a fake service matches how production inserts a real one.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/api/test_01_schemas.py tests/api/test_02_errors.py \
  tests/api/test_03_resources.py tests/api/test_04_operations.py tests/api/test_05_routes.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| An exception message riding in a response | Internal detail never leaks to a client. |
| A route importing a domain type | The transport layer stays replaceable. |
| An HTTP 500 for `budget_exceeded` | A budget overrun is never reported as a server error. |
| `index_text` present in a response | The internal indexing scheme never becomes a contract. |
| A request against an unassembled app | It fails on the first request rather than running quietly. |

### What you should be able to explain now

- **What has leaked in when a route grows longer?**
  - **Answer:** Domain rules, workflow control flow, or infrastructure handling has crossed into the transport layer instead of staying behind the service seam.
- **Why does `review` return 200 even on failure?**
  - **Answer:** The current code does not return 200 on failure. Only `ok` maps to 200; `budget_exceeded` maps to 429, `schema_rejected` to 502, and `error` to 503 through `STATUS_CODES`.
- **What does router registration order affect?**
  - **Answer:** It determines the order in which endpoints appear in the generated OpenAPI document, so the chosen order guides readers through the API.
- **Why a factory rather than a module-level `app`?**
  - **Answer:** A factory makes application construction and service injection explicit, allowing isolated apps without making a bare import perform composition work.
- **Why must a test insert a fake service the same way production inserts a real one?**
  - **Answer:** Using the same dependency override seam verifies the actual wiring contract instead of exercising a test-only path.

---

[← Previous: Errors and dependencies](02-errors-deps.md) · [Module overview](../03-build.md) · [Next: Runtime assembly →](04-runtime.md)
