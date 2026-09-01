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
- 최근 대화·인용 카드·5단계 온보딩을 갖춘 Next.js 서비스
- corpus 상태, 골든셋, 실험 비교, API Inspector를 갖춘 Corpus Lab
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
| `web/` | Next.js App Router 서비스, Corpus Lab, localStorage 대화 |
| `data/` | corpus manifest, golden suite, profiles, evaluation artifacts |

## 요구사항

- [uv](https://docs.astral.sh/uv/)
- Docker Engine과 Docker Compose
- Node.js 24+와 npm 11+ — Next 개발·테스트 시
- 선택: `OPENAI_API_KEY` — 실제 LLM 리뷰
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
OPENAI_API_KEY=<your-openai-key>
```

키는 사용하는 기능에만 필요합니다. 기본 deterministic embedding과 retrieval 테스트는
OpenAI 키 없이 실행됩니다.

로컬 실행에서는 checkout의 `.env`가 process 환경변수보다 우선합니다. OpenAI embedding
backfill까지 사용하려면 다음 선택을 함께 둡니다.

```dotenv
EMBEDDING_PROVIDER=openai
```

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
docker compose up -d db
docker compose ps db
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
docker compose up --build -d
```

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:8000/docreview-rag-agent/
```

상태와 로그는 다음과 같이 확인합니다.

```bash
curl -s http://127.0.0.1:8000/health
docker compose logs -f app
```

서비스만 중지하고 PostgreSQL은 유지하려면:

```bash
docker compose stop app
```

## Next.js 개발 모드

FastAPI와 PostgreSQL은 Docker로 실행하고 Next dev server만 호스트에서 띄웁니다.

```bash
docker compose up --build -d app

NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 \
  scripts/run_operator_web.sh
```

개발 화면:

```text
http://127.0.0.1:3000/docreview-rag-agent/
```

operator 모드는 실제 `/admin/*` API를 사용합니다. 공개 Firebase build는 같은 화면을
보여주지만 Corpus Lab 실행 버튼은 비활성화되고 저장된 측정 결과만 표시합니다.

### 로컬 Operations

현재 checkout의 검사와 로컬 Docker 서비스를 웹에서 제어하려면 host 전용 console을
실행합니다. 이 스크립트는 임시 인증 token, `127.0.0.1:18001` Operations API, Next dev
server를 함께 띄웁니다. app container를 중지해도 `http://127.0.0.1:3000` 화면은 남습니다.

```bash
scripts/run_local_operator_web.sh
```

3000번이 사용 중이면 다른 고정 포트를 양쪽 service에 함께 전달합니다.

```bash
DOCREVIEW_OPERATOR_WEB_PORT=3010 scripts/run_local_operator_web.sh
```

Operations는 registry에 고정된 argv만 `shell=False`로 실행합니다. public build와 원격
SSH tunnel UI에는 command URL이나 token이 없으므로 화면 자체가 나타나지 않습니다.
corpus 수집·ingest·embedding·BM25 작업은 기존 Corpus Lab에 남고, DB reset·volume 삭제·
deploy·Git stage/commit은 웹 명령으로 제공하지 않습니다.

local Compose는 `.env`의 `OPENAI_API_KEY`, `DART_API_KEY`, `SEC_USER_AGENT`, 선택적
`EMBEDDING_PROVIDER`를 app container에 전달합니다. 코드나 frontend가 바뀐 뒤에는
Operations의 **Build and start app** 또는 다음 명령으로 image를 다시 만듭니다.

Linux bind mount 쓰기는 host data group으로 맞춥니다. 기본 GID는 1000이며 다른 환경은
`.env`에 `HOST_GID=<id -g 결과>`를 설정합니다. host-owned `data/`는 group write 권한을
유지해야 Corpus Lab의 artifact·manifest 작업이 동작합니다.

```bash
docker compose up --build -d app
```

배포본은 현재 `canned/read-only` 정책을 유지합니다. `/admin/*`, Usage, local Operations는
노출하지 않습니다. 배포 환경에서 live 관리 기능을 열려면 인증·감사 log·원격 job 취소·
비용 상한을 별도 설계한 뒤에만 확장합니다.

서비스 UI는 시작·30초 주기·탭/네트워크 복귀 때 `/health`와 `/ready`를 확인합니다. API가
응답하지 않으면 retry/reload 전까지 blocking dialog를 표시하고, DB·schema·corpus가
degraded면 닫을 수 있는 경고와 System status 이동을 제공합니다. 긴 대화는 workspace
우측 scrollbar로 메시지만 스크롤되며 sidebar·topbar·composer는 고정됩니다.

튜토리얼은 New review, composer, evidence, recent reviews, Corpus Lab, System status,
local Operations, Documentation의 실제 control을 spotlight합니다. 강조된 control을 직접
클릭해 동작시키거나 Next로 진행할 수 있고 reduced-motion 환경에서는 pointer animation을
멈춥니다.

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
| `db-start` | `docker compose up -d db` | Start the local pgvector service and retain its existing volume. | required |
| `db-stop` | `docker compose stop db` | Stop the local database without deleting its volume. | required |
| `app-start` | `docker compose up --build -d app` | Build the local image and start the app with its database dependency. | required |
| `app-stop` | `docker compose stop app` | Stop the local app container while leaving PostgreSQL unchanged. | required |
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
Corpus Lab의
`Overview`에서는 누락 문서 수집, manifest ingest, embedding backfill, BM25 통계
재구축을 background job으로 실행할 수 있습니다.

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

## Corpus Lab과 골든 평가

Corpus Lab은 다음 영역으로 구성됩니다.

- `Overview`: DB/schema/index 상태와 안전한 corpus 작업
- `Documents`: registry·issuer·연도·언어·chunk 상태
- `Golden Tests`: SEC/DART × EN/KO suite와 retrieval profile
- `Experiments`: baseline 대비 metric·case 변화
- `Jobs`: quick/matrix background job
- `API Inspector`: strict JSON 요청과 typed 응답
- `Usage`: local run/trace에 기록된 모델별 token과 예상 비용 (`live` operator 전용)

조절 가능한 retrieval profile:

- strategy: vector, lexical, hybrid
- `k`, `candidate_k`, `rrf_k`
- `ts_rank_cd` 또는 BM25와 `k1`, `b`, IDF
- query language routing
- 선택적 cross-encoder reranking

빠른 실행은 현재 DB index를 사용합니다. matrix 실행은 격리 PostgreSQL corpus에서
chunk 크기·strategy·ranker 조합을 비교하고 운영 corpus를 변경하지 않습니다.

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
docker compose up -d db
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

로컬 Compose는 `db`와 `app` 두 서비스를 제공합니다. DB만 실행하거나 전체 서비스를
실행할 수 있습니다.

```bash
docker compose up -d db
docker compose up --build -d
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
| `database_unavailable` | `docker compose ps db`, `DB_PORT`, `DATABASE_URL` |
| `schema drift` | `app.db.migrate --plan` 후 등록 migration 적용. 남으면 아래 rebuild 경고 참고 |
| `/review` 503 | `REVIEW_MODEL`, `OPENAI_API_KEY`, `/ready`의 model policy 상태 |
| 공개 review 429 | IP rate limit 또는 UTC daily cost limit |
| 검색 결과 없음 | ingest 여부와 최초 `--embed-missing` 실행 |
| BM25 stale | ingest 또는 BM25 stats rebuild 실행 |
| `sbert`/reranker import 오류 | `uv sync --extra cpu` |
| Next 클릭이 동작하지 않음 | 개발 URL과 `allowedDevOrigins`, browser console |

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
| Review UX | verified | SSE progress/cancel, safe GFM, right-edge scroll, runtime modal, target-click tour | Vitest and local browser health/tour QA |
| Corpus Lab | verified | public read-only, local live operator, usage, golden evaluation jobs | component/API tests and successful local quick evaluation |
| Local Operations | verified | authenticated fixed command registry, logs, cancel, service confirmation | operator API tests and browser Git-status run |
| Release UI | verified | test, typecheck, isolated static build, fixed shell chrome | static build and local browser QA |
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
