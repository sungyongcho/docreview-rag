# 계획 04 — 빌드 계획 · 모듈 스켈레톤

> [00-plan §5](00-plan.md#5-r1--최소한으로-채용-가능한-시스템)의 마일스톤 표를 **모듈 단위로 펼친 것.** 계약(입력→출력)과 레이어 골격만 확정하고, **시그니처·상수는 각 모듈 착수 시 풀업한다.** 전신: `new-docs/05-build-plan.md` (삭제됨 — `git show HEAD:new-docs/05-build-plan.md`로 열람 가능)

## 읽는 법

각 모듈 블록의 형식:

```
### app/<area>/<module>.py                                    [마일스톤]
책임      한 줄
계약      입력 → 출력
레이어    L1 → L2 → …            ← 03-build.md의 목차가 된다
테스트    tests/<area>/test_NN_*.py · <AREA>_MODULE 스위치
문서      풀세트 6종 | 축약형(02-spec + 05-verify)
완료      검증 가능한 조건
소유체크  콜드로 답할 수 있어야 하는 질문
```

**하네스는 전 모듈 필수** — [00-plan §4](00-plan.md#4-개발-방식--레이어-튜토리얼--단계별-테스트-하네스)의 5요소 (`<AREA>_MODULE` 스위치 · `need()` skip · 레이어=파일순서 · `golden.py` · doc-code 동기화). 이 기록을 만든 당시에는 레퍼런스 옆 learner scaffold를 두는 방식을 계획했다. `zero` 재구성에서는 그 방식을 폐기하고, 각 마일스톤에서 정식 `x.py`를 직접 생성한다. M1.1의 `parser.py`만 완성된 기준선으로 유지한다.

**상태 범례:** ✅ 완료 · 🔨 R1 · ⏸ R1.1 · 💤 R1.2

---

## M1 — ingestion

### `app/ingestion/edgar.py` ✅
- **책임** EDGAR에서 10-K 수집 → `data/corpus` 스냅샷 + `manifest.json`
- **완료** 20 filing 로컬 확보, 스냅샷 고정

### `app/ingestion/parser.py` · `xref.py` ✅
- **책임** 10-K HTML → `ParsedFiling`(Item 섹션). 프로파일(데이터)이 전략을 선택
- **레이어** L1 자료구조 → L2 정규화 → L3 블록화 → L4 속성추출 → L5 규칙평가기 → L6 문맥신호 → L7 세그멘테이션A(헤딩) → L8 세그멘테이션B(xref) → L9 판별 → L10 상태분류 → L11 프로파일 I/O → L12 검증 → L13 오케스트레이션 → L14 CLI
- **완료** 20/20 파싱, 경고 0. 문서 `docs/ko/m1-1-parser/` 풀세트 6종
- → 이 모듈이 이후 전 모듈의 **템플릿**이다

---

### `app/ingestion/tables.py` ✅ [M1.2]
- **책임** table HTML → markdown. **표를 통짜로 보존**한다
- **계약** table HTML `str | None` → markdown `str`. `Block`은 변경하지 않는 순수 변환기이며 M1.3이 호출한다
- **레이어**
  - `L1` 입력 계약·코퍼스 측정
  - `L2` `rowspan`/`colspan`을 dense grid로 전개
  - `L3` all-empty 행·열 제거
  - `L4` 통화·퍼센트 단위 전용 열을 값 열에 병합
  - `L5` `<th>` 없는 표의 header/body 경계 추론
  - `L6` markdown 직렬화와 pipe escape
  - `L7` 빈/layout-only 표를 포함한 entry point 조립
- **테스트** `tests/ingestion/test_09_tables.py` · 골든값은 기존 `tests/ingestion/golden.py`에 합류
- **문서** [`docs/ko/m1-2-tables/`](../../ko/m1-2-tables/00-README.md) 풀세트 6종
- **완료** 20문서 1,200개 table Block 전수 검증, 33개 M1.2 테스트 통과. 괄호음수는 원문 표기 보존
- **소유체크** "표를 왜 markdown으로? HTML 그대로 두면 뭐가 문제인가" / "병합셀을 어떻게 처리했나"
- **결정** ingestion은 원문 충실성을 우선해 괄호음수를 보존한다. 숫자 해석은 retrieval/eval 경계에서 별도 처리

### `app/ingestion/chunk.py` ✅ [M1.3] ★핵심
- **책임** `ParsedFiling` → 검색 가능한 청크 + **원문 char span**
- **계약** `ParsedFiling` → `list[Chunk]` (각 청크가 `start_char`/`end_char` 보유)
- **레이어**
  - `L1` 청크 타입 정의 — `kind`(text/table) · `item` · `ordinal` · **span** · `citation`
  - `L2` text 청커 — 구조 기반(Section/Block 계층 활용). 크기는 설정 가능한 상수
  - `L3` **table 청커** — row-level provenance가 없으므로 표 하나를 한 청크로 보존
  - `L4` 문맥 헤더 — 현재 `source_group` 제목만 붙이고 body와 합성 문맥을 분리
  - `L5` **span 부여·정렬** — 개별 Block 검증 → 그룹 내 span 집계 → stable source sort
- **선행 작업** `parser.py`의 `Block`에 `source_pos`·`end_pos` 추가
  + xref의 떨어진 서사 범위와 제목을 구분하는 `source_group`·`source_heading` 추가 (`source_pos()`·`line_offsets()` 재사용 — [02-design §1](02-design.md#1-span-인용))
- **테스트** `tests/chunk/` (+`conftest.py`·`golden.py`) · **`CHUNK_MODULE`** 스위치
- **문서** [`docs/ko/m1-3-chunk/`](../../ko/m1-3-chunk/00-README.md) **풀세트 6종**
- **완료** 20문서 9,172 chunks, 모든 청크가 canonical source hash·오프셋 보유, span overlap 0, **snapshot identity·span 왕복·exact-once 테스트**와 M1.3 테스트 32개 통과 (원문 슬라이스를 정규화한 텍스트가 청크 본문을 **포함**한다 — 동등이 아니라 포함)
- **소유체크** "왜 이 청킹 전략인가 — 고정크기 vs 섹션 vs 표전용" / "청크에서 출처를 어떻게 되짚나" / "왜 chunk_id가 아니라 span으로 인용하나"
- **유보 결정** 청크 크기 기본값의 승자는 [M3 ablation](02-design.md#ablation-매트릭스)이 정한다. M1.3은 설정 가능성과 citation 안정성만 보장한다

### `app/ingestion/seed.py` ✅ [M1.4] + `app/db/models.py` 확장
- **책임** 청크를 pgvector에 적재. **재실행 안전**
- **계약** `list[Chunk]` → DB rows (idempotent)
- **레이어**
  - `L1` 스키마 확장 — document `parse_status`·`item_index` JSONB와 chunk `body`·`context_header`·`index_text`·`start_char`·`end_char`·source hash 추가 ([02-design §2](02-design.md#2-db-스키마))
  - `L2` PostgreSQL upsert — document `doc_id`, chunk `(doc_id, ordinal)`을 키로 하고 text 변경 시 stale embedding을 무효화
  - `L3` 재실행 안전 — bounded batch, atomic transaction, trailing ordinal cleanup
- **테스트** `tests/db/` 27개 + 실제 PostgreSQL temporary-table integration
- **문서** [`docs/ko/m1-4-seed/`](../../ko/m1-4-seed/00-README.md) 풀세트 6종
- **완료** `documents=20` · `chunks=9,172` · 표 청크 존재 · 재실행 무중복 · 변경 text의 embedding `NULL`
- **소유체크** "재실행 시 중복을 어떻게 막나" / "임베딩은 언제 채우나"

---

## M2 — retrieval 🔨

> **착수 첫날: [3.14/torch 블로커](00-plan.md#2-착수-전-블로커-m2-첫날-해소) 1회 확인부터.**

- **문서** 축약형 · **테스트** `tests/retrieval/` · **스위치** `RETRIEVAL_MODULE`
- **레이어 순서** = 아래 모듈 순서

### `app/retrieval/types.py`
- **책임** 공유 타입. 다른 retrieval 모듈이 전부 이걸 import한다
- **계약** `ChunkHit` — `chunk_id·doc_id·item·kind·citation(사람용)·start_char·end_char(기계용)·source_sha256·body·context_header·index_text·score` ([02-design §1](02-design.md#인용-표면))

### `app/retrieval/embeddings.py`
- **책임** 텍스트 → 벡터. **API 경로가 기본**(로컬 모델 상주 회피)
- **계약** `list[str]` → `list[list[float]]` · provider ABC로 교체 가능
- **이식 원본** `old/app/retrieval/embeddings.py`

### `app/retrieval/vector.py`
- **책임** pgvector 코사인 검색
- **계약** `(query_vec, k, filters)` → `list[ChunkHit]`
- **이식 원본** `old/app/retrieval/vector.py`

### `app/retrieval/lexical.py`
- **책임** PostgreSQL FTS (`websearch_to_tsquery` + `ts_rank_cd`). **ablation의 바닥 기준선** ([#4](01-requirements.md#4-렉시컬이-필수-기준선--02-vi1-ix))
- **계약** `(query, k, filters)` → `list[ChunkHit]`
- **주의** `ts_rank_cd`는 범위 밀도(cover density) 점수다. **BM25가 아니다** — 말뭉치 통계(IDF)도 문서 길이 정규화도 쓰지 않는다

### `app/retrieval/bm25.py`
- **책임** 직접 구현한 BM25. `lexical.py`와 **같은 어댑터 시그니처**를 공유하는 두 번째 어휘 랭커
- **계약** `(query, k, filters, k1, b)` → `list[ChunkHit]`
- **전제** `content_tsv`에서 파생한 term 통계 (`tf` · `df` · `N` · `dl` · `avgdl`). 새 의존성 없음
- **순서** M2.8 이후(**M2.9**)에 만든다. 승자 선택은 **M3.4 측정**이지 여기가 아니다
- **소유체크** "`k1`과 `b`가 각각 무엇을 고치나" / "왜 TF-IDF가 아니라 BM25인가"

### `app/retrieval/hybrid.py`
- **책임** **RRF**로 벡터·렉시컬 순위 결합
- **계약** `(list[ChunkHit], list[ChunkHit], k)` → `list[ChunkHit]`
- **소유체크** "RRF가 가중합보다 나은 이유" / "rank와 score를 왜 헷갈리면 안 되나"

### `app/retrieval/rerank.py`
- **책임** top-N 재정렬. **ablation 비교군 전용 — 데모 경로에 없다**
- **분기** 3.14에서 cross-encoder가 되면 `--group rerank`로 격리, 안 되면 provider 경계 뒤로
- **소유체크** "리랭커를 왜 top-N에만 돌리나" / "bi-encoder와 cross-encoder 차이"

- **M2 완료** `--query "NVDA 2024 R&D"` → 해당 filing 청크 top + **원문 span 인용**. 결정적(eval 재현 가능)

---

## M3 — evals 🔨 ★차별점

- **문서** **풀세트 6종** · **테스트** `tests/evals/` · **스위치** `EVAL_MODULE`
- **★ 채점 로직 자체를 테스트한다** — 지표 버그는 틀린 숫자를 믿게 만들어 이후 모든 결정을 오염시킨다

### `app/evals/loader.py`
- **책임** `data/golden/*.json` 로드·검증
- **계약** JSON → `list[GoldenCase]` (포맷은 [02-design §4](02-design.md#골든셋-포맷-datagoldenretrievaljson))
- **미결(착수 시)** 골든셋 24~30개 **수작업 제작** ← [최대 병목](00-plan.md#7-위험). `demo-hero`·`category` 태그를 라벨링과 **동시에** 붙인다

### `app/evals/scoring.py`
- **책임** **IoU 겹침 판정** + 지표 계산
- **계약** `(golden_spans, retrieved_hits, k)` → `recall@k · hit_rate@k · MRR`
- **핵심 상수** `IOU_THRESHOLD`(0.05) — 값은 상수 선언에만 둔다
- **소유체크** "hit_rate와 recall@k와 MRR의 차이" / "IoU 임계가 왜 이렇게 낮나"

### `app/evals/ablation.py`
- **책임** 청킹 × 검색 조합을 돌려 비교표 생성 ([매트릭스](02-design.md#ablation-매트릭스))
- **계약** `list[Config]` → 비교표 + `data/eval_runs/<ts>-<config>.json` **원시 산출물**
- **완료** "왜 구조 기반인가" · "왜 하이브리드인가"를 **숫자로**

### `app/evals/retrieval_eval.py`
- **책임** CLI 진입점 + 지연 예산 측정 ([#2](01-requirements.md#2-성능-예산--02-vi1-vii12))
- **완료** 인덱싱 ≤5분 · 200질문 ≤90초를 **측정해서 리포트에 싣는다**

### `app/evals/regression.py`
- **책임** `eval_results` 저장 → baseline 대비 회귀 감지
- **계약** `(suite, config, metrics)` → DB row + 이전 대비 diff

- **M3 완료** ablation 비교표 + 지연 예산 + `docs/ko/eval-report.md` 초안. **★ 골든셋을 청킹 설정 2개 이상에 재사용해서 무효화되지 않음을 증명** (span 설계의 존재 이유)

---

## M4 — llm · workflow · observability 🔨

- **문서** **풀세트 6종** · **테스트** `tests/workflow/` · **스위치** `WORKFLOW_MODULE`
- **결정적 테스트와 LLM 테스트를 분리한다**

### `app/llm/provider.py`
- **책임** LLM 호출 경계 **한 곳**. mock/openai. (Mistral·키 로테이션은 ⏸ R1.1)
- **계약** `(prompt, schema, budget)` → `(parsed, StepTrace)`
- **왜 한 곳인가** 캐시·canned·비용 가드를 나중에 이 앞에 끼우기 위해

### `app/llm/schemas.py`
- **책임** 구조화 출력 스키마 + **fail-closed 사다리** ([02-design §6](02-design.md#6-스키마-fail-closed-사다리))
- **레이어** `L1` 검증 → `L2` 복구(1회 재시도, 실패 사유를 되돌려줌) → `L3` **거부**(무음 통과 금지)
- **소유체크** "가드레일이 프롬프트만이면 왜 부족한가" / "스키마를 코드가 보증한다는 게 무슨 뜻인가"

### `app/workflow/state.py` · `nodes.py` · `graph.py`
- **책임** retrieve → grade → check → report. **노드는 순수 함수**, LangGraph는 배선만
- **가드레일 3종 (코드가 강제)**
  - 근거 없음 → `NOT_IN_DOCS` 강등
  - 검색 결과에 없는 `chunk_id` 인용 → 제거
  - 인용 0개인 `SUPPORTED` → `NOT_IN_DOCS` 강등
- **실패 피드백** 모든 퇴화 경로에 타입 있는 사유 ([02-design §7](02-design.md#7-실패-모드-피드백))
- **함정** LangGraph는 스키마에 없는 상태 키를 **조용히 버린다**
- **소유체크** "LLM이 없는 걸 주장하면 어떻게 막나" / "왜 LangGraph? 어디까지 LangChain?"

### `app/observability/trace.py` · `cost.py`
- **책임** `StepTrace`/`RunReport` 기록 + **예산 강제**
- **계약** [02-design §3](02-design.md#3-관측성-스키마) 스키마 그대로. `system_prompt`·raw `llm_output`까지 저장
- **예산** 노드 진입 직전 **1곳**에서 누적치 검사 → 초과 시 `status="budget_exceeded"` **구조화된 실패** (크래시 아님. `runs` 행이 남고 `traces`에 끊긴 지점이 남는다)
- **소유체크** "비용을 어떻게 추정·로깅하나" / "예산 초과를 왜 예외로 안 던지나"

- **M4 완료** 지지→`SUPPORTED`+인용 / 없는 수치→`NOT_IN_DOCS` / 예산 초과→구조화된 실패 / 스키마 위반→거부

---

## M5 — 서빙 🔨

- **문서** 축약형 · **테스트** `tests/api/`
- **동기 경로만** (워커·Redis는 ⏸ R1.1)

### `app/api/schemas.py` · `deps.py` · `routes/`
- **책임** 타입 있는 HTTP 경계. 라우트는 **리소스당 파일** (retrieve·documents·ingest·review·runs·traces·eval)
- **이식 원본** `old/app/api/`
- **필수** 응답에 `chunk_id`와 **span** 포함

### `app/cli.py`
- **책임** Docker 없이 도는 얇은 CLI ([#5](01-requirements.md#5-cli가-1급-인터페이스--크래시-금지--02-vi6))
- **필수** 모든 경로가 인자. **하드코딩 금지**
- **퇴화 입력에 절대 크래시 금지** — 빈 쿼리 · `k=0` · 없는 파일 · 깨진 JSON

### `app/main.py` · `docker-compose.yml` · `Dockerfile`
- **이식 원본** `old/docker-compose.yml` (app/worker 서비스·Dockerfile 부재가 기존 갭)
- **M5 완료** **fresh checkout → `compose up` → curl로 전 과정 재현**

---

## M6 · M7 — 데모 · 문서 · 배포 🔨

코드 모듈이 아니라 산출물이다. → [03-scope §5~7](03-scope-and-narrative.md#5-데모-ux)

- **M6** Gradio(prefilled 예시 · 대비 데모 · 투명성 패널) · **영문 README**([#16 고정 섹션](01-requirements.md#16-리포-위생과-영문-readme)) · `architecture.md` · `eval-report.md`([#11 템플릿](01-requirements.md#11-benchmark_reportmd--03-v7)) · `failure-analysis.md`
  - **`old/docs/eval-report.md`를 실패 분석 재료로 쓴다** — 더미 코퍼스에서 `hit_rate 1.000`이 나온 기록
  - **`old/`는 여기서 완전 삭제** (이식 완료 시점)
  - **Makefile** — `install`·`run`·`debug`·`clean`·`lint`
- **M7** HF Spaces + canned/rate limit/BYO-key + **클린 체크아웃 재현 검증** + 정직 워딩

---

## ⏸ R1.1 — 릴리즈 직후

| 순서 | 모듈 | 비고 |
|---|---|---|
| 1 | `app/mcp/server.py` | retrieve·check 툴을 stdio + streamable HTTP로. **툴 스키마 → 매뉴얼 동적 생성** ([#7](01-requirements.md#7-mcp-서버--03-v2)) |
| 2 | `app/worker/` (ARQ) | 비동기 ingestion/review. Redis(큐) vs Postgres(상태) 역할 분리 |
| 3 | `app/llm/provider.py` 확장 | **Mistral** 추가 + 다중 키 로테이션 + fallback ([#10](01-requirements.md#10-프로바이더-추상화--03-v6)) |
| 4 | `app/ingestion/incremental.py` · 캐시 | 파일 변경분만 재색인 · exact-match 캐시 |

## 💤 R1.2

소스 어댑터 패턴 — DART(한국어) · 20-F · 코드/문서 코퍼스. **파서 입구만 어댑터, 정규화 후 파이프라인은 전부 공유** ([03-scope §8](03-scope-and-narrative.md#8-다국어--소스-확장-r12))
