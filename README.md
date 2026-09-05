# DocReview

SEC 10-K와 한국 DART 사업보고서를 원문 근거와 함께 검토하는 evidence-first RAG
서비스입니다. 공시 원문을 파싱하고 PostgreSQL/pgvector에 저장한 뒤 vector·lexical
검색을 RRF로 융합하며, 답변은 검색된 source span을 인용해야만 `SUPPORTED`로
종료할 수 있습니다. 근거가 없으면 `NOT_IN_DOCS`를 반환합니다.

사용자 화면은 정적 Next.js 서비스이고, FastAPI가 검색·리뷰·평가·관리 API를
제공합니다. 공개 배포에서는 실제 검색과 비용 제한 LLM 리뷰를 제공하고, corpus 변경과
골든 평가 작업은 SSH tunnel을 통한 local operator 모드에서만 실행합니다.

## 주요 기능

- SEC EDGAR·DART 원문 수집과 registry별 파싱
- source SHA-256와 half-open character span으로 되짚을 수 있는 청크
- pgvector exact vector search와 `ts_rank_cd`/BM25 lexical search
- RRF 융합, 선택적 cross-encoder reranking, 한국어 n-gram lexical 경로
- 인용 검증 LLM workflow와 `NOT_IN_DOCS` fail-closed 종료
- 순서형 Build 파이프라인(원문 → 파싱·청킹 → 임베딩 → BM25 → 질문 → 답변 모델 → 평가), 인용 카드, 단계형 튜토리얼을 갖춘 Next.js 서비스
- Playground·골든셋·평가 실행·스냅샷 비교를 갖춘 Measure와 readiness·Operations·API inspector·Usage를 갖춘 System
- Recall@k·Hit Rate@k·MRR·latency, 교차언어 parity, ablation 평가
- FastAPI·SSE·MCP agent·Gradio 내부 evidence fixture
- Firebase Hosting, GCP VM, Caddy, Cloudflare Worker 배포 구성

## 시스템 구조

```text
SEC EDGAR / Open DART
        │
        ▼
download → manifest → registry parser → sections/tables → source-stable chunks
        │
        ▼
PostgreSQL + pgvector + language-aware lexical index
        │
        ├─ vector search
        ├─ ts_rank_cd / BM25
        └─ RRF → optional reranker
                     │
                     ▼
        evidence validation → LLM review → citations / NOT_IN_DOCS
                     │
                     ▼
             FastAPI → Next.js service
```

| 경로 | 역할 |
|---|---|
| `app/ingestion/` | EDGAR·DART 수집, 파싱, 표, 청크, DB seed |
| `app/retrieval/` | embedding, vector/lexical/BM25, RRF, reranking |
| `app/evals/` | golden evaluation, ablation, parity, regression |
| `app/llm/`, `app/workflow/` | provider boundary, 예산, 인용 검증 workflow |
| `app/api/` | public API와 SSH-only administrator API |
| `app/agent/` | citation-required tool loop와 MCP stdio server |
| `app/release/` | rate/cost guard, secret redaction, Next 정적 서비스 |
| `web/` | Next.js App Router 서비스, Build/Measure/System 워크스페이스, localStorage 대화 |
| `data/` | corpus manifest, golden suite, profiles, evaluation artifacts |

## 요구사항

- [uv](https://docs.astral.sh/uv/)
- Docker Engine과 Docker Compose 2.24.4+
- Node.js 24+와 npm 11+ — Next 개발·테스트 시
- 선택: `OPENAI_API_KEY`, 또는 `MODE`별 슬롯 `OPENAI_API_KEY_LOCAL`(dev)·`OPENAI_API_KEY_PROD`(prod) — 실제 LLM 리뷰
- 선택: `DART_API_KEY` — DART 원문 수집
- SEC 수집 시 연락처를 포함한 `SEC_USER_AGENT`

## 설치

```bash
uv sync
cd web
npm ci
cd ..
```

로컬 SBERT와 cross-encoder까지 사용하려면 CPU extra를 설치합니다.

```bash
uv sync --extra cpu
```

루트 `.env`는 git에 포함되지 않습니다. 시작 템플릿은 다음과 같습니다.

```bash
cp .env.example .env
```

```dotenv
SEC_USER_AGENT=Jane Doe jane@example.com
DART_API_KEY=<your-dart-key>
OPENAI_API_KEY_LOCAL=<your-dev-openai-key>
OPENAI_API_KEY_PROD=<your-prod-openai-key>
```

키는 사용하는 기능에만 필요합니다. 기본 deterministic embedding과 retrieval 테스트는
OpenAI 키 없이 실행됩니다.

OpenAI 키는 세 슬롯 중 하나로 둡니다. `OPENAI_API_KEY`가 있으면 항상 그 키를 씁니다.
없으면 `rag-dev`는 `OPENAI_API_KEY_LOCAL`, `rag-prod`는 `OPENAI_API_KEY_PROD`를 읽습니다.
모드는 명령이 지정하므로 `.env`에 `MODE`를 적지 않습니다. dev(live operator)는 공개 rate/cost 한도를 적용하지 않고 prod(readonly)는
적용하므로, 슬롯마다 다른 프로젝트 키를 두면 비용 경계가 분리됩니다. `/ready`의
`review_engines.openai.key_slot`이 어느 슬롯이 쓰였는지 값 없이 알려 줍니다.

일반 설정과 API 키는 기존 `.env` 우선 규칙을 유지합니다. 명령이 지정한 모드는 오래된
`.env` 값보다 우선하며, 로컬 모델 연결의 별도 우선순위는 아래에 설명합니다.
OpenAI embedding backfill까지 사용하려면 다음 선택을 함께 둡니다.

```dotenv
EMBEDDING_PROVIDER=openai
```

### dev / prod는 명령으로 선택

기본 `docker/docker-compose.yml`은 `db`·`app`·`web`을 포함하는 dev 스택입니다. 기본 명령은
`docker compose --project-directory . -f docker/docker-compose.yml up -d`와 `docker compose --project-directory . -f docker/docker-compose.yml down`이며 `.env`의 `MODE`나 `COMPOSE_FILE`로
모드를 선택하지 않습니다. 다음 프로젝트 명령은 Local Operations까지 함께 관리합니다.

저장소에서 Bash 또는 Zsh의 현재 터미널에 별칭을 불러옵니다. 매 터미널에서 사용하려면 자신의 `.bashrc` 또는 `.zshrc`에
이 파일의 **실제 절대 경로**를 사용하는 `source` 한 줄을 추가합니다. 이미 등록했다면
중복 추가할 필요가 없습니다.

```bash
source ./alias.sh
rag-help
rag-dev up -d
```

`source ./alias.sh`는 `DOCREVIEW COMMANDS` ASCII 배너와 `[OK]` 등록 완료 메시지,
대상 저장소 경로, 사용 가능한 명령 목록을 표시합니다. 등록은 현재 셸에 적용됩니다.
`bash alias.sh`나 `zsh alias.sh`로 별도 실행하면 등록하지 않고 `source` 사용법을 안내합니다.
`rag-help`에서 시작·종료·로그·진단 명령과 옵션 예시를 확인할 수 있습니다.

```bash
rag-dev down
rag-prod up -d
rag-prod down
rag-dev logs -f
rag-prod ps
```

`rag-dev-up/down`, `rag-prod-up/down`도 같은 동작의 단축 명령입니다. 어느 디렉터리에서
실행해도 별칭을 등록한 이 저장소를 대상으로 합니다. 다른 프로젝트의 `dev-up` 등은 바꾸지
않습니다. 별칭 없이도 `bash scripts/run_local.sh dev up -d`처럼 실행할 수 있습니다.

**두 모드에서 여는 웹 주소는 같습니다.**

```text
http://localhost:8000/docreview-rag-agent/
```

`127.0.0.1:8000`도 사용할 수 있습니다. 포트를 바꾸려면 `.env`에 `APP_PORT`를 지정합니다.
브라우저가 웹과 API에 같은 주소로 요청하고 Next가 내부 API로 전달하므로 별도의 3000번
화면이나 API 주소를 선택할 필요가 없습니다. API를 중지해도 웹과 상태 안내는 열립니다.

| 실행 | 화면·권한 | 소스 수정 |
|---|---|---|
| `rag-dev up -d` | 개발 도구, 로컬 모델, Prompt·RAG 편집, Build·Measure 실행 | 웹·API 자동 반영 |
| `rag-prod up -d` | 공개 화면 미리보기, 개발용 변경 작업과 Local LLM 차단 | 웹·API 자동 반영 |
| 실제 배포 | 공개 정적 웹과 배포 API | 배포용 빌드·배포 필요 |

로컬 prod는 **공개 화면을 편집하며 확인하는 미리보기**입니다. 소스가 갱신돼도 prod 권한은
유지됩니다. 실제 배포 구성에는 개발 서버와 소스 마운트가 들어가지 않습니다. dev/prod는
같은 로컬 스택을 전환해서 사용하며 DB와 데이터 볼륨은 유지합니다. `down -v`는 데이터를
지우므로 프로젝트 명령에서는 허용하지 않습니다.

### 로컬 모델로 답변하기 (선택)

**Ollama는 사용자가 별도로 설치하고 실행하는 모델 서버입니다. 이 프로젝트의 Compose에는
Ollama 컨테이너가 없습니다.** DocReview는 실행 중인 Ollama에 질문을 보내 답변을 받습니다.

```text
브라우저 → DocReview 앱 → HTTP 요청 → 사용자가 실행한 Ollama → 선택한 모델
```

#### 먼저 알아둘 주소의 차이

`127.0.0.1` 또는 `localhost`는 **지금 그 프로그램이 실행되는 곳의 자기 자신**입니다.
PC에서 실행한 앱이라면 PC 자신이지만, Docker 안의 앱이라면 그 컨테이너 자신을 가리킵니다.
따라서 PC에 설치한 Ollama를 Docker의 앱에서 찾을 때 `127.0.0.1`을 넣으면 다른 곳을 찾게 됩니다.

Compose의 `extra_hosts` 설정은 `host.docker.internal`이라는 이름으로 PC에 접근할 수 있게
해 줍니다. **이 이름이 있다고 Ollama의 접속 허용 설정까지 바뀌지는 않습니다.** Ollama가
PC 내부에서만 요청을 받도록 실행 중이면 Docker의 앱은 접속할 수 없습니다.

| 어디에 입력하는 주소인가 | 기본 예시 |
|---|---|
| 브라우저에서 DocReview 열기 | `http://localhost:8000/docreview-rag-agent/` |
| Docker의 DocReview가 같은 PC의 Ollama에 연결 | `http://host.docker.internal:11434` |
| PC에서 직접 실행한 앱이 같은 PC의 Ollama에 연결 | `http://127.0.0.1:11434` |
| 다른 PC의 Ollama에 연결 | 그 PC의 접근 가능한 주소와 포트 |

웹 Settings의 Server URL은 **백엔드가 모델 서버에 접근할 주소**입니다. 기본값이 자동으로
채워져 있어도 Ollama 실행, 설치 모델, 백엔드에서 접근 가능한 수신 주소가 필요합니다.

#### 1. 기존 서버와 설치 모델 확인

설치 전이라면 [공식 Linux 설치 안내](https://docs.ollama.com/linux)를 따릅니다.
systemd 서비스로 설치했다면 상태를 확인하고, 꺼져 있을 때 시작합니다.

```bash
systemctl status ollama --no-pager
sudo systemctl start ollama
ollama list
ollama ps
```

`ollama list`는 **설치된 모델**, `ollama ps`는 **현재 메모리에 올라간 모델**을 보여 줍니다.
서버는 켜져 있어도 모델을 아직 사용하지 않았다면 `ps`가 비어 있을 수 있습니다.
`ollama status`는 서버 상태 확인 명령이 아닙니다.

원하는 모델이 설치되어 있지 않을 때만 내려받습니다.

```bash
ollama pull gemma4:e4b
```

서비스 계정과 일반 사용자 계정은 모델 저장소가 다를 수 있습니다. 서버를 다른 계정으로
새로 띄웠을 때 목록이 비었다면 기존 서버와 저장소부터 확인하고 다시 다운로드하지 않습니다.

#### 2. Docker에서 접속할 수 있도록 서버 수신 주소 확인

```bash
ss -ltn 'sport = :11434'
```

`127.0.0.1:11434`에서만 수신하면 Docker에서는 접근할 수 없습니다. 기존 systemd 서비스는
다음처럼 **별도 설정 파일**을 추가합니다. 원본 서비스 파일은 바꾸지 않습니다.

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/99-docreview-listen.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

이 설정은 다른 네트워크 인터페이스에서도 연결을 받게 하므로 신뢰하는 개발 환경에서
사용합니다. 프로젝트와 진단 스크립트는 서비스나 방화벽을 자동 변경하지 않습니다.
편집기로 `systemctl edit`을 쓴다면 실제로 설정이 저장됐는지 `systemctl cat ollama`로 확인합니다.

systemd 없이 직접 실행하고 **같은 포트에 기존 서버가 없을 때**는 다음 명령도 가능합니다.

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

이 명령은 서버 프로세스라 터미널을 사용합니다. 계속 백그라운드로 서빙하려면 이미 설치된
systemd 서비스를 사용합니다. 별도 터미널의 `OLLAMA_HOST` 값은 실행 중인 서비스에 적용되지
않습니다. `address already in use`라면 두 번째 서버를 띄우지 말고 기존 서비스를 확인합니다.
[Ollama의 수신 주소 설명](https://docs.ollama.com/faq#how-can-i-expose-ollama-on-my-network)

#### 3. 대화 프롬프트 없이 모델만 준비

```bash
ollama run gemma4:e4b "" --keepalive=-1s
ollama ps
```

빈 문자열은 대화를 시작하지 않고 모델만 메모리에 올립니다. 명령이 끝나면 터미널로
돌아오고 Ollama 서비스는 계속 요청을 받습니다. `ps`의 `Forever`로 현재 유지 상태를
확인합니다. 웹에서 질문할 때도 모델은 필요에 따라 로드되므로 미리 올리는 단계는 선택입니다.

`Forever`는 재부팅이나 서비스 재시작 뒤의 자동 로드를 뜻하지 않습니다. 이후 요청의
유지 시간 설정에 따라 해제될 수도 있습니다. 모델만 메모리에서 내리려면 다음을 사용합니다.

```bash
ollama stop gemma4:e4b
```

이는 서버 종료와 다릅니다. 서버 자체의 시작·중지는 사용자가 관리합니다.
[모델 미리 로드와 유지 시간](https://docs.ollama.com/faq#how-can-i-preload-a-model-into-ollama-to-get-faster-response-times)

#### 4. Settings에서 연결하고 대화창에서 모델 선택

`Settings → Local LLM`에서 주소를 확인하고 **Connect & save**를 누릅니다. 모델명은
미리 설정하지 않습니다. 서버와 모델 정보가 확인되면 즉시 화면에 반영됩니다.

- **Connect & save:** 확인한 연결을 앱에 저장합니다. 새 주소 확인에 실패하면 기존 연결은 유지됩니다.
- **Disconnect:** 비활성 상태를 저장합니다. 기본값으로 다시 자동 연결하지 않습니다.
- **Reset to initial connection:** 웹 저장값 대신 초기 설정으로 되돌아갑니다.

서버 주소는 앱 전체에 적용하고, 대화 입력창 아래의 Answer engine·Local model 선택은
대화별로 저장합니다. 답변 가능한 모델 하나는 자동 적용하고 여러 개면 선택합니다.
엔진은 자동으로 OpenAI에서 Local LLM으로 전환하지 않습니다.

초기 설정의 우선순위는 다음과 같습니다.

```text
웹에서 저장한 연결 > 프로세스 환경변수 > .env > 기본값
```

직접 실행한 호스트 앱은 `http://127.0.0.1:11434`, Compose는
`http://host.docker.internal:11434`를 기본값으로 사용합니다. `.env`는 선택적인 초기값입니다.

```dotenv
LOCAL_LLM_BASE_URL=http://host.docker.internal:11434
```

웹에 저장한 값은 `data/local-settings/local-llm.json`에 보존되며 앱 재시작 후에도 유지됩니다.
`.env`를 바꿔도 웹 저장값이 우선하므로 초기값을 사용하려면 Reset을 누릅니다. 초기 환경변수를
변경했을 때만 `rag-dev up -d`로 앱을 재생성합니다. Settings의 변경에는 재생성이 필요 없습니다.
명시적 Disconnect와 prod 차단은 어떤 초기 주소보다 우선합니다.

HTTP/HTTPS와 사용자 지정 포트를 지원합니다. 사용자 지정 URL에 포트를 생략하면 HTTP는
80, HTTPS는 443이며 11434를 자동으로 붙이지 않습니다. HTTPS 서버는 실제 TLS와 신뢰할 수
있는 인증서가 필요합니다. HTTP 주소의 글자만 바꾸어서는 연결되지 않습니다.
[HTTPX 인증서 검증](https://www.python-httpx.org/advanced/ssl/)

Ollama URL에는 `/v1`을 붙이지 않습니다. Auto detect에서 `/v1`은 기존 OpenAI Responses
호환 서버를 구분하는 접미사입니다. Protocol에서 명시적으로 선택할 수도 있습니다.

#### 5. 상태 표시와 진단

Settings와 System의 Local model policy는 설치 모델·용량·파라미터·양자화·지원 기능·로드
상태를 표시합니다. 답변용으로 확인되지 않은 모델과 임베딩 전용 모델은 답변 선택에서 제외됩니다.
서버 연결 성공과 답변 모델 존재 여부는 별도로 표시합니다. 검색용 임베딩 설정은 바뀌지 않습니다.

화면이 보이는 동안 30초마다 확인하고 숨겨진 탭에서는 중지합니다. 화면 복귀·온라인 복구와
연결 저장 직후에도 확인합니다. 백엔드는 10초 캐시를 공유하며 상세 정보는 digest별로 재사용하고
전체 모델 조회는 2초로 제한합니다. 상태 조회는 다운로드·모델 로드·추론을 실행하지 않습니다.
선택 모델이 삭제되거나 연결이 끊기면 선택을 유지하면서 실행을 막고 복구를 자동 반영합니다.

```bash
rag-ollama-check
rag-ollama-check --help
rag-ollama-check --web-url http://localhost:18080
# 별칭 없이 실행하거나 웹 포트를 별도로 지정할 때
bash scripts/diagnose_ollama.sh
bash scripts/diagnose_ollama.sh --web-url http://localhost:18080
```

`rag-diagnose`도 같은 진단을 실행하며 동일한 옵션을 받습니다. `--web-url`에는 Ollama 서버가
아닌 **DocReview 웹 주소**를 넣습니다. 진단은 연결과 모델 메타데이터를 확인하며 Ollama를
설치하거나 시작하지 않습니다.

진단은 현재 앱의 모드와 활성 설정을 먼저 읽고, 웹·API → 백엔드의 모델 서버 접근 → 모델
목록·지원 기능·로드 상태 → 웹 반영 순서로 확인합니다. `.env`의 예전 주소로 대신 검사하지
않습니다. Docker health 표시만으로 성공을 판단하지 않고 HTTP 응답을 확인합니다.

| 출력 | 의미와 조치 |
|---|---|
| `PASS` | 해당 단계가 확인됨. 미로드 모델도 정상 대기 상태일 수 있음 |
| `FAIL` | 설정·연결 문제. 함께 표시된 주소·서비스·TLS·인증 안내를 확인 |
| `SKIP` | 도구나 실행 환경 때문에 미확인, 또는 prod에서 의도적으로 생략 |
| 종료 코드 `0 / 1 / 2` | 확인 완료 / 확인된 문제 / 진단 불완전 |

호스트 HTTP는 성공하지만 Docker에서 실패하고 loopback 수신이 확인되면 위 2단계로 안내합니다.
원격 Ollama를 쓴다면 PC에 Ollama CLI가 없어도 됩니다. 진단은 서비스·방화벽·설정 파일을
바꾸거나 모델을 다운로드·로드·추론하지 않습니다. prod에서는 로컬 서버에 요청하지 않습니다.

CPU 모델의 실제 답변은 상태 조회보다 오래 걸릴 수 있습니다. 개별 호출 기본 제한은 120초이고
고급 설정은 `LOCAL_LLM_TIMEOUT_S`·`LOCAL_LLM_MAX_INPUT_TOKENS`·`LOCAL_LLM_MAX_OUTPUT_TOKENS`입니다.
대화 전체 한도는 RAG settings → Run limits에서 조절합니다. 연결 성공이 답변 품질 검증 완료를
뜻하지는 않으며, 실패 원인은 응답의 Run trace에서 확인합니다.

## 5분 로컬 실행

### 1. 원문 준비

새 clone에는 manifest만 있고 원문은 없습니다. SEC 20건을 내려받으려면 `.env`의
`SEC_USER_AGENT`를 먼저 설정합니다.

```bash
uv run python -m app.ingestion.edgar_api
```

DART manifest의 삼성전자·SK하이닉스·NAVER FY2022~FY2024 원문은 선택 사항입니다.

```bash
uv run python -m app.ingestion.dart_api
```

수집 명령은 원문과 manifest까지만 준비합니다. 파싱·청킹·DB 저장은 다음 ingest
단계가 담당합니다.

### 2. PostgreSQL과 인제스트

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d db
docker compose --project-directory . -f docker/docker-compose.yml ps db
```

SEC corpus를 넣고, 비어 있는 DB에 현재 schema를 만듭니다. 파싱·청킹·DB batch 저장·
BM25 재계산은 터미널 진행률로 표시됩니다.

```bash
uv run python -m app.cli ingest \
  --manifest data/corpus/manifest.json \
  --create-schema
```

기존 volume에서 `schema_drift`가 나오면 그 DB는 현재 ORM보다 오래된 것입니다.
먼저 등록된 data-preserving migration이 해당 drift를 처리하는지 확인하고 적용합니다.

```bash
uv run python -m app.db.migrate --plan
uv run python -m app.db.migrate --apply
```

`--create-schema`는 기존 table을 변경하지 않습니다. migration 적용 뒤에도 알 수 없는
drift가 남고, 기존 DB 내용을 버리고 corpus에서 다시 만들기로 결정한 경우에만 아래
명령을 사용합니다.

> **경고:** model table, chunk, embedding, BM25 통계, run/eval 결과가 삭제됩니다.

```bash
uv run python -m app.cli ingest \
  --manifest data/corpus/manifest.json \
  --recreate-schema
```

DART corpus를 추가합니다.

```bash
uv run python -m app.cli ingest \
  --manifest data/corpus/dart-manifest.json
```

첫 검색에서 비어 있는 embedding을 채웁니다.

```bash
uv run python -m app.cli retrieve \
  --query "data center revenue drivers" \
  --embed-missing \
  --provider deterministic
```

### 3. 전체 서비스 시작

```bash
docker compose --project-directory . -f docker/docker-compose.yml up --build -d
```

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:8000/docreview-rag-agent/
```

상태와 로그는 다음과 같이 확인합니다.

```bash
curl -s http://127.0.0.1:8000/docreview-rag-agent/api/health/
docker compose --project-directory . -f docker/docker-compose.yml logs -f app
```

서비스만 중지하고 PostgreSQL은 유지하려면:

```bash
docker compose --project-directory . -f docker/docker-compose.yml stop app
```

## Next.js 로컬 라이브 편집

dev와 prod 미리보기 모두 `web/` 소스를 직접 마운트하고 Next 개발 서버로 엽니다.
`node_modules`와 `.next`는 별도 볼륨이며 API는 읽기 전용 `app/` 소스를 감지해 자동 reload합니다.
호스트 소스 경로는 Dockerfile이 아니라 Compose에서 연결합니다.

| 변경한 것 | 반영 방법 |
|---|---|
| `web/` 코드·CSS | 저장하면 두 로컬 모드 모두 자동 반영 |
| `app/` Python 코드 | 저장하면 API 자동 재시작; 실행 중 작업은 interrupted가 될 수 있음 |
| 웹 의존성·lockfile | 현재 모드의 `rag-dev restart web` 또는 `rag-prod restart web` |
| Python 의존성·lockfile | 현재 모드 명령에 `up --build -d` 사용 |
| 웹에서 저장한 Local LLM 연결 | 즉시 적용; 재시작 불필요 |
| `.env`의 초기 연결값·포트 | 현재 모드 명령으로 `up -d`; 웹 저장값은 계속 우선 |
| dev/prod 전환 | `rag-dev up -d` / `rag-prod up -d` |
| 실제 배포용 코드 | 정적 빌드·배포 절차 사용; 로컬 prod 미리보기와 구분 |

현재 모드·capability를 기준으로 화면과 API가 같은 권한을 적용합니다. localhost라는 이유로
prod를 DEV로 표시하지 않습니다. 같은 주소에서 기존 dev 대화를 prod로 열었을 때 허용되지
않는 설정이 있으면 전송을 막고 새 대화를 안내하며, 원래 저장값이나 엔진을 임의 변경하지 않습니다.
이전 3000번 origin의 브라우저 대화는 8000번으로 자동 이전되지 않고 원래 저장소에 남습니다.

### 대화 설정 위치

| 위치 | 설정 |
|---|---|
| 입력창 아래 | Answer engine·Local model·선택 상태 |
| 입력창 주변 | Corpus·retrieval preset·Filters·준비 상태 |
| 입력창 위 확장 패널 | Filters / Retrieval / Evidence / Run limits |
| Settings → Prompt | 현재 대화 지침·보호 지침·미리보기·프롬프트만 새 대화 기본값으로 저장 |
| Settings → Local LLM | 앱 전체 서버 연결·저장·해제·초기값 복귀 |
| Settings → Data & help | 저장 용량·튜토리얼·문서·초기화·대화 삭제 |
| Measure → Defaults / Snapshots | 실험 기본값 / 공개 snapshot 조회·비교 |
| System → System status / Operations | 상태·환경 정보 / 로컬 작업·알림 |

대화 설정은 대화별로 저장되며 실행 중인 요청은 시작 당시 설정을 유지합니다. Prompt 기본값
저장은 추가 지침만 바꾸고 기존 대화나 다른 기본값을 덮어쓰지 않습니다. 공개 화면에서는
허용된 필터·preset·snapshot 비교만 제공하며 개발용 설정과 Local LLM 메뉴는 표시하지 않습니다.

하단 메뉴 위의 `DEV MODE` / `PROD MODE` 배지는 서버의 실제 모드를 표시합니다.
Local model 사용 배지와 별개이며, 하단 System 버튼에서 API·DB 상태를 확인합니다. 시스템 healthy와 모델 사용 가능 여부는
별개입니다. 답변 대기 표시의 6단계는 실제 서버 이벤트만 반영하고 작은 글리프는 장식입니다.
Build의 준비·검증 7단계는 완료 후에도 번호를 유지하며, 평가하지 않은 상태를 품질 검증
완료로 표시하지 않습니다. 튜토리얼과 오류 이동 버튼은 이 단계 번호와 실제 설정 위치를 따릅니다.

### 로컬 Operations

`rag-dev up -d`는 호스트의 loopback Operations API와 임시 토큰을 관리합니다. 명령은
registry의 고정 argv만 `shell=False`로 실행하며 Docker 소켓이나 루트 `.env` 전체를 웹에
전달하지 않습니다. `rag-dev down`과 prod 전환은 이 프로젝트가 시작한 Operations만 종료합니다.
API를 중지해도 단일 웹 화면은 남아 상태 확인과 가능한 복구 작업을 할 수 있습니다.

기본 `docker compose --project-directory . -f docker/docker-compose.yml up -d`만 사용할 수도 있지만 호스트 Operations는 연결되지 않습니다.
필요하면 `rag-dev up -d`를 사용합니다. `scripts/run_local_operator_web.sh`는 같은 dev 실행의
호환 진입점입니다. prod와 공개 화면에는 Operations URL·토큰·메뉴를 제공하지 않습니다.

Linux의 host-owned `data/`는 앱의 쓰기를 위해 host data group의 write 권한이 필요합니다.
기본 GID는 1000이며 다른 환경은 `.env`의 `HOST_GID`를 자신의 `id -g` 결과에 맞춥니다.
스크립트는 DB reset·볼륨 삭제·배포·Git stage/commit을 자동 실행하지 않습니다.

<!-- operator-commands:start -->
| ID | Command | Purpose | Confirmation |
|---|---|---|---|
| `git-status` | `git status --short --branch` | Show branch plus staged, unstaged, and untracked paths. | no |
| `python-lint` | `.venv/bin/ruff check app tests scripts` | Check application, tests, and scripts without rewriting files. | no |
| `python-format-check` | `.venv/bin/ruff format --check app tests` | Report files Ruff would reformat without changing them. | no |
| `python-tests-offline` | `.venv/bin/pytest -q -m not live_postgres` | Run the suite without live PostgreSQL cases or provider requests. | no |
| `python-tests-postgres` | `.venv/bin/pytest -q -m live_postgres --require-live-postgres` | Require the live PostgreSQL marker instead of silently skipping it. | no |
| `web-tests` | `npm test` | Run the Vitest component and client-contract suite. | no |
| `web-typecheck` | `npm run typecheck` | Run TypeScript without emitting build output. | no |
| `web-build` | `.venv/bin/python scripts/check_web_build.py` | Build the current static Next source in an isolated temporary checkout. | no |
| `db-migrate-plan` | `.venv/bin/python -m app.db.migrate --plan` | Inspect pending data-preserving schema migrations without changing the database. | no |
| `db-migrate-apply` | `.venv/bin/python -m app.db.migrate --apply` | Apply pending additive migrations while preserving corpus and run rows. | required |
| `db-start` | `docker compose --project-directory . -f docker/docker-compose.yml up -d db` | Start the local pgvector service and retain its existing volume. | required |
| `db-stop` | `docker compose --project-directory . -f docker/docker-compose.yml stop db` | Stop the local database without deleting its volume. | required |
| `app-start` | `docker compose --project-directory . -f docker/docker-compose.yml up --build -d app` | Build the local image and start the app with its database dependency. | required |
| `app-stop` | `docker compose --project-directory . -f docker/docker-compose.yml stop app` | Stop the local app container while leaving PostgreSQL unchanged. | required |
<!-- operator-commands:end -->

## 데이터와 corpus 관리

기본 corpus:

| Registry | 발행인 | 범위 |
|---|---|---|
| SEC EDGAR | NVDA, AMD, INTC, MU | 각 5개년 10-K |
| DART | 삼성전자, SK하이닉스, NAVER | 각 FY2022~FY2024 사업보고서 |

SEC 기간과 회사를 확장할 수 있습니다.

```bash
uv run python -m app.ingestion.edgar_api --years 2015-2024
uv run python -m app.ingestion.edgar_api \
  --ticker TSM AVGO \
  --years 2020-2024
```

DART 회사와 사업연도를 확장할 수 있습니다.

```bash
uv run python -m app.ingestion.dart_api \
  --stock-codes 005930 000660 035420 \
  --fiscal-year 2022 2023 2024
```

모든 수집 작업은 재실행 가능하며 기존 manifest 항목을 보존합니다. DART는 manifest의
파일 길이와 SHA-256이 원문과 일치하면 해당 회사·사업연도를 API 호출 전에 건너뜁니다.
Build의 `Pipeline`에서는
단계 카드로 누락 문서 수집, `Ingest all manifests`(manifest별 순차 job), embedding backfill,
BM25 통계 재구축을 background job으로 실행할 수 있습니다. 2단계 카드는 manifest 항목 수와
실제 인제스트 수의 차이를, 1단계 카드는 manifest별 원문 파일 존재 수(`sources_present`)를
표시합니다.

## 검색과 리뷰

CLI 검색:

```bash
uv run python -m app.cli retrieve \
  --query "Samsung memory business risks" \
  -k 5
```

세부 retrieval 실험:

```bash
uv run python -m app.retrieval \
  --query "메모리 사업 위험" \
  --lexical-ranker bm25 \
  --route-by-language
```

`EMBEDDING_PROVIDER=openai` 또는 `REVIEW_MODEL`을 설정하면 OpenAI 키가 필요합니다.
모델과 가격은 역할별 정책에 고정되며, 임의 모델이나 수동 가격 환경변수는 시작 전에
거부됩니다.

```dotenv
REVIEW_MODEL=gpt-5.6-terra
```

공개 release는 IP당 분·일 제한, 요청당 비용 제한, UTC 일일 비용 상한을 적용합니다.
한도가 소진되면 프런트는 LLM 답변 대신 실제 retrieval evidence를 표시합니다.

## Build, Measure, System

사이드바는 Build → Measure → System 순서이며 각 워크스페이스는 탭으로 나뉩니다.

Build:

- `Pipeline`: Filings → Parse & chunk → Embeddings → Lexical index (BM25) → Ask →
  Answer model → Evaluate 일곱 단계 카드. 각 카드는 `/ready`·`/admin/corpus`·`/admin/jobs`에서
  도출한 상태(Done / Action needed / Running / Failed / Blocked / Read-only)와 실제 숫자,
  하나의 주 버튼, "Why this matters"를 보여 주고, 상단 runtime strip과 Next step 콜아웃이
  지금 해야 할 한 가지를 가리킵니다
- `Documents`: registry·issuer·연도·언어·form·parse/embedding 상태·Snapshot membership
  facet, Registry/회사/연도 grouping, cursor page, 구조화된 filing/index/chunk 상세
- `Jobs`: persistent corpus/evaluation queue, progress, history, retry/cancel

Measure:

- `Playground`: 질문 하나를 명시적 retrieval profile로 `/admin/retrieval/preview`·
  `/admin/review/preview`에 보내 component ranking(vector·lexical·언어별)과 융합 결과,
  리뷰 라벨을 바로 비교 (`live` operator 전용)
- `Golden Tests`: SEC/DART × EN/KO suite의 canonical 질문과 DB draft 편집
- `Runs`: New run(suite·revision·quick/matrix·retrieval profile)과 Results(결과 선택,
  Use selected set, Compare, 상세)
- `Compare`: baseline 대비 metric·case 변화
- `Snapshots`: eval 결과, exact document/chunk membership, embedding copy, BM25 통계를
  불변 단위로 저장하고 공개된 두 결과를 provider 호출 없이 비교

System:

- `System status`: readiness, corpus 카운터, 모델 정책, 활성 키 슬롯
- `Operations`: 고정 명령 registry (host operator 실행 시)
- `API inspector`: strict JSON 요청과 typed 응답 (`live` 전용)
- `Usage`: local run/trace에 기록된 모델별 token과 예상 비용 (`live` 전용)

Pipeline의 단계 카드는 해당 corpus/evaluation 작업의 stage, committed progress, 대기 순서를
카드 안에 표시하고 Next step 콜아웃에서 실행 중 job을 취소할 수 있습니다. `Jobs`의 통합
Job Center에서는 domain/status filter, queue position, request/result provenance, 안전한
Retry/Cancel을 확인합니다. Job 상태는 PostgreSQL에 저장되며 진행 기록은 job마다 한 번에
하나만 쓰고 종료 상태를 마지막에 기록합니다. app 재시작으로 중단된 작업은 자동 재실행하지
않고 `interrupted`로 남깁니다. System › Operations에서 완료·실패 desktop notification을
opt-in할 수 있습니다.

조절 가능한 retrieval profile:

- strategy: vector, lexical, hybrid
- `k`, `candidate_k`, `rrf_k`
- `ts_rank_cd` 또는 BM25와 `k1`, `b`, IDF
- query language routing
- 선택적 cross-encoder reranking

빠른 실행은 현재 DB index를 사용합니다. matrix 실행은 격리 PostgreSQL corpus에서
chunk 크기·strategy·ranker 조합을 비교하고 운영 corpus를 변경하지 않습니다.

Embedding Backfill은 provider identity별 committed row count를 완료 후 다시 확인합니다.
progress row 수와 실제 DB 상태가 다르면 성공으로 표시하지 않고 `postcondition_failed`로
종료합니다.

Local operator의 Measure › Golden Tests에서는 canonical JSON 질문 표를 항상 read-only로 확인하고,
DB draft를 만든 뒤 질문·reference answer·category/facet·tags·expected label·source span을
structured form 또는 single-case JSON으로 수정합니다. 연결된 eval 결과가 있으면 질문별
hit/miss, first rank, reciprocal rank를 같은 표에 표시합니다. `Validate`는 suite uniqueness와
exact source hash/span을 확인합니다. Quick/Matrix eval은 현재 선택한 DB revision ID와 byte hash를
그대로 사용하며, 검증된 revision만 `Publish JSON`으로 원자적으로 반영합니다.
Published revision과 eval result는 Snapshot에 함께 고정할 수 있습니다.

Snapshot은 문서/source hash, chunk body/context/span/citation, generated FTS vector,
embedding vector/identity, chunk term/length, 언어별 BM25 corpus·lexeme 통계를 독립 revision
테이블에 복사합니다. 이후 live corpus를 재청킹하거나 교체해도 Dev의 `Use for review`는
snapshot 테이블만 검색하며, Prod에서는 공개된 Snapshot 결과 비교만 허용합니다.
Queryable Snapshot은 현재 live-index quick eval에서 만들 수 있습니다. 격리 matrix의
chunking arm은 운영 index와 다른 임시 corpus이므로 결과 artifact 비교만 허용하며, 현재
corpus인 것처럼 잘못 고정하려는 요청은 거부합니다. 새 chunking revision을 queryable하게
만들려면 해당 revision을 live index로 검증한 quick eval 결과에서 Snapshot을 생성합니다.

CLI 평가:

```bash
uv run python -m app.evals.run
uv run python -m app.evals.crosslingual --corpus edgar --gate
uv run python -m app.evals.crosslingual \
  --corpus dart \
  --lexical-ranker bm25 \
  --gate
```

Recall@k·Hit Rate@k·MRR은 retrieval을 평가합니다. 최종 LLM 답변의 사실성이나
claim-level entailment를 증명하는 지표로 해석하지 않습니다.

## API

로컬 Swagger UI:

```text
http://127.0.0.1:8000/docs
```

주요 public endpoint:

| 메서드 | 경로 | 역할 |
|---|---|---|
| `GET` | `/health` | 프로세스 상태 |
| `GET` | `/ready` | 모델 정책·DB·schema·corpus readiness |
| `POST` | `/retrieve` | 인용 근거 검색 |
| `POST` | `/review` | 근거 검증 리뷰 |
| `POST` | `/review/stream` | SSE 리뷰 스트림 |
| `GET` | `/documents` | 인제스트 문서 목록 |
| `GET` | `/runs/{run_id}` | 리뷰 실행 결과 |
| `GET` | `/runs/{run_id}/traces` | 단계별 비용·토큰 trace |
| `GET` | `/eval` | 저장된 평가 결과 |
| `GET` | `/snapshots` | 공개된 불변 평가 Snapshot |
| `GET` | `/snapshots/compare` | 저장 결과 비교, eval 재실행 없음 |

`/admin/*`는 local operator API입니다. 공개 Caddy 설정에서는 `/admin/*`와 `/ingest`를
차단하고, GCP 운영 환경에서는 SSH tunnel을 통해서만 접근합니다.

## Agent와 MCP

provider 호출 없는 agent loop:

```bash
uv run python -m app.agent \
  --question "What drove NVIDIA data center growth?"
```

OpenAI provider 사용:

```bash
uv run python -m app.agent \
  --question "What drove NVIDIA data center growth?" \
  --provider openai \
  --model gpt-5.6-terra \
  --max-cost-usd 0.25
```

MCP stdio server:

```bash
uv run python -m app.agent --mcp
```

## 테스트와 품질 검사

DB가 필요 없는 Python 테스트:

```bash
uv run pytest -m "not live_postgres"
```

실제 PostgreSQL/pgvector 테스트:

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d db
uv run pytest -m live_postgres --require-live-postgres
```

전체 Python·정적 검사:

```bash
uv run pytest -q
uv run ruff check app tests scripts
uv run ruff format --check app tests
```

Next 검사:

```bash
cd web
npm test
npm run typecheck
npm run build
npm audit
```

클린 archive, Compose, 일반/Hugging Face 이미지, health와 Next landing까지 확인하는
통합 게이트:

```bash
scripts/verify_clean_checkout.sh
```

## Docker와 데이터 수명주기

로컬 Compose는 `db`·`app`·`web` 세 서비스를 제공합니다. DB만 실행하거나 전체 서비스를
실행할 수 있습니다.

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d db
docker compose --project-directory . -f docker/docker-compose.yml up --build -d
```

포트 변경, 볼륨 보존·삭제, schema drift 처리 등 자세한 운영 명령은
[Docker Compose 운영](deploy/docker-compose.md)에 있습니다.

## 배포

배포 구조:

```text
sungyongcho.com/docreview-rag-agent/*
        │
        ▼
Cloudflare Worker
        ├─ static UI ──> Firebase Hosting
        └─ /api/* ─────> GCP e2-small → Caddy → FastAPI → PostgreSQL
```

Firebase용 Next 정적 파일 생성과 배포:

```bash
FIREBASE_PROJECT_ID=<project-id> scripts/deploy_firebase_web.sh
```

GCP VM 준비·배포 스크립트:

```bash
GCP_PROJECT_ID=<project-id> deploy/gcp/create_vm.sh
GCP_PROJECT_ID=<project-id> deploy/gcp/deploy_backend.sh
```

실관리 UI는 SSH tunnel 뒤에서 실행합니다.

```bash
GCP_PROJECT_ID=<project-id> deploy/gcp/operator_tunnel.sh
scripts/run_operator_web.sh
```

배포 스크립트는 비용과 외부 상태를 변경하므로 값을 검토한 뒤 별도로 실행해야 합니다.

## 트러블슈팅

| 증상 | 확인할 것 |
|---|---|
| `database_unavailable` | `docker compose --project-directory . -f docker/docker-compose.yml ps db`, `DB_PORT`, `DATABASE_URL` |
| `schema drift` | `app.db.migrate --plan` 후 등록 migration 적용. 남으면 아래 rebuild 경고 참고 |
| `/review` 503 | `REVIEW_MODEL`, `OPENAI_API_KEY`, `/ready`의 model policy 상태 |
| 공개 review 429 | IP rate limit 또는 UTC daily cost limit |
| 검색 결과 없음 | ingest 여부와 최초 `--embed-missing` 실행 |
| BM25 stale | ingest 또는 BM25 stats rebuild 실행 |
| `sbert`/reranker import 오류 | `uv sync --extra cpu` |
| Next 클릭이 동작하지 않음 | 개발 URL과 `allowedDevOrigins`, browser console |
| 리뷰가 답 없이 끝남 | 메시지의 **Run trace**를 편다. 실패 종류와 걸린 한도, 멈춘 단계가 그대로 나오고 해당 설정을 여는 버튼이 붙는다 |
| `budget_exceeded` | `resource`가 어느 한도인지 본다. `wall_clock_s` 기본값은 120초이며 토큰 예산이 아니다. 한도는 대화창의 RAG settings › Run limits |
| `provider_failure` | `status`와 `details`. 로컬 모델이면 대개 제한 시간 초과나 host 미도달, 또는 스키마 미준수 |
| `node_error` | `error_type`과 `message`. 모델이 아니라 그 앞 단계가 실패한 것이다 |
| job이 `interrupted` | 애플리케이션 재시작에 잘린 것이다. 자동으로 이어받지 않으므로 Retry를 직접 누른다 |

리뷰 실패의 세 모양과 각 필드의 뜻은 `AGENTS.md` §11에 정리돼 있습니다.

등록된 additive migration만 명시적 plan/apply로 실행하며 startup에서는 DDL을 수행하지
않습니다. 등록 migration으로 해결되지 않는 drift의 마지막 수단은 재구축입니다. 다음
명령은 모델 테이블·청크·embedding·통계를 삭제하고 다시 생성하는 **파괴적 개발 명령**
이므로 백업과 재인제스트 준비 없이 실행하지 마십시오.

```bash
uv run python -m app.cli ingest \
  --manifest data/corpus/manifest.json \
  --recreate-schema
```

## 관련 운영 문서

- [Docker Compose 운영](deploy/docker-compose.md)
- [골든셋 author review queue](data/golden/REVIEW.md)
- [테스트 파일 배치 규칙](tests/RULES.md)

## 제품 완성 로드맵

`planned`는 설계만 확정된 상태, `implemented`는 코드와 focused test가 있는 상태,
`verified`는 아래 증거와 실제 로컬 화면까지 확인한 상태입니다.

<!-- product-roadmap:start -->
| Gate | State | Included behavior | Verification evidence |
|---|---|---|---|
| Model policy | verified | role allowlist, reasoning, cached/cache-write pricing, Agent USD cap | Python policy/provider tests |
| Schema migration | verified | explicit additive usage-accounting migration with row preservation | live PostgreSQL migration test and local ledger |
| Readiness | verified | typed `/ready`, policy and corpus state, 200/503 split | release API tests and local `/ready` response |
| Review UX | verified | composer toolbar and readiness banners, six-step SSE progress, verdict-first answer cards, cancel, safe GFM, right-edge scroll, runtime modal, target-click tour | Vitest and local browser review QA (Supported · N citations, stepper, evidence fold) |
| Build / Measure / System | verified | ordered Build pipeline with per-stage state and one action, Ingest all manifests, Measure Playground/golden/runs/compare/snapshots, System status/Operations/API inspector/usage, public read-only parity | component/API tests, local Ingest all manifests → backfill run, Playground rankings and quick evaluation in the browser |
| Local Operations | verified | authenticated fixed command registry, logs, cancel, service confirmation | operator API tests and browser Git-status run |
| Runtime strip shortcuts | implemented | Build's runtime strip runs `db-start`, migration plan/apply, and `app-start` through Local Operations when an operator is attached; command lines otherwise | build-pipeline component tests; browser run pending an operator session |
| Release UI | verified | test, typecheck, isolated static build, fixed shell chrome, canned build never calls `/admin/*` | static live and canned builds and local browser QA |
| Build pipeline | verified | client-derived stage state from `/ready`, `/admin/corpus`, `/admin/jobs`; manifest registry and on-disk source counts; canned fixture labelled as such | pipeline unit tests, admin ordering tests, and a local browser job run |
| Key slots | verified | `rag-dev`/`rag-prod`-selected OpenAI key (`OPENAI_API_KEY_LOCAL` / `_PROD`) with explicit override, `key_slot` in `/ready` | settings tests and local `/ready` on the rebuilt container |
| Local answer engine | verified | Command-selected prod blocks local discovery and execution; dev supports persisted web connection settings, automatic metadata and per-conversation model selection | 218 focused Python tests, 176 web tests, real Ollama RAG response with a citation, prod HTTP/UI block, connection persistence across down/up |
| Job ledger | verified | coalesced progress writes, terminal write last with retry, worker survives ledger failures | offline ledger tests, live PostgreSQL suite, stuck ingest reproduced and fixed locally |
<!-- product-roadmap:end -->

## 재조립 기록

아래 영역은 현재 서비스 사용 설명이 아니라 `assemble` 재구현 과정의 기계 입력과
역사 기록입니다. `.dashboard/`와 `.githooks/pre-commit`이 marker가 있는 표를 직접
읽으므로 marker·열 구조를 변경하지 않습니다.

<details>
<summary>재조립 순서, 이식 범위, 리뷰 기록과 대시보드</summary>

### implementation order
재배치 비교표 (zero 완성본 기준)

#	모듈	zero 완성 순서	재배치 (수작업 재구현 루트)	변경
1	M1 — Ingestion	M1.1 → M1.2 → M1.3 → M1.4	동일	계약만 source-agnostic으로 설계
2	M2 — Retrieval	M2.1 → … → M2.11	동일	—
3	M3 — Evaluation	M3.1 → (M3.2+M3.3) → M3.4 → M3.5	동일	—
4	M4 — LLM Workflow	M4.1 → M4.2 → M4.3 → M4.4	M4.1 → M4.4 → M4.2 → M4.3	M4.4 전진 (기존 결론 유지)
5	M8 — Crosslingual	(M7 뒤) M8.1 → M8.2 → M8.3 → M8.4	M4 직후로 전진, 내부 동일	모듈 성격이 바뀌어서 이동
6	M10 — KR filings (신규)	없음	M10.1 → … → M10.6	DART 파서 삽입 지점
7	M5 — Serving	M5.1 → M5.2 → M5.3 → M5.4	M5.1 → M5.4 → M5.2 → M5.3	M5.4 전진 (기존 결론 유지)
8	M9 — Agent	(M8 뒤) M9.1 → … → M9.6	내부 동일, M5 직후	기존 결론 유지
9	M6 — Demo	(M5 뒤) (M6.1+M6.2) → M6.3	내부 동일, M9 뒤로	기존 결론 유지
10	M7 — Deployment	(M6 뒤) M7.1 → M7.2 → M7.3	내부 동일, 종점	localization 소멸로 자연 종점화


재배치 후 체인 한 줄씩
M1 — Ingestion: M1.1 → M1.2 → M1.3 → M1.4
M2 — Retrieval: M2.1 → M2.2 → M2.3 → M2.4 → M2.5 → M2.6 → M2.7 → M2.8 → M2.9 → M2.10 → M2.11
M3 — Evaluation: M3.1 → (M3.2 + M3.3) → M3.4 → M3.5
M4 — LLM Workflow: M4.1 → M4.4 → M4.2 → M4.3
M8 — Crosslingual: M8.1 → M8.2 → M8.3 → M8.4
M10 — KR filings (DART): M10.1 → M10.2 → M10.3 → M10.4 → M10.5 → M10.6
M5 — Serving: M5.1 → M5.4 → M5.2 → M5.3
M9 — Agent: M9.1 → M9.2 → M9.3 → M9.4 → M9.5 → M9.6
M6 — Demo: (M6.1 + M6.2) → M6.3
M7 — Deployment: M7.1 → M7.2 → M7.3

### 이식 범위 (실측)

각 행은 실제 이식 덩이 하나이며 커밋 하나에 대응합니다. `zero 범위`는 그 덩이가
`zero`에서 가져온 파일이고, `assemble 착지`는 이 브랜치에서 어디에 놓였는지입니다.
착지가 zero와 다른 행은 그 사실을 함께 적습니다.

`기준`이 채워져 있으면 그 덩이는 들어온 것이고, `—`이면 아직입니다. 별도의 상태 칸을
두지 않는 이유는 그 둘이 언제나 같은 말이었고, 손으로 맞춰야 하는 칸이 하나 늘수록
표가 어긋날 자리도 하나 늘기 때문입니다. 이 칸은 커밋 훅이 자동으로 채웁니다
(`.githooks/pre-commit`). 훅은 클론마다 한 번 켜야 동작합니다:
`git config core.hooksPath .githooks`.

`기준`은 그 덩이가 **올라간 시점의 HEAD**이며, 덩이 자신의 커밋 해시가 아닙니다.
자기 해시는 커밋을 만든 뒤에야 생기므로 그 행을 같은 커밋에 넣을 수 없고, 표가 항상
한 커밋씩 뒤처집니다. 기준은 커밋 전에 이미 알 수 있으므로 행을 코드와 같은 커밋에
담을 수 있고, 그래야 표가 어긋나지 않습니다. 덩이 자신의 커밋은 `기준`의 자식이며,
코드 리뷰 범위도 `git diff <그 모듈 첫 덩이의 기준>..HEAD`로 바로 나옵니다.

`.dashboard/`의 대시보드가 이 표를 읽어 다음 단계를 표시하므로 마커를 지우지 마십시오.

<!-- port-map:start -->
| 단계 | zero 범위 | assemble 착지 | 기준 |
|---|---|---|---|
| init | 스캐폴드 | app/ingestion/xref.py | 루트 |
| M1.1, M1.2 | app/ingestion/{parser,tables}.py | 동일 + data/profiles | ab2c23b |
| M1.3 | app/ingestion/chunk.py | 동일 | a2ba790 |
| M1.4 | app/ingestion/seed.py, app/db/ | 동일 | 2b47b71 |
| M2.1~M2.4 | app/retrieval/{types,embeddings,vector,lexical}.py | 동일 + _sql.py 분리 | 7fde61e |
| M2.5~M2.8 | app/retrieval/{hybrid,rerank,service,__main__}.py | 동일 | bc33427 |
| M2.9~M2.11 | app/retrieval/{bm25,sbert,cross_encoder}.py | 동일 + _sentence_transformers.py | d8c0439 |
| M3.1~M3.3 | app/evals/{types,loader,scoring,regression}.py | 동일 | 7532b72 |
| M3.4 | app/evals/{ablation,retrieval_eval}.py | retrieval_eval 1449줄을 arms·artifacts·corpus·measurement·run으로 분할 | dd4cc60 |
| M3.5 | app/evals/{curation,breakdown}.py | 동일 + reporting.py 공유 | c55a4ec |
| M4.1, M4.4 | app/llm/ | 동일 | 17cad6e |
| M4.2 | app/observability/ | 동일 + db Run·Trace 모델 | 2790ece |
| M4.3 | app/workflow/ | 동일 | 81b668f |
| M8.1~M8.4 | app/evals/{bilingual,crosslingual,parity}.py, app/retrieval/{language,translate}.py | 동일 + identity·cli 공유. tests/crosslingual은 tests/evals·tests/retrieval로 분산 | b1475b7 |
| M10.0 | zero 없음 (신규) | app/ingestion/registry.py | cc1957b |
| M10.1~M10.3 | zero 없음 (신규) | app/ingestion/{dart,dart_api}.py | a370c44 |
| M10.4~M10.6 | zero 없음 (신규) | app/retrieval/korean.py, data/golden/dart_* | b5a3e54 |
| M5.1, M5.4 | app/api/{schemas,errors,deps,app}.py, app/api/routes/ — 1069줄 | app/api/ | 0881a52 |
| M5.3 | app/api/runtime.py — 522줄 | app/api/ — 문서 리소스를 레지스트리 중립으로 교정 | fd71a74 |
| M5.2 | app/cli.py, app/main.py, Dockerfile, docker-compose.yml | app/ — compose는 병합, db healthcheck 유지 | 8d2264c |
| M9.1~M9.4 | app/agent/{types,tools,registry,provider,loop,builtin_tools}.py — 1359줄 | app/agent/ — 도구 스키마를 레지스트리 중립으로 교정 | b150fdb |
| M9.5~M9.6 | app/agent/{decompose,eval,mcp_server,__main__}.py — 735줄 | app/agent/ — 리뷰 반영으로 eval은 app/evals/decomposition.py로, 융합은 retrieval의 fuse_ranked_lists로 이동 | 71cbabb |
| M6.1~M6.3 | app/demo.py — 595줄 | app/demo.py | bceca7f |
| M7.1~M7.3 | app/release/ — 7파일 518줄, deploy/huggingface/, 클린 체크아웃 스크립트 | app/release/ — 검증 스크립트를 실재하는 경로로 교정 | da34df5 |
<!-- port-map:end -->

### 리뷰 단위

코드 리뷰는 덩이 하나가 아니라 **모듈 하나가 다 들어온 뒤**에 받습니다. 덩이는 커밋을
가르는 단위이고, 리뷰는 모듈이 단위입니다 — 한 모듈의 경계가 다 서기 전에는 서로를
어떻게 쓰는지가 아직 안 보여서, 덩이 하나만 놓고 보는 리뷰는 같은 지적을 다음 덩이에서
다시 받게 됩니다. 소속 모듈은 위 표의 단계 라벨 앞자리(`M5.1` → `M5`)로 정해지므로 여기에
따로 적지 않습니다.

아래는 모듈별로 리뷰에서 특히 볼 것입니다. 대시보드의 `이식 진행`이 이 표를 읽어
모듈이 다 차면 알려주고, 상세 화면에서 해당 문단을 클립보드로 넘깁니다.

`리뷰` 칸은 그 모듈의 코드 리뷰 반영분이 **올라간 시점의 HEAD**입니다(이식 범위표의
`기준`과 같은 규칙). 비어 있으면 아직 리뷰 전이고, 채워져 있으면 대시보드가 리뷰
시점 알림을 멈춥니다. 이 칸이 생기기 전에 리뷰한 모듈은 `기록 이전`으로 둡니다.

<!-- review-focus:start -->
| 모듈 | 리뷰 | 리뷰에서 집중할 것 |
|---|---|---|
| M1 | 기록 이전 | 청크가 원문 오프셋과 해시로 되짚어지는가. 표 파싱이 레지스트리별 규칙에 갇혀 있는가 |
| M2 | 기록 이전 | 융합 순위가 각 경로의 점수 척도에 휘둘리지 않는가. SQL이 파이썬으로 새어나오지 않는가 |
| M3 | 기록 이전 | 측정이 설정 지문에 묶여 재현되는가. 골든 케이스가 구현을 따라 바뀌지 않았는가 |
| M4 | 기록 이전 | 모델이 증거 규칙을 스스로 정하지 못하게 막혀 있는가. 예산 초과와 스키마 거절이 서로 다른 실패로 남는가 |
| M5 | 3129e63 | 타입 계약이 경계에서만 검증되는가. 오류 봉투가 5xx 세부나 비밀을 흘리지 않는가. 주입이 실제로 교체 가능한가. SSE가 클라이언트 이탈에 워크플로까지 취소하는가 |
| M6 | 최종으로 미룸 | 데모가 실제 파이프라인을 쓰는가, 아니면 결과를 흉내내는가. 오프라인 기본 경로가 유료 공급자를 부르지 않는가. **개별 리뷰를 건너뛴다**(§4-1 예외) — 배포용 개편 뒤 최종 전체 리뷰가 대신한다 |
| M7 | 최종으로 미룸 | 릴리스 가드가 게시되지 않은 것을 게시됐다고 주장하지 않는가. 아카이브가 비밀이나 코퍼스 원문을 담지 않는가. **개별 리뷰를 건너뛴다**(§4-1 예외) — 배포용 개편 뒤 최종 전체 리뷰가 대신한다 |
| M8 | 기록 이전 | 언어 라우팅이 번역 암과 분리돼 측정되는가. 패리티 게이트가 한쪽 언어에 맞춰 느슨해지지 않았는가 |
| M9 | d1dd9b7 | 도구 선택을 모델에 넘기고도 중단 조건이 계약으로 남아 있는가. 인용 없는 종료가 막혀 있는가. **두 덩이로 나눠 리뷰한다**(§4-1 예외) — 앞 덩이로는 "하나의 스키마가 LLM·MCP·프롬프트를 모두 먹여 살린다"를 닫을 수 없다. MCP가 뒤 덩이에 있다 |
| M10 | 기록 이전 | 레지스트리 어댑터가 SEC 이름을 경계 밖으로 내보내지 않는가. 한국어 lexical 통계가 언어별로 분리돼 있는가 |
<!-- review-focus:end -->

이식 덩이가 아닌 커밋: `17cad6e` `2790ece` `91b42d1` 리팩터·수정, `e130627` `afb8242` `3714d62` 문서·도구.

모듈 총량 (zero 대 현재):

| 모듈 | zero | assemble |
|---|---|---|
| M1 ingestion | 7파일 3471줄 | 10파일 4352줄 |
| M2 retrieval | 14파일 2184줄 | 17파일 2774줄 |
| M3 evals | 12파일 4901줄 | 20파일 5653줄 |
| M4 llm+observability+workflow | 14파일 3115줄 | 14파일 2999줄 |
| M5 api (대기) | 17파일 2035줄 | — |
| M9 agent (대기) | 11파일 2145줄 | — |
| M6 demo (대기) | 1파일 595줄 | — |
| M7 release (대기) | 7파일 509줄 | — |

### Review runtime과 혼합언어 검색

Review 입력은 먼저 conversation gate를 통과합니다. 완전한 인사·짧은 잡담은 retrieval 없이
응답하고, 공시 질문은 manifest issuer alias로 corpus를 제한한 뒤 활성 언어별 query variant,
vector, lexical lane을 실행해 RRF로 합칩니다. 사용자 원문은 answer question으로 유지하며
검색용 번역은 provenance로만 전달됩니다. 내부 `NOT_IN_DOCS`와 citation membership 계약은
완화하지 않습니다.

Answer provider가 설정되지 않은 Dev에서도 명확한 greeting은 provider 없이 응답합니다.
공시 질문은 Balanced retrieval을 실행해 실제 evidence를 표시하고, 생성 답변이 없다는 점을
명시합니다. Korean처럼 language routing을 요청한 profile만 translation provider를 요구합니다.
Request validation 오류는 실패한 field 위치를 conversation에 함께 표시합니다.

Session profile은 OpenAI API 또는 server-side Local LLM, Auto/SEC/DART corpus, retrieval
preset을 conversation별로 보관합니다. Local endpoint와 credential은 browser에 노출되지
않습니다. Evidence candidates는 30분 signed snapshot으로 pin/exclude 후 재검증할 수 있고,
Evaluation Jobs의 성공한 result profile은 `Use selected set`으로 현재 review에 적용합니다.

OpenAI embedding 기본 모델은 `text-embedding-3-large`이며 pgvector 폭은 `dimensions=384`로
고정합니다. Vector row에는 provider/model/dimensions identity를 함께 저장하므로 모델 변경 뒤
기존 vector는 stale 처리되고 명시적 backfill 전까지 검색에서 제외됩니다. 실제 OpenAI
review·translation·embedding 호출은 운영자가 유효한 key와 budget을 설정한 경우에만 수행합니다.

Build·Measure 상단의 `DEV`/`PROD`는 현재 hostname에서 자동으로 결정되며 선택 control이 아닙니다.
Provider 인증·schema·usage 실패는 `NOT_IN_DOCS`로 숨기지 않고 typed engine error로 표시합니다.

### 대시보드

브랜치·품질·이식 진행·반복 점검을 한 화면에서 봅니다. 표시만 하고 아무것도 고치지
않습니다. `space`는 즉시 갱신, `1`~`6`은 섹션 접기, `m`은 증거 창 전환, `q`는 종료이고,
마우스가 되는 터미널이면 줄을 눌러 상세 화면으로 들어갑니다(`esc`로 복귀).

```bash
.dashboard/dashboard.sh            # 1초마다 제자리 갱신
.dashboard/dashboard.sh --once     # 한 프레임만 출력 (파이프·CI)
.dashboard/dashboard-refresh.sh    # 전체 스위트·수집 수 캐시 갱신
```

전체 스위트는 몇 분이 걸리므로 틱에서 돌리지 않습니다. 위 갱신 스크립트가
`.dashboard-cache/`에 결과를 넣고 대시보드는 그 값과 나이를 읽습니다. 캐시보다 나중에
수정된 소스가 있으면 그 결과는 이 트리를 설명하지 못하므로 나이 대신 경고를 띄웁니다.

작업 중인 세션이 대시보드에 한 줄을 올릴 수 있고, 읽는 쪽의 반응은
`.dashboard-cache/events.jsonl`에 한 줄짜리 JSON으로 쌓입니다.

```bash
.dashboard/dash-send.sh note "M5.1 범위 확인 중"
.dashboard/dash-send.sh ask "한 덩이로 갈까?" "그렇게" "나눠서"
.dashboard/dash-send.sh clear
```

클릭이 이스케이프 문자로 새어 나오는 터미널이면 `--no-mouse`로 끄고 키만 씁니다.

</details>
