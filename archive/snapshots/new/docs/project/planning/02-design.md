# 계획 02 — 설계 · span 인용 · 스키마 · eval · 예산

> 요구사항 근거는 [01-requirements](01-requirements.md). 마일스톤 배치는 [00-plan §5](00-plan.md#5-r1--최소한으로-채용-가능한-시스템). 이 문서는 **무엇을 만드나**(계약·스키마·판정기준)만 다룬다. 레이어별 구현은 각 마일스톤의 `03-build.md`가 맡는다.

## 아키텍처 (데이터 흐름)

```
SEC EDGAR 10-K (20-file immutable snapshot)
   |  M1 ingestion -- parse (done) -> table markdown (done) -> span chunks (done)
   ▼
Postgres + pgvector -- documents / chunks(+span) / runs / traces / eval_results
   |  M2 retrieval -- embed -> vector + lexical -> RRF -> optional rerank
   ▼
ChunkHit (span citation + score + chunk_id)
   |  M4 workflow -- retrieve -> grade -> check -> report
   ▼
Structured report -> M5 API/CLI -> M6 demo/docs -> M7 deployment
                       M3 span-labeled eval measures the retrieval path
```

**결정적 경계** — 파싱·청킹·검색·RRF·eval 채점·가드레일 코드 = 순수 파이썬(테스트 가능) **LLM 경계** — grade·check(판정)만. 임베딩·리랭커·LLM = 기성품

---

## 1. span 인용

### 스키마 변경

```python
@dataclass
class Block:
    kind: Literal["heading", "paragraph", "table"]
    text: str
    level: int | None = None
    html: str | None = None
    source_pos: int | None = None  # start offset in the original HTML
    end_pos: int | None = None  # exclusive end offset in the original HTML
    source_group: int = 0  # contiguous narrative range within one Section
    source_heading: str | None = None  # title of that narrative range
```

```python
@dataclass(frozen=True, slots=True)
class Chunk:
    doc_id: str
    item: str | None
    kind: Literal["text", "table"]
    ordinal: int
    body: str
    context_header: str
    citation: str
    start_char: int
    end_char: int
    source_sha256: str
```

`Block.source_pos`는 기존 `line_offsets()`와 `source_pos()`를 재사용한다. `end_pos`는 다음 source Block의 시작이며 마지막 Block은 원문 파일 길이를 쓴다. xref Item이 서로 떨어진 서사 구간을 소유할 수 있으므로 `source_group` 변경은 강제 청크 경계이고 `source_heading`이 구간별 검색 문맥을 복원한다.

청크의 span은 같은 source group 안에서 개별 좌표의 유효성·순서·비중첩을 검증한 뒤 첫 Block의 start와 마지막 Block의 end로 만든다. `source_sha256`가 이 좌표가 속한 canonical snapshot을 고정한다.

### 왕복 검증 (M1.3 완료 기준)

```
raw_html[chunk.start_char : chunk.end_char] -> visible source tokens
    contains chunk.body tokens in order
```

**정확히 같을 수 없다** — 오프셋은 원본 HTML 기준이라 슬라이스에는 태그가 섞인다. 따라서 판정은 **동등**이 아니라 **포함**이다: 슬라이스에서 뽑은 visible token이 청크 body를 순서대로 담으면 통과. (표 청크는 markdown으로 변환된 뒤라 원문 셀 텍스트가 순서대로 등장하는지로 본다.) `context_header`는 검색을 위한 합성 문맥이므로 왕복 대상이 아니다.

### 인용 표면

사람이 읽는 `citation` 문자열(`"NVDA FY2024 · Item 7"`)은 **유지한다** — 데모·리포트 표시는 그게 낫다. span은 그 밑에 붙는 **기계 판정용 좌표**다. 둘 다 `ChunkHit`에 담는다.

```python
class ChunkHit(BaseModel):
    chunk_id: int
    doc_id: str
    item: str | None
    kind: Literal["text", "table"]
    citation: str
    start_char: int
    end_char: int
    source_sha256: str
    body: str
    context_header: str
    index_text: str
    score: float
```

---

## 2. DB 스키마

| 테이블 | 역할 | 핵심 컬럼 |
|---|---|---|
| `documents` | filing 메타 | `doc_id`(PK) · ticker · cik · fiscal_year · form · filing_date · accession · url · **parse_status** · **item_index(JSONB)** · **source_sha256** · source_length |
| `chunks` | 청크 | doc_id(FK) · item · **kind(text/table)** · ordinal · **body** · **context_header** · index_text · **start_char** · **end_char** · citation · embedding `Vector(dim)` · content_tsv |
| `runs` | 워크플로우 실행 | status · claim · node_path(JSONB) · report(JSONB) · **system_prompt** · iterations · total_* · error |
| `traces` | 스텝 관측성 | run_id(FK) · step · model_name · api_url · input/output_tokens · request_time_ms · **llm_output(raw)** · retries |
| `eval_results` | 평가 결과 → 회귀 비교 | suite · config(JSONB) · metrics(JSONB) · created_at |

- `chunks.kind`가 **표 청크를 텍스트와 구분한다** — 표 처리가 이 프로젝트 ingestion 난제의 핵심
- `body`만 인용 가능한 evidence다. `context_header`는 합성 문맥이고 `index_text`가 둘을 합친다
- span은 UTF-8 byte가 아니라 canonical decoded source의 반열림 Python character index다
- `documents.source_sha256`가 span이 어느 immutable snapshot의 좌표인지 고정한다
- `documents.item_index`가 body 청크가 없는 xref Item의 `Not applicable`/참조 상태 근거를 보존한다
- `UniqueConstraint(doc_id, ordinal)` = 재실행 안전 키 (이미 있음)
- `eval_results`가 회귀 감지의 baseline 저장소
- **골든셋은 DB가 아니라 JSON 파일** (`data/golden/`) — 사람이 손으로 고치고 git diff로 리뷰해야 하므로

---

## 3. 관측성 스키마

[#8](01-requirements.md#8-스텝-단위-사용량-추적-스키마--03-v3-v4)의 `StepMetrics`/`SolutionOutput`을 채용한다. **raw 출력과 system_prompt까지 저장하는 게 핵심** — 숫자가 조작이 아님을 보이는 장치다.

```python
class StepTrace(BaseModel):          # → traces 행
    step: int
    node: str                        # "retrieve" | "grade" | "check" | "report"
    model_name: str
    api_url: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    llm_output: str                  # raw — 파싱 전
    retries: int
    error: str | None = None

class RunReport(BaseModel):          # → runs 행
    run_id: str
    status: Literal["ok", "budget_exceeded", "schema_rejected", "error"]
    iterations: int
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_time_seconds: float
    system_prompt: str               # 전문 — provenance
    node_path: list[str]
    report: dict | None
    steps: list[StepTrace]
```

우리 워크플로우엔 샌드박스가 없으므로 `sandbox_input`/`sandbox_output`은 `node` + `llm_output`으로 대체한다.

---

## 4. eval 설계

### 골든셋 포맷 (`data/golden/retrieval.json`)

```json
{
  "id": "q07",
  "question": "What was NVIDIA's R&D expense in fiscal 2024?",
  "category": "exact_number",
  "tags": ["demo-hero"],
  "answers": [
    { "doc_id": "NVDA-FY2024", "start_char": 481203, "end_char": 482010 }
  ],
  "expected_label": "SUPPORTED",
  "note": "Item 7 MD&A, R&D 표"
}
```

- `category` ∈ `simple_lookup` · `exact_number` · `multi_hop` · `absent`
- `absent` 케이스는 `answers: []` + `expected_label: "NOT_IN_DOCS"` (가드레일 채점용)
- `demo-hero` 태그 = 데모 예시 질문. **라벨링과 동시에 붙인다** (나중에 다시 훑지 않도록)
- **규모: 24~30개.** 코퍼스 전체 커버 시도 금지 — [최대 병목](00-plan.md#7-위험)이다

### 채점 — IoU 겹침 (`02 §VII.1.1`)

정답 span `a`와 검색된 청크 span `b`가 **같은 `doc_id`**이고:

```
overlap = max(0, min(a.end, b.end) - max(a.start, b.start))
union   = (a.end - a.start) + (b.end - b.start) - overlap
IoU     = overlap / union          →  IoU ≥ IOU_THRESHOLD(0.05) 이면 적중
```

**다른 문서는 절대 적중이 아니다.** 임계가 낮은 이유: 참조 span과 정확히 일치할 필요 없이 "올바른 파일의 올바른 영역을 덮으면" 충분하기 때문 — 이게 **청킹 설정을 바꿔도 골든셋이 살아남는 이유**다.

### 지표

| 지표 | 뜻 | 왜 |
|---|---|---|
| `recall@k` | 그 질문의 정답 span 중 top-k가 덮은 비율 | **공식 지표**([#1](01-requirements.md#1-recallk가-공식-지표--02-vii1)) |
| `hit_rate@k` | 정답을 하나라도 덮은 질문 비율 | "찾았나" |
| `MRR` | 첫 적중 순위의 역수 평균 | "얼마나 위에 올렸나" |
| `schema_valid_rate` | 구조화 출력이 스키마를 통과한 비율 | [#14](01-requirements.md#14-신뢰성을-수치로-보고--01-v5) |
| `label_accuracy` | 4라벨 판정 정확도 (`expected_label` 대조) | [#14](01-requirements.md#14-신뢰성을-수치로-보고--01-v5) |

**채점 로직 자체를 테스트한다.** 지표 계산 버그는 틀린 숫자를 믿게 만들어서 이후 모든 결정을 오염시킨다.

### ablation 매트릭스

| 축 | 비교군 |
|---|---|
| **청킹** | 고정 500 · 고정 1200+오버랩 · semantic(SemanticChunker) · **구조 기반(우리)** |
| **검색** | **lexical 단독 ← 바닥 기준선**([#4](01-requirements.md#4-렉시컬이-필수-기준선--02-vi1-ix)) · vector 단독 · hybrid(RRF) · hybrid+rerank |
| **어휘 랭커** | `ts_rank_cd`(범위 밀도, M2.4) · **BM25**(직접 구현, M2.9) · `bm25` `b=0`(길이 정규화 기여도 분리) |

→ **"왜 구조 기반인가" · "왜 하이브리드인가" · "왜 이 어휘 랭커인가"를 숫자로.** 정성 설명은 M6 문서화. 전 조합을 다 돌릴 필요는 없다 — 한 축을 훑을 때 나머지 축은 그때까지의 최선 설정에 고정한다.

어휘 랭커 축은 특히 깨끗하다. `ts_rank_cd`와 BM25가 같은 `to_tsvector('english', index_text)`를 공유하므로 토크나이저·어간 추출·불용어가 동일하고, **차이는 순위 공식 하나뿐인 통제 실험**이 된다.

### 성능 예산

> 근거: [#2 성능 예산](01-requirements.md#2-성능-예산--02-vi1-vii12)

| 예산 | 목표 | 측정 |
|---|---|---|
| 인덱싱 | 전체 코퍼스 **≤5분** | `seed` 실행 wall-clock |
| 검색 처리량 | **≤90초 / 200질문** | 골든셋을 반복해 200개로 늘려 측정 |

정확도와 **동급의 통과 조건**으로 취급한다. eval-report에 항상 같이 싣는다.

### 원시 산출물

> 근거: [#11 BENCHMARK_REPORT.md](01-requirements.md#11-benchmark_reportmd--03-v7)

모든 eval 실행은 `data/eval_runs/<timestamp>-<config>.json`에 **원본 그대로 저장하고 커밋한다.** `docs/ko/eval-report.md`의 표는 그 파일들의 **요약**이며, 어느 행이 어느 파일에서 나왔는지 링크한다. → *숫자가 믿기는 이유는 원본이 같이 있기 때문이다.*

---

## 5. 예산 강제

> 근거: [#9 하드 예산 강제](01-requirements.md#9-하드-예산-강제--03-vi1)

```python
class Budget(BaseModel):
    max_iterations: int = 6
    max_input_tokens: int = 60_000      # 누적 — 전 스텝 합
    max_output_tokens: int = 4_000      # 누적
    max_wall_clock_s: float = 120.0
```

**강제 지점 = 노드 진입 직전 1곳.** 매 스텝 시작 시 누적치를 검사하고, 초과하면 예외가 아니라 `status="budget_exceeded"`인 **구조화된 실패**를 반환하고 그래프를 종료한다.

- 토큰은 **누적**이다 (한 스텝 기준이 아니라 run 전체 합)
- 초과는 크래시가 아니다 — `runs` 행이 남고 `traces`에 어디서 끊겼는지 남는다
- **데모 비용 가드가 같은 코드다** ([03-scope §7](03-scope-and-narrative.md#7-배포--비용-제약))

---

## 6. 스키마 fail-closed 사다리

> 근거: [#13 프롬프트로 구조화 출력을 기대하는 건 신뢰 불가](01-requirements.md#13-프롬프트로-구조화-출력을-기대하는-건-신뢰-불가--01-v33)

프롬프트가 아니라 **코드가** 스키마를 보증한다. 3단:

```
① 검증   구조화 출력 파싱 → pydantic 검증
              ↓ 실패
② 복구   1회 재시도 (검증 실패 사유를 프롬프트에 명시해서 되돌려줌)
              ↓ 또 실패
③ 거부   status="schema_rejected" 로 종료.  ★무음 통과 금지
```

**추가 가드레일 (판정 결과에 대한 코드 검사):**
- 근거가 비면 → `NOT_IN_DOCS`로 강등 (LLM이 뭐라 했든)
- 검색 결과에 없는 `chunk_id`를 인용하면 → 그 인용 제거
- 인용이 하나도 안 남은 `SUPPORTED` → `NOT_IN_DOCS`로 강등

프롬프트는 best-effort고, **이 세 검사가 실제 보증이다.**

---

## 7. 실패 모드 피드백

> 근거: [#12 모든 실패 모드에 명시적 피드백](01-requirements.md#12-모든-실패-모드에-명시적-피드백--03-v1)

노드는 어떤 퇴화 경로에서도 **타입 있는 사유**를 반환한다. 침묵 금지.

| 상황 | 반환 |
|---|---|
| 검색 0건 | `RetrievalEmpty(query, k, filters)` |
| 관련도 미달 (CRAG grade 실패) | `RelevanceBelowThreshold(scores, threshold)` → 재검색 트리거 |
| 컨텍스트 절단 | `ContextTruncated(dropped_chunks, budget)` |
| 스키마 위반 | `SchemaRejected(errors, attempt)` |
| 예산 초과 | `BudgetExceeded(which, used, limit)` |

전부 `traces`에 남고, 데모의 투명성 패널에 그대로 노출된다.
