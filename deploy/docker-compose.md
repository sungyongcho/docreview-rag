# Docker Compose 로컬 운영

루트 `docker-compose.yml`은 PostgreSQL/pgvector `db`와 Next 정적 서비스가 포함된
FastAPI `app`을 제공합니다. DB 통합 테스트만 할 때는 `db`만 시작하고, 브라우저
서비스까지 확인할 때는 두 서비스를 함께 시작합니다.

운영 GCP VM용 설정은 `docker-compose.prod.yml`이며 Caddy, 비공개 PostgreSQL,
persistent host directory와 Docker secrets를 추가합니다.

## DB만 실행

```bash
docker compose up -d db
docker compose ps db
```

빠른 테스트는 DB가 필요 없습니다.

```bash
uv run pytest -m "not live_postgres"
```

실제 PostgreSQL/pgvector 동작을 요구하는 테스트:

```bash
uv run pytest -m live_postgres --require-live-postgres
```

`--require-live-postgres`를 사용하면 연결 실패를 skip하지 않고 실패로 처리합니다.

## 전체 서비스 실행

```bash
docker compose up --build -d
docker compose ps
```

서비스 URL:

```text
http://127.0.0.1:8000/docreview-rag-agent/
```

API와 container 상태:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/release
docker compose logs -f app
```

로컬 Compose의 `app`은 다음 모드로 실행됩니다.

- `DOCREVIEW_MODE=runtime`
- `DOCREVIEW_ADMIN_MODE=live`
- deterministic embedding
- `.env`에 `OPENAI_API_KEY`, 또는 `MODE`에 맞는 `OPENAI_API_KEY_LOCAL`(dev)·
  `OPENAI_API_KEY_PROD`(prod) 슬롯이 있을 때만 LLM review 활성화
- `./data`를 `/app/data`에 bind mount해 corpus와 eval artifact 보존
- loopback live operator는 공개 서비스용 IP rate limit과 일일 비용 상한을 적용하지 않음

## Next 개발 모드

backend container를 실행한 뒤 Next dev server를 별도로 시작합니다.

```bash
docker compose up --build -d app

NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 \
  scripts/run_operator_web.sh
```

Next 개발 URL:

```text
http://127.0.0.1:3000/docreview-rag-agent/
```

로컬 Compose는 root `.env`의 `OPENAI_API_KEY`, `DART_API_KEY`, `SEC_USER_AGENT`와
선택적 `EMBEDDING_PROVIDER`를 app에 전달합니다. `.env`가 있으면 application settings도
같은 이름의 process 환경변수보다 `.env` 값을 우선합니다. public deployment에서는
administrator와 Usage route를 계속 노출하지 않습니다.

app은 non-root UID 10001을 유지하면서 `HOST_GID`를 supplementary group으로 받아
host-owned `./data` bind mount에 씁니다. 기본은 1000이고 host group이 다르면 `.env`에
`HOST_GID=$(id -g)`의 숫자 값을 넣습니다. `data/`, `data/corpus`, `data/eval_runs`는 group
write 가능한 상태여야 합니다.

정적 frontend는 배포 환경에서도 configured API base의 `/health`와 `/ready`를 확인합니다.
API origin이 내려가면 blocking retry/reload dialog를, runtime DB가 degraded면 dismissible
warning을 표시합니다. Canned release의 `not_applicable` corpus는 정상 상태입니다.

Compose는 local Next origin만 administrator CORS에 허용합니다. 공개 정적 build는
Corpus Lab의 실제 실행 API를 호출하지 않습니다.

## 로컬 연결 설정

| 항목 | 기본값 |
|---|---|
| DB 이미지 | `pgvector/pgvector:pg16` |
| 데이터베이스 | `filing` |
| 사용자 | `filing` |
| 비밀번호 | `filing` |
| DB 호스트 포트 | `5432` |
| app 호스트 포트 | `8000` |
| 호스트 연결 URL | `postgresql+asyncpg://filing:filing@127.0.0.1:5432/filing` |

이 자격 증명은 로컬 개발 전용입니다. 운영 Compose는 secret file과 별도 비밀번호를
사용하며 PostgreSQL 포트를 외부에 publish하지 않습니다.

5432 포트가 이미 사용 중이면 DB 포트를 바꿉니다.

```bash
DB_PORT=55432 docker compose up -d db

DATABASE_URL=postgresql+asyncpg://filing:filing@127.0.0.1:55432/filing \
  uv run pytest -m live_postgres --require-live-postgres
```

app 포트 변경:

```bash
APP_PORT=8080 docker compose up --build -d app
```

## 서비스 수명주기

app만 중지하고 DB는 유지:

```bash
docker compose stop app
```

DB를 중지·재시작:

```bash
docker compose stop db
docker compose start db
```

container와 network를 제거하고 `pg_data` volume은 보존:

```bash
docker compose down
```

상태와 로그:

```bash
docker compose ps
docker compose logs db
docker compose logs app
```

## Schema drift

`bootstrap_schema()`은 기존 table에 현재 ORM column이 없으면 fail-closed합니다.
`create_all()`은 없는 table만 만들고 기존 table을 ALTER하지 않기 때문에, 이 검사가
없으면 ingest나 retrieval 중간에 모호한 `UndefinedColumn` 오류가 발생합니다.

Corpus Lab은 drift를 표시하고 모든 쓰기 작업을 차단합니다. 기존 corpus가 재다운로드
가능하더라도 먼저 등록된 additive migration을 plan/apply합니다. migration은 app startup
중 자동 실행되지 않으며 배포 전 명시적 운영 단계로 실행합니다.

```bash
uv run python -m app.db.migrate --plan
uv run python -m app.db.migrate --apply
```

등록 migration으로 해결되지 않고 DB를 재구축하기로 명시적으로 결정한 경우에만 다음
개발 명령을 사용합니다.

> **경고:** 아래 명령은 model table, chunk, embedding, BM25 통계, run/eval 데이터를
> 삭제합니다. 필요한 결과를 먼저 백업하십시오.

```bash
uv run python -m app.ingestion.seed \
  --manifest data/corpus/manifest.json \
  --recreate-schema
```

재구축 후 DART manifest를 추가 ingest하고 embedding을 다시 채워야 합니다.

## 데이터 volume 삭제

다음 명령은 로컬 `pg_data` volume을 삭제합니다. 복구할 수 없으며 일반적인 종료에
사용하지 않습니다.

```bash
docker compose down -v
```

`./data`는 host bind mount이므로 위 명령으로 삭제되지 않습니다.

## GCP 운영 Compose

`docker-compose.prod.yml`은 다음 경계를 추가합니다.

- PostgreSQL은 Docker network 내부에만 노출
- FastAPI는 VM loopback `127.0.0.1:8000`에만 publish
- Caddy만 80/443 공개
- Caddy가 `/admin/*`와 `/ingest` 차단
- corpus, eval artifact, PostgreSQL, Caddy state를 `/var/lib/docreview`에 보존
- app container는 capability 제거와 `no-new-privileges` 적용

설정 예시는 `deploy/gcp/backend.env.example`에 있습니다. 실제 VM 생성과 배포는
비용과 외부 상태를 변경하므로 스크립트를 검토한 후 별도로 실행합니다.

```bash
GCP_PROJECT_ID=<project-id> deploy/gcp/create_vm.sh
GCP_PROJECT_ID=<project-id> deploy/gcp/deploy_backend.sh
```

실관리 접속:

```bash
GCP_PROJECT_ID=<project-id> deploy/gcp/operator_tunnel.sh
scripts/run_operator_web.sh
```
