# M7.2 튜토리얼 3 — 파이썬에서 지킨 약속을 이미지 안까지 운반한다

M7.1에서 코드 수준 가드를 모두 만들었다. 컨테이너를 다음과 같이 구성하면 그 가드들이 동작하지 않거나 우회된다.

- **root로 돈다** — 컨테이너 탈출이 훨씬 큰 피해를 준다
- **워커를 여러 개 띄운다** — `InProcessRateLimiter`는 한 프로세스 안에서 세므로, 워커 넷이면 의도한 한도의 네 배가 된다
- **비밀을 패키징한다** — 빌드 컨텍스트로 쓸려 들어간 `.env`는 이미지를 가진 누구나 키를 읽게 한다
- **엉뚱한 포트를 연다**

**두 번째 항목은 오류를 발생시키지 않는다. 속도 제한이 단일 프로세스를 전제한다는 사실을 모르는 상태에서 성능을 위해 워커 수를 올리면, 한도는 그대로인데 실제 허용량만 워커 수만큼 늘어난다.**

그래서 배포 산출물이 코드와 같은 전제를 유지해야 한다. 경계는 코드에서 끝나지 않는다.

**선행 조건:** 튜토리얼 2의 `tests/release` 앱 스위트가 통과해야 한다.

### 메타데이터는 설정이지 증명이 아니다

`deploy/huggingface/README.md`는 배포 방법을 설명하는 문서이고, **배포가 실제로 수행됐다는 증거는 아니다.**

헬스체크도 프로세스가 요청을 받을 준비가 됐다는 것만 확인하고, 로컬 UI 스모크 테스트는 canned 모드의 Gradio 경계만 검증한다. 각 산출물이 무엇을 증명하고 무엇을 증명하지 않는지 구분해 기록한다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `.dockerignore` | **설정 작성 후 책임 확인** | 빌드 컨텍스트에서 빼야 하는 것 |
| `Dockerfile` | **구조 작성 후 설계 결정 확인** | 비루트·단일 워커·헬스체크 |
| `docker-compose.yml` | **구조 작성** | 로컬 API·DB 경로 |
| HF `Dockerfile` | **경계 변환 검토** | Space가 요구하는 것과 우리 가정의 접점 |
| `space.env.example` | **설정 작성** | 공개해도 되는 기본값 |

### 1. 빌드 컨텍스트에서 빼야 하는 것

#### `.dockerignore` 생성 — 빌드 컨텍스트 제외

**학습 행동 — 설정 작성 후 책임 확인:** 각 줄이 어떤 유출 또는 이미지 크기 증가를 막는지 확인한다.

<!-- file: .dockerignore -->
```text
.git
.venv
.env
.env.*
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.mypy_cache
htmlcov
old
42_curriculum
data/corpus/**/*.html
data/eval_runs
```

**코드에서 꼭 볼 것**

- `.env`가 목록에 있다. **이 줄이 빠지면 키가 이미지 레이어에 포함되고, 이후 파일을 삭제하는 레이어를 추가해도 앞선 레이어에 원본이 남는다.**
- `data/`가 목록에 있다. 코퍼스 전체가 빌드 컨텍스트에 들어가면 이미지가 그만큼 커진다. 루트 `Dockerfile`은 `COPY`로 `data`를 명시적으로 포함하고, Space 이미지는 포함하지 않는다.

### 2. 비루트·단일 워커·헬스체크

#### `Dockerfile` 생성 — 로컬 API 이미지

**학습 행동 — 구조 작성 후 설계 결정 확인:** `USER appuser`의 위치와 `--workers 1`이 지정된 이유를 확인한다.

<!-- file: Dockerfile -->
```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "python", "-m", "app.cli", "serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**코드에서 꼭 볼 것**

- `useradd`로 uid 10001 사용자를 만들고 `USER appuser`로 전환한다. 이 줄 이후의 모든 명령이 비루트 사용자로 실행된다.
- `COPY --chown=appuser:appuser`로 소유권을 함께 지정한다. root 소유로 복사된 파일을 비루트 프로세스가 읽지 못하는 상황을 막는다.
- `--workers 1`을 명시한다. **M7.1의 속도 제한은 프로세스 안의 상태로 요청을 세므로, 워커가 둘이면 실제 허용량이 설정한 한도의 두 배가 된다.**
- 의존성 설치를 코드 `COPY`보다 **먼저** 둔다. 코드가 바뀌어도 의존성 레이어의 캐시가 유지된다.
- `HEALTHCHECK`가 `/health`를 호출한다. M5.2에서 데이터베이스를 조회하지 않도록 만든 엔드포인트다.

#### `docker-compose.yml` 생성 — 로컬 스택

**학습 행동 — 구조 작성:** 데이터베이스 서비스와 API 서비스의 의존 관계를 확인한다.

<!-- file: docker-compose.yml -->
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: filing
      POSTGRES_USER: filing
      POSTGRES_PASSWORD: filing
    ports: ["${DB_PORT:-5432}:5432"]
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U filing -d filing"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      CORPUS_DIR: /app/data/corpus
      DATABASE_URL: postgresql+asyncpg://filing:filing@db:5432/filing
      EMBEDDING_PROVIDER: deterministic
    depends_on:
      db:
        condition: service_healthy
    ports: ["${APP_PORT:-8000}:8000"]
    init: true
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()",
        ]
      interval: 10s
      timeout: 3s
      start_period: 10s
      retries: 5

volumes:
  pg_data:
```

**코드에서 꼭 볼 것**

- pgvector가 포함된 이미지를 사용한다. M1.4의 `CREATE EXTENSION`이 성공하려면 확장이 설치된 이미지여야 한다.
- API 서비스의 `depends_on`에 헬스체크 조건을 건다. 데이터베이스가 준비되기 전에 시드가 실행되지 않는다.

### 3. Space가 요구하는 것과 우리 가정의 접점

#### `deploy/huggingface/Dockerfile` 생성 — Space 이미지

**학습 행동 — 경계 변환 검토:** 루트 `Dockerfile`과 나란히 놓고 차이점을 모두 찾는다.

<!-- file: deploy/huggingface/Dockerfile -->
```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DOCREVIEW_MODE=canned \
    DOCREVIEW_PORT=7860

RUN useradd --create-home --uid 1000 user \
    && mkdir --parents /home/user/app \
    && chown user:user /home/user/app
WORKDIR /home/user/app

COPY --from=uv /uv /uvx /bin/
COPY --chown=user:user pyproject.toml uv.lock README.md ./

USER user
RUN uv sync --locked --no-dev --extra demo --no-install-project

COPY --chown=user:user app ./app

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "uvicorn", "app.release.space:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--log-level", "warning"]
```

**코드에서 꼭 볼 것**

- uid가 **1000**이다. Hugging Face Space가 요구하는 값이므로 선택한 것이 아니라 플랫폼 제약이다.
- 포트가 7860이다. 이 값도 Space 규약이다.
- `DOCREVIEW_MODE=canned`를 **이미지에 포함한다.** 환경 변수를 지정하지 않아도 canned 모드로 기동하므로, M7.1의 기본값이 이미지 계층에서 한 번 더 고정된다.
- `data`를 복사하지 않는다. Space는 코퍼스 없이 canned 모드로만 동작한다.
- `--extra demo`로 Gradio를 설치한다. 로컬 이미지에는 포함하지 않는 의존성이다.

#### `deploy/huggingface/space.env.example` 생성 — 공개 기본값 예시

**학습 행동 — 설정 작성:** 이 파일에 실제 키 값이 없다는 점을 확인한다.

<!-- file: deploy/huggingface/space.env.example -->
```bash
# Public Spaces should remain canned unless runtime dependencies are explicitly provisioned.
DOCREVIEW_MODE=canned
DOCREVIEW_RATE_LIMIT_PER_MINUTE=10
DOCREVIEW_RATE_LIMIT_PER_DAY=100
DOCREVIEW_RATE_LIMIT_MAX_CLIENTS=1024
DOCREVIEW_TRUST_PROXY_HEADERS=false
DOCREVIEW_ALLOW_INGEST=false

# Runtime review is opt-in and still bounded by all three caps.
DOCREVIEW_OPENAI_MODEL=gpt-4.1-mini
DOCREVIEW_OPENAI_MAX_INPUT_TOKENS=12000
DOCREVIEW_OPENAI_MAX_OUTPUT_TOKENS=600
DOCREVIEW_OPENAI_MAX_COST_USD=0.01
DOCREVIEW_OPENAI_INPUT_PER_MILLION_USD=0.40
DOCREVIEW_OPENAI_OUTPUT_PER_MILLION_USD=1.60

# Configure OPENAI_API_KEY only as a server-side Space secret, never as a public variable.
```

**코드에서 꼭 볼 것**

- 파일 이름에 `.example` 접미사가 있고 `.dockerignore`가 `.env`를 제외한다. 이 예시를 복사해 실제 파일을 만들어도 그 파일은 이미지에 포함되지 않는다.
- 실제 비밀 값은 Space 설정 화면에 입력한다. 저장소에는 두지 않는다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/release/test_05_assets.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| root로 도는 이미지 | 컨테이너가 비루트로 실행된다. |
| 1이 아닌 워커 수 | 인프로세스 속도 제한 가정이 유지된다. |
| `.env`가 `.dockerignore`에서 빠진 경우 | 비밀이 이미지 레이어에 남지 않는다. |
| Space 규약과 다른 포트·uid | 플랫폼 제약을 만족한다. |
| 이미지 기본값이 runtime | 배포가 기본으로 돈을 쓰지 않는다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 설정 파일과 연결해 설명해 본다.

- **워커 수를 올리면 M7.1의 무엇이 조용히 해체되는가?**
  - **답:** `InProcessRateLimiter`는 프로세스마다 독립적으로 요청을 센다. 워커가 둘이면 설정한 트래픽의 약 두 배를 허용하므로 오류 없이 단일 프로세스 속도 제한 경계가 깨진다.
- **`.env`가 이미지에 한 번 들어가면 왜 지워도 늦는가?**
  - **답:** 컨테이너 이미지는 이전 레이어의 내용을 계속 보존한다. 뒤 레이어에서 파일을 지우면 최종 파일 시스템에서는 보이지 않지만 레이어 기록에서 비밀 값을 복구할 수 있다.
- **루트 이미지와 Space 이미지의 uid가 다른 이유는 무엇인가?**
  - **답:** 루트 이미지는 비루트 애플리케이션 사용자로 실행하려고 uid 10001을 선택했다. Hugging Face Spaces는 uid 1000을 요구하므로 Space 이미지는 같은 비루트 보장을 유지하면서 플랫폼 제약을 따른다.
- **이미지에 `DOCREVIEW_MODE=canned`를 박아 두는 이유는 무엇인가?**
  - **답:** 애플리케이션 설정뿐 아니라 이미지 계층에서도 비용 0인 기본값을 고정한다. 배포 환경에 아무 설정이 없어도 공급자 호출이 실수로 시작되지 않는다.
- **README가 배포의 증거가 아닌 이유는 무엇인가?**
  - **답:** README는 구성과 실행 방법을 기록할 뿐 원격 서비스가 생성되어 기동하고 요청에 응답했다는 사실을 보여 주지 않는다. 게시를 주장하려면 실제 실행 중인 배포에서 얻은 증거가 필요하다.

---

[← 이전: 릴리스 앱 조립](02-release-app.md) · [모듈 개요](../03-build.md) · [다음: 클린 체크아웃 검증 →](04-clean-checkout.md)
