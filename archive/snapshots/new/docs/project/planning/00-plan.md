# 계획 00 — 프로젝트 계획 · 단일 스파인

> 이 문서가 **구현의 유일한 스파인**이다. 근거는 [01-requirements](01-requirements.md), 설계는 [02-design](02-design.md), 도메인·서사는 [03-scope-and-narrative](03-scope-and-narrative.md), **모듈 단위 착수 계획은 [04-build-plan](04-build-plan.md)**. 이전 계획(`new-docs/`, `old/docs/plan.md`)은 이 문서로 **대체됐다**.

## 왜 이 프로젝트인가

취업용 포트폴리오다 (`~/Documents/jobs/llm-rag-agent-side-project.md`, `jobs/rules/01-positioning.md`). 목표는 **"LLM/RAG를 직접 다뤘다"의 공개 증거 1개** — 챗봇 데모가 아니라 검색품질·eval·가드레일·관측성이 있는 시스템.

`jobs/status.md` 기준 활성 지원 51건, 리크루터 스크린 진행 중 → **릴리즈 속도가 최우선 제약이다.** 완벽한 미출시 시스템은 0점이다.

## 전제 — 42 과제는 하지 않는다

42의 RAG 과제 3종(`42_curriculum/01·02·03`)은 **구현하지 않는다.** 세 subject PDF는 **오직 요구사항 명세로만** 읽는다 — "2026년에 심사자가 실제로 뭘 검사하는가"의 무료 명세서. 코드가 아니라 **요구사항과 측정 규율**만 가져온다. 따라서 [01-requirements](01-requirements.md)의 17항목은 **전부 이 리포가 직접 짊어진다.** 대신 만들어주는 별도 리포는 없다.

> **재조합안을 기각한 기록.** 세 과제를 따라 하고 재조합하는 안은 포트폴리오 전략으로 부적합하다 — ① 코호트 전원이 동일 산출물을 갖는다, ② 42의 금지 조항(03 LangGraph·smolagents 금지, 01 transformers·outlines 금지, 유료 API 금지)이 [시장의 table stakes 스택](01-requirements.md#시장-근거)에서 의도적으로 멀어지는 방향이라 제약을 그대로 상속한다, ③ 희소 자산인 10-K 파서가 과제 더미에 묻힌다.

## 완료 자산 (유지)

| | 상태 |
|---|---|
| **M0** 코퍼스 | NVDA·AMD·INTC·MU × 5년 = **20 filing**, `data/corpus` 스냅샷 고정 |
| **M1.1** 파서 | `app/ingestion/parser.py` + `xref.py`. **20/20 파싱, 경고 0**. 완료 당시 309 tests |
| **M1.1** 문서 | `docs/ko/m1-1-parser/` 6문서 — 이후 모든 마일스톤의 **템플릿**([§4](#4-개발-방식--레이어-튜토리얼--단계별-테스트-하네스)) |
| **M1.2** 표 | `tables.py` 순수 변환기 + 33 tests + `docs/ko/m1-2-tables/` 6문서 |
| **M1.3** 청킹 | source hash·원문 span·xref 연속구간·text/table 청킹 + 32 tests + `docs/ko/m1-3-chunk/` 6문서 |
| **M1.4** 적재 | PostgreSQL atomic upsert + status JSONB + stale cleanup + embedding invalidation + 27 tests + `docs/ko/m1-4-seed/` 6문서 |
| **M1 통합 검증** | **401 tests passed**, live PostgreSQL rerun 포함 (2026-08-12) |

---

## 1. 확정 결정

1. **flagship = 10-K 유지.** M1.1 파서는 희소 자산이다 — "RAG는 검색보다 적재가 어렵다"의 실증. 2. **Python 3.14 고정.** 42의 3.10 요구와 무관하게 현재 셋업 최신을 쓴다. 다운그레이드는 선택지가 아니다. 3. **MCP는 범위 안**(R1.1). 이전 계획의 "범위 밖: MCP" 결정을 **뒤집는다** — [시장에서 희소 신호](01-requirements.md#7-mcp-서버--03-v2). 4. **LangGraph 유지** — 오케스트레이션 한 곳. 단 노드는 순수 함수, 로직을 프레임워크 뒤에 숨기지 않는다. 5. **직접 구현 경계 유지** — 직접 = 파이프라인 로직(파싱·청킹·검색·RRF·eval 채점·가드레일), 기성품 = 모델·경계 프레임워크. 근거는 [03-scope §4](03-scope-and-narrative.md#4-의도적-직접-구현-결정). 6. **GraphRAG는 범위 밖** — 문서에 "다음 확장"으로 명시만.

---

## 2. 착수 전 블로커 (M2 첫날 해소)

`pyproject.toml`이 `requires-python = ">=3.14"`인데 `torch`/`sentence-transformers`가 의존성에 **아직 없다.** cross-encoder 리랭커가 torch를 끌고 온다. → **3.14에 맞춰 해결한다. 파이썬을 리랭커에 맞추지 않는다.**

[03-scope의 배포 제약](03-scope-and-narrative.md#7-배포--비용-제약)이 이미 답의 절반을 갖고 있다 ("임베딩을 API로", "리랭커는 데모서 끈다"):

1. **임베딩 = API 경로가 기본** → torch 불필요. 로컬 모델 상주도 없어 저비용 배포와 일치. 2. **리랭커는 ablation 비교군일 뿐 데모 경로에 없다** → 휠 유무가 릴리즈를 막지 않는다. 3. **1회 확인:** `uv add --group rerank sentence-transformers`가 3.14에서 도는가.
   - 되면 → `--group rerank`로 격리 (기본 설치 제외)
   - 안 되면 → **리랭커를 provider 경계 뒤로**: 기존 LLM 경계로 top-N 점수화(신규 의존성 0) 또는 rerank API

→ **어느 분기든 R1은 안 막히고, "+rerank" ablation arm은 유지된다.**

---

## 3. 릴리즈 원칙

> 42-02 §IX: **"보너스는 mandatory가 전부 통과한 뒤에만 채점된다."**

이걸 릴리즈 원칙으로 채용한다. **핵심이 다 돌기 전엔 빛나는 것 금지.** R1에서 명시적으로 뺀 것: ARQ 워커·Redis · MCP · 멀티 프로바이더 · 증분 인덱싱 · 캐시 · DART 다국어 · GraphRAG.

---

## 4. 개발 방식 — 레이어 튜토리얼 + 단계별 테스트 하네스

**M1이 확립한 패턴을 이후 모든 마일스톤이 반복한다.** 이게 "강의 따라친 코드"와 갈리는 지점이고, 각 마일스톤의 **소유 체크**(콜드로 설명할 수 있나)를 실제로 강제하는 장치다. **새 모듈은 반드시 이 형태로 추가한다.**

### 하네스 5요소 (M1에서 검증됨 — 일반화해서 재사용)

| 요소 | M1의 구현 | 새 영역에 적용 |
|---|---|---|
| **구현 경로** | M1.1의 정식 `app.ingestion.parser` | `zero`에서는 영역별 정식 경로를 직접 생성한다. 환경 변수 기반 복사본 전환은 사용하지 않으며, 테스트 하네스는 아직 없는 정식 심벌을 진행 단계에 따라 건너뛴다. |
| **미구현 = 실패가 아니라 skip** | `tests/support.py:need(P, "fn", …)` | **그대로 재사용.** `pytest` 출력이 그대로 진행 상황판이 된다<br>(`44 passed, 265 skipped` = L4까지 짠 상태) |
| **레이어 순서 = 파일의 물리적 순서** | `parser.py` L1~L14.<br>아래층이 위층을 모른다 | 각 마일스톤 `03-build.md`가 L1..Ln.<br>레이어마다 **개념 → 로직 → 코드 → 돌려보기** |
| **골든값 단일 출처** | `tests/ingestion/golden.py`<br>(문서의 표는 읽기용 사본) | 영역마다 `tests/<area>/golden.py` |
| **문서-코드 동기화 강제** | `scripts/check_doc_code.py` + `tests/test_doc_sync.py`<br>(`<!-- src: … -->` 코드블록 · `` `NAME`(값) `` 상수 · 링크/앵커) | **새 영역으로 확장.** 문서가 갈라지면 pytest가 깨진다 |

### 문서 규칙 — 같은 사실을 두 곳에 적으면 반드시 갈라진다

실측은 `01-findings`에만 · 버그 이력은 `04-bugs`에만 · 골든값은 `golden.py`에만 · 코드는 소스에만 · 임계값은 상수 선언에만. 다른 문서는 `[F9]`·`[B04]`처럼 **링크만** 한다.

### 마일스톤이 남기는 문서

**풀세트 6종** (M1.1~M1.4 전체와 난도 높은 구간 = M3 eval · M4 워크플로우): `00-README`(진입점·읽는 순서) · `01-findings`(실측 F1..Fn) · `02-spec`(계약·타입·스키마·검증기준 + **설계됨·미구현**) · `03-build`(레이어 L1..Ln, 전체 코드) · `04-bugs`(디버깅 이력 B01..Bn) · `05-verify`(최종확인 + pytest 대응표)

**축약형** (M5 등 작은 후속 구간): `02-spec` + `05-verify`만. 단 **하네스 자체(테스트 스위치 · `need()` · `golden.py`)는 전 구간 필수.**

### 마일스톤 완료 조건에 항상 포함

- `03-build.md`에 **"레이어를 하나씩 채우면 몇 개가 켜지나" 누적 통과 표**(실측)
- 각 레이어에 **"돌려보기"** 스니펫 — **테스트 피드백이 0인 레이어는 눈으로 확인할 방법을 반드시 제공** (M1의 L7이 그랬다: 세그멘테이션 테스트가 전부 `parsed` 픽스처에 걸려 있어 짜는 동안 채점이 안 됐다)
- `uv run python scripts/check_doc_code.py` 통과

---

## 5. R1 — 최소한으로 채용 가능한 시스템

> 아래는 마일스톤당 1행 요약이다. **모듈 하나씩 착수할 때는 [04-build-plan](04-build-plan.md)을 편다** — 모듈별 계약(입력→출력)·레이어·테스트·완료기준·소유체크가 거기 있다.

| 단계 | 레이어 (`03-build.md`) | 테스트 | 완료 기준 |
|---|---|---|---|
| **M1.2 ✅** 표 | L1 계약/측정 → L2 grid 전개 → L3 빈 축 제거 → L4 단위 열 병합 → L5 header 추론 → L6 직렬화 → L7 조립 | `tests/ingestion/test_09_tables.py` | table HTML → markdown. 표 행이 통째로 보존 |
| **M1.3 ✅** 청킹 | L1 청크 타입(+span) → L2 text 청커 → L3 **table 청커** → L4 문맥 헤더 → L5 span·정렬 | `tests/chunk/` + `golden.py`<br>`CHUNK_MODULE` | 모든 청크가 source hash와 원문 오프셋을 갖는다.<br>**snapshot identity·span 왕복·비중첩 테스트** 통과 |
| **M1.4 ✅** 적재 | L1 스키마(document status/index JSONB + chunk evidence/context/span) → L2 upsert → L3 재실행 안전 | `tests/db/` | documents=20, 9,172 chunks, xref status·표 청크 보존, 재실행 무중복 |
| **M2** 검색 | L1 `ChunkHit`(span 인용) → L2 임베딩(API) → L3 벡터 → L4 BM25 → L5 **RRF** → L6 rerank(선택 arm) | `tests/retrieval/`<br>`RETRIEVAL_MODULE` | `"NVDA 2024 R&D"` → 해당 filing 청크 top + **원문 span** |
| **M3 ★** 평가 | L1 골든셋 로더 → L2 **IoU 겹침 채점** → L3 `recall@k`·MRR·hit_rate → L4 **ablation 러너** → L5 지연 측정 → L6 `eval_results` 저장·회귀비교 | `tests/evals/`<br>`EVAL_MODULE`<br>**채점 로직 자체를 테스트** | 골든셋 **24~30개 span 라벨**.<br>ablation 비교표 + 지연 예산.<br>**원시 산출물 커밋** |
| **M4** 워크플로우 | L1 상태 → L2 프로바이더 경계 → L3 **스키마 fail-closed** → L4 노드(retrieve/grade/check/report) → L5 **예산 강제** → L6 그래프·CRAG → L7 trace | `tests/workflow/`<br>`WORKFLOW_MODULE`<br>결정적/LLM 분리 | 지지→`SUPPORTED`+인용 / 없는 수치→`NOT_IN_DOCS` /<br>예산 초과→**구조화된 실패** / 스키마 위반→거부 |
| **M5** 서빙 | L1 스키마 → L2 라우트(리소스당) → L3 **얇은 CLI** → L4 runs/traces 저장 → L5 퇴화 입력 | `tests/api/` | `compose up` → curl 전 과정.<br>빈 쿼리·k=0·없는 파일·깨진 JSON에 **크래시 없음** |
| **M6** 데모·문서 | — | — | Gradio(canned + 대비 데모 + 투명성 패널) ·<br>**영문 README** · architecture · eval-report · failure-analysis |
| **M7** 배포 | — | — | HF Spaces + 비용 가드 + **클린 체크아웃 재현 검증** |

### R1.1 (릴리즈 직후, 이 순서)

1. **MCP 서버** (retrieve/check 툴, stdio + streamable HTTP) — 희소 신호, ~1일. *면접 임팩트가 급하면 R1으로 당길 수 있음(+1일)* 2. **ARQ 워커 + Redis** — 비동기 ingestion/review 복원 3. **프로바이더 #2 = Mistral** + 다중 키 로테이션 + fallback 4. **증분 인덱싱** + exact-match 캐시

### R1.2 (스트레치)

두 번째 코퍼스 어댑터(코드/문서) — ["동일 criteria" 서사](03-scope-and-narrative.md#8-다국어--소스-확장-r12)의 실증 · DART 한국어 cross-lingual.

---

## 6. 문서·디렉토리 정리

### 살릴 것

| 대상 | 처리 | 이유 |
|---|---|---|
| `docs/ko/m1-1-parser/` (6문서) | **유지** | flagship 최고 자산이자 [§4](#4-개발-방식--레이어-튜토리얼--단계별-테스트-하네스) 패턴의 원본 템플릿 |
| `old/app/` · `old/tests/` · `old/docker-compose.yml` | **M5까지 유지 → M6에서 삭제** | 이식 원본. 다 옮기면 용도 끝 |
| `old/docs/eval-report.md` | **증거로 보존** → `docs/ko/failure-analysis.md` 재료 | 더미 코퍼스에서 `hit_rate 1.000` = **왜 코퍼스를 버렸는지의 실증** |
| `old/docs/failure-analysis.md` | 새 failure-analysis의 씨앗 | 39줄, 재활용 |
| `app/ingestion/parser.py` | **유지** (M1.1 완성 기준선) | [§4](#4-개발-방식--레이어-튜토리얼--단계별-테스트-하네스)의 첫 완료 지점. M1.2부터는 정식 파일을 직접 만든다. |
| `scripts/check_doc_code.py` · `scripts/measure_tables.py` | **유지** | 전자는 문서-코드 동기화 테스트의 실행 본체, 후자는 M1.2 코퍼스 실측 재현 도구 |

### 지울 것 (전부 git 추적 중 → 복구 가능)

| 대상 | 이유 |
|---|---|
| `new-docs/` 전체 | 이 4문서로 대체됨. 살릴 내용은 [01](01-requirements.md)·[03](03-scope-and-narrative.md)에 흡수 완료 |
| `old/data/sample1/` · `sample2/` (zip 포함) | 명시적으로 버린 "깔끔한 가짜 더미". 남기면 혼선 |
| `old/docs/plan.md`(875줄) · `refactor-plan.md` · `architecture.md` · `deployment.md` | 전부 superseded |
| `old/docs/docreview-rag-agent.en.subject.md`(493줄) | 자작 구 subject. 현 방향으로 대체됨 |
| `old/docs/llm-rag-agent-side-project.md` | `jobs/`의 원본과 중복. 단일 출처는 `jobs/` |
| `old/docs/lecture-videos.md` | 개인 학습 경로 기록 — 포트폴리오 콘텐츠 아님 |
| `old/scratch/` (4파일) | 학습용 랩 |
| `old/pyproject.toml` · `uv.lock` · `.python-version` · `.gitignore` · `.env*` | 구 프로젝트 설정 |

→ **`old/`는 M6에서 완전 삭제.** (`old/.env`는 git 추적되지 않는다 — 추적되는 건 `old/.env.example` 뿐. 확인 완료)

### 최종 리포 구조

```
app/     ingestion(edgar·parser·xref·tables·chunk·seed) · retrieval · llm · workflow · evals · db · api · observability
tests/   ingestion/ · chunk/ · db/ · retrieval/ · evals/ · workflow/ · api/    ← 영역마다 conftest + golden.py
scripts/ check_doc_code.py
data/    corpus(스냅샷) · profiles · golden(span 라벨 24~30) · eval_runs(원시 산출물 ★커밋)
docs/    m1-1-parser/ · m1-2-tables/ · m1-3-chunk/ … m7/ · architecture.md · eval-report.md · failure-analysis.md
docs/project/planning/   00-plan · 01-requirements · 02-design · 03-scope-and-narrative · 04-build-plan
README.md(영문) · Makefile · docker-compose.yml · Dockerfile
```

---

## 7. 위험

1. **골든셋이 릴리즈의 진짜 병목이다.** 수작업이고 M3(차별점)의 게이트다. span 라벨링이 싸게 만들지만([02-design](01-requirements.md#왜-span인가--골든셋-노동이-여기서-갈린다)) 여전히 최대 리스크. → **24~30개로 작게 고정**, `demo-hero`/`category` 태그를 라벨링과 **동시에** 붙인다. 2. **17항목 전부를 R1에 넣으려는 충동.** MCP·멀티 프로바이더·증분 인덱싱은 매력적이지만 R1.1이다. **릴리즈가 늦으면 면접에서 못 쓴다.** 3. **§4 하네스가 각 마일스톤을 무겁게 만든다.** → M1은 책임 분리를 위해 모두 풀세트로 남기고, 이후 문서는 난도에 따라 축약한다. 하네스 자체는 전 구간 필수. 4. **3.14/torch** — [§2](#2-착수-전-블로커-m2-첫날-해소)에서 첫날 해소.

---

## 8. 검증

| 시점 | 명령 / 확인 |
|---|---|
| M1.3·M1.4 | `uv run pytest -q` 전 통과 유지.<br>**span 왕복** — 청크의 `(source_sha256, start_char, end_char)`로 고정 원문을 확인하면 그 청크 body가 순서대로 복원된다 |
| M2 | `uv run python -m app.retrieval --query "NVDA 2024 R&D"` → span 인용 포함 top-k |
| M3 | `uv run python -m app.evals.retrieval_eval` → ablation 비교표 + 지연 측정.<br>**★ 골든셋을 청킹 설정 2개 이상에 재사용해서 무효화되지 않음을 증명** (span 설계의 존재 이유) |
| M4 | 없는 수치 → `NOT_IN_DOCS` / 예산 초과 → 크래시가 아니라 구조화된 실패 / 스키마 위반 → 복구 후 거부 |
| M5 | fresh checkout → `docker compose up` → curl 전 과정 재현 |
| 전 구간 | `uv run python scripts/check_doc_code.py` 통과 · 퇴화 입력에 크래시 없음 ·<br>정식 모듈 경로를 집중 테스트로 직접 채점 가능 |
