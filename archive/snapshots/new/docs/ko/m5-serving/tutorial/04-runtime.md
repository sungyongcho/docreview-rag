# M5.2 튜토리얼 4 — import만으로는 아무 일도 일어나지 않아야 한다

M5.1에서 만든 API 패키지는 아직 도메인 구현과 연결되지 않았다. 이 문서에서 M2의 검색과 M4의 워크플로를 실제로 연결한다.

연결 과정에서 지킬 규칙이 하나 있다. **import 시점에 데이터베이스를 열거나 공급자를 호출하지 않는다.**

**선행 조건:** 튜토리얼 3의 `tests/api` 라우트 스위트가 통과해야 한다.

### import 부수효과가 문제인 이유

`app/main.py`를 import하는 것만으로 데이터베이스 연결이 열린다고 하자. 그러면 다음 세 가지가 발생한다.

- **테스트 수집에 데이터베이스가 필요해진다.** `pytest --collect-only`조차 못 돈다
- **`--help`가 느려진다.** CLI 도움말을 보려는데 연결을 기다린다
- **오류가 엉뚱한 곳에서 난다.** import 실패는 읽기 어려운 스택 트레이스를 만든다

**그래서 자원을 모듈 최상단이 아니라 팩터리 함수 안에서 만든다.** 모듈을 import하는 시점에는 아무 자원도 생성되지 않고, 함수를 호출할 때 만들어진다. `app/main.py`는 ASGI 앱을 노출하되 조립은 호출 시점에 수행한다.

### 유료 호출은 기본값으로 일어나지 않는다

`RuntimeApiServices`의 생성자에 규칙이 하나 박혀 있다.

```text
(llm_provider is None) != (provider_budget is None)  →  reject
```

LLM 공급자와 예산은 **둘 다 있거나 둘 다 없어야 한다.** 공급자만 주입하면 한도 없이 호출하게 되고, 예산만 주입하면 그 값을 사용할 호출이 없다.

**이 제약 때문에 환경 변수 기본값만으로 기동한 컨테이너는 유료 모델을 호출할 수 없다.** 검토 기능은 공급자와 예산을 함께 지정해야 동작하며, 이것이 이 프로젝트에서 fail-closed 원칙이 적용되는 마지막 지점이다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 네 개의 `Protocol` | **설계 결정 확인** | 런타임이 도메인을 느슨하게 잡는 법 |
| 투영 헬퍼 셋 | **필드 매핑 작성** | ORM 행이 API 리소스가 되는 지점 |
| `RuntimeApiServices.__init__` | 짝 제약을 **직접 구현** | 유료 호출을 기본값으로 막는 법 |
| 일곱 서비스 메서드 | 예외 변환을 **직접 구현** | 인프라 실패를 503으로 옮기는 경계 |
| `app/main.py` | **구조 작성** | 팩터리와 ASGI 앱의 관계 |

### 1. 런타임이 도메인을 느슨하게 잡는다

#### `app/api/runtime.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** 이 파일이 M1부터 M4까지를 모두 import한다는 점을 확인한다. 조립이 일어나는 지점이다.

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

#### `app/api/runtime.py` 확장 — 서비스 프로토콜

**학습 행동 — 설계 결정 확인:** 프로토콜 네 개가 각각 무엇을 교체 가능하게 만드는지 확인한다.

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

**코드에서 꼭 볼 것**

- `SessionFactory`, `RetrievalService`, `WorkflowService`, `RunPersister` 네 개가 모두 `Protocol`이다. 테스트가 필요한 것만 개별적으로 교체할 수 있다.
- 기본값은 실제 구현이다(`Session`, `retrieve`, `run_workflow`, `persist_run_report`). 주입하지 않으면 실제 구현이 사용되므로, 운영 경로에는 대체 구현이 끼어들 자리가 없다.

### 2. ORM 행이 API 리소스가 되는 지점

#### `app/api/runtime.py` 확장 — 투영 헬퍼

**학습 행동 — 필드 매핑 작성:** `_run_report`가 `Run`과 `Trace` 행을 어떻게 결합하는지 확인한다.

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

**코드에서 꼭 볼 것**

- `_document_resource`는 `chunk_count`를 인자로 받는다. **ORM 관계를 지연 로딩하면 문서 목록의 각 행마다 추가 질의가 발생하므로, 집계 값은 호출부의 단일 질의에서 계산해 전달한다.**
- `_run_report`는 M4.2의 `RunReport`를 **재구성한다.** 재료는 M1.4가 정의한 `Run`과 `Trace` 행이며, 저장된 행을 다시 도메인 값으로 만드는 지점은 이 함수 하나다.
- `_unavailable`은 503을 만든다. **인프라 의존성이 응답하지 않는 경우는 요청이 잘못된 것도 서버 코드가 실패한 것도 아니므로, 재시도가 의미 있는 상태 코드로 구분한다.**

### 3. 유료 호출을 기본값으로 막는다

#### `app/api/runtime.py` 완성 — 런타임 서비스

**학습 행동 — 짝 제약과 예외 변환 구현:** 생성자의 첫 검사를 직접 구현하고, 각 메서드의 `except` 블록이 어떤 예외를 잡는지 확인한다.

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

**코드에서 꼭 볼 것**

- `(llm_provider is None) != (provider_budget is None)`은 배타적 논리합이다. 둘 중 하나만 주어지면 생성 자체를 거부한다.
- 임베딩 공급자의 기본값은 `DeterministicEmbeddingProvider()`다. 검색은 비용 없이 동작하고 검토만 명시적 설정을 요구하므로, 비용이 발생하는 경로에만 fail-closed를 적용한다.
- 메서드마다 세션을 새로 연다(`async with self._session_factory()`). 요청 하나가 세션 하나를 소유하며, M2.7에서 세션을 호출자 소유로 정의한 결정이 이 구조를 가능하게 한다.
- `except OpenAIError`와 `except SQLAlchemyError`가 각각 다른 코드로 503을 만든다. 어느 의존성이 응답하지 않았는지가 응답 코드에 남는다.
- 예외 메시지에는 `type(error).__name__`만 넣는다. **원본 메시지에는 연결 문자열이 포함될 수 있으므로 타입 이름만 노출한다.**

### 4. 팩터리와 ASGI 앱

#### `app/main.py` 생성 — 런타임 진입점

**학습 행동 — 구조 작성:** 마지막 줄의 `app = create_app()`이 앞의 규칙과 충돌하지 않는 이유를 확인한다.

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

**코드에서 꼭 볼 것**

- `app = create_app()`이 모듈 수준에 있다. ASGI 서버가 `app.main:app` 형태의 참조를 요구하므로 이 줄은 필요하다.
- 그러나 `RuntimeApiServices()` 생성자는 **연결을 열지 않는다.** **엔진 객체만 만들고 실제 연결은 첫 요청에서 열리므로, 모듈을 import해도 데이터베이스에 접속하지 않는다.**
- `/health`가 이 파일에 있다. 컨테이너 헬스체크가 도메인 코드를 호출하지 않고 프로세스 생존만 확인한다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **import 시점에 연결을 열면 어떤 개발 작업이 느려지는가?**
  - **답:** CLI의 `--help`가 연결을 기다리며, 테스트 수집도 테스트를 실행하기 전부터 실제 DB를 요구하게 된다.
- **LLM 공급자와 예산을 XOR로 묶으면 무엇이 불가능해지는가?**
  - **답:** 공급자만 있고 예산이 없거나 예산만 있고 공급자가 없는 설정이 불가능해져, 반쪽짜리 설정에서 무제한 유료 호출이 생기지 않는다.
- **검색은 기본값으로 도는데 검토는 안 도는 이유는 무엇인가?**
  - **답:** 검색에는 무료 결정론적 임베딩 기본값이 있지만, 유료 호출이 가능한 검토는 LLM 공급자와 예산을 명시적으로 함께 넣어야 켜지기 때문이다.
- **인프라 실패가 500이 아니라 503인 이유는 무엇인가?**
  - **답:** 애플리케이션 자체의 오류가 아니라 DB나 공급자 의존성이 일시적으로 이용 불가한 상태라서, 나중에 재시도하면 성공할 수 있음을 알리기 위해서다.
- **모듈 수준 `app = create_app()`이 import 부수효과가 아닌 이유는 무엇인가?**
  - **답:** `create_app()`은 설정 객체만 만들며, `RuntimeApiServices`는 엔진을 보관할 뿐 첫 요청 전에는 실제 연결을 열지 않기 때문이다.

---

[← 이전: 라우트](03-routes.md) · [모듈 개요](../03-build.md) · [다음: CLI →](05-cli.md)
