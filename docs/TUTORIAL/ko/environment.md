# 환경 준비

저장소를 clone했는데 무엇부터 할지 모르겠다면 `source ./rag-alias.sh` 후
`rag-start-quick`를 실행하세요. `rag-start-fresh`는 확인된 체크아웃 정리,
`rag-reset`는 설정·볼륨을 보존하는 ORM 데이터·원문 초기화입니다.
모든 명령에 `--verbose` (`-vv`)를 붙일 수 있습니다. [CLI 안내](cli.md)를 참고하세요.

이 페이지는 GitHub에서 DocReview RAG를 clone한 뒤 로컬에서 처음부터 실행하는 사람을 위한 안내입니다. 아래 Part 1을 따라 서비스를 준비하고 데이터 준비 화면을 엽니다. 이미 실행 중인 앱을 바로 체험하려면 [Quick Start](quickstart.md)를 보세요.

## Part 1: 환경 준비 {#qs-setup}

### 선행 조건 {#prerequisites}

Bash 또는 Zsh, uv, Docker Engine·Compose 2.24.4+를 준비하세요.
웹의 Node/npm은 컨테이너에서 실행되므로 이 경로에서는 호스트에 별도로 설치하지 않습니다.

```bash
git clone https://github.com/sungyongcho/docreview-rag-agent.git
cd docreview-rag-agent
source ./rag-alias.sh
rag-help
rag-start-quick
```

source 한 번으로 설치와 활성화를 진행합니다. Y는 자동 등록을 저장하고 로그인 셸로 재시작하며 배너에서 rag-help 입력을 안내합니다. N은 이번 셸만 불러옵니다. 다시 source하면 버전과 등록된 정의를 비교해 [already installed] 또는 [update required]를 표시하며 이후 변경은 `rag-alias update`로 반영합니다.

Helper는 저장소에 포함됩니다. `source`는 현재 터미널에 등록하며,
선택적인 [영구 등록 방법](cli.md#명령-등록과-도움말)은 명령 안내를 참고하세요.
첫 실행은 `.env`가 없을 때만 생성합니다. 파일을 로컬에서 편집하고 `rag-start-quick`를 다시 실행하세요.

```dotenv
SEC_USER_AGENT=Your Real Name your-real-contact@example.org
DART_API_KEY=<your-own-dart-key>
OPENAI_API_KEY_LOCAL=<your-own-openai-development-key>
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
```

예제 값을 실제 연락처·키로 바꾸세요. DEV는 `OPENAI_API_KEY_LOCAL`,
운영은 `OPENAI_API_KEY_PROD`만 읽습니다. 키를 문서 입력란에 넣거나 화면에 캡처하지 마세요.
저장소의 임베딩 차원은 384입니다. deterministic 임베딩은 이 실습의 완료 기준이 아닙니다.
SEC 연락처와 DART 키는 원문 수집에 필요하고, 임베딩 생성에는 OpenAI 비용이 발생합니다.
첫 실행 명령 자체는 수집·임베딩·답변 요청을 하지 않습니다.

빈 DB에만 스키마를 생성하고 기존 정상 DB는 보존합니다. 스키마가 맞지 않으면 자동 초기화하지
않고 원인을 안내합니다. 설정·도구 누락을 해결한 뒤 같은 명령을 재실행하세요.
설치 문제를 고치려고 `rag-reset`를 실행하지 마세요.
표시된 주소(기본 `http://localhost:8000/docreview-rag-agent/`)를 엽니다.

설정 명령은 사전 요구사항 → 로컬 설정 → 프로젝트 서비스 상태·시작 → 스키마 준비 → DEV 서버 준비 확인의 다섯 단계를 표시합니다. `db`, `app`, `web` 각각의 중지·시작 중·비정상·실행 상태를 구분합니다. 헬스 체크가 없는 컨테이너가 실행 중이라는 사실만으로 서버 준비 완료를 선언하지 않습니다. 이미 정상 실행 중인 서비스도 Compose가 개발 설정을 적용하기 전에 표시합니다.

설정에서 중단되면 각 키의 `.env` 줄·shell 값·실제 적용 출처를 보여 주고 인증 정보는 숨깁니다.
`[f]`로 이번 실행의 잘못된 export를 제외하거나 `[e]`로 공개 임베딩 설정 두 개를 저장할 수
있습니다. 파일을 고친 뒤 `[r]`로 같은 단계에서 다시 확인하고, `[q]`로 취소합니다. 부모 셸은
바꾸지 않으므로 이후 실행에도 적용하려면 출력된 `unset KEY`를 부모 셸에서 실행하세요.
시작·readiness 실패 시 기존 읽기 전용 진단을 실행하고, 확인 후 볼륨을 보존하는
종료·빌드·시작 복구를 한 번 제안합니다.

## 1. 실행 환경 열고 확인하기 {#step-1}

> [!GOAL]
> 현재 환경에서 문서를 살펴보고 필요한 준비 작업을 할 수 있는지 확인합니다.
>
> **준비** [Part 1: 환경 준비](#qs-setup) 또는 호환되는 DB가 연결된 실행 중인 서비스 · **완료** API가 응답하고 DB가 연결되며 스키마를 사용할 수 있습니다.

사이드바 **시스템 → 시스템 상태**를 엽니다. 페이지 제목은 **실행 준비 상태**입니다. 모드 표시를 읽고 준비 과정을 실습하려면 개발 환경을 사용하세요. 공개 모드는 권한이 달라 일부 조작이 보이지 않을 수 있습니다. 이 확인을 위해 원문 수집·임베딩·답변 요청을 실행할 필요는 없으며, 질문이나 기업을 입력하지 않습니다. 대신 서비스 주소가 의도한 환경인지 확인하세요. 화면이 같아 보여도 API·DB 주소가 다르면 다른 데이터를 사용하는 환경일 수 있습니다. 코퍼스 수치는 두 빌드 모두 표시되며 쓰기 가능 여부만 감춥니다.

1. **새로고침**을 한 번 누르고 **확인 중…**이 끝날 때까지 기다립니다. 상태 정보가 갱신되며, 시스템 메뉴나 연결 경고에서 API 상태를 읽습니다.
2. 데이터베이스·스키마 항목을 확인합니다. 코퍼스 수치와 모델 정책은 같은 환경의 다른 준비 항목입니다.
3. 완료 여부를 확인합니다. API가 응답하고 DB가 연결되며 스키마를 사용할 수 있으면 현재 환경에서 문서 준비를 허용하는지도 파악한 것입니다. 코퍼스가 비어 있어도 이 조건은 충족할 수 있으며, 기존 데이터 확인은 다음 단계에서 합니다. 알 수 없는 항목은 확인되지 않은 상태이므로 통과로 해석하지 않습니다.
4. 페이지는 열리는데 API 확인이 실패하면 `rag-dev ps`와 `rag-dev logs --tail=80 app`을 확인하고, [문제 해결](troubleshooting.md)에서 기록된 증상에 맞는 조치를 적용한 뒤 다시 새로고침합니다. 새 DB라면 위의 스키마 준비를 따르고, 스키마 불일치가 있다고 기존 DB를 삭제하지 않습니다.

| 항목 | 확인할 내용 | 이것만으로 알 수 없는 것 |
|---|---|---|
| API 상태 | 연결 실패·확인 중에 머물지 않고 서비스가 응답하는지. | 문서나 모델 호출의 준비 완료 여부. |
| 데이터베이스 | 의도한 DB에 연결되었는지. | 스키마 호환 여부. |
| 스키마 | 누락 테이블이나 스키마 불일치가 없는지. | 문서가 한 건이라도 존재하는지. |
| 모드와 권한 | 필요할 때 개발용 준비 조작을 사용할 수 있는지. | 공개 서비스에서 관리자 쓰기가 허용되는지. |
| 코퍼스 | 빈 상태·일부 준비 상태를 포함해 실제 수치가 수집되었는지. | 모든 벡터가 의도한 모델로 만들어졌는지. |
| 모델 가용성 | 선택한 엔진이 사용 가능하거나 빠진 조건이 설명되는지. | 모델 요청의 성공이나 답변 근거의 충분함. |

### SCREENSHOT NEEDED
<!-- feature=runtime-readiness-status; mode=dev; locale=ko; theme=light; state=checked-runtime-readiness-with-api-database-schema-and-mode-facts; expected-evidence=system-status-heading-connection-warning-refresh-control-and-fact-rows -->

데이터 준비 화면을 열고 아래 개발용 준비 안내로 이어갑니다.

## 데이터 준비 화면을 열고 이어가기 {#open-build}

출력된 앱 주소를 열고 **데이터 준비 → 파이프라인**을 선택합니다. 준비 단계 그래프와 선택한 단계를 살펴볼 수 있는지 확인하세요. 데이터 준비 화면을 여는 것만으로 원문을 다운로드하거나 모델을 실행하지 않습니다.

**서비스 준비와 데이터 준비는 다릅니다.** [Quick Start for DEV MODE](quickstart-dev.md#qs-web-1)에서 CLI 또는 Web을 선택해 환경 확인, 예제 보고서 두 건 수집, 파싱·청킹, 임베딩·BM25 준비, 질문 전 준비 확인을 이어갑니다. 이미 끝난 작업은 재사용하세요. 이후 [12단계 학습 경로](overview.md#learning-path)에서 질문·설정·평가로 이어집니다.

## 준비 단계가 막혔을 때 {#schema-recovery}

데이터 준비 화면은 DB 스키마와 원문 저장 경로의 쓰기 권한을 구분합니다. 스키마 불일치가 `data/` 쓰기 권한 부족을 뜻하지는 않습니다. **스키마 확인**으로 현재 상태를 다시 읽습니다. **터미널에서 실행 필요** 안내가 있으면 명령을 복사해 이 저장소의 터미널에서 실행한 뒤, 같은 단계로 돌아와 **상태 업데이트 확인**을 누르세요. 문제가 남아 있으면 계속 표시되며, 버튼을 누르는 것만으로 복구되지는 않습니다.

```bash
uv run python -m scripts.schema check
```

비어 있는 로컬 DB에만 다음 명령으로 스키마를 준비한 뒤 다시 확인합니다.

일반 Compose 시작은 DB health 확인 후 빈 DB 스키마를 자동 준비합니다. 이미지 진입점은 기존 DB를 변경 없이 검사하고, 불일치하면 API 실행을 차단합니다. DEV·로컬 PROD 모드·해당 이미지의 배포 Compose에 적용됩니다. 웹만 열리고 API가 차단됐다면 `rag-dev logs --tail 80 app`에서 진단과 로컬 `check`/`recover` 명령을 확인하세요. DB 없는 공개 예시 모드는 검사를 건너뜁니다. 원문 수집과 인덱싱은 여전히 별도 선행조건입니다.

DB만 따로 시작한 경우에는 빈 DB에 한해 다음 수동 준비도 가능합니다.

```bash
uv run python -m scripts.schema prepare
```

기존의 호환되지 않는 DB는 보존되며 준비 명령이 변경을 거부합니다. 이미지를 다시 빌드하거나 서비스를 재시작해도 호환되지 않는 DB 구조가 복구되지는 않습니다. 인덱싱 전 호환되거나 비어 있는 로컬 DB를 선택하세요. 로컬 DEV DB 내용을 버리기로 명시적으로 선택한 경우에만 CLI 안내의 `scripts.schema recreate` 경로를 검토하세요. 자동 초기화는 하지 않습니다. 서비스 중지나 실제 저장 권한 문제에는 해당 문제의 터미널 명령과 확인할 결과가 별도로 표시됩니다.

### 로컬 컨테이너 파일 소유권

로컬 Compose는 이미지의 비루트 UID 10001을 유지하고 `HOST_GID`를 앱의 기본 그룹으로
사용합니다(기본값 1000, `rag-dev`는 실행한 호스트 그룹을 전달). 기존 DB 초기화 절차를
거친 뒤 API 시작 시 `umask 0002`를 적용합니다. 새 원문·다운로드·평가 디렉터리는 그룹이
쓸 수 있고, 저장된 로컬 모델 설정은 호스트 그룹이 읽을 수 있는 0640 권한입니다.
이미지 기본 사용자와 배포 Compose는 바꾸지 않는 로컬 bind mount 공유 정책입니다.

호스트의 `data/` 디렉터리는 해당 그룹의 쓰기를 허용해야 합니다. 기본 그룹이 1000이 아닌
호스트에서 Compose를 직접 실행한다면 `HOST_GID`를 `id -g` 값으로 지정하세요. 예전에
컨테이너가 만든 파일의 기존 권한은 자동 변경되지 않습니다. 초기화 미리보기는 차단된 원문
경로에 필요한 관리자 권한 복구 명령을 출력합니다. 오래된 `data/local-settings` 또는
`data/eval_runs`에도 호스트 접근이 필요하면 소유자가 같은 범위 제한 ACL 복구를 해당
디렉터리에 적용해야 합니다. 소유권·ACL은 자동 변경하지 않습니다. 이 로컬 Compose 정책을
업데이트한 뒤에는 `rag-dev up -d`로 앱 컨테이너를 재생성하세요. 소스 자동 반영만으로 기존
컨테이너의 기본 그룹이나 실행 명령이 바뀌지는 않습니다. [초기화 복구](cli.md)를 참고하세요.

오류의 **이 단계 점검**으로 관련 파이프라인 단계에 이동합니다. DB·스키마 문제는 설치 안내로 연결합니다. 도착한 단계에서 현재 진단과 터미널 안내를 확인하며, 다른 오류 영역에는 원인과 이동 링크만 간단히 표시합니다.

스키마가 호환되지 않으면 `.venv/bin/python -m scripts.schema check`로 진단하세요. Quickstart는 외부 `DATABASE_URL`이 아니라 로컬 `DB_PORT`를 사용합니다. 안전한 대상 선택 복구는 [#25](https://github.com/sungyongcho/docreview-rag-agent/issues/25)에서 다룹니다. 이 중단을 해결하려고 데이터베이스를 초기화하지 마세요.

## 실행 환경과 준비 작업 구분하기 {#environment-boundaries}

Ollama는 로컬 답변을 위한 선택 사항이며 DocReview 스택과 별도로 설치합니다. **설정 → 로컬 LLM**에서 **Default**를 선택하고 **연결 진단 실행**으로 확인한 뒤 필요한 연결 변경을 수행합니다. **서버 추가…**는 다른 주소를 사용할 때만 선택합니다. [macOS·Linux 설치 안내](ollama.md)에서 설치와 백엔드 접근을 설명하며 `rag-ollama-check`는 읽기 전용 진단입니다. 답변 모델이 없다는 사실만으로 API·DB·스키마가 고장 났다고 판단하지 않습니다.

개발 서비스는 소스 자동 반영과 문서 실시간 편집을 지원합니다. API 재시작은
실행 중인 작업을 중단할 수 있으므로 재시도 여부를 결정하기 전에 작업 기록을
확인하세요. 작업·실행 상태는 [실행 상태](runtime.md)에서 설명합니다.

이번 릴리스는 DEV와 PROD를 각각의 실행 모드로 지원합니다. DEV 안의 **배포 화면 미리보기**는 [후속 이슈 #211](https://github.com/sungyongcho/docreview-rag-agent/issues/211)로 미루며 이번 릴리스에서는 제공하지 않습니다.

`rag-prod`는 공개 권한을 적용하는 독립된 로컬 PROD 모드를 시작합니다. 사이트를 외부에
게시하는 명령은 아닙니다. 개발 환경에서 로컬 모델 연결이 정상이어도 공개
모드에서 로컬 LLM이 허용되는 것은 아닙니다. 의도적으로 모드를 바꾸려면
[CLI 환경 명령](cli.md#dev와-prod-미리보기), 저장 연결은 [설정](settings.md)을 참고하세요.

준비 표시를 초록색으로 만들기 위해 파괴적 초기화를 사용하지 마세요.
새로고침은 상태를 읽으며 복구·적재·인덱스 생성·답변 모델 호출을 실행하지 않습니다.

## 운영 배포 (거의 무료 구성) {#production-deployment}

위 내용은 모두 내 기계에서 돌아갑니다. 공개 사이트는 의도적으로 작게 잡은 별도
대상입니다. Cloudflare Worker 뒤의 Always Free VM 한 대와 Firebase Hosting의 정적
내보내기입니다. 스크립트는 `deploy/gcp/`와 `scripts/deploy/`에 있으며 튜토리얼 과정에서
실행되는 것은 없습니다.

```text
visitor ──HTTPS──> sungyongcho.com/docreview-rag-agent/*
                          │  Cloudflare Worker (gomoku repo)
            ┌─────────────┴──────────────┐
   /docreview-rag-agent/*        /docreview-rag-agent/api/*
            │                              │  plain HTTP
            ▼                              ▼
   Firebase Hosting             GCP e2-micro (us-central1-a, ephemeral IP)
   static Next export           firewall: tcp:8000 from Cloudflare IPv4 only
                                  Caddy :80 → host 8000
                                    allow-list + X-DocReview-Public: true
                                      └─> FastAPI ──> pgvector Postgres
                                  operator: 127.0.0.1:8001 via SSH tunnel only
```

TLS는 Cloudflare에서 끝납니다. VM은 `8000` 포트에서 평문 HTTP만 받고, GCP 방화벽은
Cloudflare가 공개한 IPv4 대역만 허용하므로 다른 곳에서는 직접 닿을 수 없습니다. Caddy는
공개 경로만 프록시하고 `X-DocReview-Public: true`를 붙입니다. `/admin/*`과 `/ingest`를
숨기는 것은 이 헤더이므로 외부에서 닿는 모든 포트 앞에는 Caddy가 있어야 합니다. 운영자
API는 `deploy/gcp/operator_tunnel.sh`로만 닿으며, 이 스크립트는 loopback 전용 포트 `8001`을
전달합니다.

### 실행 순서 {#production-order}

1. `.env`에 `DEPLOY_GCP_PROJECT`(선택으로 `DEPLOY_GCP_ZONE`, `DEPLOY_VM_NAME`,
   `DEPLOY_MACHINE_TYPE`)를 채우고 `deploy/gcp/backend.env.example`을
   `deploy/gcp/backend.env`(gitignore 대상)로 복사합니다. `deploy/gcp/deploy_env_config.sh`가
   두 파일을 읽어 마스킹된 요약을 출력합니다.
2. `deploy/gcp/create_vm.sh`가 `pd-standard` 30 GB 부트 디스크, 임시 외부 IP, `tcp:8000`에
   대한 Cloudflare 전용 방화벽 규칙을 갖춘 e2-micro VM을 만듭니다. 첫 부팅 때
   `deploy/gcp/startup.sh`가 Docker와 2 GB 스왑 파일을 설치합니다.
3. 준비된 코퍼스를 VM의 `/var/lib/docreview/corpus`에 복사한 뒤
   `deploy/gcp/deploy_backend.sh`를 실행합니다. `docker-compose.deploy.yml`,
   `deploy/Caddyfile`, `backend.env`(`/opt/docreview/.env`로)를 복사하고 스택을 띄웁니다.
4. `deploy/gcp/print_origin.sh`가 `DEPLOY_DOCREVIEW_ORIGIN=http://<ip>:8000`과
   `DEPLOY_DOCREVIEW_SITE_ORIGIN=https://<site>.web.app`을 출력합니다.
5. 그 줄들을 gomoku 저장소의 `.env`에 붙여 넣고 그쪽 `03_deploy_cloudflare.sh`를
   실행합니다. Worker가 `/docreview-rag-agent/api/*`는 VM으로, 나머지
   `/docreview-rag-agent/*`는 Firebase Hosting으로 보냅니다.
6. `FIREBASE_PROJECT_ID=<project-id> scripts/deploy/firebase.sh`가
   `NEXT_PUBLIC_ADMIN_MODE`를 비운 채 공개 번들을 빌드하고 배포합니다.

외부 IP는 임시입니다. VM을 멈췄다 켜면 바뀌므로 그 뒤에는 4·5단계를 반복합니다. 고정
IP를 예약하면 이를 피할 수 있지만 월 약 $3가 듭니다.

### 월 비용 {#production-cost}

| 구성 요소 | 내용 | 비용 |
|---|---|---|
| GCP e2-micro | `us-central1`, `us-east1`, `us-west1`에서 Always Free: 공유 vCPU 1개, RAM 1 GB, `pd-standard` 30 GB, 북미 송신 월 1 GB | $0 |
| 외부 IP | 임시 IP. 고정 IP를 예약하면 월 약 $3 | $0 |
| Firebase Hosting | 무료 등급(정적 내보내기) | $0 |
| Cloudflare Worker | 무료 등급, gomoku Worker와 공유 | $0 |
| OpenAI | `DOCREVIEW_PUBLIC_DAILY_COST_USD`(compose 파일에서 `1.00`)로 UTC 하루 단위 상한 | ≤ $1/day |

트레이드오프: VM이 북미에 있어 유럽 방문자는 약 100 ms의 지연이 더 붙습니다.
데이터베이스(현재 약 430 MB)는 Postgres, Docker 이미지, 스왑을 두고도 30 GB 디스크에
넉넉히 들어갑니다. RAM 1 GB에 맞춰 Postgres는 `shared_buffers=128MB`, `work_mem=4MB`로
돌고, 2 GB 스왑 파일이 가끔의 급증을 받아냅니다.
