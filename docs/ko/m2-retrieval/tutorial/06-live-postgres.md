# M2.8 튜토리얼 6 — 진짜 PostgreSQL로 전체 경로 증명하기

지금까지의 테스트는 SQL을 컴파일해 문자열을 검사하는 방식이었다. 빠르고 오프라인에서 실행되지만, 다음 네 가지는 확인하지 못한다.

- pgvector 확장이 정말 설치돼 있는가
- `vector(384)` 차원이 정말 맞는가
- `content_tsv` 생성 열이 정말 채워지는가
- 코사인 정렬이 정말 우리가 생각한 방향인가

**컴파일된 SQL은 질의의 문법과 구조만 증명하고, 그 질의가 실제 데이터베이스에서 어떤 결과를 내는지는 증명하지 않는다.** 이 문서에서 처음으로 실제 데이터베이스에 연결해 그 부분을 확인한다.

**선행 조건:** 튜토리얼 5의 `uv run pytest tests/retrieval/test_07_service.py -q`가 통과해야 한다. 이 문서만 실제 PostgreSQL 연결을 사용한다.

## 무엇을 검증하고 어디를 직접 확인할까

이 문서는 새 파일을 거의 만들지 않는다. 앞의 다섯 문서에서 작성한 코드가 **실제 데이터베이스에서도 같은 결과를 내는지** 확인하는 단계이므로, 학습 행동도 작성이 아니라 검증이다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `bootstrap_schema` | 순서 제약을 **직접 구현** | 확장과 테이블 사이의 의존 방향 |
| pgvector 차원 확인 | **실제 데이터베이스에서 확인** | 컴파일 검증이 잡지 못하는 것 |
| `content_tsv` 채움 확인 | **실제 데이터베이스에서 확인** | 생성 열이 언제 계산되는가 |
| 코사인 정렬 방향 확인 | **실제 데이터베이스에서 확인** | 연산자 방향을 거꾸로 잡았을 때의 증상 |
| 전체 인수 실행 | **결과 해석** | 건너뜀과 실패를 가르는 기준 |

데이터베이스에 연결할 수 없으면 이 문서의 테스트만 건너뛴다. 건너뛴 테스트는 통과한 테스트가 아니므로, 실제 PostgreSQL에서 검증했다고 기록하려면 최소 한 번은 연결한 상태로 실행해야 한다.

## 확장을 만든 다음에 테이블을 만든다

새 데이터베이스에는 `vector(384)` 타입이 존재하지 않는다. 이 타입은 pgvector 확장을 활성화해야 생긴다.

그래서 `bootstrap_schema`는 다음 순서를 지켜야 한다.

```
CREATE EXTENSION IF NOT EXISTS vector   ← first
        ↓
Base.metadata.create_all                ← then
```

**순서가 반대이면 `chunks` 테이블을 만드는 시점에 vector 타입이 없어 DDL이 실패한다.** 두 구문 모두 `IF NOT EXISTS`를 사용하므로 멱등하고, 시드 CLI가 `--create-schema`로 여러 번 호출해도 결과가 같다.

### 대상 파일: `app/db/bootstrap.py`

<!-- src: app/db/bootstrap.py::ensure_vector_extension,bootstrap_schema -->
```python
async def ensure_vector_extension(connection: AsyncConnection) -> None:
    """Enable pgvector in the current database if it is not already enabled."""
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Enable pgvector before creating missing SQLAlchemy tables and indexes."""
    async with engine.begin() as connection:
        await ensure_vector_extension(connection)
        await connection.run_sync(Base.metadata.create_all)
```

**코드에서 꼭 볼 것**

- 두 구문이 하나의 `engine.begin()` 블록 안에서 실행된다. 중간에 실패하면 전체가 롤백되므로 절반만 만들어진 스키마가 남지 않는다.
- `run_sync`는 동기 SQLAlchemy API를 async 코드에서 실행하게 해 준다. `create_all`은 스키마를 동기적으로 검사하고 DDL을 발행하며, async 버전이 없다.
- 두 함수 모두 import 시점에 호출되지 않는다. `--create-schema`를 지정한 실행만 이 경로에 닿으므로, 스키마 생성이 프로그램 시작의 부수효과가 되지 않는다.

## 통합 테스트가 안전하려면

실제 데이터베이스에 쓰는 테스트는 대상 데이터베이스를 잘못 지정하면 실제 데이터를 변경할 수 있다. 그래서 세 가지 방어를 둔다.

**루프백 주소만 허용한다.** 픽스처는 설정된 프로젝트 데이터베이스만 받고 `localhost`를 `127.0.0.1`로 정규화한다. 스테이징이나 운영 URL이 설정에 들어가면 테스트가 실행을 거부한다.

**임시 테이블만 사용한다.** M1.4와 같은 방식으로 연결 범위의 임시 `documents`, `chunks`를 만들고 결정론적 벡터 세 개를 넣는다. **임시 테이블은 연결이 닫힐 때 사라지므로, 테스트가 실패하거나 중단되어도 애플리케이션 스키마와 데이터가 남지 않는다.**

**연결 프로브에 짧은 타임아웃을 건다.** 데이터베이스가 없는 환경에서 테스트가 오래 대기하지 않고 곧바로 건너뛴다.

이 조건 아래에서 확장 설정, 정확 코사인 SQL, 생성 FTS 열, RRF, 인용 필드, 출처 해시까지 전체 경로를 한 번에 검증한다.

```
bootstrap_schema → pgvector → tables → isolated test rows → vector/lexical search → RRF → grounded result
```

**건너뛴 테스트는 통과가 아니라 아직 검증하지 않은 항목이다.** 실행 결과를 읽을 때 두 상태를 구분한다.

이 체크포인트에서는 새 파일을 만들지 않는다. `app/db/bootstrap.py`와 `app/ingestion/seed.py`는 M1.4에서 이미 만들었고, 여기서는 그 경계를 실제 PostgreSQL에 연결한다.

이 단계에서 새로 생기는 계약은 없다. 검증 대상은 모두 앞에서 작성했고 컴파일된 SQL로 확인한 것들이다. 달라지는 것은 그 확인을 수행하는 주체가 문자열 비교가 아니라 실제 데이터베이스라는 점이다.

| 컴파일된 SQL이 말해 줄 수 없던 것 | 진짜 데이터베이스가 결론 내는 것 |
|---|---|
| `vector` 타입이 애초에 존재하는가 | pgvector가 설치되고 활성화돼 있다. |
| `vector(384)`가 저장된 열과 맞는가 | 질의와 열의 차원이 실제로 일치한다. |
| `content_tsv`가 정말 채워지는가 | 생성 열이 쓰기 시점에 채워진다. |
| `<=>`가 실제로 어느 방향으로 정렬하는가 | 가장 가까운 근거가 정말 먼저 온다. |
| 두 경로가 같은 행을 돌려주는가 | RRF가 하나의 코퍼스에서 뽑힌 목록을 융합한다. |

여기까지 확인했으면 테스트를 실행해 결과를 확인한다.

```bash
docker compose up -d db
uv run pytest tests/retrieval/test_08_postgres.py -q
```

설정한 루프백 PostgreSQL에 연결한 상태에서 이 테스트가 통과해야 한다. 건너뛴 결과는 환경 검증이 끝나지 않았다는 뜻이다.

테스트가 실패하거나 건너뛰면 M2를 완료로 표시하지 않는다. 애플리케이션 코드를 수정하지 말고, 프로젝트 데이터베이스에 연결할 수 있는 상태를 만든 뒤 다시 실행한다.

테스트를 건너뛰면 `docker compose ps db`와 설정된 루프백 데이터베이스 URL을 확인한다. PostgreSQL이 `vector` 타입을 찾지 못한다고 보고하면 `CREATE EXTENSION IF NOT EXISTS vector`가 `Base.metadata.create_all`보다 먼저 실행되는지 확인한다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **컴파일된 SQL 테스트가 결코 잡을 수 없는 결함 부류는 무엇인가?**
  - **답:** 확장·타입의 실제 존재 여부, 생성 열의 동작, PostgreSQL 연산자가 만드는 실제 정렬처럼 살아 있는 데이터베이스의 실행 동작은 잡을 수 없다.
- **확장 활성화가 `create_all`보다 뒤가 아니라 앞이어야 하는 이유는 무엇인가?**
  - **답:** `create_all`은 테이블을 만들면서 `vector(384)` 열 타입을 해석해야 하는데, pgvector를 활성화하기 전에는 그 타입이 존재하지 않는다.
- **건너뛴 통합 테스트가 통과한 테스트와 같지 않은 이유는 무엇인가?**
  - **답:** 건너뜀은 필요한 환경을 사용할 수 없었다는 뜻이므로 실제 PostgreSQL 동작은 아직 검증되지 않았다.
- **전용 테스트 데이터베이스가 지켜 주지 못하는 무엇을 임시 테이블이 지키는가?**
  - **답:** 테스트 데이터베이스 안에서도 애플리케이션의 영구 스키마와 행을 건드리지 않게 하고, 연결이 닫히면 테스트 데이터를 자동으로 없앤다.

---

# 전체 인수 경로

```bash
docker compose up -d db
uv run python -m app.ingestion.seed --create-schema
uv run python -m app.retrieval --provider deterministic --embed-missing --query "NVDA 2024 R&D" -k 3
uv run pytest tests/retrieval -q
uv run ruff check --no-fix app tests scripts
uv run python scripts/check_doc_code.py
```

건너뛴 항목을 해석하거나, 공급자를 변경하거나, 근사 인덱스를 추가하기 전에 [검증](../05-verify.md)을 읽는다.

---

[← 이전: 서비스](05-service.md) · [모듈 개요](../03-build.md)
