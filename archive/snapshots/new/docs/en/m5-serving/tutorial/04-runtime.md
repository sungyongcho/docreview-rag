# M5.2 Tutorial 4 — Importing must do nothing on its own

M5.1's API package is still a shell. The real M2 retriever and M4 workflow have to be wired in.

One rule holds here. **Do not open a database or call a provider at import time.**

**Prerequisite:** The `tests/api` route suite from tutorial 3 passes.

### Why import side effects are a problem

Suppose importing `app/main.py` opens a database connection. Then these things happen.

- **test collection requires a database.** Even `pytest --collect-only` will not run without one
- **`--help` is slow.** You wanted CLI help and are waiting on a connection
- **errors appear in the wrong place.** Import failures produce stack traces that are hard to read

So a factory pattern is used. Nothing happens at module top level; resources are created when a function is called. `app/main.py` exposes the ASGI app while its composition happens at call time.

### A paid call never happens from defaults

One rule is embedded in `RuntimeApiServices`'s constructor.

```text
(llm_provider is None) != (provider_budget is None)  →  reject
```

The LLM provider and its budget must be **both present or both absent.** Inject only the provider and calls happen with no budget; inject only the budget and it has nowhere to apply.

The effect is large. From environment defaults alone, a container **cannot make a paid model call.** Review turns on only when switched on explicitly — the last application of fail-closed.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| The four `Protocol`s | **Review the design decision** | How the runtime holds the domain loosely |
| The three projection helpers | **Write the field mapping** | Where an ORM row becomes an API resource |
| `RuntimeApiServices.__init__` | **Implement** the paired constraint yourself | Blocking paid calls from defaults |
| The seven service methods | **Implement** the exception conversion yourself | The boundary that moves infrastructure failure to 503 |
| `app/main.py` | **Define the structure** | How the factory relates to the ASGI app |

### 1. How the runtime holds the domain loosely

#### Create `app/api/runtime.py` — module header

**Learning action — define the structure:** this file imports all of M1, M2, M3, and M4. It is the assembly point.

```python
"""Production database composition for the synchronous M5 HTTP resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from openai import OpenAIError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import ApiServices
from app.api.errors import ApiProblemError, bad_request
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.db.bootstrap import bootstrap_schema
from app.db.models import Chunk, Document, EvalResult, Run, Trace
from app.db.session import Session, engine
from app.ingestion.seed import SeedResult, persist_seed_batch, prepare_seed_batch
from app.llm import LLMProvider, ProviderBudget
from app.observability import RunReport, StepTrace, persist_run_report
from app.retrieval import (
    ChunkHit,
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    RetrievalFilters,
    RetrievalResult,
    retrieve,
)
from app.workflow import WorkflowRequest, run_workflow

```

#### Extend `app/api/runtime.py` — service protocols

**Learning action — review the design decision:** note what each of the four protocols makes replaceable.

<!-- src: app/api/runtime.py::SessionFactory,RunPersister -->
```python
class SessionFactory(Protocol):
    """Build one caller-owned async session context."""

    def __call__(self) -> AsyncSession: ...


class RetrievalService(Protocol):
    """M2 retrieval call shape used by both retrieve and review resources."""

    def __call__(
        self,
        session: AsyncSession,
        query: str,
        *,
        provider: EmbeddingProvider | None,
        k: int,
        filters: RetrievalFilters,
    ) -> Awaitable[RetrievalResult]: ...


class WorkflowService(Protocol):
    """M4 workflow call shape used by the review resource."""

    def __call__(
        self,
        request: WorkflowRequest,
        *,
        retriever: Callable[
            [str, int, RetrievalFilters],
            Awaitable[RetrievalResult | Sequence[ChunkHit]],
        ],
        provider: LLMProvider,
        on_node: NodeObserver | None = None,
    ) -> Awaitable[RunReport]: ...


class RunPersister(Protocol):
    """M4 persistence call shape used after a workflow completes."""

    def __call__(
        self,
        session: AsyncSession,
        report: RunReport,
        *,
        secret_values: Iterable[str],
    ) -> Awaitable[Run]: ...
```

**What to look for in the code**

- `SessionFactory`, `RetrievalService`, `WorkflowService`, and `RunPersister` are all `Protocol`s. A test can replace each independently.
- The defaults are the real implementations (`Session`, `retrieve`, `run_workflow`, `persist_run_report`). Inject nothing and the real thing runs — only tests substitute.

### 2. Where an ORM row becomes an API resource

#### Extend `app/api/runtime.py` — projection helpers

**Learning action — write the field mapping:** note how `_run_report` recombines `Run` and `Trace`.

<!-- src: app/api/runtime.py::_unavailable,_run_report -->
```python
def _unavailable(code: str, message: str) -> ApiProblemError:
    return ApiProblemError(status_code=503, code=code, message=message)


def _document_resource(document: Document, chunk_count: int) -> DocumentResource:
    return DocumentResource(
        doc_id=document.doc_id,
        ticker=document.ticker,
        cik=document.cik,
        fiscal_year=document.fiscal_year,
        form=document.form,
        filing_date=document.filing_date,
        report_period=document.report_period,
        accession=document.accession,
        url=document.url,
        parse_status=document.parse_status,
        source_length=document.source_length,
        source_sha256=document.source_sha256,
        chunk_count=chunk_count,
    )


def _step_trace(trace: Trace) -> StepTrace:
    return StepTrace(
        step=trace.step,
        node=trace.node,
        model_name=trace.model_name,
        api_url=trace.api_url,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        request_time_ms=trace.request_time_ms,
        llm_output=trace.llm_output,
        retries=trace.retries,
        error=trace.error,
    )


def _run_report(run: Run, traces: Sequence[Trace]) -> RunReport:
    return RunReport(
        run_id=run.run_id,
        status=run.status,
        iterations=run.iterations,
        total_requests=run.total_requests,
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
        total_time_seconds=run.total_time_seconds,
        system_prompt=run.system_prompt,
        node_path=tuple(run.node_path),
        report=run.report,
        steps=tuple(_step_trace(trace) for trace in traces),
    )
```

**What to look for in the code**

- `_document_resource` takes `chunk_count` as an argument. Lazily loading an ORM relationship would produce N+1 queries, so the aggregate arrives from one query at the call site.
- `_run_report` **reconstructs** M4.2's `RunReport` from M1.4's `Run` and `Trace` rows. It is the only place stored data becomes a domain value again.
- `_unavailable` produces a 503. Infrastructure failure is neither 400 nor 500 — it means retrying later may work.

### 3. Blocking paid calls from defaults

#### Complete `app/api/runtime.py` — the runtime services

**Learning action — implement the paired constraint and the exception conversion:** implement the constructor's first check yourself. Then note what each method's `except` blocks catch.

<!-- src: app/api/runtime.py::RuntimeApiServices -->
```python
class RuntimeApiServices(ApiServices):
    """Compose API resources over one session per synchronous request.

    Retrieval defaults to the configured embedding provider. Review is fail-closed until
    an LLM provider and its explicit budget are injected; the container therefore cannot
    make a paid model call from environment defaults alone.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = Session,
        database_engine: AsyncEngine = engine,
        embedding_provider: EmbeddingProvider | None = None,
        llm_provider: LLMProvider | None = None,
        provider_budget: ProviderBudget | None = None,
        retrieval_service: RetrievalService = retrieve,
        workflow_service: WorkflowService = run_workflow,
        run_persister: RunPersister = persist_run_report,
        run_id_factory: Callable[[], str] | None = None,
        secret_values: Iterable[str] = (),
    ) -> None:
        if (llm_provider is None) != (provider_budget is None):
            raise ValueError("llm_provider and provider_budget must be configured together")
        self._session_factory = session_factory
        self._database_engine = database_engine
        self._embedding_provider = (
            DeterministicEmbeddingProvider() if embedding_provider is None else embedding_provider
        )
        self._llm_provider = llm_provider
        self._provider_budget = provider_budget
        self._retrieval_service = retrieval_service
        self._workflow_service = workflow_service
        self._run_persister = run_persister
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")
        self._secret_values = tuple(secret_values)

    async def _retrieve_with_session(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        return await self._retrieval_service(
            session,
            query,
            provider=self._embedding_provider,
            k=k,
            filters=filters,
        )

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
        """Call the M2 service through one request-owned database session."""
        try:
            async with self._session_factory() as session:
                return await self._retrieve_with_session(
                    session,
                    request.query,
                    request.k,
                    request.filters,
                )
        except OpenAIError as error:
            raise _unavailable(
                "provider_unavailable",
                f"Embedding provider is unavailable ({type(error).__name__}).",
            ) from error
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return filing resources with deterministic chunk counts."""
        statement = (
            select(Document, func.count(Chunk.id).label("chunk_count"))
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .group_by(Document.doc_id)
            .order_by(Document.ticker, Document.fiscal_year, Document.doc_id)
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).all()
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(_document_resource(document, count) for document, count in rows)

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Prepare locally, bootstrap explicitly, and preserve the M1 atomic upsert."""
        path = Path(request.manifest_path)
        if not path.is_file():
            raise bad_request("manifest_not_found", f"Manifest file was not found: {path}")
        try:
            batch = prepare_seed_batch(path, expected_documents=request.expected_documents)
        except json.JSONDecodeError as error:
            raise bad_request(
                "invalid_manifest_json",
                f"Manifest is not valid JSON at line {error.lineno} column {error.colno}.",
            ) from error
        except UnicodeDecodeError as error:
            raise bad_request(
                "invalid_manifest_encoding",
                "Manifest must be UTF-8 text.",
            ) from error
        except FileNotFoundError as error:
            raise bad_request(
                "corpus_file_not_found",
                f"Corpus file was not found: {error.filename}",
            ) from error
        except ValueError as error:
            raise bad_request("invalid_manifest", str(error)) from error

        try:
            await bootstrap_schema(self._database_engine)
            async with self._session_factory() as session:
                return await persist_seed_batch(
                    session,
                    batch,
                    chunk_batch_size=request.chunk_batch_size,
                )
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def review(self, request: ReviewRequest) -> RunReport:
        """Call M4 over the same M2 seam and persist its structured terminal report."""
        return await self._review(request, on_node=None)

    async def review_stream(
        self,
        request: ReviewRequest,
        on_node: NodeObserver,
    ) -> RunReport:
        """Run one reviewed workflow while reporting each completed node."""
        return await self._review(request, on_node=on_node)

    async def _review(
        self,
        request: ReviewRequest,
        *,
        on_node: NodeObserver | None,
    ) -> RunReport:
        if self._llm_provider is None or self._provider_budget is None:
            raise _unavailable(
                "provider_unavailable",
                "Review requires an explicitly configured LLM provider and budget.",
            )
        workflow_request = WorkflowRequest(
            run_id=self._run_id_factory(),
            query=request.query,
            k=request.k,
            filters=request.filters,
            budget=request.budget,
            provider_budget=self._provider_budget,
            max_context_chars=request.max_context_chars,
        )
        try:
            async with self._session_factory() as session:

                async def retrieve_for_workflow(
                    query: str,
                    k: int,
                    filters: RetrievalFilters,
                ) -> RetrievalResult:
                    return await self._retrieve_with_session(session, query, k, filters)

                report = await self._workflow_service(
                    workflow_request,
                    retriever=retrieve_for_workflow,
                    provider=self._llm_provider,
                    on_node=on_node,
                )
                if session.in_transaction():
                    await session.rollback()
                async with session.begin():
                    await self._run_persister(
                        session,
                        report,
                        secret_values=self._secret_values,
                    )
                return report
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def _trace_rows(self, session: AsyncSession, run_id: str) -> tuple[Trace, ...]:
        rows = await session.scalars(
            select(Trace).where(Trace.run_id == run_id).order_by(Trace.step)
        )
        return tuple(rows)

    async def get_run(self, run_id: str) -> RunReport | None:
        """Load one run and its ordered traces without executing workflow code."""
        try:
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return _run_report(run, traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Load trace resources only when their parent run exists."""
        try:
            async with self._session_factory() as session:
                if await session.get(Run, run_id) is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return tuple(_step_trace(trace) for trace in traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Load newest evaluation records through their strict public schema."""
        statement = select(EvalResult).order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        try:
            async with self._session_factory() as session:
                rows = tuple(await session.scalars(statement.limit(limit)))
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(
            EvalResultResource(
                result_id=row.id,
                suite=row.suite,
                config=row.config,
                metrics={name: float(value) for name, value in row.metrics.items()},
                raw_artifact_path=row.raw_artifact_path,
                created_at=row.created_at,
            )
            for row in rows
        )
```

**What to look for in the code**

- `(llm_provider is None) != (provider_budget is None)` is an XOR. Exactly one present is rejected.
- The embedding provider defaults to `DeterministicEmbeddingProvider()`. Retrieval runs without money while review does not — only the costly side is fail-closed.
- Each method opens its own session (`async with self._session_factory()`). One request owns one session — M2.7's decision to leave sessions caller-owned pays off here.
- `except OpenAIError` and `except SQLAlchemyError` produce 503s with different codes. Which dependency died survives in the response.
- Only `type(error).__name__` enters the message. The original message may contain a connection string.

### 4. The factory and the ASGI app

#### Create `app/main.py` — the runtime entry point

**Learning action — define the structure:** work out why the final `app = create_app()` is acceptable.

```python
"""FastAPI runtime entrypoint without import-time database or provider calls."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.api import ApiServices, RuntimeApiServices, create_api_app


class HealthResponse(BaseModel):
    """Stable process-liveness response used by container health checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"


def create_app(services: ApiServices | None = None) -> FastAPI:
    """Build one API instance with an injectable database-backed service boundary."""
    active_services = RuntimeApiServices() if services is None else services
    application = create_api_app(active_services)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["runtime"],
        operation_id="runtime_health",
    )
    async def health() -> HealthResponse:
        return HealthResponse()

    return application


app = create_app()
```

**What to look for in the code**

- `app = create_app()` sits at module level. An ASGI server demands `app.main:app`, so it is unavoidable.
- Yet the `RuntimeApiServices()` constructor **opens no connection.** It only holds an engine object; a real connection opens on the first request. That is the precise meaning of "no import side effects."
- `/health` lives here. A container health check confirms process liveness without touching the domain.

### What you should be able to explain now

- **Which development task slows down when a connection opens at import time?**
  - **Answer:** CLI `--help` waits for the connection, and test collection also begins requiring a live database before any test runs.
- **What becomes impossible by pairing the LLM provider and budget with XOR?**
  - **Answer:** The runtime cannot be configured with a provider but no budget, or with a budget that has no provider, so an unbounded paid call cannot arise from a half-configured service.
- **Why does retrieval run from defaults while review does not?**
  - **Answer:** Retrieval has a deterministic free embedding default, while review requires an explicitly paired LLM provider and budget because it can make paid calls.
- **Why is infrastructure failure a 503 rather than a 500?**
  - **Answer:** The application is available but a database or provider dependency is temporarily unavailable, which tells the client that retrying later may succeed.
- **Why is a module-level `app = create_app()` not an import side effect?**
  - **Answer:** `create_app()` only constructs configuration objects; `RuntimeApiServices` holds an engine but opens no connection until the first request.

---

[← Previous: Routes](03-routes.md) · [Module overview](../03-build.md) · [Next: CLI →](05-cli.md)
