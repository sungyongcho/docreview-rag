# 로컬 실행 명령 안내

> [!DEV]
> 이 명령들은 로컬 저장소와 서비스를 관리하는 운영자를 위한 안내입니다. 공개 화면의 방문자가 실행하는 기능이 아닙니다.

`rag_alias.sh`는 이 저장소를 실행·종료하고 상태를 확인하는 명령을 현재 셸에 등록합니다.
아래 명령은 Bash 또는 Zsh에서 사용합니다. 화면을 따라 실습하려면
[DocReview RAG v2 개요](overview.md)의 12단계 경로에서 시작합니다.
아래 명령과 함께 [환경 준비](environment.md#step-1), [원문 수집](acquisition.md#step-3),
[인덱싱](indexing.md#step-5) 문서를 참고하세요.

같은 로컬 DB와 원문 폴더를 사용하는 CLI·대시보드는 처리 결과를 공유합니다. CLI에서 끝낸 작업은
대시보드에서 상태를 확인하면 됩니다. 다른 `DATABASE_URL`이나 원격 서버는 같은 환경이 아닙니다.

## 명령 등록과 도움말

저장소 루트에서 다음을 실행합니다.

```bash
./rag_alias.sh
source ./rag_alias.sh
rag-help
```

`./rag_alias.sh`는 현재 체크아웃의 자동 등록과 Helper 파일을 확인합니다. 미설치 상태에서 Y를 선택하면 설치하고 N이면 변경하지 않습니다. 이미 정상 설치됐다면 재설치 질문 없이 검증 결과를 표시합니다. 출력된 `source` 명령과 `rag-help`를 실행하면 셸 재시작 없이 바로 사용할 수 있습니다. Helper 등록은 앱 의존성 설치와 별개입니다.
처음 실행한다면 아래 설치·설정도 완료합니다.

셸과 웹은 저장소에 있는 같은 Small ASCII 워드마크를 사용합니다. 80열 터미널에는 전체 이름을,
좁은 터미널에는 DR 모노그램이나 일반 제품명 한 줄을 표시합니다. `NO_COLOR`, dumb 터미널,
파일로 보낸 출력에는 색상 이스케이프가 남지 않습니다. 배너 출력에는 언어 런타임이나 네트워크가 필요하지 않습니다.

설치기는 기존 내용을 백업·보존하면서 `.bashrc` 또는 `${ZDOTDIR:-$HOME}/.zshrc`에 한 줄만 추가합니다. 새 터미널에서는 자동으로 로드됩니다. 수동으로 등록할 때 사용하는 동일한 줄은 다음과 같습니다.

```bash
# /실제/저장소/경로를 본인 체크아웃의 절대경로로 바꿉니다.
source /실제/저장소/경로/rag_alias.sh >/dev/null
```

등록된 `rag-*` 명령은 어느 디렉터리에서도 등록 당시 저장소를 대상으로 합니다.
Python CLI·파일 조회·직접 Docker 명령은 **저장소 루트**에서 실행합니다.

| 작업 | 명령 | 효과 |
|---|---|---|
| 도움말 | `rag-help` | 등록된 명령과 예제·저장소 경로 표시 |
| 개발 시작 | `rag-dev up -d` | dev 스택 시작·설정 반영 |
| 재빌드 후 시작 | `rag-dev up --build -d` | Python 의존성·이미지 변경 반영 |
| DB만 시작 | `rag-dev up -d db` | API·웹 실행 전 DB 준비 |
| 상태 확인 | `rag-dev ps` | 컨테이너·health 표시 |
| API 로그 | `rag-dev logs --tail=80 app` | 최근 오류 확인 |
| 로그 따라가기 | `rag-dev logs -f web` | Ctrl+C는 로그 조회만 종료 |
| 웹 재시작 | `rag-dev restart web` | 웹 의존성·시작 시 준비되는 자산 갱신 |
| API만 중지 | `rag-dev stop app` | 웹 상태 안내와 DB 유지 |
| 데이터 보존 종료 | `rag-dev down` | 컨테이너 종료, DB 볼륨 유지 |
| prod 미리보기 | `rag-prod up -d` | 로컬 공개 화면·권한으로 전환 |
| 모델 진단 | `rag-ollama-check` | DocReview부터 Ollama까지 연결 확인 |

`rag-dev`, `rag-prod`는 인자가 없으면 `up -d`를 실행합니다.
`rag-dev-up/down`, `rag-prod-up/down`은 같은 시작·종료의 단축 명령입니다.
별칭 없이 실행하려면 `bash scripts/run_local.sh dev up -d`처럼 사용합니다.

## 설치와 초기 설정

**목적:** 실행 도구와 개발용 키를 준비합니다.

**CLI 실행·설정:** uv, Docker Engine과 Compose 2.24.4 이상, Node.js 24 이상과 npm 11 이상이 필요합니다.
Python은 프로젝트의 고정 의존성과 함께 uv로 준비합니다.

```bash
uv --version
docker compose version
node --version
npm --version
uv sync --locked
(cd web && npm ci)
# 이미 .env가 있으면 덮어쓰지 않습니다.
if [ ! -f .env ]; then cp .env.example .env; fi
```

`.env`를 편집기로 열어 다음 항목을 맞춥니다. `OPENAI_API_KEY_LOCAL`의 placeholder는
**실제 개발용 키로 교체**하고, 사용하지 않는 키는 아래처럼 비워 둡니다. 키를 명령행·스크린샷·Git에 남기지 않습니다.

```dotenv
SEC_USER_AGENT=Your Real Name your-real-contact@example.com
OPENAI_API_KEY_LOCAL=<실제 개발용 OpenAI API 키로 교체>
OPENAI_API_KEY_PROD=
DART_API_KEY=
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
```

SEC 연락처도 본인의 실제 이름과 연락 가능한 이메일로 바꿉니다. `.env.example`에 들어 있는
DART·prod 키의 placeholder를 그대로 남겨 두지 않습니다. 셸에 별도로 설정한 키가 있다면
그 값도 확인하되 출력하지 않습니다. DEV는 `OPENAI_API_KEY_LOCAL`, 운영은
`OPENAI_API_KEY_PROD`만 읽습니다. `MODE`는 `.env`에 추가하지 않습니다.
Python CLI는 아래에서 `MODE=dev`를 지정하고 `rag-dev`는 자동으로 dev를 선택합니다.

현재 저장소의 모델 정책은 embedding `text-embedding-3-large`·384차원,
답변 `gpt-5.6-terra`, 번역 기본값 `gpt-5.6-luna`입니다. 임의의 모델명으로 바꾸지 않습니다.
키의 모델 접근 권한과 사용 가능 잔액도 확인합니다. `deterministic` embedding은 연결 시험용이므로
실제 의미 검색 품질을 판단하는 이 실습의 기본 경로로 사용하지 않습니다.

프로젝트 Python 요구사항은 3.14 이상입니다.

기본 호스트 DB 주소는 `postgresql+asyncpg://filing:filing@localhost:5432/filing`입니다.
기존 `.env`에 다른 `DATABASE_URL`이 있으면 이번 실습용 로컬 DB인지 먼저 확인합니다.
`DB_PORT`를 바꿨다면 호스트 CLI의 `DATABASE_URL` 포트도 맞춥니다. Docker 앱의 DB 주소는
Compose가 내부 서비스 이름 `db`로 지정합니다.

**웹에서 확인:** 최초 의존성 설치와 키 입력은 터미널·로컬 편집기에서 진행합니다.
서비스를 시작한 뒤에는 시스템 → 시스템 상태에서 API·DB와 OpenAI 사용 가능 상태를 확인합니다.
웹에 키를 입력하거나 `.env`를 업로드하지 않습니다.

**예상 결과:** 의존성 설치가 끝나고, `.env`에는 실제 SEC 연락처와 개발용 키, OpenAI embedding 설정이 있습니다.
아직 OpenAI 호출은 하지 않았습니다.

**완료 조건:** 도구·키·대상 DB가 확인되면 아래 초기 schema 준비를 진행합니다.

## 초기 schema 준비

```bash
rag-quickstart
```

Python 환경과 설정을 확인하고, 비어 있는 데이터베이스에 스키마를 준비한 뒤 개발 서비스를 시작합니다. 호환되는 기존 데이터는 보존합니다. 스키마가 맞지 않으면 중단하므로 기존 DB를 유지하고 비어 있는 별도 DB나 호환 DB를 선택하세요. 설치 오류를 복구하기 위해 초기화를 실행하지 않습니다.

## dev와 prod 미리보기

```bash
rag-dev up --build -d
rag-dev ps
```

웹 주소는 두 모드 모두 [로컬 DocReview](http://localhost:8000/docreview-rag-agent/)입니다.
포트를 바꾸려면 `.env`의 `APP_PORT`를 사용하고 `up -d`로 반영합니다.

| 변경 | 반영 방법 |
|---|---|
| 웹·API 소스 | 로컬 개발 서버의 자동 반영; API 재시작은 job을 interrupted로 만들 수 있음 |
| 웹 의존성 | `rag-dev restart web` |
| 튜토리얼 Markdown·참조 이미지 추가/교체 | 저장하면 열린 Documentation에 자동 반영 |
| Python 의존성·이미지 | `rag-dev up --build -d` |
| `.env` 초기 설정·포트 | `rag-dev up -d` |
| 웹에서 저장한 로컬 LLM 연결 | 즉시 적용; 웹 저장값이 `.env`보다 우선 |

prod 미리보기는 배포가 아닙니다. 같은 로컬 스택을 전환하며 DB 볼륨을 유지합니다.
OpenAI embedding 설정을 유지하면 prod API 초기화에도 실제 `OPENAI_API_KEY_PROD`가 필요합니다.
키를 준비한 뒤 다음 명령을 사용합니다. 키 설정·화면 열기 자체는 답변 호출이 아닙니다.

```bash
rag-dev down
rag-prod up -d
# 확인 후 개발 모드로 복귀
rag-prod down
rag-dev up -d
```

**튜토리얼 라이브 편집:** `docs/TUTORIAL/ko/`와 `en/`의 Markdown을 VS Code에서 저장하면
열려 있는 개발용 Documentation도 자동 갱신됩니다. 공유 이미지는 `docs/TUTORIAL/assets/`에 두고
다음처럼 연결합니다. VS Code Markdown 미리보기와 웹이 같은 원본을 사용합니다.

```markdown
![화면에서 확인할 내용을 설명하는 대체 텍스트](../assets/02-pipeline.ko.jpg)
```

참조 이미지 추가·같은 파일 교체도 자동 반영되며 이미지를 누르면 원본 크기로 열립니다. 잘못된
링크나 누락된 원문은 오류를 표시하고 수정해 저장하면 복구됩니다. 이 자동 반영은 개발 서비스용이며,
prod 정적 미리보기에는 다시 빌드한 번들이 필요합니다.

prod에서는 로컬 LLM과 개발용 변경 작업이 차단됩니다. 기존 dev 대화가 차단되면 새 대화를
만들고, 키가 없어서 API가 실패한 것을 화면만 보고 정상이라고 판단하지 않습니다.
일반 종료는 `down`입니다. `rag-dev down -v`와 `rag-prod down -v`는 데이터 보호를 위해 차단됩니다.

## 선택적 리뷰 스트림 측정 정보

API 클라이언트는 리뷰 스트림 요청에 `X-DocReview-Telemetry: stages` 헤더를 보내 단계 시작·종료
이벤트를 받을 수 있습니다. 이 stage SSE 이벤트는 기존 이벤트에 추가되며, 헤더를 생략한
클라이언트의 기본 스트림은 그대로입니다. 화면은 실제 이벤트로 실행 진행과 성능을 표시하고,
누락된 시간값을 추정해 채우지 않습니다. 선택적 실행 메타데이터는 기존 JSON payload에 저장합니다.

## 상태와 로그 확인

```bash
rag-dev ps
rag-dev logs --tail=80 app
rag-dev logs -f web
```

`ps`는 서비스 상태이고 로그는 실제 실패 위치를 확인하는 자료입니다. 로그를 공유하기 전에
개인 정보·비밀값 포함 여부를 확인합니다. `logs -f`에서 Ctrl+C를 눌러도 서비스는 종료되지 않습니다.
웹에서는 시스템 → 시스템 상태와 데이터 준비 → 작업에서 상태를 확인할 수 있습니다.

DB가 준비된 상태에서 문서·검색 통계를 읽기 전용으로 확인하려면:

```bash
rag-dev exec -T db psql -U filing -d filing -c 'SELECT doc_id FROM documents ORDER BY doc_id;'
rag-dev exec -T db psql -U filing -d filing -c 'SELECT count(*) AS chunks, count(embedding) AS embedded FROM chunks; SELECT count(*) AS bm25_stat_rows FROM bm25_corpus_stats;'
```

embedding 개수는 모델 정체성까지 검증하지 않습니다. 웹의 provider·pending 상태와 함께 봅니다.
CLI가 직접 수행한 수집·DB 적재는 웹 작업 큐를 거치지 않아 작업에 나타나지 않을 수 있습니다.

## 로컬 모델 연결 진단

Ollama는 프로젝트 Compose와 별도로 설치합니다. [macOS·Linux Ollama 안내](ollama.md)에서 설치·시작·수신 주소 변경·모델 준비를 설명합니다. **설정 → 로컬 LLM**에서 현재 연결을 유지하거나 **Default**를 선택하며, 다른 서버를 사용할 때만 **서버 추가…**를 엽니다. **연결 진단 실행**은 선택한 서버를 검사하고 설정 저장이나 답변 실행은 하지 않습니다.

```bash
rag-ollama-check
rag-ollama-check --details
rag-ollama-check --setup
rag-ollama-check --help
# Only when DocReview uses a different web address:
rag-ollama-check --web-url http://localhost:18080
```

| 옵션 | 의미 |
| --- | --- |
| 옵션 없음 | 설정된 DocReview 주소를 통해 활성·기본 서버 진단. URL 입력 불필요 |
| `--details` | 호스트·컨테이너·수신 주소의 상세 근거 포함 |
| `--setup` | 서비스에 접속하거나 변경하지 않고 수동 준비 안내 출력 |
| `--web-url` | Ollama 주소가 아닌 **DocReview 프런트엔드 주소** 지정 |

`rag-diagnose`도 같은 진단을 실행합니다. 진단은 설치, 모델 다운로드·로드, 서비스 시작, 설정 저장, 답변 생성을 수행하지 않습니다. 설정·백엔드 연결·답변 모델 검사를 나누어 읽습니다. 목록을 확인하지 못하면 미확인이며, 설치됐지만 로드되지 않은 모델은 정상 대기입니다.

공유 진단 route가 없는 이전 API에서는 읽기 전용 호환 진단으로 전환했음을 명시합니다. `ollama list`와 `ollama ps`는 설치 모델·현재 로드된 모델을 별도로 확인합니다. [서버 선택](settings.md#local-server), [연결 복구](ollama.md#diagnostics), [답변 구성](answers.md#engines)에서 이어갑니다.

## NVIDIA 한 건만 준비하기

```bash
rag-corpus acquire_edgar --identifier NVDA --year 2024
rag-corpus status
rag-corpus ingest_manifest --manifest manifest.json --selection sec-08b5f645cc174083 --expected-documents 1
rag-corpus status
```

각 작업이 성공한 뒤 다음 명령을 실행합니다. 수집 결과는 공통 manifest 안의 정확한 처리 선택을 알려줍니다. 문서 목록을 추출하거나 manifest를 복사하지 않습니다.

## Python CLI 참고

### DB 적재

Python CLI도 웹과 같은 서버 작업을 요청합니다.

```bash
uv run python -m app.cli ingest --manifest manifest.json --selection SELECTION_ID
```

수집 결과의 선택 ID를 사용합니다. 개발 주소가 기본값과 다르면 `--api-url`로 지정합니다. 스키마 준비는 `rag-quickstart`, 전체 초기화는 `rag-fresh-start`의 역할입니다.

### Embedding과 검색

```bash
rag-corpus backfill_embeddings --manifest manifest.json --selection SELECTION_ID
rag-corpus status
rag-corpus rebuild_bm25
rag-corpus status
uv run python -m app.cli retrieve --query 'NVIDIA revenue' --issuer NVDA --fiscal-year 2024
```

임베딩 생성에는 공급자 사용료가 발생할 수 있습니다. 검색 명령은 근거를 확인하며 답변 요청을 보내지 않습니다. [검색](retrieval.md)을 확인한 뒤 [첫 답변 안내](answers.md)로 이어가세요.

### DART 수집

```bash
rag-corpus acquire_dart --identifier 005930 --year 2024
rag-corpus status
```

반환된 선택 ID로 DB 적재를 요청합니다. SEC와 DART는 같은 `manifest.json`을 사용합니다.

### 옵션 도움말

```bash
rag-corpus --help
uv run python -m app.cli ingest --help
uv run python -m app.cli retrieve --help
```

## 종료와 선택적 데이터 삭제

### 보존하며 종료하고 다시 시작하기

**목적:** 실습 결과를 유지한 채 서비스를 끕니다.

**CLI 실행:**

```bash
rag-dev down
# 나중에 새 터미널에서 저장소 루트로 이동한 뒤
source ./rag_alias.sh
rag-dev up -d
```

**예상 결과:** 일반 `down`은 컨테이너·네트워크를 정리하고 named volume을 보존합니다.
문서·청크·embedding과 run/eval/job 기록은 재시작 후 남습니다. 원문·설정 파일과 브라우저 데이터도 남습니다.

**완료 조건:** 재시작 후 데이터 준비 → 문서와 기존 대화를 확인합니다. 데이터가 준비됐다면 수집과 유료 embedding을 반복하지 않습니다.

### 삭제 전 범위 선택

**목적:** 지우려는 대상만 선택합니다. 다음 절차는 모두 선택 사항입니다.

| 범위 | 지워지는 것 | 남는 것 |
|---|---|---|
| 브라우저 대화 | 현재 origin의 이 브라우저에 저장한 대화 | PostgreSQL 데이터, 원문, 서버 연결 설정 |
| Compose DB 볼륨 | 문서·청크·embedding·BM25·run/trace·eval/snapshot·job 등 DB 기록 | 호스트 `data/` 원문·manifest·golden·profiles·연결 파일, `.env`, 브라우저 데이터 |
| 다운로드 원문 | 확인한 HTML 파일 | DB, manifest·golden·profiles, 다른 원문 |
| 로컬 연결 파일 | 저장한 앱 전체 로컬 LLM 연결 상태 | DB와 원문, `.env`의 초기 설정, 브라우저 대화별 엔진 선택 |

### 브라우저 대화 삭제

**목적:** 이 브라우저의 대화만 비웁니다.

**클릭 전:** 보관할 답변과 인용은 먼저 별도로 저장합니다. 이 삭제에 자동 복구 기능은 없습니다.
설정 → 데이터와 도움말 → **대화 삭제**에서 대상을 확인하고 승인합니다.
Reset conversation settings와 Reset saved defaults는 각각 대화 설정·새 대화와 실험 기본값 초기화이며 대화 삭제와 다릅니다.

**예상 결과와 확인:** 대화 목록이 비워집니다. 데이터 준비 → 문서와 작업의 DB 기록은 남아 있어야 합니다.
다른 브라우저·포트의 대화는 별도 origin 저장소이므로 이 작업으로 함께 지워지지 않습니다.

**완료 조건:** 대화만 사라졌으면 종료합니다. DB 삭제까지 이어서 할 필요는 없습니다.

### 로컬 Compose DB 볼륨 삭제

**목적:** 실습용 DB 전체를 버리고 빈 DB에서 다시 시작합니다.

**명령 전:** `--project-directory . -f docker/docker-compose.yml`이 이번 실습 스택인지 확인합니다.
다른 `-p` 이름으로 운영한 스택에 그대로 적용하지 않습니다. `down -v`는 이 프로젝트의
`pg_data`뿐 아니라 `web_node_modules`, `web_next` 캐시 볼륨도 제거합니다.
필요한 기록은 아래처럼 DB를 백업하고, 백업 파일이 유효한지 검사합니다. 백업 없이 삭제하면
원문으로 검색 데이터는 다시 만들 수 있어도 이전 run/eval/job 기록은 복구할 수 없습니다.

```bash
rag-dev ps
mkdir -p /tmp/docreview-backups
docreview_backup=$(mktemp /tmp/docreview-backups/filing.XXXXXX.dump)
rag-dev exec -T db pg_dump -U filing -d filing -Fc > "$docreview_backup"
rag-dev exec -T db pg_restore --list < "$docreview_backup"
```

덤프와 목록 검사 모두 성공했을 때만 다음으로 갑니다. 백업을 보존할 안전한 위치에 복사합니다.
`/tmp`는 재부팅·시스템 정리로 없어질 수 있습니다. 복구하려면 호환되는 PostgreSQL/pgvector의
빈 DB에 이 덤프를 `pg_restore`로 복원해야 합니다. 목록 검사는 실제 복원 시험을 대신하지 않습니다.

**파괴적 명령 — 위 대상과 백업을 확인한 경우에만 실행:**

```bash
rag-dev down
docker compose --project-directory . -f docker/docker-compose.yml down -v
rag-dev up -d db
rag-dev exec -T db psql -U filing -d filing -c '\dt'
```

**예상 결과와 확인:** 새 DB에는 아직 앱 테이블이 없습니다. 원문과 `.env` 등은 그대로 있어야 합니다.
[초기 schema 준비](#초기-schema-준비)로 빈 DB에 테이블을 만들고 [실습 가이드](walkthrough.md)의 DB 적재부터 다시 진행합니다.
embedding 재생성은 다시 유료입니다. 웹 재시작 후 DB 문서와 과거 job/eval 기록 상태를 확인합니다.
브라우저의 예전 대화는 남지만 삭제된 DB 근거·run을 더 이상 조회하지 못할 수 있습니다.

**완료 조건:** 빈 DB 또는 재DB 적재 후 의도한 상태가 확인되면 종료합니다.

### 다운로드 원문만 삭제

**목적:** 실습에서 받은 특정 원문 파일만 제거합니다.

**명령 전:** 진행 중인 수집·DB 적재·평가를 종료하고 해당 파일이 삭제 대상인지 확인합니다.
다른 실습이 같은 원문을 쓸 수 있습니다. 원문을 보존할 위치에 백업하거나 SEC에서 다시 받을 수
있음을 확인한 뒤에만 삭제합니다. `data/corpus` 전체를 지우지 않습니다.

```bash
ls -l data/corpus/NVDA/2024-02-21_0001045810-24-000029.html
# 필요한 백업을 마친 뒤, 확인한 이 파일만 삭제합니다.
rm -i -- data/corpus/NVDA/2024-02-21_0001045810-24-000029.html
test ! -e data/corpus/NVDA/2024-02-21_0001045810-24-000029.html && echo 'Source removed'
```

**예상 결과와 확인:** 그 원문만 사라지고 manifest·golden·profiles와 DB는 남습니다.
원문을 참조하는 검증·재DB 적재는 실패할 수 있습니다. 복구할 때는 위 한 건 수집 명령으로
다시 받은 뒤 원문 존재와 데이터 준비 상태를 확인합니다. 현재 개별 DB 문서를 삭제하는 버튼이나 API는 제공하지 않습니다.

**완료 조건:** 파일 부재와 보존 대상 존재를 확인하면 종료합니다.

### 로컬 연결 설정 초기화 또는 삭제

**목적:** 저장된 로컬 LLM 연결을 해제하거나 초기값으로 돌립니다.

**클릭:** 설정 → 로컬 LLM에서 **연결 해제**는 명시적 비활성 상태를 저장하므로
자동으로 기본 주소에 재연결하지 않습니다. **Default로 복귀**는 프로세스 환경변수 →
`.env` → 기본값으로 정해진 초기 서버를 검사한 뒤 전환합니다. 검사·저장 실패 시 동작하던
연결을 보존하며, 추가한 서버 목록도 유지합니다. 둘 다 파일 삭제와 다릅니다.

**예상 결과:** 연결 해제 후 비활성, Default 전환 성공 후 기본 서버가 표시됩니다. OpenAI 키나 대화는 지우지 않습니다.

저장 파일 자체를 지워야 할 때만 다음 절차를 사용합니다. 대상은 기본 경로
`data/local-settings/local-llm.json` 하나입니다. 보관할 서버 목록·연결 주소·프로토콜은 먼저 안전하게
기록하거나 파일을 백업합니다. 파일을 없애면 저장된 서버 목록과 명시적 연결 해제도 사라져 다음 시작에서
초기 주소가 다시 사용될 수 있습니다. 단순 연결 차단이 목적이면 연결 해제를 사용합니다.

```bash
rag-dev down
ls -l data/local-settings/local-llm.json
# 백업과 대상 확인을 마친 경우에만 실행합니다.
rm -i -- data/local-settings/local-llm.json
test ! -e data/local-settings/local-llm.json && echo 'Saved connection file removed'
rag-dev up -d
```

**확인과 완료 조건:** 설정에서 초기 연결이 적용됐는지 확인합니다. 잘못 지웠다면 앱을 중지하고
백업을 원래 경로에 복원한 뒤 재시작합니다. `.env`나 브라우저의 모델 선택은 별도로 남습니다.

## 문제가 생겼을 때

실행 데이터 초기화가 차단되면 파이프라인 왼쪽 위의 실행 데이터 초기화에서 마지막 점검 시각과
초기화 진단을 먼저 읽습니다. 권한 상세에는 실제 경로와 작업 서비스 계정이 표시됩니다. 수동 ACL
제안은 자동 실행되지 않습니다. 앱의 기존 접근 권한을 유지하고 소유자와 필요한 권한을 확인한 뒤
조치하고 다시 점검하세요. 초기화가 차단돼 있어도 실습을 위해 반드시 초기화할 필요는 없습니다.

**목적:** 증상에 맞는 확인만 수행하고 무조건 DB를 지우지 않습니다.

**CLI에서 확인:** 먼저 서비스 상태·로그의 실제 실패 위치와 메시지를 읽습니다.

```bash
rag-dev ps
rag-dev logs --tail=80 app
rag-corpus readiness
```

**웹에서 확인:** 웹이 열리면 시스템 → 시스템 상태의 연결 상태, 데이터 준비 → 작업의 실패 작업,
질문 결과의 실행 트레이스에서 해당 오류를 확인합니다. 웹 자체가 열리지 않을 때는 CLI 로그부터 확인합니다.

스키마 비호환 진단이 나오면 기존 데이터를 변경하지 않고 시작을 중단합니다. 기존 DB를 보존한 상태로 연결 대상과 진단을 확인합니다.

| 증상·위치 | 원인 확인 | 조치와 다음 조건 |
|---|---|---|
| 웹 연결 실패 | web 시작 로그, APP_PORT, 기존 포트 점유 | `rag-dev logs --tail=80 web` 확인 후 올바른 주소로 접속 |
| 웹은 열리지만 API·DB 실패 | 시스템 상태, `rag-dev ps`, DB health | 해당 서비스 연결을 복구하고 새로고침; healthy와 schema 확인 |
| `schema_drift` | 현재 구조와 기존 DB가 다름 | 기존 DB를 보존하고 비어 있는 별도 DB나 호환 DB를 선택 |
| embedding 누락·stale | 데이터 준비의 provider·pending·모델 정체성 | OpenAI 설정과 키를 확인하고 필요한 누락 임베딩 생성 실행; 유료이므로 manifest와 명시적 선택 범위 확인 |
| BM25 미준비 | DB 적재 뒤 통계 누락·무효화 | Rebuild BM25 후 succeeded와 ready 확인 |
| `NOT_IN_DOCS` | corpus·기업·연도 필터와 검색된 근거 | 문서와 인용 후보 확인 후 문서에 실제 있는 질문으로 재시도 |
| `provider_failure` | 실행 트레이스의 status·attempts·details·node | 키·모델 접근 권한·연결·한도를 확인; DB 재생성으로 해결하지 않음 |
| `budget_exceeded` | resource·limit·observed·blocked_node | 대화 설정 → 실행 한도에서 해당 한도만 조정; 재시도는 추가 비용 가능 |
| `node_error` | error_type·message·node | 해당 검색·파싱 등 단계의 원인을 해결한 뒤 재시도 |
| job이 `interrupted` | 앱 재시작으로 작업 중단 | 자동 재개되지 않음; 상태 확인 후 작업의 새 작업으로 재시도로 다시 실행 |

Run limits의 기본 wall clock은 **120초**이며 토큰 수가 아니라 run 전체 경과 시간입니다.
`input_tokens`, `output_tokens`, `iterations`도 개별 호출이 아니라 run 누적 한도입니다.
근거 길이는 **대화 설정 → 근거**의 별도 설정입니다. 로컬 LLM은 연결 조회가 성공해도
실제 답변이 오래 걸릴 수 있으므로 시간 부족을 토큰 부족으로 오해하지 않습니다.

job의 `queued`·`running`은 진행 중, `succeeded`·`failed`·`cancelled`는 종료 상태입니다.
`interrupted`는 재시작으로 끊긴 상태이며 Retry는 failed·interrupted에 제공됩니다.
유료 embedding 작업을 재시도할 때는 이미 처리된 수와 남은 범위를 먼저 확인합니다.

**예상 결과:** 실패가 발생한 단계와 조치가 연결되고, schema 재생성이나 원문 삭제를 진단 대신 쓰지 않습니다.

**완료 조건:** 해당 상태가 복구되면 실패했던 단계부터 이어갑니다. 웹 실습은 [첫 공시부터 인용 답변까지](walkthrough.md)에서 이어갑니다.

<!-- capture:16-run-trace -->

![저장된 성공 실행의 원래 ID, 반복 4회, 제공자 요청 2회, 토큰 수와 약 119.6초의 경과 시간이 표시됩니다.](../assets/16-run-trace.ko.jpg)

*저장된 성공 실행의 원래 ID, 반복 4회, 제공자 요청 2회, 토큰 수와 약 119.6초의 경과 시간이 표시됩니다. 과거에 기록된 값이며 새로 측정한 결과가 아닙니다.*

## 명령 등록 해제

등록만 해제하려면 현재 셸에서 다음 명령을 실행하고 대상을 확인합니다.

```bash
rag-alias-delete
# 등록된 명령을 사용할 수 없다면
./rag_alias.sh --delete
```

확인 후 이 체크아웃의 정확한 시작 파일 등록 줄을 백업하고 제거합니다. 다른 프로젝트의 등록이나
프로젝트 파일·DB는 지우지 않습니다. `rag-alias-delete`는 현재 셸의 변경되지 않은 프로젝트 명령도
해제하지만 별도로 실행한 `--uninstall`은 부모 셸을 바꿀 수 없으므로 안내된 후속 명령을 따릅니다.
백업 경로를 보관하고 새 터미널에서 자동 로드되지 않는지 확인합니다. 다시 등록하려면
[명령 등록과 도움말](#명령-등록과-도움말)을 따릅니다.


## 일반 초기화와 extreme 초기화

`rag-fresh-start`는 실행 중인 DEV 스택과 정확한 대화형 확인을 요구합니다. 웹과 같은 미리보기·상태 API를 사용하며, 409 거절 시 알려진 안전한 오류 코드와 복구 방법만 표시합니다. 권한 오류는 Reset diagnosis에서 확인하고 소유자에게 접근 권한을 요청하세요. 실행 중인 작업은 Jobs에서 완료를 기다리거나 취소하세요. 알 수 없는 코드·타임아웃·잘못된 응답은 실행 실패의 증거가 아닙니다. 재요청 전에 **View reset status**를 확인하세요. CLI는 삭제를 자동 재시도하지 않습니다.

일반 초기화는 검증된 DB·파일 삭제와 이후 빌드·시작 결과를 나눠 표시합니다. 코드·Git·`.env`·키·추적된 원본·무관한 파일·호스트 Ollama는 보존합니다. 브라우저 데이터는 초기화 UI에서 별도로 지우기 전까지 남습니다. 시작 후 `rag-corpus readiness`로 확인하세요. Docker 시작 성공은 데이터 준비 완료가 아닙니다. 이후 수집·처리·인덱스 구축을 다시 진행합니다. 부분 삭제나 빌드·시작 실패는 전체 복구 성공으로 표시하지 않습니다.

```bash
rag-fresh-start --help
rag-fresh-start --extreme
```

extreme은 정확한 삭제 목록을 먼저 표시합니다. `.env`·대화·사용자 코퍼스 백업 여부에 동의한 뒤, 복원 불가능한 삭제에 동의하려면 `EXTREME <체크아웃 이름>`을 입력해야 합니다. 두 단계 모두 기본값은 거절이며 Enter·No·EOF·비대화형 입력은 삭제를 승인하지 않습니다. 대상 변경이나 미리보기 만료도 실행을 막습니다. 백업은 생성되지 않으며 앱이 삭제한 데이터를 복구할 수 없습니다.

새 clone 상태의 **런타임 콘텐츠** 범위는 다음과 같습니다.

- `data/corpus`의 사용자 PDF·JSON을 포함해 `data/eval_runs`, `data/local-settings`, `build`, `dist`, `web/.next`, `web/out`, `web/.tutorial`, `web/public/tutorial-assets`, `.pytest_cache`, `.ruff_cache` 아래의 추적되지 않은 파일과 루트의 추적되지 않은 `.env*` 파일을 삭제합니다. 빈 디렉터리는 남을 수 있습니다.
- 해당 체크아웃 소유로 확인된 `db`·`app`·`web` 컨테이너와 로컬 Compose `pg_data`·`web_next`·`web_node_modules` 볼륨만 삭제합니다. 외부·공유 볼륨, 예상 밖 컨테이너, 심볼릭 링크가 있으면 중단합니다.
- Git 추적 파일과 수정 내용·히스토리, 호스트 `.venv`·`node_modules`, 그 밖의 개인 파일, 다른 Docker 프로젝트, 호스트 Ollama·외부 자격증명·초기화 감사 기록은 보존합니다. 전체 `git clean`이나 호스트 초기화가 아닙니다.

터미널에서 두 번 확인한 뒤 다른 DocReview 탭을 닫고, 대화가 저장된 브라우저로 출력된 `/reset-local/#<operation-id>` URL을 여세요. 페이지가 해당 주소의 DocReview local/session storage를 삭제·검증하고 같은 작업 ID로 인증된 확인 응답을 보내야 로컬 삭제가 진행됩니다. CLI는 그 확인을 받은 브라우저·주소에 한해 삭제 완료를 표시합니다. 다른 프로필·기기·포트와 localhost/127.0.0.1 주소는 별개입니다. 메모리에 대화가 남은 이전 탭을 다시 열지 마세요. 확인이 만료되면 로컬 삭제는 시작하지 않지만 브라우저 삭제는 이미 발생했을 수 있으므로 상태를 먼저 확인하세요.

extreme 성공 후에도 서비스는 중지 상태로 유지합니다. `rag-quickstart`로 새 `.env`를 준비하고 로컬에서 설정한 다음 Quick Start를 따라 데이터를 다시 준비하세요. 부분 실패는 완료된 단계를 확인하세요. 자동 재시작이나 삭제 재시도는 하지 않습니다.

### SCREENSHOT NEEDED
<!-- Feature: extreme CLI browser acknowledgement. State: matching waiting operation on reset-local, then acknowledged deletion. Capture en and ko in light mode using disposable data only; no credentials. -->
브라우저 확인 페이지의 새 스크린샷 증거는 아직 없습니다.


`rag-fresh-start --status`는 extreme 삭제로 `.env`가 없어지거나 웹 컨테이너가 중지돼도 기존 로컬 operator 연결로 마지막 초기화 상태를 읽습니다. 삭제를 재요청하지 않습니다. 코드를 업데이트한 뒤에는 `rag-dev down`, `rag-dev up -d` 순서로 로컬 operator를 재시작한 후 새 옵션을 사용하세요. 이 명령들은 데이터 볼륨을 보존합니다.
