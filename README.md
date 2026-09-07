# DocReview

[처음 사용자용 튜토리얼](docs/TUTORIAL.md)

SEC 10-K와 한국 DART 사업보고서를 원문 근거와 함께 검토하는 evidence-first RAG
서비스입니다. 공시 원문을 파싱하고 PostgreSQL/pgvector에 저장한 뒤 vector·lexical
검색을 RRF로 융합하며, 답변은 검색된 source span을 인용해야만 `SUPPORTED`로
종료할 수 있습니다. 근거가 없으면 `NOT_IN_DOCS`를 반환합니다.

사용자 화면은 정적 Next.js 서비스이고, FastAPI가 검색·리뷰·평가·관리 API를
제공합니다. 공개 배포에서는 실제 검색과 비용 제한 LLM 리뷰를 제공하고, corpus 변경과
골든 평가 작업은 SSH tunnel을 통한 local operator 모드에서만 실행합니다.

## 처음 실행하기

새 clone의 전체 설치 경로는 [환경 준비](docs/TUTORIAL/ko/environment.md#qs-setup)를 따릅니다. 이미 실행 중인 앱은 [Quick Start](docs/TUTORIAL/ko/quickstart.md)에서 바로 체험하세요.

원문·DB·청크·임베딩과 `.env`는 clone에 포함되지 않습니다. Bash 또는 Zsh에서
[uv](https://docs.astral.sh/uv/getting-started/installation/)와 Docker Engine·Compose 2.24.4+를 준비하세요.
RAG Helper는 저장소에 포함되어 있어 따로 내려받지 않습니다.

```bash
git clone https://github.com/sungyongcho/docreview-rag-agent.git
cd docreview-rag-agent
source ./rag-alias.sh
rag-help
rag-start-quick
```

**clone했는데 무엇부터 할지 모르겠다면 `rag-start-quick`를 실행하세요.**
`rag-start-fresh`는 `.env*`·도구 설정·보존 목록·Ollama 모델을 남기고 체크아웃과 해당 Docker 자원을
정리한 뒤 다시 준비합니다. `--no-start`는 정리 후 중지합니다. `rag-reset`는 ORM 데이터와 원문만 초기화합니다.
모든 명령에 `--verbose` (`-vv`)를 붙일 수 있으며 기본 출력은 단계 상태·소요 시간입니다.
삭제 미리보기의 `(Y/n)`은 대문자 한 글자 `Y`만 승인합니다.

`rag-start-quick`는 Python 환경을 설치하고, `.env`가 없으면 템플릿을 생성합니다.
안내된 SEC 연락처·DART 키·OpenAI 개발 키를 **로컬 `.env`에서만** 입력한 뒤 `[r]`로 같은 단계에서 다시 확인하세요.
충돌한 값은 `.env` 줄과 shell 출처를 구분해 표시합니다. `[f]`는 이번 실행의 잘못된 export를 제외하고,
`[e]`는 공개 임베딩 설정 두 개를 맞춥니다. 부모 셸이나 인증 정보는 자동 변경하지 않습니다.
OpenAI 임베딩은 `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-large`로 설정합니다.
기존 설정과 데이터는 보존하며, 첫 실행 자체는 원문 다운로드나 유료 모델 호출을 하지 않습니다.

서비스가 준비되면 표시된 **Quick Start — DEV ONLY** 링크를 여세요. 기본 포트에서는
[한국어 Quick Start — DEV ONLY](http://localhost:8000/docreview-rag-agent/docs/ko/quickstart-dev/) 또는
[English Quick Start — DEV ONLY](http://localhost:8000/docreview-rag-agent/docs/en/quickstart-dev/)에서
**CLI / Web** 중 하나를 선택해 NVIDIA SEC FY2024와 삼성전자 DART FY2024의 원문부터
청킹·OpenAI 임베딩·BM25까지 준비합니다. [GitHub에서 바로 읽기](docs/TUTORIAL/ko/quickstart-dev.md)도 가능합니다.

`source` 등록은 현재 터미널에 적용됩니다. 영구 등록은 아래 설치 절의 절대경로 안내를 따르세요.
`rag-reset`는 기존 데이터를 지우는 재시작 명령이므로 새 clone의 첫 실행에는 사용하지 않습니다.

## 주요 기능

- SEC EDGAR·DART 원문 수집과 registry별 파싱
- source SHA-256와 half-open character span으로 되짚을 수 있는 청크
- pgvector exact vector search와 `ts_rank_cd`/BM25 lexical search
- RRF 융합, 선택적 cross-encoder reranking, 한국어 n-gram lexical 경로
- 인용 검증 LLM workflow와 `NOT_IN_DOCS` fail-closed 종료
- 순서형 Build 파이프라인(원문 → 파싱·청킹 → 임베딩 → BM25 → 질문 → 답변 모델 → 평가), 인용 카드, 단계형 튜토리얼을 갖춘 Next.js 서비스
- Playground·골든셋·평가 실행·스냅샷 비교를 갖춘 Measure와 readiness·Operations·API inspector·Usage를 갖춘 System
- Recall@k·Hit Rate@k·MRR·latency, 교차언어 parity, ablation 평가
- FastAPI·SSE·MCP agent와 공통 웹·CLI 작업
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
- 선택: `MODE`별 슬롯 `OPENAI_API_KEY_LOCAL`(dev)·`OPENAI_API_KEY_PROD`(prod) — 실제 LLM 리뷰
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

OpenAI 키는 환경별 전용 슬롯에 둡니다. `rag-dev`는 `OPENAI_API_KEY_LOCAL`,
`rag-prod`는 `OPENAI_API_KEY_PROD`만 읽으며 다른 환경의 키로 대체하지 않습니다.
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
source ./rag-alias.sh
rag-help
rag-dev up -d
```

`source ./rag-alias.sh`는 Small Slant `DocReview RAG` 배너와 `[OK]` 등록 완료 메시지,
대상 저장소 경로와 `rag-help` 안내를 표시합니다. 등록은 현재 셸에 적용됩니다.
대화형 `source ./rag-alias.sh`는 자동 등록 선택과 현재 셸 활성화를 한 번에 처리합니다.
Y는 시작 파일에 저장하고 N은 현재 셸만 활성화합니다. `rag-alias --check-updates`는 설치된
hash와 파일 hash를 비교하고, `rag-alias update [새 경로]`는 변경된 명령과 기존 등록 줄을
갱신합니다. 실행형 `./rag-alias.sh`는 별도로 기본값 No인 로그인 셸 선택을 제공하며,
부모 셸을 바꾸지 않습니다. 기본 활성화 경로는 source입니다.
셸 시작 파일에서 자동 로드할 때는 `source /실제/경로/rag-alias.sh >/dev/null`로 안내문 출력을 생략합니다.
`rag-alias-delete` 또는 `./rag-alias.sh --delete`은 확인 후 이 파일의 정확한 자동 등록 줄만
백업하고 제거합니다(Python 3 필요). 다른 파일을 불러오는 줄이나 프로젝트 파일은 제거하지 않습니다.
`rag-alias-delete`는 현재 셸에서 이 스크립트가 등록한 뒤 변경되지 않은 함수와 별칭만 해제합니다.
별도 실행한 `--uninstall`은 부모 셸을 변경할 수 없으므로 기존 셸의 해제 명령을 안내합니다.
삭제 확인은 `--delete` 또는 `rag-alias-delete`를 명시적으로 실행했을 때만 표시합니다.
`rag-help`에서 시작·종료·로그·진단 명령과 옵션 예시를 확인할 수 있습니다.

```bash
rag-dev down
rag-prod up -d
rag-prod down
rag-dev logs -f
rag-prod ps
```

등록된 명령은 어느 디렉터리에서 실행해도 등록 당시 저장소를 대상으로 합니다.
시작·종료는 `rag-dev up -d` / `rag-dev down`, 공개 미리보기는 `rag-prod`로 선택합니다.
별칭 없이 실행하려면 저장소 루트에서 `.venv/bin/python -m scripts.stack dev up -d`를 사용합니다.
`rag-help`는 Quick Start 명령과 다음 URL 안내를 맨 앞에, 초기화·복구를 별도 RESET 영역에
표시합니다. 두 열로 정렬하고 TTY에서는 굵은 명령명과 색상 제목·주의를 사용합니다. NO_COLOR나 파일 출력은 일반 텍스트입니다. 상세 옵션은 각 명령의
`--help`에서 확인합니다. 이전 밑줄 파일명으로 등록한 경우 source 설치가 정확한 이전 경로를
알리고 백업 후 변경을 제안합니다. 호환 링크는 만들지 않습니다.
스키마 관리는 `rag-schema check|prepare|recover|recreate`로 통합했습니다.
패키지와 직접 실행 경로는 [스크립트 안내](scripts/README.md), 제거된 단축 명령은
[로컬 실행 명령 안내](docs/TUTORIAL/ko/cli.md#명령-통합)에서 확인하세요.

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
.venv/bin/python -m scripts.diagnostics.ollama
.venv/bin/python -m scripts.diagnostics.ollama --web-url http://localhost:18080
```

`--web-url`에는 Ollama 서버가
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
gemma4처럼 thinking을 지원하는 모델은 요청에서 thinking을 끈 채(`think: false`) 실행하고, 창 크기
(`num_ctx`)는 설정된 입력+출력 허용량으로 한 실행 동안 고정해 호출 사이에 모델을 다시 로드하지
않습니다. GPU 없는 CPU(Ryzen 7 8845HS) 실측은 생성 약 10 tok/s, 프롬프트 평가 약 80–95 tok/s,
기준 질문 36–103초입니다(`docs/TUTORIAL/ko/ollama.md`의 지원 구성 표). 프롬프트가 남은 입력
허용량을 넘길 것으로 추정되면 호출 전에 거절되고 Run trace에 `projected_input_tokens`로 남습니다.
대화 전체 한도는 RAG settings → Run limits에서 조절합니다. 연결 성공이 답변 품질 검증 완료를
뜻하지는 않으며, 실패 원인은 응답의 Run trace에서 확인합니다.

## 5분 로컬 실행

### 1. 환경과 원문 준비

Helper를 등록한 뒤 `rag-start-quick`를 실행하면 Python 환경과 빈 스키마를 준비하고
개발 서비스를 시작합니다. 기존 설정과 호환되는 데이터는 보존합니다.
`rag-dev up --build -d`도 DB health 확인 후 이미지 시작 게이트에서 빈 DB 스키마를
자동 생성합니다. 기존 DB는 검사만 하며 불일치하면 API 시작을 차단합니다.
`rag-dev logs --tail 80 app`에서 원인과 `scripts.schema check`/`recover` 안내를 확인하세요.
이 동작은 prod 미리보기와 배포 Compose에도 적용되며, 공개 예시 모드는 DB 없이 시작합니다.

```bash
source ./rag-alias.sh
rag-help
rag-start-quick
rag-corpus acquire_edgar --identifier NVDA --year 2024
rag-corpus acquire_dart --identifier 005930 --year 2024
rag-corpus status
```

SEC는 `SEC_USER_AGENT`, DART는 `DART_API_KEY`가 필요합니다. 두 수집 작업은 공통
`manifest.json`에 원문과 문서 선택을 기록합니다. 완료 작업의 `selection_id`를 다음
단계에서 사용합니다. CLI와 웹 Build는 같은 애플리케이션 작업을 실행합니다.

### 2. 파싱, 인덱스와 검색

각 수집 작업의 선택 ID로 인제스트하고 작업 완료를 확인합니다.

```bash
rag-corpus ingest_manifest --manifest manifest.json --selection <selection-id>
rag-corpus status
rag-corpus backfill_embeddings --manifest manifest.json --selection <selection-id>
rag-corpus status
rag-corpus rebuild_bm25
rag-corpus inspect
```

임베딩은 설정된 공급자에 따라 비용이 발생합니다. 변경되지 않은 입력과 동일한 임베딩
설정은 기존 벡터를 재사용합니다. 웹의 준비 상태는 작업 완료 후 자동 갱신됩니다.

`schema_drift`는 저장된 스키마와 현재 모델이 맞지 않는다는 뜻입니다. 실행 중인 코드와
DB 연결을 확인하고 기존 데이터를 보존한 상태에서 운영자가 원인을 조사해야 합니다.
기본 복구는 기존 데이터를 보존합니다. `uv run python -m scripts.schema recreate`는
ORM 데이터와 다운로드 원문·manifest 원문 항목을 지우므로 대상·행 수·원문 경로를 확인한 뒤
`Y`로 승인합니다. `--keep-sources`는 원문을 보존하며,
`--sample`은 동일한 초기화 뒤 NVDA/AMD FY2023–2024 초안만 저장하고 다운로드하지 않습니다.
코드·`.env`·평가 내보내기·무관한 테이블·DB 볼륨은 보존합니다. 완료 후 `rag-up`으로 시작하세요.
`rag-reset`는 같은 ORM·원문 범위의 확인된 초기화 뒤 DEV 시작·readiness 확인·Quick Start — DEV ONLY의 Web 1단계 안내까지 이어갑니다.
`--keep-sources`·`--sample`을 지원하며 설정·내보내기·DB 볼륨은 보존합니다. 권한 오류는 소유자에게 요청할
정확한 명령과 한 번의 검사 재시도를 제공합니다. 더 넓은 삭제는 `rag-start-fresh`이며,
`rag-start-fresh --extreme`은 대문자 `Y` 두 번 확인 후 `.env*`와 프로젝트 Ollama 모델 볼륨도 지우고 멈춥니다. 브라우저 데이터는 설정 → 데이터와 도움말에서 별도로 지우세요.

검색 결과와 원문 근거를 확인한 뒤 [첫 답변 안내](docs/TUTORIAL/ko/answers.md#step-9)를
따릅니다. Quick Start — DEV ONLY는 답변 질문을 제출하기 전에 끝납니다.

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
필요하면 `rag-dev up -d`를 사용합니다. prod와 공개 화면에는 Operations URL·토큰·메뉴를 제공하지 않습니다.

로컬 Compose 앱은 비루트 UID 10001과 호스트 기본 그룹(`HOST_GID`)으로 실행하고,
`umask 0002`로 새 다운로드·평가 디렉터리의 그룹 쓰기를 허용합니다. 로컬 모델 설정 파일은
0640으로 저장해 호스트 그룹이 읽을 수 있습니다. `data/` 자체의 그룹 쓰기 권한은 필요하며,
직접 Compose를 실행하는 다른 GID 환경은 `.env`의 `HOST_GID`를 `id -g` 값에 맞춥니다.
기존 컨테이너 소유 경로는 자동 변경하지 않습니다. `rag-reset`가 확인·API 중지 전에
정확한 `sudo` 복구 명령을 출력하며, 실패 후 API 복구 명령은 `rag-dev up -d`입니다.
자세한 동작은 [환경 안내](docs/TUTORIAL/ko/environment.md)를 참고하세요.
스크립트는 DB reset·볼륨 삭제·배포·Git stage/commit을 자동 실행하지 않습니다.

<!-- operator-commands:start -->
| ID | Target | Command | Purpose | Confirmation |
|---|---|---|---|---|
| `git-status` | App | `git status --short --branch` | Show branch plus staged, unstaged, and untracked paths. | no |
| `python-lint` | Python | `.venv/bin/ruff check app tests scripts` | Check application, tests, and scripts without rewriting files. | no |
| `python-format-check` | Python | `.venv/bin/ruff format --check app tests` | Report files Ruff would reformat without changing them. | no |
| `python-tests-offline` | Python | `.venv/bin/pytest -q -m not live_postgres` | Run the suite without live PostgreSQL cases or provider requests. | no |
| `python-tests-postgres` | Database | `.venv/bin/pytest -q -m live_postgres --require-live-postgres` | Require the live PostgreSQL marker instead of silently skipping it. | no |
| `web-tests` | Web | `npm test` | Run the Vitest component and client-contract suite. | no |
| `web-typecheck` | Web | `npm run typecheck` | Run TypeScript without emitting build output. | no |
| `web-build` | Web | `.venv/bin/python scripts/release/web_build.py` | Build the current static Next source in an isolated temporary checkout. | no |
| `schema-check` | Database | `.venv/bin/python -m scripts.schema check` | Inspect this checkout's local database schema without changing data. | no |
| `schema-prepare` | Database | `.venv/bin/python -m scripts.schema prepare` | Create schema objects only in an empty local database; preserve existing data. | required |
| `db-start` | Database | `docker compose --project-directory . -f docker/docker-compose.yml up -d db` | Start the local pgvector service and retain its existing volume. | required |
| `db-stop` | Database | `docker compose --project-directory . -f docker/docker-compose.yml stop db` | Stop the local database without deleting its volume. | required |
| `app-start` | App | `docker compose --project-directory . -f docker/docker-compose.yml up --build -d app` | Build the local image and start the app with its database dependency. | required |
| `app-stop` | App | `docker compose --project-directory . -f docker/docker-compose.yml stop app` | Stop the local app container while leaving PostgreSQL unchanged. | required |
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
단계 카드로 누락 문서 수집, `Ingest selected documents`(manifest별 순차 job), embedding backfill,
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
| `GET` | `/ready` | 모델 정책·DB·schema·corpus readiness (상태 판독은 최대 2초, 작업 실행 중에는 10초 동안 재사용하고 작업이 끝나면 새로 잽니다) |
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
scripts/release/clean_checkout.sh
```

게이트는 `basedpyright app`과 전체 Ruff 검사에 더해, 방금 빌드한 앱 이미지로
격리된 Compose DB의 실제 reset을 검증합니다. 사용자의 DB나 서비스는 대상으로 삼지 않습니다.
reset 테스트를 단독 실행하려면 `DOCREVIEW_WIPE_TEST_IMAGE`에 검증할 로컬 앱 이미지 태그를
지정하세요. 이 값이 없는 선택적 실행은 이유를 표시하고 건너뛰지만,
`--require-live-postgres`를 지정한 필수 검증은 준비 조건이 없으면 실패합니다.

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
FIREBASE_PROJECT_ID=<project-id> scripts/deploy/firebase.sh
```

GCP VM 준비·배포 스크립트:

```bash
GCP_PROJECT_ID=<project-id> deploy/gcp/create_vm.sh
GCP_PROJECT_ID=<project-id> deploy/gcp/deploy_backend.sh
```

실관리 UI는 SSH tunnel 뒤에서 실행합니다.

```bash
GCP_PROJECT_ID=<project-id> deploy/gcp/operator_tunnel.sh
scripts/stack/operator_web.sh
```

배포 스크립트는 비용과 외부 상태를 변경하므로 값을 검토한 뒤 별도로 실행해야 합니다.

## 트러블슈팅

| 증상 | 확인할 것 |
|---|---|
| `database_unavailable` | `docker compose --project-directory . -f docker/docker-compose.yml ps db`, `DB_PORT`, `DATABASE_URL` |
| `schema_drift` | 코드와 DB 연결 대상 및 스키마 진단을 확인. 기존 데이터를 보존하고 운영자 조사 |
| `/review` 503 | `REVIEW_MODEL`, MODE에 맞는 개발/운영 키, `/ready`의 model policy 상태 |
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

## 관련 운영 문서

- [Docker Compose 운영](deploy/docker-compose.md)
- [골든셋 author review queue](data/golden/REVIEW.md)
- [테스트 파일 배치 규칙](tests/RULES.md)
