# DocReview RAG Agent

정책 문서에 대한 **주장(claim)을 검증**하는 RAG 백엔드. 검색된 근거로 주장을 `SUPPORTED / CONTRADICTED / NOT_IN_DOCS / PARTIALLY_SUPPORTED`로 판정하고 **인용을 붙인다.**

핵심은 **가드레일**이다 — 순진한 RAG는 문서에 없는 주장도 자신 있게 지어내지만, 이 시스템은 근거가 없거나 관련 없으면 `NOT_IN_DOCS`로 **모른다고 강제**한다. (평가에서 `NOT_IN_DOCS` 16문항 중 완벽 판정, 아래 참조)

> **정직한 워딩:** 학습·포트폴리오 프로젝트다. 합성/공개 데이터만 쓰고, "production-ready"라고 주장하지 않는다. 설계 판단과 그 근거를 보여주는 데 초점이 있다.

## 하는 것 / 안 하는 것

**하는 것**
- 마크다운 정책 문서 파싱 → 섹션 단위 청킹(안정적 인용 `HR-001 §2.1`)
- **하이브리드 검색**: pgvector 코사인 + Postgres `tsvector` BM25, **RRF**로 결합, cross-encoder 리랭킹
- **claim 검증 워크플로우**(LangGraph): retrieve → 근거 채점(grade) → (부족하면 쿼리 재구성 후 재검색: **Corrective RAG**) → 판정. 프롬프트+코드 **이중 가드레일**
- **비동기 실행**(ARQ 워커): 긴 리뷰를 요청에서 분리, `runs` 테이블이 상태의 source of truth
- **평가 스위트**: 골든셋으로 검색(hit_rate/MRR)·판정(정확도·혼동행렬)·체크리스트 채점 + 회귀 비교
- **관측성**: 트레이스 테이블(모델·프롬프트버전·지연·실제토큰·추정비용·노드경로) + `/traces` 뷰어, 프로바이더 폴백

**안 하는 것**
- 지식그래프(GraphRAG), 멀티모달, 실제 사내 데이터, 인증/멀티테넌시. 웹 검색 폴백(닫힌 코퍼스).

## 아키텍처

```
POST /review ──enqueue──▶ Redis(큐) ──▶ ARQ 워커
     │(즉시 pending)                        │
     ▼                                       ▼  LangGraph
  Postgres(runs: 상태)          retrieve → grade → [reformulate→retrieve] → check
     ▲                                       │        (Corrective RAG 루프)
GET /runs/{id} ─────────── runs/traces ◀─────┘  가드레일: 근거없음→NOT_IN_DOCS /
GET /traces                                        지어낸 인용 제거 / 근거없는 SUPPORTED 강등

검색 레이어(동기): POST /retrieve
  parse → embed(sentence-transformers) → pgvector + BM25 → RRF → cross-encoder rerank
```

- **Redis = 큐**(API→워커 전달), **Postgres = 상태**(runs/traces 영구 기록). 역할 분리.
- **프레임워크 경계 원칙:** 파싱·청킹·임베딩·검색·인용매핑·저장·평가는 전부 **순수 파이썬 직접 구현.** LangGraph는 오케스트레이션 한 곳, LangChain은 LLM 구조화 출력 경계 한 곳에만. 핵심 로직을 프레임워크 뒤에 숨기지 않는다.

## 기술 스택
FastAPI · PostgreSQL 16 + pgvector · Redis + ARQ · LangGraph · LangChain(경계) · sentence-transformers(임베딩) · cross-encoder(리랭킹) · SQLAlchemy 2.0(async) · uv · pytest

## 셋업

```bash
# 1) 인프라
docker compose up -d db redis

# 2) 환경변수 (OpenAI 키 채우기)
cp .env.example .env      # OPENAI_API_KEY=..., EMBEDDING_PROVIDER=st

# 3) 스키마 + 시드 (문서 6개 → 청크 85개, 384차원)
uv run python -m app.db.reset --seed

# 4) 워커 (백그라운드 리뷰 처리)
PRIMARY_LLM_PROVIDER=openai uv run arq app.worker.settings.WorkerSettings

# 5) API
uv run uvicorn app.main:app --reload    # http://localhost:8000/docs (Swagger)
```

## API 예시

```bash
# 검색 (동기, LLM 안 씀 — 인용 달린 하이브리드+리랭크 결과)
curl -s -X POST localhost:8000/retrieve -H 'content-type: application/json' \
  -d '{"query":"how much can a manager approve for expenses","k":5,"rerank":true}' | jq

# 주장 검증 (비동기)
curl -s -X POST localhost:8000/review -H 'content-type: application/json' \
  -d '{"claim":"New hires accrue 18 PTO days per year"}'
# → {"run_id":"...","status":"pending"}
curl -s localhost:8000/runs/<run_id> | jq
# → {"status":"done","node_path":["retrieve","grade","check"],
#    "report":{"label":"SUPPORTED","citations":["HR-001 §2.1"],"rationale":"..."}}

# 관측성
curl -s localhost:8000/traces | jq '.[0]'
# → {"model":"gpt-4.1-mini","latency_ms":4267,"input_tokens":870,"est_cost_usd":0.000519,...}
```
다른 엔드포인트: `GET /documents`, `POST /ingest`, `GET /health`.

## 평가 결과 (전체 [`docs/eval-report.md`](docs/eval-report.md))

| 평가 | 결과 |
| --- | --- |
| 검색 (16문항, hit_rate·MRR) | **hybrid+rerank MRR 1.000** (hybrid 단독 < lexical이었으나 rerank가 교정) |
| 판정 (16주장) | accuracy **0.875**, **`NOT_IN_DOCS` 4/4 (지어내기 0)**, hard-negative 0.833 |
| 체크리스트 (4시나리오) | item **0.917**, overall **1.000** |

- 유일한 오류는 `PARTIALLY_SUPPORTED → CONTRADICTED` 2건 — **오승인이 아니라 엄격한 방향(안전한 실패)**. 상세 [`docs/failure-analysis.md`](docs/failure-analysis.md).

## 테스트

```bash
uv run pytest          # 28개. 결정적 스위트는 무DB·무과금(FakeEmbedder/MockProvider)
```
- DB/LLM 필요한 통합 테스트는 연결 안 되면 자동 skip → CI 기본은 무료로 돈다.
- 지표·가드레일·라우팅 등 **순수 로직은 모두 무LLM 테스트.**

## 설계 판단 (면접 대비)
- **RRF vs 가중합(β):** RRF는 순위 기반이라 스케일 정규화·가중치 튜닝을 없앰 → 재현성·설명력.
- **가드레일 = 프롬프트 + 코드 이중:** LLM이 지시를 어겨도 코드가 강제(근거없음→NOT_IN_DOCS, 지어낸 인용 제거).
- **Corrective RAG:** 검색이 top-k를 찾아도 관련 없으면 grade가 걸러 재검색/NOT_IN_DOCS → 관련성 가드레일.
- **Redis(큐) vs Postgres(상태) 분리**, **결정적(검색·평가) vs LLM 의존(판정) 경계** 명확.
- **평가로 의사결정:** "감"이 아니라 골든 숫자로 fusion·rerank 채택.

## 알려진 한계 / 향후
- 골든셋이 작고(16/16/4) 합성 → 절대 수치보다 "파이프라인 건전성" 신호로 해석.
- `PARTIALLY_SUPPORTED` 경계 모호(프롬프트 보강 여지).
- 캐싱(exact-match), Alembic 마이그레이션, 프로바이더 폴백 실배선(2번째 프로바이더), 배포는 [`docs/plan.md`](docs/plan.md) Phase B.

## 문서
- [`docs/plan.md`](docs/plan.md) — 전체 실행 계획 + 학습 여정 + 의사결정 기록
- [`docs/eval-report.md`](docs/eval-report.md) — 평가 결과
- [`docs/failure-analysis.md`](docs/failure-analysis.md) — 실패 분석
- [`docs/lecture-videos.md`](docs/lecture-videos.md) — 학습 자료 정리
