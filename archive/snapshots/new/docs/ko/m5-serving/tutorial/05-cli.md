# M5.2 튜토리얼 5 — CLI는 일급 시민이다

이 시스템은 Docker와 HTTP 서버 없이 터미널에서 바로 실행할 수 있어야 한다. 질의 하나를 확인하려고 컨테이너를 기동하면 확인에 필요한 시간이 실행 시간보다 길어진다.

또한 CLI는 **실패할 때도 일정한 형식으로 실패해야 한다.** 빈 질의, 잘못된 개수, 존재하지 않는 파일, 깨진 JSON, 응답하지 않는 의존성이 각각 고정된 종료 코드와 JSON을 반환해야 한다. **이 CLI를 스크립트가 호출하므로, 종료 코드가 상황마다 달라지면 호출 측이 실패 유형을 구분할 수 없다.**

**선행 조건:** 튜토리얼 4에서 `api/runtime.py`와 `main.py`를 작성한 상태여야 한다.

### 종료 코드를 의미로 나눈다

| 코드 | 의미 |
|---|---|
| 0 | 성공 |
| 2 | 입력이 잘못됨 (빈 질의, 음수 k) |
| 3 | 파일이 잘못됨 (없음, 깨진 JSON) |
| 4 | 의존성에 닿을 수 없음 (DB, 공급자) |

**2와 3은 모두 호출 측이 고쳐야 하는 실패지만 고칠 대상이 다르다.** 2는 명령의 인자를 고쳐야 하고, 3은 입력 파일을 고쳐야 한다.

4를 따로 둔 이유도 같다. **인프라에 닿지 못한 실패는 같은 명령을 그대로 다시 실행해도 성공할 수 있으므로, 재시도가 의미 없는 2·3과 구분한다.**

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `ExitCode`·`CliError` | **레코드 선언 작성** | 종료 코드를 의미로 나누는 법 |
| `CliArgumentParser` | **설계 결정 확인** | argparse 기본 종료 코드를 바꾸는 이유 |
| `_validate_arguments` | 검증을 **직접 구현** | I/O 전에 거부하는 경계 |
| `_retrieve`·`_ingest` | **필드 매핑 작성** | HTTP와 같은 근거 모양을 내는 법 |
| `main` | 예외 변환을 **직접 구현** | 예외가 종료 코드가 되는 지점 |

### 1. 종료 코드를 의미로 나눈다

#### `app/cli.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록에서 `app.api.runtime`을 확인한다. CLI가 HTTP와 **같은 조립 계층**을 사용한다는 뜻이다.

```python
"""Deterministic command-line entrypoints for retrieval, ingestion, and serving."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
import json
from pathlib import Path
import sys
from typing import Any, Literal, TextIO

from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.retrieval.types import ChunkHit, RetrievalFilters

ProviderName = Literal["deterministic", "openai"]

```

#### `app/cli.py` 확장 — 종료 코드와 파서 기반

**학습 행동 — 레코드 선언 작성:** `CliArgumentParser`가 어떤 메서드를 재정의하는지 확인한다.

<!-- src: app/cli.py::ExitCode,CliArgumentParser -->
```python
class ExitCode(IntEnum):
    """Stable process exit codes for expected CLI outcomes."""

    OK = 0
    INVALID_INPUT = 2
    INVALID_FILE = 3
    UNAVAILABLE = 4


class CliError(Exception):
    """An expected CLI failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class CliArgumentParser(argparse.ArgumentParser):
    """Convert argparse failures into the same JSON envelope as runtime failures."""

    def error(self, message: str) -> None:
        """Raise a structured CliError instead of printing usage and exiting."""
        raise CliError("invalid_arguments", message, ExitCode.INVALID_INPUT)
```

**코드에서 꼭 볼 것**

- `ExitCode`는 `IntEnum`이다. `sys.exit(ExitCode.INVALID_INPUT)`이 그대로 정수 2를 반환한다.
- `CliArgumentParser.error`가 argparse의 기본 종료 코드를 `INVALID_INPUT`으로 명시한다. 두 값이 현재는 같지만, **명시하지 않으면 argparse가 기본값을 바꿀 때 이 CLI의 종료 코드 계약도 함께 바뀐다.**
- `CliError`는 코드, 메시지, 종료 코드 세 가지를 담는다. 예외를 던지는 쪽이 종료 코드까지 결정한다.

### 2. I/O 전에 거부한다

#### `app/cli.py` 확장 — 인자 정의

**학습 행동 — 구조 작성:** 서브커맨드 세 개가 각각 어떤 인자를 받는지 확인한다.

<!-- src: app/cli.py::_add_retrieve_arguments,arguments -->
```python
def _add_retrieve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True, help="Nonblank retrieval query.")
    parser.add_argument("-k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per retrieval component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai"),
        default="deterministic",
        help="Embedding provider; deterministic is the offline default.",
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument("--doc-id", action="append", default=[], help="Exact document filter.")
    parser.add_argument("--ticker", action="append", default=[], help="Exact ticker filter.")
    parser.add_argument(
        "--fiscal-year",
        action="append",
        default=[],
        type=int,
        help="Exact fiscal-year filter.",
    )
    parser.add_argument("--form", action="append", default=[], help="Exact filing-form filter.")
    parser.add_argument("--item", action="append", default=[], help="Exact filing-item filter.")
    parser.add_argument(
        "--kind",
        action="append",
        default=[],
        choices=("text", "table"),
        help="Exact chunk-kind filter.",
    )


def _add_ingest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the corpus manifest JSON file.",
    )
    parser.add_argument(
        "--expected-documents",
        type=int,
        default=20,
        help="Fail unless the manifest contains this many documents.",
    )
    parser.add_argument(
        "--chunk-batch-size",
        type=int,
        default=500,
        help="Number of chunk rows per PostgreSQL upsert statement.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create missing tables before ingestion; existing tables are not migrated.",
    )


def _add_serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="Interface address to bind.")
    parser.add_argument("--port", type=int, default=8000, help="TCP port to bind.")
    parser.add_argument("--workers", type=int, default=1, help="Number of Uvicorn workers.")
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default="info",
        help="Uvicorn log level.",
    )


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse one explicit runtime command without opening files or services."""
    parser = CliArgumentParser(prog="docreview", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    retrieve = subparsers.add_parser("retrieve", help="Retrieve cited filing evidence.")
    ingest = subparsers.add_parser("ingest", help="Upsert one local corpus manifest.")
    serve = subparsers.add_parser("serve", help="Run the FastAPI application with Uvicorn.")
    _add_retrieve_arguments(retrieve)
    _add_ingest_arguments(ingest)
    _add_serve_arguments(serve)
    return parser.parse_args(argv)
```

**코드에서 꼭 볼 것**

- `arguments()`는 파일도 서비스도 열지 않는다. 인자 파싱과 실행을 분리했으므로 인자 검증만 따로 테스트할 수 있고, 잘못된 명령이 데이터베이스에 닿기 전에 거부된다.
- `required=True`가 서브커맨드를 필수로 만든다. **이 설정이 없으면 서브커맨드 없이 `docreview`만 실행했을 때 아무 작업도 하지 않고 종료 코드 0을 반환하므로, 호출한 스크립트가 성공으로 처리한다.**
- 인자 정의를 각각 함수로 분리했다. 명령이 늘어도 `arguments()`는 `add_parser` 호출과 `_add_*_arguments` 호출 두 줄씩만 늘어나므로 엔트리포인트는 계속 읽을 만하다.

#### `app/cli.py` 확장 — 검증과 투영

**학습 행동 — 검증 구현:** `_validate_arguments`를 직접 구현하고, 이 함수가 I/O를 전혀 수행하지 않는다는 점을 확인한다.

<!-- src: app/cli.py::_validate_arguments,_evidence_payload -->
```python
def _validate_arguments(args: argparse.Namespace) -> None:
    if args.command == "retrieve":
        if not args.query.strip():
            raise CliError(
                "empty_query",
                "query must not be blank",
                ExitCode.INVALID_INPUT,
            )
        if args.k <= 0:
            raise CliError("invalid_k", "k must be positive", ExitCode.INVALID_INPUT)
        if args.candidate_k is not None and args.candidate_k < args.k:
            raise CliError(
                "invalid_candidate_k",
                "candidate-k must be at least k",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "ingest":
        if args.expected_documents <= 0:
            raise CliError(
                "invalid_expected_documents",
                "expected-documents must be positive",
                ExitCode.INVALID_INPUT,
            )
        if args.chunk_batch_size <= 0:
            raise CliError(
                "invalid_chunk_batch_size",
                "chunk-batch-size must be positive",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "serve":
        if not args.host.strip():
            raise CliError("invalid_host", "host must not be blank", ExitCode.INVALID_INPUT)
        if not 1 <= args.port <= 65_535:
            raise CliError(
                "invalid_port",
                "port must be between 1 and 65535",
                ExitCode.INVALID_INPUT,
            )
        if args.workers <= 0:
            raise CliError(
                "invalid_workers",
                "workers must be positive",
                ExitCode.INVALID_INPUT,
            )


def _provider_settings(settings: Settings, provider: ProviderName) -> Settings:
    return settings.model_copy(update={"embedding_provider": provider})


def _filters(args: argparse.Namespace) -> RetrievalFilters:
    return RetrievalFilters(
        doc_ids=tuple(args.doc_id),
        tickers=tuple(args.ticker),
        fiscal_years=tuple(args.fiscal_year),
        forms=tuple(args.form),
        items=tuple(args.item),
        kinds=tuple(args.kind),
    )


def _evidence_payload(hit: ChunkHit) -> dict[str, object]:
    """Project the same public evidence fields exposed by the HTTP boundary."""
    from app.api.schemas import EvidenceHit

    return EvidenceHit.from_chunk_hit(hit).model_dump(mode="json")
```

**코드에서 꼭 볼 것**

- `_validate_arguments`는 파일을 열지도 연결을 만들지도 않는다. **잘못된 명령은 데이터베이스 연결이나 공급자 호출 없이 거부된다.**
- `_evidence_payload`가 `ChunkHit`을 딕셔너리로 변환한다. 이 결과의 필드 구성이 HTTP의 `EvidenceHit`과 같아야 하며, M5.3이 두 경로를 대조해 검증한다.
- `_filters`가 CLI 인자를 `RetrievalFilters`로 옮긴다. M2.1의 정규화가 CLI 경로에서도 그대로 적용된다.

### 3. HTTP와 같은 이음매를 쓴다

#### `app/cli.py` 확장 — 명령 실행

**학습 행동 — 필드 매핑 작성:** `_retrieve`가 `RuntimeApiServices`를 어떻게 사용하는지 확인한다.

<!-- src: app/cli.py::_retrieve,_run_data_command -->
```python
async def _retrieve(args: argparse.Namespace) -> dict[str, object]:
    from app.db.session import Session
    from app.retrieval.embeddings import embed_missing_chunks, get_embedding_provider
    from app.retrieval.service import retrieve

    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    async with Session() as session:
        backfill = None
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            filters=_filters(args),
        )
    return {
        "status": "ok",
        "command": "retrieve",
        "query": args.query,
        "provider": settings.embedding_provider,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [_evidence_payload(hit) for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


def _checked_manifest(path: Path) -> Path:
    if not path.is_file():
        raise CliError(
            "manifest_not_found",
            f"manifest file does not exist: {path}",
            ExitCode.INVALID_FILE,
        )
    return path


async def _ingest(args: argparse.Namespace) -> dict[str, object]:
    from app.db.bootstrap import bootstrap_schema
    from app.db.session import Session, engine
    from app.ingestion.seed import persist_seed_batch, prepare_seed_batch

    manifest = _checked_manifest(args.manifest)
    try:
        batch = prepare_seed_batch(
            manifest,
            expected_documents=args.expected_documents,
        )
    except json.JSONDecodeError as error:
        raise CliError(
            "invalid_manifest_json",
            f"manifest is not valid JSON at line {error.lineno} column {error.colno}",
            ExitCode.INVALID_FILE,
        ) from error
    except UnicodeDecodeError as error:
        raise CliError(
            "invalid_manifest_encoding",
            "manifest must be UTF-8 text",
            ExitCode.INVALID_FILE,
        ) from error
    except FileNotFoundError as error:
        raise CliError(
            "corpus_file_not_found",
            f"corpus file does not exist: {error.filename}",
            ExitCode.INVALID_FILE,
        ) from error
    except ValueError as error:
        raise CliError(
            "invalid_manifest",
            str(error),
            ExitCode.INVALID_FILE,
        ) from error

    if args.create_schema:
        await bootstrap_schema(engine)
    async with Session() as session:
        result = await persist_seed_batch(
            session,
            batch,
            chunk_batch_size=args.chunk_batch_size,
        )
    return {
        "status": "ok",
        "command": "ingest",
        "manifest": str(manifest),
        "documents": result.documents,
        "chunks": result.chunks,
    }


async def _run_data_command(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "retrieve":
        return await _retrieve(args)
    if args.command == "ingest":
        return await _ingest(args)
    raise AssertionError(f"unsupported data command: {args.command}")
```

**코드에서 꼭 볼 것**

- `RuntimeApiServices`를 직접 생성해 사용한다. HTTP 라우트가 주입받는 것과 같은 타입이므로, **진입점이 둘이어도 도메인을 호출하는 경로는 하나다.**
- `_checked_manifest`가 파일 존재 여부와 JSON 유효성을 확인하고 `INVALID_FILE`을 던진다. 인자 자체가 잘못된 `INVALID_INPUT`과 구분되는 지점이다.
- `_ingest`가 `--create-schema`를 지원한다. M1.4의 부트스트랩이 CLI 옵션으로 노출된다.

### 4. 예외가 종료 코드가 되는 지점

#### `app/cli.py` 완성 — 서브 실행과 진입점

**학습 행동 — 예외 변환 구현:** `main`의 `try/except` 계층을 직접 구현하고, 각 절이 어떤 종료 코드로 이어지는지 확인한다.

<!-- src: app/cli.py::_serve,entrypoint -->
```python
def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level,
    )


def _failure_payload(error: CliError) -> dict[str, object]:
    return {
        "status": "error",
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }


def _write_json(value: dict[str, object], stream: TextIO) -> None:
    json.dump(value, stream, ensure_ascii=False, sort_keys=True)
    stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return a stable process exit code."""
    try:
        args = arguments(argv)
        _validate_arguments(args)
        if args.command == "serve":
            _serve(args)
            return ExitCode.OK
        payload = asyncio.run(_run_data_command(args))
    except CliError as error:
        _write_json(_failure_payload(error), sys.stderr)
        return error.exit_code
    except OpenAIError as error:
        failure = CliError(
            "provider_unavailable",
            f"embedding provider is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code
    except SQLAlchemyError as error:
        failure = CliError(
            "database_unavailable",
            f"database is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code

    _write_json(payload, sys.stdout)
    return ExitCode.OK


def entrypoint() -> None:
    """Run the installed console script without printing a Python traceback."""
    raise SystemExit(main())
```

**코드에서 꼭 볼 것**

- `main`은 `int`를 반환한다. **`sys.exit`을 호출하지 않으므로 테스트가 이 함수를 직접 호출해 종료 코드를 값으로 검사할 수 있다.**
- `_failure_payload`가 실패도 JSON으로 출력한다. 호출한 스크립트가 stdout을 파싱해 오류 코드를 읽는다.
- `ApiProblemError`를 잡아 `UNAVAILABLE`로 변환한다. M5.1에서 503으로 나가던 상태가 CLI에서는 종료 코드 4로 표현된다.
- `_serve`가 uvicorn을 호출하는 유일한 함수다. import 시점이 아니라 `serve` 명령을 실행할 때만 호출된다.

파일 마지막에 모듈 실행 가드를 덧붙인다. 이 두 줄이 있어야 `python -m app.cli`가 동작한다.

```python
if __name__ == "__main__":
    entrypoint()
```

### 5. 조립은 따로 검증한다

M5.1의 테스트는 가짜 서비스로 HTTP 응답 형태만 검증했고, M5.2의 테스트는 런타임 어댑터만 따로 검증했다.

**두 테스트가 모두 통과해도 조립된 상태에서는 다르게 동작할 수 있다.**

예를 들어 HTTP는 근거를 `EvidenceHit`으로 반환하는데 CLI는 필드 구성이 조금 다른 딕셔너리를 반환하는 경우, 두 테스트는 각각 통과한다. 이 차이는 두 경로를 함께 사용하는 M6의 UI에서 드러난다.

그래서 M5.3은 **새 코드를 작성하지 않고 조립된 상태만 검증한다.**

- `/retrieve`가 정말 M2를 부르는가 (가짜가 아니라)
- `/review`가 M2를 거쳐 M4에 닿는가
- 종료 리포트가 정말 저장되는가
- **CLI와 HTTP가 같은 근거 모양을 내는가**
- 헬스와 OpenAPI가 노출되는가

### 헬스체크는 코퍼스를 요구하면 안 된다

`/health`는 `HealthResponse()`만 반환하고 데이터베이스에 접근하지 않는다.

헬스체크가 답하는 질문은 프로세스가 요청을 받을 수 있는 상태인지이고, 코퍼스가 적재됐는지는 다른 질문이다.

**헬스체크가 데이터베이스를 조회하면 컨테이너는 정상 기동했는데 시딩이 끝나지 않은 동안 헬스체크가 실패하고, 오케스트레이터가 그 컨테이너를 계속 재시작한다.** 두 상태를 서로 다른 확인 경로로 분리한다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/api/test_06_cli.py tests/api/test_07_runtime.py -q
uv run pytest tests/api/test_08_integration.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 빈 질의와 없는 파일이 같은 종료 코드 | 스크립트가 고칠 대상을 구분할 수 있다. |
| import 시점의 데이터베이스 연결 | 테스트 수집과 `--help`가 DB 없이 돈다. |
| HTTP와 다른 CLI 근거 모양 | 두 진입점이 같은 이야기를 한다. |
| DB를 때리는 헬스체크 | 시딩 지연이 재시작 루프를 만들지 않는다. |
| 기본값만으로 도는 유료 호출 | 검토는 명시적으로 켜야 켜진다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **종료 코드 2와 3을 나누면 스크립트가 무엇을 판단할 수 있는가?**
  - **답:** 명령 인자를 고쳐야 하는지, 파일을 수정하거나 교체해야 하는지 구분해 다음 동작을 선택할 수 있다.
- **`_validate_arguments`가 I/O를 하지 않는 것이 왜 중요한가?**
  - **답:** 잘못된 명령을 파일, 네트워크, DB 비용 없이 결정론적으로 거부할 수 있기 때문이다.
- **CLI가 `RuntimeApiServices`를 직접 쓰는 것이 무엇을 보장하는가?**
  - **답:** 현재 CLI는 `RuntimeApiServices`를 `_retrieve`나 `_ingest`에서 쓰지 않고 DB·검색·수집 호출을 직접 조립한다. 따라서 이 구현 자체만으로 HTTP와의 일치성이 보장되지는 않는다.
- **`main`이 `sys.exit`을 부르지 않는 이유는 무엇인가?**
  - **답:** 테스트와 다른 파이썬 호출자가 `SystemExit`을 잡지 않고 정수 결과를 확인할 수 있게 하고, 프로세스 종료 변환은 `entrypoint`에만 맡기기 위해서다.
- **헬스체크가 데이터베이스를 때리면 배포에서 무슨 일이 생기는가?**
  - **답:** 시딩이나 일시적인 DB 지연 때문에 정상 프로세스도 준비되지 않은 것으로 판정되어 오케스트레이터가 계속 재시작할 수 있다.

---

[← 이전: 런타임 조립](04-runtime.md) · [모듈 개요](../03-build.md)
