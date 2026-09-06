# MANUAL — 로컬 실행·기능 테스트

브랜치 `zero` 코드베이스에서 직접 확인한 명령만 적는다. 실행하지 않은 항목은 본문에 `[미검증]`으로 표시했다.
검증 환경: PostgreSQL 컨테이너 `docreview-rag-agent-db-1` 기동 상태, `.venv`는 `dev` 그룹 + `cpu`/`demo` extra가 설치된 상태.

---

## 1. 사전 준비

### 1.1 의존성 동기화

| 목적 | 명령 | 비고 |
|---|---|---|
| 최소(테스트만) | `uv sync --locked --group dev` | `make setup` / `make install`과 동일 |
| 로컬 모델 포함 | `uv sync --locked --group dev --extra cpu` | sbert 임베딩, cross-encoder 리랭커 |
| 데모 포함 | `uv sync --locked --group dev --extra cpu --extra demo` | Gradio UI, 릴리스 앱 |

현재 `.venv`가 마지막 조합과 일치하는지 확인:

```bash
uv sync --locked --group dev --extra cpu --extra demo --dry-run
# → Would make no changes
```

**함정 — `make setup`은 extras를 제거한다.** `uv sync`는 프루닝을 하므로 extra 없이 돌리면 45개 패키지가 빠진다
(`torch`, `sentence-transformers`, `gradio`, `gradio-client` 포함). 확인:

```bash
uv sync --locked --group dev --dry-run | grep -cE "^ - "   # → 45
```

백엔드 extra는 `[tool.uv] conflicts`로 상호 배타다:

```bash
uv sync --locked --extra cpu --extra cu130 --dry-run
# → error: Extras `cpu` and `cu130` are incompatible with the declared conflicts
```

`cu130`(NVIDIA), `rocm`(AMD)은 설치를 시도하지 않았다 `[미검증]`. `cpu`가 pyproject가 명시한 개발·배포 기본값이다.

### 1.2 데이터베이스

```bash
docker compose up -d db
docker compose ps --format "{{.Service}} {{.Status}}"   # → db Up ... (healthy)
docker compose config --quiet                          # 설정 문법 확인
```

`docker-compose.yml`의 `db` 서비스는 `pgvector/pgvector:pg16`, DB/유저/비밀번호 모두 `filing`, 포트는 `${DB_PORT:-5432}`,
볼륨은 `pg_data`. `app` 서비스도 정의돼 있지만(포트 `${APP_PORT:-8000}`) 로컬 개발에서는 `db`만 띄우고 앱은 호스트에서 실행하는 편이 빠르다.

### 1.3 `.env`

`app/config.py`의 `Settings`가 `.env`를 읽는다(`SettingsConfigDict(env_file=".env", extra="ignore")`).

- **필수 없음.** 모든 필드에 기본값이 있고, 기본 `DATABASE_URL`이 로컬 컨테이너를 가리킨다.
- `OPENAI_API_KEY`는 **OpenAI 경로에서만** 필요하다: `--provider openai` 임베딩, 에이전트 `--provider openai`,
  crosslingual `--handling translated`, 릴리스 runtime 모드의 리뷰. 기본 경로(deterministic)는 키 없이 전부 동작한다.
- **`ReleaseSettings`(`DOCREVIEW_*`)는 `.env`를 읽지 않는다.** `app/release/config.py`에 `env_file`이 없다.
  `.env`에 `OPENAI_API_KEY`가 있어도 릴리스 앱은 `openai_enabled: false`로 뜬다(§5.5에서 실측 확인).

### 1.4 Settings 환경변수 (`app/config.py`)

| 환경변수 | 기본값 | 의미 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://filing:filing@localhost:5432/filing` | 비동기 DSN |
| `CORPUS_DIR` | `data/corpus` | 원문 파일 루트 |
| `EMBEDDING_PROVIDER` | `openai` | `openai` \| `deterministic` \| `sbert` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI 임베딩 모델 |
| `SBERT_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | 로컬 임베딩 모델 |
| `EMBED_DIM` | `384` | `Literal[384]` — **다른 값 불가** |
| `EMBEDDING_BATCH_SIZE` | `128` | `0 < n <= 2048` |
| `OPENAI_API_KEY` | `None` | `SecretStr` |
| `LEXICAL_RANKER` | `ts_rank_cd` | `ts_rank_cd` \| `bm25` |
| `QUERY_LANGUAGE_ROUTING` | `false` | 한국어 질의에서 lexical 아크를 건너뛴다 |
| `BM25_K1` / `BM25_B` / `BM25_IDF` | `1.2` / `0.75` / `lucene` | BM25 파라미터 |

`Settings`의 기본 `EMBEDDING_PROVIDER`는 `openai`다. `app/cli.py retrieve`와 `app/retrieval`은 CLI 기본값이
`deterministic`이라 안전하지만, **`app/agent`와 `app/api`의 일부 경로는 `get_embedding_provider()`를 인자 없이
호출해 이 기본값을 그대로 쓴다**(§7.1, §8).

---

## 2. 데이터 준비

### 2.1 코퍼스

`data/corpus/{AMD,INTC,MU,NVDA}/*.html` + `data/corpus/manifest.json`(20개 항목, JSON 배열).
원문 HTML은 `.gitignore` 대상이고 재현 경로는 `python -m app.ingestion.edgar`다(SEC에서 직접 내려받음) `[미검증 — 네트워크 다운로드라 실행하지 않음]`.

파싱 상태 점검(DB 불필요):

```bash
make run                                     # = python -m app.ingestion.parser --coverage
uv run python -m app.ingestion.parser --coverage --ticker NVDA
```

기대 출력: 문서별 `전체 / 섹션 / 커버 %` 한 줄씩. 실측 커버리지는 AMD 98.1~98.5%, INTC 93.9~95.7%, NVDA 96.0~96.5%.
확인 포인트: 커버가 급락한 문서가 있으면 헤딩 인식이 깨진 것이다. 다른 서브커맨드는 `--help`로 확인
(`--blocks --sections --headings --items --profile`).

### 2.2 시드(파싱 → PostgreSQL upsert)

```bash
uv run python -m app.cli ingest --manifest data/corpus/manifest.json --create-schema
# → {"chunks": 9172, "command": "ingest", "documents": 20, "manifest": "...", "status": "ok"}
```

동등한 저수준 진입점(출력 형식만 다름): `uv run python -m app.ingestion.seed --manifest data/corpus/manifest.json --create-schema`.

- 소요 약 40초(20문서 파싱 포함).
- `--create-schema`는 없는 테이블만 만든다. 마이그레이션은 하지 않는다.
- **멱등하며 임베딩을 보존한다.** upsert가 `index_text`가 그대로면 기존 `embedding`을 유지한다
  (`app/ingestion/seed.py`의 `on_conflict_do_update` + `case(...)`). 실측: 재실행 후에도 `9172 | 9172` 유지.

### 2.3 임베딩 백필

백필은 별도 명령이 아니라 두 CLI의 `--embed-missing` 플래그다.

```bash
uv run python -m app.cli retrieve --query "probe" -k 1 --embed-missing           # provider 기본 deterministic
uv run python -m app.retrieval --query "probe" --k 1 --provider sbert --embed-missing
```

기대 출력: 결과 JSON의 `backfill` 필드. 전부 채워져 있으면
`{"batches": 0, "embedded": 0, "selected": 0, "skipped_stale": 0}`.
3개 행을 `NULL`로 만들고 다시 돌린 실측값은 `{"batches": 1, "embedded": 3, "selected": 3, "skipped_stale": 0}`.

| provider | 비용 | 비고 |
|---|---|---|
| `deterministic` | 무료·오프라인 | 토큰 해시 384차원. 기본값이자 현재 DB에 적재된 벡터 |
| `sbert` | 무료·로컬 CPU | 최초 1회 모델 가중치 다운로드. 이 머신에는 캐시 존재(`~/.cache/huggingface`) |
| `openai` | 유료 | 전체 9,172 청크 = `index_text` 7,540,125자 ≈ 190만 토큰. `text-embedding-3-small` 단가 기준 대략 $0.04 (단가는 코드에 없는 외부 공시가 `[미검증]`) |

**provider끼리 벡터 공간이 다르다.** 현재 DB는 deterministic으로 임베딩돼 있다(실측: 1번 청크의 저장 벡터와
deterministic 재계산 벡터의 코사인 = 1.0). provider를 바꾸려면 `embedding` 컬럼을 비우고 전량 재임베딩해야 한다.

```bash
# 전량 재임베딩 준비 (파괴적)
docker exec docreview-rag-agent-db-1 psql -U filing -d filing -c "update chunks set embedding = null;"
```

### 2.4 BM25 통계

`bm25` 랭커는 `chunk_terms` / `lexeme_stats` / `chunk_lengths` 세 테이블을 쓴다.

```bash
uv run python -m app.retrieval --query "probe" --k 1 --provider deterministic \
  --lexical-ranker bm25 --rebuild-bm25-stats
# → "bm25_stats": {"terms": 517893, "chunks": 9172, "lexemes": 9520}
```

원자적 재구축이며 약 5초. 시드 후 청크가 바뀌었으면 한 번 돌린다.

### 2.5 DB 초기화

```bash
docker compose down -v      # pg_data 볼륨 삭제 → 전체 재시드 필요  [미검증 — 파괴적이라 실행하지 않음]
docker compose up -d db
uv run python -m app.cli ingest --manifest data/corpus/manifest.json --create-schema
uv run python -m app.cli retrieve --query "probe" -k 1 --embed-missing
uv run python -m app.retrieval --query "probe" --k 1 --lexical-ranker bm25 --rebuild-bm25-stats
```

현재 상태 확인:

```bash
docker exec docreview-rag-agent-db-1 psql -U filing -d filing \
  -c "select count(*) from documents;" -c "select count(*), count(embedding) from chunks;"
# → 20 documents / 9172 chunks / 9172 embedded
```

---

## 3. 검색 CLI

두 개의 진입점이 있다. `app.cli retrieve`는 API와 동일한 evidence 스키마를 뱉는 얇은 표면이고,
`app.retrieval`은 랭커·리랭커 노브가 전부 열린 실험용이다.

### 3.1 `app.cli retrieve`

```bash
uv run python -m app.cli retrieve --query "revenue concentration risk" -k 3 --ticker NVDA
```

기대 출력(단일 JSON 라인, `sort_keys=True`):

```json
{"status": "ok", "command": "retrieve", "query": "...", "provider": "deterministic",
 "backfill": null, "hits": [...], "component_rankings": {"lexical": [...], "vector": [...]}}
```

실측: `NVDA-FY2021 · Item 7`, `NVDA-FY2020 · Item 7`, `NVDA-FY2022 · Item 7`.

확인 포인트
- `provider`가 `deterministic`인지 (DB 벡터와 같은 공간인지).
- `component_rankings`에 `lexical`과 `vector`가 모두 비어 있지 않은지. 한쪽이 0이면 그 아크가 죽은 것이다.
- 필터는 반복 지정으로 OR: `--doc-id --ticker --fiscal-year --form --item --kind{text,table}`.
- 종료 코드: `0` 성공, `2` 잘못된 인자, `3` 매니페스트 파일 문제, `4` provider/DB 불가(`app/cli.py ExitCode`).

### 3.2 `app.retrieval` (실험용)

```bash
uv run python -m app.retrieval --query "supply chain concentration" --k 3 \
  --provider deterministic --lexical-ranker bm25
uv run python -m app.retrieval --query "inventory write-down" --k 3 \
  --provider deterministic --rerank
uv run python -m app.retrieval --query "inventory write-down" --k 2 --provider sbert
```

전체 옵션: `--provider {openai,deterministic,sbert}`, `--embed-missing`, `--rerank`,
`--lexical-ranker {ts_rank_cd,bm25}`, `--bm25-k1`, `--bm25-b`, `--bm25-idf {lucene,robertson}`,
`--rebuild-bm25-stats`, `--candidate-k`.

확인 포인트
- 출력 상단의 `lexical_ranker` / `bm25_k1` / `bm25_b` / `bm25_idf`가 요청대로 반영됐는지. `ts_rank_cd`면 bm25 필드는 `null`.
- `--rerank`는 로컬 cross-encoder(`cross-encoder/ms-marco-MiniLM-L-6-v2`)를 쓴다. 무료·오프라인이지만
  `cpu` extra와 캐시된 가중치가 필요하고, stderr에 `Loading weights` 진행바가 찍힌다(`HF_HUB_OFFLINE=1`로도 동작 확인).
- `--provider sbert`로 조회하면 명령은 성공하지만 DB 벡터가 deterministic이라 vector 아크 결과는 무의미하다.

---

## 4. API 서버

### 4.1 실행

```bash
uv run python -m app.cli serve --port 8011 --log-level warning     # 기본 host 127.0.0.1, port 8000
# 동등: uv run uvicorn app.main:app --host 127.0.0.1 --port 8011
```

`app.main:app`은 `RuntimeApiServices()`를 인자 없이 조립한다 → 임베딩은 `DeterministicEmbeddingProvider`,
**LLM provider는 주입되지 않아 리뷰가 fail-closed**다.

### 4.2 라우트 (`/openapi.json` 실측)

| 메서드 | 경로 | 실측 결과 |
|---|---|---|
| GET | `/health` | `{"status":"ok"}` |
| GET | `/documents` | 20개 filing 리소스 |
| POST | `/retrieve` | 순위화된 evidence |
| POST | `/ingest` | 로컬 매니페스트 시드 |
| POST | `/review` | 503 `provider_unavailable` (기본 구성) |
| POST | `/review/stream` | SSE (§4.4) |
| GET | `/runs/{run_id}` | 404 `run_not_found` |
| GET | `/runs/{run_id}/traces` | 저장된 provider trace |
| GET | `/eval` | 저장된 평가 결과 (`?limit=1..100`, 기본 20) |

### 4.3 curl 예시

```bash
curl -s http://127.0.0.1:8011/health
curl -s http://127.0.0.1:8011/documents

curl -s -X POST http://127.0.0.1:8011/retrieve \
  -H 'content-type: application/json' \
  -d '{"query":"gross margin decline","k":2,"filters":{"tickers":["INTC"]}}'

curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8011/review \
  -H 'content-type: application/json' -d '{"query":"gross margin decline","k":2}'
# → HTTP 503
# {"error":{"code":"provider_unavailable","message":"Review requires an explicitly configured LLM provider and budget.","details":[]}}

curl -s "http://127.0.0.1:8011/eval?limit=2"
curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8011/runs/does-not-exist
# → HTTP 404 {"error":{"code":"run_not_found",...}}
```

`filters` 키(`app/retrieval/types.py`): `doc_ids`, `tickers`, `fiscal_years`, `forms`, `items`, `kinds`.
`ReviewRequest`는 추가로 `budget`(`max_iterations` 6 / `max_input_tokens` 60000 / `max_output_tokens` 4000 /
`max_wall_clock_s` 120.0)과 `max_context_chars`(12000)를 받는다.

**리뷰를 실제로 돌리려면** `app.main:app`이 아니라 릴리스 앱 runtime 모드를 써야 한다(§5). `app.main`에는
provider를 주입하는 환경변수 스위치가 없다 — 코드 주입(`create_app(services)`)만 가능하다.

### 4.4 SSE 스트리밍

```bash
curl -sN -X POST http://127.0.0.1:8011/review/stream \
  -H 'content-type: application/json' -H 'accept: text/event-stream' \
  -d '{"query":"gross margin decline","k":2}'
```

기대 출력(기본 구성, provider 없음):

```
event: error
data: {"error":{"code":"provider_unavailable","message":"Review requires an explicitly configured LLM provider and budget.","details":[]}}

event: done
data: {}
```

응답 헤더 실측: `content-type: text/event-stream; charset=utf-8`, `cache-control: no-store`,
`x-accel-buffering: no`, `Transfer-Encoding: chunked`.

확인 포인트
- 실패해도 HTTP 상태는 200이고, 오류는 `event: error`로 실려 온다. 마지막은 반드시 `event: done`.
- provider가 주입된 구성에서는 `event: node`가 노드별로 먼저 흐르고
  (`node`, `evidence_count`, `relevant_count`, `step_count`), 그다음 `event: report`가 온다
  `[미검증 — 유료 호출이라 실행하지 않음]`.
- `-N`(버퍼링 해제) 없이 curl하면 스트림이 한꺼번에 보이는 것처럼 착시가 생긴다.

---

## 5. Gradio 데모와 릴리스 앱

### 5.1 M6 데모 단독 실행

```bash
uv run python -m app.demo      # http://127.0.0.1:7860, share=False
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7860/    # → 200
```

`demo` extra가 없으면 `RuntimeError: Install the optional 'demo' dependency to launch the Gradio UI.`
서비스 주입 없이 띄우면 `CannedDemoService`(모드 라디오: `canned` 하나)로, 고정 픽스처만 답한다.
예시 질문은 `HERO_EXAMPLES` 두 개(`"What revenue did Acme report in fiscal year 2024?"`,
`"What does the filing say about an acquisition?"`)이고 그 밖의 질문은 일반화하지 않는다.

### 5.2 M7 릴리스 앱 — canned 모드(기본)

```bash
uv run uvicorn app.release.space:app --host 127.0.0.1 --port 7861 --log-level warning
```

```bash
curl -s http://127.0.0.1:7861/health
# → {"status":"ok","mode":"canned"}
curl -s http://127.0.0.1:7861/release
# → {"mode":"canned","openai_enabled":false,"key_handling":"server_environment_only","key_persisted":false,
#    "rate_limit_scope":"single_process","rate_limit_per_minute":10,"rate_limit_per_day":100,
#    "max_input_tokens":12000,"max_output_tokens":600,"max_cost_usd":"0.01"}
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7861/          # Gradio 랜딩 → 200
```

canned 모드에서는 services가 주입되지 않으므로 `/retrieve` 같은 API 리소스는 **503 `service_unavailable`**이 정상이다.
UI는 canned 픽스처로 동작한다.

### 5.3 rate limit 확인

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -D - -X POST http://127.0.0.1:7861/retrieve \
    -H 'content-type: application/json' -d '{"query":"test","k":1}' \
  | grep -iE "^(HTTP/1.1|x-ratelimit-remaining-minute|retry-after)"
done
```

실측: 1~10번째는 `X-RateLimit-Remaining-Minute`가 9→0으로 감소, 11번째부터 `HTTP/1.1 429` + `retry-after: 60`.
GET은 미터링되지 않는다(상태 변경 메서드만 소비).

```bash
curl -s -w " HTTP %{http_code}\n" -X POST http://127.0.0.1:7861/ingest \
  -H 'content-type: application/json' -d '{"manifest_path":"data/corpus/manifest.json"}'
# → HTTP 403 {"error":{"code":"release_read_only",...}}
```

### 5.4 runtime 모드

```bash
DOCREVIEW_MODE=runtime uv run uvicorn app.release.space:app --host 127.0.0.1 --port 7862 --log-level warning
```

키 없이 띄운 실측:

```bash
curl -s http://127.0.0.1:7862/release      # → "mode":"runtime","openai_enabled":false
curl -s -X POST http://127.0.0.1:7862/retrieve -H 'content-type: application/json' \
  -d '{"query":"gross margin","k":1}'      # → 실제 DB 검색 결과 (deterministic 임베딩)
curl -s -X POST http://127.0.0.1:7862/review -H 'content-type: application/json' \
  -d '{"query":"gross margin","k":1}'      # → HTTP 503 provider_unavailable
```

즉 runtime 모드는 **검색은 살아나고 리뷰는 여전히 fail-closed**다. 리뷰를 켜려면 프로세스 환경에 키가 있어야 한다:

```bash
DOCREVIEW_MODE=runtime DOCREVIEW_OPENAI_API_KEY=sk-... \
  uv run uvicorn app.release.space:app --host 127.0.0.1 --port 7863
curl -s http://127.0.0.1:7863/release      # → "openai_enabled":true
```

더미 키로 `openai_enabled: true`까지 확인했다. 실제 리뷰 호출은 유료라 실행하지 않았다 `[미검증]`.

### 5.5 `DOCREVIEW_*` 환경변수 (`app/release/config.py`)

| 변수 | 기본값 |
|---|---|
| `DOCREVIEW_MODE` | `canned` (`canned` \| `runtime`) |
| `DOCREVIEW_HOST` / `DOCREVIEW_PORT` | `0.0.0.0` / `7860` |
| `DOCREVIEW_RATE_LIMIT_PER_MINUTE` | `10` |
| `DOCREVIEW_RATE_LIMIT_PER_DAY` | `100` (per_minute 이상이어야 함) |
| `DOCREVIEW_RATE_LIMIT_MAX_CLIENTS` | `1024` |
| `DOCREVIEW_TRUST_PROXY_HEADERS` | `false` |
| `DOCREVIEW_ALLOW_INGEST` | `false` |
| `DOCREVIEW_OPENAI_API_KEY` | `None` (별칭으로 `OPENAI_API_KEY`도 인정) |
| `DOCREVIEW_OPENAI_MODEL` | `gpt-4.1-mini` |
| `DOCREVIEW_OPENAI_MAX_INPUT_TOKENS` / `_OUTPUT_` | `12000` / `600` |
| `DOCREVIEW_OPENAI_MAX_COST_USD` | `0.01` |
| `DOCREVIEW_OPENAI_INPUT_PER_MILLION_USD` / `_OUTPUT_` | `0.40` / `1.60` |

`deploy/huggingface/space.env.example`에 배포용 예시가 있다. `ReleaseSettings`는 `.env`를 읽지 않으므로
로컬에서도 **프로세스 환경변수로만** 전달된다.

---

## 6. 평가 하네스

### 6.1 M3 — retrieval ablation

```bash
uv run python -m app.evals.retrieval_eval --help
uv run python -m app.evals.retrieval_eval \
  --target-text-chars 1200 --strategies lexical --lexical-rankers ts_rank_cd --budget-queries 2
```

실측 소요 39초(최소 매트릭스). 기본값은 `--target-text-chars 500 1200`,
`--strategies lexical vector hybrid`, `--lexical-rankers ts_rank_cd bm25`, `-k 5`, `--candidate-k 20`이라
전체 매트릭스는 훨씬 오래 걸린다.

기대 출력: Markdown 비교표 + JSON.

```
| Config | Chunk target | Retrieval | Lexical ranker | Recall@k | Hit rate@k | MRR | P95 ms | Raw |
| structure-1200-lexical-ts-rank-cd | 1200 | lexical | ts_rank_cd | 0.270833 | 0.291667 | 0.171528 | 180.781 | ... |
```

확인 포인트
- 아티팩트는 `data/eval_runs/<UTC timestamp>-<arm>.json` + `<timestamp>-budgets.json`. 이 디렉터리는 `.gitignore` 대상이다.
- `indexing.arms[].passed`가 `true`인지(인덱싱 예산 300초). 실측 `derived_standalone_seconds` 34.4초.
- 골든셋은 `data/golden/retrieval.json`(`--golden`으로 교체).
- 이 하네스는 **세션 스코프 TEMPORARY 테이블**에 별도 코퍼스를 심는다. 실사용 `chunks` 테이블은 건드리지 않는다
  (실행 후 `9172 | 9172` 유지 확인).
- `--persist-results`를 주면 `eval_results` 테이블에 기록되고 API `/eval`로 조회된다.
  회귀 비교는 `app/evals/regression.py`의 `latest_comparable_baseline` — 같은 suite의 최신 행을 baseline으로 삼아
  higher-is-better 메트릭을 비교한다.

### 6.2 M8 — cross-lingual 매트릭스

```bash
uv run python -m app.evals.crosslingual --help
uv run python -m app.evals.crosslingual --provider deterministic --strategies lexical --languages en ko -k 5
```

기대 출력: 아크 비교표 → 카테고리별 표 → EN/KO parity 표 → 진단 JSON.

실측(deterministic·lexical·direct):

```
| xling-deterministic-lexical-ts-rank-cd-en | lexical | direct | en | 24 | 0.270833 | 0.291667 | 0.171528 |
| xling-deterministic-lexical-ts-rank-cd-ko | lexical | direct | ko | 24 | 0.000000 | 0.000000 | 0.000000 |
...
FAIL — m8-crosslingual-v1, k=5, 24 scored cases, recall_at_k floor 0.85.
```

진단 JSON 필드: `twin_alignment`(EN/KO 쌍의 코사인 — deterministic에서 mean 0.103),
`lexical_coverage`(KO는 28건 중 4건이 zero-candidate, 비율 0.143), `indexing`, `translations`, `artifacts`, `gate`.

확인 포인트
- 골든셋 두 개: `data/golden/retrieval.json`(EN, `--golden`), `data/golden/retrieval_ko.json`(KO, `--ko-golden`).
- `--gate`를 주면 shipping 아크가 parity 하한(`--min-recall-ratio`, 기본 0.85)에 미달할 때 **exit 1**.
  게이트 대상은 `strategy == "hybrid"`이면서 `handling != "direct"`인 아크뿐이다(`gated_assessments`).
  즉 위 lexical/direct 실행의 `FAIL` 문구는 게이트를 켜지 않으면 종료 코드에 영향을 주지 않는다.
- provider 선택지: `deterministic`, `openai`(유료), `sbert`, `sbert-multi`.
  `sbert-multi`는 새 provider가 아니라 `sbert`를 `paraphrase-multilingual-MiniLM-L12-v2`로 겨눈 것이다(역시 384차원).
- `--handling translated`는 `--translator-model`(기본 `gpt-4.1-mini`)로 OpenAI를 호출한다 — 유료.
- 아티팩트는 `data/eval_runs/<timestamp>-xling-<arm>-<lang>.json`.

---

## 7. 에이전트 (M9)

### 7.1 CLI

```bash
uv run python -m app.agent --help
EMBEDDING_PROVIDER=deterministic uv run python -m app.agent \
  --question "How did NVDA describe supply concentration in FY2023?" --k 3
```

옵션: `--question`, `--k`(기본 5), `--provider {deterministic,openai}`, `--model`(기본 `gpt-5-mini`),
`--max-iterations`(기본 8), `--mcp`.

기대 출력(deterministic): 2턴 스크립트 — 1턴에서 `search_filings`를 실제로 호출하고, 2턴에서 `NOT_IN_DOCS`로 정직하게 종료.

```json
{"status": "ok",
 "answer": {"label": "NOT_IN_DOCS", "answer": "NOT_IN_DOCS", "citations": [], "rationale": "The offline demo provider cannot ground an answer; ..."},
 "iterations": 2, "total_input_tokens": 0, "total_output_tokens": 0, "steps": [...]}
```

**함정.** `--provider deterministic`은 LLM만 오프라인이다. 툴 안의 검색은
`get_embedding_provider()`를 인자 없이 호출하므로 `EMBEDDING_PROVIDER` 기본값(`openai`)을 그대로 쓴다.
앞에 `EMBEDDING_PROVIDER=deterministic`을 붙이지 않으면 (a) 질의 임베딩이 유료로 호출되고
(b) DB 벡터(deterministic)와 공간이 달라 검색 품질이 무너진다. 실측: 변수 없이 돌렸을 때 NVDA 질문에
AMD/INTC 청크가 RRF 하한 점수(0.0164)로 올라왔다.

`--provider openai`는 실제 tool-calling 루프를 돌린다 — 유료 `[미검증]`.

### 7.2 MCP 서버

```bash
EMBEDDING_PROVIDER=deterministic uv run python -m app.agent --mcp     # stdio 트랜스포트
```

stdio 서버라 단독 실행 후 붙는 게 아니라 클라이언트가 프로세스를 띄운다. 검증에 쓴 최소 클라이언트:

```python
import asyncio, json, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main() -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "app.agent", "--mcp"],
        env={**os.environ, "EMBEDDING_PROVIDER": "deterministic"},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print("tools:", [t.name for t in tools.tools])
        result = await session.call_tool("search_filings", {
            "query": "inventory write-down", "k": 2,
            "tickers": ["MU"], "fiscal_years": None, "forms": None,
        })
        print(result.is_error, json.loads(result.content[0].text)["hits"][0]["citation"])

asyncio.run(main())
```

실측 출력: `tools: ['compare_years', 'fetch_chunk', 'search_filings']`, `False MU FY2021 · Item 7`.

확인 포인트
- 스키마가 **strict**다. `tickers` / `fiscal_years` / `forms`를 생략하면 `is_error: True`와
  `3 validation errors for SearchFilingsParams ... Field required`가 돌아온다. 값이 없으면 `null`을 명시해야 한다.
- 툴 실패는 예외로 새지 않고 `is_error: True` + 텍스트로 온다(프로토콜 레벨 에러가 아님).
- 외부 MCP 클라이언트(Claude Desktop 등) 등록은 시도하지 않았다 `[미검증]`.

---

## 8. 테스트 스위트 지도

`make test`는 `pyproject.toml`의 `testpaths`만 돈다 — `tests/test_doc_format.py` + `tests/ingestion/test_01`~`test_08`
(`test_09_tables.py`는 빠져 있다). 실측 **312 passed / 46초**. 나머지 하네스는 경로를 명시해서 돌린다.

| 명령 | 수집 개수 | 실측 | 외부 의존 |
|---|---:|---|---|
| `uv run pytest` (`make test`) | 312 | 46s pass | 코퍼스 파일(DB 불필요) |
| `uv run pytest tests/ingestion` | 341 | 57s pass | `data/corpus` 필요 — 없으면 skip |
| `uv run pytest tests/chunk` | 32 | 38s pass | 코퍼스 파싱 |
| `uv run pytest tests/db` | 35 | 20s pass | **PostgreSQL** |
| `uv run pytest tests/retrieval` | 173 | 1.4s pass | 일부 PG (loopback DSN 아니면 skip) |
| `uv run pytest tests/evals` | 131 | 1.5s pass | 대부분 오프라인 |
| `uv run pytest tests/crosslingual` | 69 | 1.1s pass | 오프라인 |
| `uv run pytest tests/api` | 56 | 3.7s pass | 오프라인(서비스 주입) |
| `uv run pytest tests/workflow` | 82 | 0.8s, 81 pass 1 skip | 오프라인 |
| `uv run pytest tests/agent` | 42 | 2.7s pass | 오프라인 |
| `uv run pytest tests/release` | 21 | 3.1s pass | 오프라인 |
| `uv run pytest tests/demo` | 17 | 3.0s pass | `demo` extra |
| `uv run pytest tests/` | 1003 | — | 위 전부 |

- PG를 실제로 붙는 파일: `tests/db/test_03_upserts.py`, `tests/db/test_05_postgres.py`,
  `tests/retrieval/test_02_embeddings.py`, `test_03_vector.py`, `test_04_lexical.py`, `test_08_postgres.py`,
  `test_09_bm25.py`, `tests/evals/test_03_regression.py`, `test_06_postgres.py`. 나머지는 오프라인이다.
  `DATABASE_URL`의 호스트가 loopback(`localhost`/`127.0.0.1`/`::1`)이 아니면 해당 테스트는 skip된다
  (`tests/retrieval/conftest.py`의 `postgres_test_database_url`).
- `make debug`는 M1 8개 파일을 `-vv --tb=long`으로 돌린다. 실측 308 passed / 45초.
- `make next`는 다음 마일스톤과 그 검증 명령을 출력한다. 실측: `next milestone: M9.6`,
  `$ uv run pytest tests/agent/test_07_mcp_cli.py -q`.
- pytest-xdist는 의도적으로 빠져 있다(세션 픽스처가 워커마다 재파싱된다).

---

## 9. 품질 게이트

| 명령 | 내용 | 실측 |
|---|---|---|
| `make lint` | `ruff check --no-fix` + `ruff format --check` (app tests scripts) | All checks passed / 191 files already formatted |
| `make typecheck` | `uv run --with basedpyright basedpyright app tests scripts` | 0 errors, 0 warnings, 0 notes |
| `make docs` | `pytest tests/test_doc_format.py` | 4 passed |
| `make test` | 위 §8 | 312 passed |
| `make quality` | lint → typecheck → docs → test → `git diff --check` | 개별 단계 전부 확인 |
| `make clean` | `__pycache__`, `.pytest_cache`, `.ruff_cache` 제거 | Makefile 정의만 확인 `[미실행]` |

`scripts/format_docs.py`는 Markdown 문단을 한 줄로 리플로우한다(`--check`로 검사만).

`scripts/verify_clean_checkout.sh`는 **브랜치 `zero`에서 그대로 돌지 않는다** `[미검증 — 부재 파일 확인만]`.
`scripts/check_doc_code.py`, `scripts/check_doc_parity.py`, `tests/test_doc_sync.py`, `tests/test_doc_parity.py`를
호출하는데 이 브랜치에는 없다.

---

## 10. 비용 주의

| 명령 / 경로 | OpenAI 호출 | 대략 비용 |
|---|---|---|
| `app.cli retrieve` (기본) | 없음 | $0 |
| `app.retrieval --provider deterministic` / `sbert` / `--rerank` | 없음 | $0 |
| `app.retrieval --provider openai` | 질의 임베딩 1건 | 무시할 수준 |
| `--embed-missing` + `EMBEDDING_PROVIDER=openai` (전량) | 임베딩 ~190만 토큰 | 약 $0.04 `[단가 미검증]` |
| `app.main:app` `/retrieve`, `/documents`, `/eval` | 없음 | $0 |
| `app.main:app` `/review`, `/review/stream` | 없음(항상 503) | $0 |
| 릴리스 canned 모드 | 없음 | $0 |
| 릴리스 runtime + 키 → `/review` | LLM 호출 | 요청당 상한 `DOCREVIEW_OPENAI_MAX_COST_USD` = $0.01 |
| `app.agent --provider deterministic` **without** `EMBEDDING_PROVIDER` | 질의 임베딩 | 무시할 수준이지만 의도치 않은 호출 |
| `app.agent --provider openai` | tool-calling 루프 전체 | 반복 수 × 토큰 |
| `app.evals.*  --provider openai` | 전체 코퍼스 임베딩 | 아크마다 재임베딩 — 비쌈 |
| `app.evals.crosslingual --handling translated` | 질의 번역 | 케이스 수 × 짧은 호출 |

코드에 핀으로 박힌 단가는 `app/observability/cost.py`의 `gpt-4.1-mini` = 입력 $0.40 / 출력 $1.60 per 1M뿐이다.
임베딩 단가는 코드에 없다.

---

## 11. 트러블슈팅

**DB가 안 떠 있으면 CLI가 traceback으로 죽는다.** 타입 있는 `database_unavailable` JSON이 아니라
`ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 5433)` 전체 스택이 나오고 **exit 1**이다.
`app/cli.py`는 `SQLAlchemyError`만 감싸는데 asyncpg의 연결 거부는 그대로 올라온다. 먼저 `docker compose up -d db`.

**임베딩 차원은 384로 고정이다.** `EMBED_DIM`은 `Literal[384]`고 `chunks.embedding`도 `vector(384)`다.
OpenAI(`dimensions=384`), sbert MiniLM, deterministic 모두 384로 맞춰져 있다. 값을 바꾸면 Settings 검증에서 막힌다.

**설정 오류는 시작 시점에 pydantic으로 터진다.**

```
EMBEDDING_BATCH_SIZE=0 → ValidationError: embedding_batch_size Input should be greater than 0
```

`BM25_B`는 0~1, `DOCREVIEW_RATE_LIMIT_PER_DAY < PER_MINUTE`는 `ReleaseSettings` 검증에서 거부된다.

**provider 불일치는 에러가 아니라 침묵하는 품질 저하다.** 저장 벡터와 질의 벡터의 provider가 다르면 예외 없이
무의미한 이웃이 나온다. 증상: vector 아크 점수가 전부 RRF 바닥값(0.016 근처)이고 티커 필터를 안 걸면 엉뚱한 회사가 올라온다.
현재 DB는 deterministic이다.

**`demo`/`cpu` extra가 없으면.** Gradio 진입점은 `RuntimeError: Install the optional 'demo' dependency to launch the Gradio UI.`
sbert 진입점은 `tests/retrieval/test_10_sbert.py`가 커버하는 actionable RuntimeError를 던진다
`[미검증 — 이 환경에는 extra가 설치돼 있어 재현하지 못함]`.

**한국어 질의는 lexical 아크가 비어 나온다.** 인덱스가 `to_tsvector('english', ...)`로 생성돼 있다.
실측: `--query "재고 평가손실"` → `component_rankings` = `{'lexical': 0, 'vector': 20}`.
`QUERY_LANGUAGE_ROUTING=true`를 켜도 CLI 출력상의 개수는 동일했다(라우팅은 lexical 아크를 *시도하지 않게* 만들 뿐).

**릴리스 앱이 키를 못 읽는다면** `.env`에 넣었기 때문이다. `ReleaseSettings`는 `.env`를 읽지 않는다.
프로세스 환경변수로 `DOCREVIEW_OPENAI_API_KEY`(또는 `OPENAI_API_KEY`)를 주입해야 `/release`의 `openai_enabled`가 `true`가 된다.

**canned 모드에서 API가 503인 건 정상이다.** services를 주입하지 않으므로 `/retrieve`도 503 `service_unavailable`이다.
검색까지 쓰려면 `DOCREVIEW_MODE=runtime`.

**`make setup`을 돌리면 데모/로컬 모델이 사라진다.** §1.1의 프루닝 함정. 항상 쓰던 extra를 함께 지정한다.

**평가 하네스가 실사용 코퍼스를 망가뜨리지 않는지 걱정된다면** — 걱정할 필요 없다.
`temporary_corpus_session`이 커넥션 스코프 TEMPORARY 테이블을 쓰고 컨텍스트 종료 시 폐기된다.
실행 전후 `chunks`는 `9172 | 9172`로 동일했다.
