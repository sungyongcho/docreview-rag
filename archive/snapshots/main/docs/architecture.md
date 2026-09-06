# Architecture

DocReview RAG Agent의 컴포넌트·데이터 흐름·설계 경계.

## 1. 개요

두 개의 진입 경로가 있다:
- **검색(동기)** — `POST /retrieve`: 요청 스레드 안에서 하이브리드 검색 + 리랭크. LLM 없음.
- **리뷰(비동기)** — `POST /review`: 잡을 큐에 넣고 즉시 반환, 워커가 LangGraph 워크플로우로 판정. LLM 사용.

**Redis = 큐(전달)**, **Postgres = 상태·저장(runs/traces/chunks)**. 역할 분리가 핵심.

## 2. 컴포넌트 (레이어)

```
app/
├── api/              HTTP 경계 — 라우트(retrieve/documents/ingest/review/runs/traces)
│                      + schemas(요청/응답 DTO) + deps(세션) + services(모델 싱글턴·arq 풀)
│                      __init__.py 의 api_router 가 라우터 조립
├── ingestion/        마크다운 파서 (doc_id/섹션/인용 추출)
├── retrieval/        검색 스택 — types(ChunkHit 공유계약) · embeddings(ABC: fake/st)
│                      · vector(pgvector) · lexical(tsvector BM25) · hybrid(RRF) · rerank(cross-encoder)
├── llm/              LLM 경계 — provider(ABC: mock/openai/fallback) · prompts · schemas(ClaimReport 등)
├── workflow/         LangGraph — state(ReviewState) · nodes(순수 함수) · graph(StateGraph + CRAG 루프)
├── evals/            골든셋 평가 — loader · retrieval/claim/checklist_eval · regression
├── worker/           ARQ 워커 (review_job)
├── observability/    비용 추정 (트레이스 기록은 worker에서)
├── db/               models · session · seed · reset
├── config.py         pydantic-settings (.env)
└── main.py           FastAPI 앱 + lifespan
```

## 3. 흐름 1 — 검색 (동기, `POST /retrieve`)

```
요청 → api/retrieve
        │
        ▼
  embeddings.embed_query ─┐
                          ├─▶ vector_search (pgvector 코사인)  ─┐
                          └─▶ lexical_search (tsvector/ts_rank) ─┤
                                                                  ▼
                                                        rrf_fuse (RRF, 순위 결합)
                                                                  │
                                                (rerank=true면) cross-encoder rerank
                                                                  ▼
                                                     ChunkHit[] (인용 포함) → JSON
```
- 전 과정 **결정적**(LLM 없음). 임베딩/리랭크 모델은 로컬(sentence-transformers/cross-encoder).

## 4. 흐름 2 — 리뷰 (비동기, `POST /review`)

```
POST /review ──(1) Run(pending) 저장──▶ Postgres
     │        ──(2) 잡 enqueue──────────▶ Redis 큐
     └──(3) {run_id, pending} 즉시 반환

ARQ 워커  ──pop──▶ review_job
     │  Run(running) 갱신
     ▼  LangGraph (app/workflow/graph.py)
   ┌─────────────────────────────────────────────────────────┐
   │ retrieve → grade ─(관련 충분)─▶ check ──▶ END             │
   │              │                                            │
   │              └─(부족 & 재시도)─▶ reformulate → retrieve   │  ← Corrective RAG 루프
   │              └─(부족 & 소진)──▶ handle_missing(NOT_IN_DOCS)│
   │ check ─(provider 에러)─▶ retry(≤N) → handle_error         │
   └─────────────────────────────────────────────────────────┘
     │  Run(done, report, node_path) + Trace(model/latency/토큰/비용) 저장
     ▼
GET /runs/{id} ─▶ 상태·인용 달린 판정·노드경로
GET /traces    ─▶ 텔레메트리
```

**가드레일 (check_claim):**
1. 근거 없음 → LLM 안 부르고 `NOT_IN_DOCS`
2. LLM이 반환한 인용 중 실제 검색된 근거에 없는 것 제거 (지어낸 인용 차단)
3. 지지 라벨(SUPPORTED/PARTIALLY)인데 유효 인용 0 → `NOT_IN_DOCS`로 강등

**관련성 가드레일 (grade, CRAG):** 검색이 top-k를 찾아도 주장과 관련 없으면 판정 안 하고 재검색/`NOT_IN_DOCS`.

## 5. 데이터 모델 (Postgres)

| 테이블 | 역할 | 주요 컬럼 |
| --- | --- | --- |
| `documents` | 문서 메타 (1) | doc_id(PK), title, version, effective |
| `chunks` | 섹션 청크 (N) | doc_id(FK), section, content, **embedding `Vector(384)`**, **content_tsv `tsvector`**(GIN), citation |
| `runs` | 리뷰 실행 상태 | id, status, claim, node_path(JSONB), report(JSONB), error |
| `traces` | 관측성 | run_id, model_name, prompt_version, latency_ms, tokens, est_cost_usd, tool_sequence |

- `chunks`는 벡터(pgvector)와 풀텍스트(tsvector)를 **한 테이블에** 둬 하이브리드 검색을 한 DB로.

## 6. 결정적 vs LLM 의존 경계

- **결정적(재현 가능·무과금 테스트):** 파싱·청킹·임베딩(fake)·벡터/렉시컬/RRF·리랭크 재정렬 로직·가드레일 코드·평가 채점·라우팅.
- **LLM 의존(비결정적·비용):** claim 판정(check)·근거 채점(grade)·쿼리 재구성(reformulate).
- 테스트는 이 경계를 따라 분리 — LLM 부분은 `MockProvider`로, 임베딩은 `FakeEmbedder`로 결정적 검증.

## 7. 프레임워크 경계 (원칙)

- **직접 구현(순수 파이썬):** 파싱·청킹·임베딩·검색·인용매핑·저장·평가·툴 본체.
- **LangGraph:** 오케스트레이션 한 곳(`workflow/graph.py`). 노드는 순수 함수를 호출만.
- **LangChain:** LLM 구조화 출력 경계 한 곳(`llm/provider.py`의 `with_structured_output`).
- 핵심 RAG 로직을 프레임워크 뒤에 숨기지 않는다.
