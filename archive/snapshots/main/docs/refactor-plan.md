# app/ 리팩토링 가이드 (계획만 — 실행 전)

> 목적: 코어(Step 0~14) 완성 후 `app/` 구조 정리. **작은 파일 granularity는 유지**(코드 바로 찾기 좋음)하되, "흩어져 난잡해 보이는" 진짜 원인을 잡는다.
> 원칙: 큰 재작성·축 변경(레이어→피처) 안 함. **저-churn·고-명확성**. 각 단계 후 `pytest`(28개) 통과 확인하며 하나씩.

## 1. 진단 — 난잡함의 진짜 원인 (파일 개수가 아님)

현재 구조는 **레이어 기반**(api/db/retrieval/llm/workflow/evals…)이고, 이건 정상·관습적이다. 문제는 "레이어 안 응집도" 4가지:

1. **중심 공유 타입 `ChunkHit`이 `retrieval/search.py`에 묻힘.** 15곳(nodes·state·vector·rerank·lexical·hybrid·prompts·evals·tests)이 `from app.retrieval.search import ChunkHit`. 그런데 `search.py`의 in-memory `search()`는 **Step 5 이후 `vector.py`가 대체해서 죽은 코드**(오직 `tests/test_retrieval.py`만 import). → 중심 타입이 "레거시 파일"에 얹혀 있음.
2. **`schemas`가 두 네임스페이스로 충돌.** `app/schemas/{retrieval,review}.py`(API 요청/응답 DTO) vs `app/llm/schemas.py`(LLM 출력 도메인 모델). 이름은 같은데 뜻이 다르고, API 스키마가 정작 쓰이는 `api/`와 떨어져 있음.
3. **라우트 granularity 불일치.** `api/routes.py`(retrieve+documents+ingest 3개 묶음) vs `api/{review,runs,traces}.py`(각 1개). 같은 레이어인데 쪼개는 기준이 다름.
4. **1-파일 디렉토리** `worker/`·`observability/`·`ingestion/` — 지금은 휑해 보임. (단, 성장 네임스페이스라 유지가 맞음, 아래 P4)

## 2. 타겟 구조 (after)

```
app/
  main.py  config.py
  api/
    __init__.py        # api_router 조립 (모든 라우터 include)
    deps.py  services.py
    schemas.py         # ← app/schemas/ 통합 (API DTO: Retrieve/Review 등)
    retrieve.py  documents.py  ingest.py  review.py  runs.py  traces.py   # 리소스당 1파일 (통일)
  db/
    models.py  session.py  seed.py  reset.py
  retrieval/
    types.py           # ← ChunkHit (중심 공유 타입 승격)
    embeddings.py  vector.py  lexical.py  hybrid.py  rerank.py
    # search.py 삭제 (in-memory search()는 vector.py가 대체)
  llm/
    schemas.py         # LLM 도메인 모델(ClaimReport/Label/EvidenceGrade…) — 역할 명확화
    provider.py  prompts.py
  workflow/
    state.py  nodes.py  graph.py
  evals/
    loader.py  retrieval_eval.py  claim_eval.py  checklist_eval.py  regression.py
  ingestion/  markdown_parser.py
  worker/     settings.py
  observability/  cost.py   (+ 미래: trace 기록 로직)
```

## 3. 구체적 이동 (우선순위·독립 단계)

### P1 — 중심 공유 타입 승격 (제일 효과 큼)
- `retrieval/search.py`의 **`ChunkHit`을 `retrieval/types.py`로** 이동.
- `search.py`의 **in-memory `search()` 삭제** (프로덕션 미사용, `vector.py`가 대체). `tests/test_retrieval.py`의 in-memory 검색 테스트도 정리 — DB 검색은 `test_db.py`가 커버하니 in-memory용은 제거하거나 fake+types만 남김.
- import 일괄 변경: `from app.retrieval.search import ChunkHit` → `from app.retrieval.types import ChunkHit` (sed 한 방, ~15곳).
- (대안) 완전 decouple을 원하면 `app/types.py`(최상위)도 가능. 근데 ChunkHit은 검색 결과 타입이라 `retrieval/types.py`가 자연스러움.

### P2 — schemas 정리 (이름 충돌 해소)
- `app/schemas/{retrieval,review}.py` → **`app/api/schemas.py` 하나로 통합**, `app/schemas/` 디렉토리 삭제.
- import: `from app.schemas.retrieval import …` / `from app.schemas.review import …` → `from app.api.schemas import …`.
- `llm/schemas.py`는 유지하되 "LLM 도메인 모델"로 역할 명확. (충돌이 계속 거슬리면 `llm/schemas.py` → **`llm/models.py`** 리네임까지.)

### P3 — 라우트 granularity 통일
- `api/routes.py`를 **`api/retrieve.py`·`api/documents.py`·`api/ingest.py`로 분리** (review/runs/traces와 일관).
- `api/__init__.py`에서 라우터 조립:
  ```python
  from fastapi import APIRouter
  from app.api import retrieve, documents, ingest, review, runs, traces
  api_router = APIRouter()
  for m in (retrieve, documents, ingest, review, runs, traces):
      api_router.include_router(m.router)
  ```
- `main.py`는 `from app.api import api_router` + `app.include_router(api_router)` 하나로 단순화.

### P4 — 1-파일 디렉토리
- `worker/`·`observability/`·`ingestion/`은 **유지.** 곧 커진다(worker: 잡 추가 / observability: 트레이스 기록·뷰어 로직 / ingestion: 파서 추가). 네임스페이스가 의도를 드러냄. 지금 병합하면 나중에 다시 쪼갬.

## 4. 하지 말 것
- **작은 파일들을 큰 파일로 병합** — granularity 선호(코드 바로 찾기)를 역행. 목표는 "모으기"가 아니라 "제자리 놓기".
- **레이어 → 피처(수직 슬라이스) 축 전환** — 이 규모·포트폴리오엔 오버킬. 레이어 기반이 더 관습적·읽기 쉬움.
- **한 번에 다** — P1→P2→P3 순서로, 각 단계 독립 커밋 + 매번 `pytest` 통과.

## 5. 실행 순서 (나중에)
1. **P1** (ChunkHit → types.py, 죽은 search() 삭제) → pytest
2. **P2** (API schemas 통합) → pytest
3. **P3** (라우트 분리 + api_router) → pytest
4. **P4** 는 스킵(유지)
- import 경로 변경은 `sed -i` 일괄, 매 단계 `uv run pytest -q`로 28개 통과 확인. ruff `--select F`로 미사용 import 정리.

## 6. 기대 효과
- 중심 타입(`ChunkHit`)이 명확한 자리 → "이게 왜 search.py에?" 사라짐.
- schemas 한 뜻 한 자리 → API DTO vs LLM 도메인 혼동 사라짐.
- 라우트 규칙 일관 → api/ 훑기 쉬움.
- 파일 수는 비슷(granularity 유지)하되 **"어디 뭐가 있는지"가 예측 가능**해짐 = 난잡함 해소.
