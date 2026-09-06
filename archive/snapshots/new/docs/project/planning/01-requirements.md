# 계획 01 — 요구사항 · 42 subject 추출 + 시장 근거

> **왜 이 문서가 있나.** 42의 RAG 과제 3종은 [구현하지 않는다](00-plan.md#전제--42-과제는-하지-않는다). 대신 세 subject PDF를 **"2026년에 심사자가 실제로 뭘 검사하는가"의 명세서**로 읽었다. 여기 17항목은 전부 이 리포가 직접 이행한다. 배치는 [00-plan §5](00-plan.md#5-r1--최소한으로-채용-가능한-시스템).

**출처 표기:** `01` = *call me maybe* (function calling / constrained decoding) · `02` = *RAG against the machine* (codebase RAG / recall@k) · `03` = *Agent smith* (code agent / sandbox / MCP). 절 번호는 각 PDF의 장·절이다.

---

## ★ 최우선 — span 인용 (`02 §VI.2`, `§VII.1.1`)

42-02는 인용을 이렇게 정의한다:

```python
class MinimalSource(BaseModel):
    file_path: str
    first_character_index: int
    last_character_index: int
```

그리고 채점은 **"같은 파일이면서 문자 범위가 겹치면 정답"**, 겹침 기준은 **IoU ≥ 0.05**로 낮다 (`02 §VII.1.1`: 참조 span과 정확히 일치할 필요 없이 *"올바른 파일의 올바른 영역을 덮는 청크를 가져오면 충분"*).

**M1.3에서 이 전제를 구현했다.** 사람용 `citation` 문자열과 별도로 모든 `Chunk`가 `doc_id`, `source_sha256`, `start_char`, `end_char`를 가진다. DB persistence는 M1.4에서 완료했고 retrieval schema로 내리는 작업은 M2다.

### 왜 span인가 — 골든셋 노동이 여기서 갈린다

| 정답 라벨 방식 | 청킹 설정을 바꾸면 | ablation 가능? | 라벨링 비용 |
|---|---|---|---|
| `chunk_id` | **골든셋 전체 무효화** | ❌ | 청크 목록에서 고르기 |
| **원문 char span** | 그대로 재사용 | ✅ | 원문 구간 긁기 (더 쌈) |

**chunk_id로 라벨하면 M3의 chunk ablation을 아예 할 수가 없다.** 청킹을 바꾸는 순간 정답이 가리키는 청크가 사라지기 때문이다. 그런데 chunk ablation은 우리의 [#1 차별점](#시장-근거)이다. → **span이 전제 조건이다.**

### 구현 상태

| 있는 것 | 위치 |
|---|---|
| `line_offsets(html) -> list[int]` | `app/ingestion/parser.py` |
| `source_pos(el, offsets) -> int \| None` | `app/ingestion/parser.py` |
| `Block.source_pos` / `end_pos` / `source_group` | M1.3 prerequisite, 완료 |
| `Chunk.source_sha256` / `start_char` / `end_char` | `app/ingestion/chunk.py`, 완료 |
| DB evidence/context/index text + source coordinates | `app/db/models.py`, M1.4 완료 |

M1.3의 코드·왕복 테스트·실측은 [`docs/ko/m1-3-chunk/`](../../ko/m1-3-chunk/00-README.md), M1.4 적재 계약과 재실행 증거는 [`docs/ko/m1-4-seed/`](../../ko/m1-4-seed/00-README.md)에 있다. 상세 설계 → [02-design](02-design.md#1-span-인용).

---

## 나머지 16항목

### 검색·평가 (출처 `02`)

#### 1. recall@k가 공식 지표 — `02 §VII.1`
42-02는 `recall@k`를 유일한 검색 지표로 쓰고 **하드 임계**를 건다: docs 질문 **80% recall@5**, code 질문 **50%**. 우리는 현재 `hit_rate`/`MRR`만 있다. → **`recall@k` 추가.** 심사자·시장 공용어다. → **M3**

#### 2. 성능 예산 — `02 §VI.1`, `§VII.1.2`
인덱싱 **≤5분**(전체 코퍼스) · 검색 **≤90초**(200질문) — 정확도와 **동급의 통과 조건**이다. 현 계획엔 latency 개념 자체가 없다. → eval-report에 **측정된 지연 예산** 추가. "노트북이 아니라 시스템"의 증거. → **M3**

#### 3. 콘텐츠 유형별 분리된 청킹 전략 — `02 §VI.1`
*"파이썬 파일과 마크다운 페이지는 같은 방식으로 쪼개지지 않는다"* → 두 청커를 **필수**로 요구한다. 우리는 이미 text vs **table**이라는 더 어려운 쌍을 갖고 있다. → 이걸 **"전략 쌍"으로 명시하고 각각 ablation.** → **M1.3 · M3**

#### 4. 렉시컬이 필수 기준선 — `02 §VI.1`, `§IX`
BM25/TF-IDF 중 하나가 **mandatory**, 시맨틱 임베딩·하이브리드는 **보너스**. 즉 채점자는 렉시컬을 바닥으로 놓고 그 위의 개선을 본다. → **ablation에 lexical-only를 바닥 기준선으로 필수 포함.** 하이브리드가 이겼음을 주장하려면 이길 대상이 있어야 한다. → **M3**

##### 이행 결정 — 2026-08-23

M2.4는 PostgreSQL FTS(`websearch_to_tsquery` + `ts_rank_cd`)를 **무의존성 어휘 바닥**으로 깔았다. 그런데 `ts_rank_cd`는 범위 밀도(cover density) 점수이고 **BM25가 아니다** — 말뭉치 IDF도, 문서 길이 정규화도 없다. 이 항목을 문자 그대로 이행하려면 어휘 랭커를 직접 구현해야 한다.

**TF-IDF가 아니라 BM25를 구현한다.**

| 근거 | 내용 |
|---|---|
| 비용이 같다 | 두 공식이 요구하는 통계가 `tf` · `df` · `N` · `dl` · `avgdl`로 동일하다. BM25는 거기에 상수 두 개(`k1` · `b`)를 더 쓸 뿐이다. TF-IDF를 고르면 같은 노동으로 더 약한 결과를 얻는다 |
| 시장 용어다 | Lucene 6 / Elasticsearch 5.0(2016) 이후 어휘 검색 기본 랭커가 BM25다. 2026년에 "lexical baseline"은 사실상 BM25를 뜻한다 |
| 약한 상대는 실험을 망친다 | 길이 정규화가 없는 TF-IDF는 청크 길이 편차(500~1200자)가 있는 SEC 코퍼스에서 긴 청크로 편향된다. 그 arm이 지면 "TF-IDF가 약해서 졌다"뿐이고 배울 게 없다 |
| TF-IDF는 파라미터로 딸려온다 | BM25에서 `b=0`이면 길이 정규화가 꺼진다. 별도 랭커를 만드는 대신 **BM25가 TF-IDF 대비 더하는 것의 기여도를 분리**하는 arm이 된다. 단 IDF 공식이 다르므로 그 arm을 "TF-IDF"라고 라벨하지 않는다 |

역사 순서도 이 방향이다. IDF는 Spärck Jones(1972), TF-IDF는 Salton의 벡터 공간 모델로 정착했고, BM25는 Robertson의 확률 모델(1976)에서 출발해 Okapi 시스템으로 TREC-3(1994)에서 확정됐다. **BM25는 TF-IDF의 경쟁자가 아니라 후계자다.**

배치는 이렇게 나눈다.

- **M2.9 구현** — M2.1~M2.8 기준선을 끝낸 뒤 `app/retrieval/bm25.py`를 `lexical.py`와 같은 어댑터 시그니처로 붙인다. 상세 계약은 [M2 명세 15절](../../ko/m2-retrieval/02-spec.md).
- **M3.4 측정** — 승자는 recall@k · MRR · 지연 시간이 정한다. 구현 시점에 기본값을 정하지 않는다.

두 arm이 같은 `to_tsvector('english', index_text)`를 공유하므로 토크나이저·어간 추출·불용어가 동일하다. **차이는 순위 공식 하나뿐인 통제 실험**이 되고, 그 자체가 eval-report에 실을 발견이다. → **M2.9 · M3.4**

#### 5. CLI가 1급 인터페이스 + 크래시 금지 — `02 §VI.6`
*"CLI는 이런 엣지케이스로 테스트되며 처리되지 않은 트레이스백으로 절대 죽으면 안 된다"* — 빈 쿼리 · 무의미한 쿼리 · `k=0` · 없는 파일 · 깨진 JSON. 모든 경로가 설정 가능한 인자여야 하고 하드코딩 금지. → **얇은 CLI 추가**(Docker 없이 데모·테스트 가능) + **모든 퇴화 경로에 타입 있는 사유 반환.** → **M5**

#### 6. 증분 인덱싱 · 캐싱 · 로컬 HTTP API — `02 §IX` (보너스)
특히 **증분 인덱싱**(파일이 바뀌면 그 파일만 재색인)은 우리에게 없던 production 신호다. → **R1.1**

### 에이전트·관측성 (출처 `03`)

#### 7. MCP 서버 — `03 §V.2`
stdio + streamable HTTP 양쪽 지원, **툴 스키마에서 매뉴얼을 동적 생성**(서버가 바뀌면 매뉴얼도 자동으로 바뀜), 툴을 파이썬 함수로 호출 가능하게 노출.

**이전 계획은 "범위 밖: MCP (안 함)"이었다. 이 결정을 뒤집는다.** 시장 근거가 반대편에 있고 (아래 [시장 근거](#시장-근거)에서 MCP는 희소 트렌드), 이미 만든 retrieval 툴 위에 얹으면 ~1일이다. → **R1.1 (1순위)**

#### 8. 스텝 단위 사용량 추적 스키마 — `03 §V.3`, `§V.4`
```
StepMetrics    step · input_tokens · output_tokens · request_time_ms · api_url · model_name
               · llm_output(raw) · sandbox_input · sandbox_output · retries · timestamp
SolutionOutput iterations · total_requests · total_input_tokens · total_output_tokens
               · total_time_seconds · steps[] · system_prompt · error
```
`03 §VI.4.1`이 이유를 명시한다: *"이 필드들은 평가자가 에이전트의 추론 과정을 추적할 수 있도록 존재한다."* **system_prompt와 raw output까지 저장하는 게 핵심** — 숫자가 조작이 아님을 보이는 장치다.

→ **이 형태를 `runs`/`traces` 테이블에 거의 그대로 채용.** 스키마 → [02-design §3](02-design.md#3-관측성-스키마). → **M4**

#### 9. 하드 예산 강제 — `03 §VI.1`
iterations · **누적** input/output 토큰 · wall-clock을 초과하면 해당 태스크는 실패. *"토큰 한도는 한 태스크의 모든 반복에 걸쳐 누적된다"*, reasoning 토큰도 포함.

이전 계획이 자인한 갭 "budget enforcement 없음"을 이걸로 닫는다. **데모 비용 가드와 같은 코드다** ([03-scope §7](03-scope-and-narrative.md#7-배포--비용-제약)). → **M4**

#### 10. 프로바이더 추상화 — `03 §V.6`
멀티 프로바이더 · **프로바이더당 다중 API 키 + 로테이션**(필수) · fallback · 재시도. 그리고 채점 기준이 명시돼 있다: *"프로바이더 선택은 채점하지 않는다. 추상화·에러 처리·전체 아키텍처의 품질을 채점한다."*

→ provider 경계를 실제 2개로: OpenAI + **Mistral**(파리 로컬 어필 — 아래 시장 근거). → **R1.1**

#### 11. BENCHMARK_REPORT.md — `03 §V.7`
요구 항목: ① 설정(무엇을·왜 골랐나) ② 결과표(모델×태스크: pass/fail·iterations·in/out 토큰·wall-clock) ③ **프로바이더 신뢰성**(평균 응답시간·재시도 횟수·가용성) ④ 중간 지표 ⑤ **ablation**(같은 태스크·같은 모델로 before/after) ⑥ **데이터에 근거한 결론**(어느 모델을 왜 골랐고 어느 걸 왜 버렸나). 그리고 — ***"뒷받침하는 solution.json 파일들이 리포에 있어야 한다."***

→ **`docs/ko/eval-report.md`의 템플릿으로 그대로 채용.** 특히 **원시 산출물 커밋**(`data/eval_runs/`)이 숫자를 믿게 만드는 장치다. → **M3 · M6**

#### 12. 모든 실패 모드에 명시적 피드백 — `03 §V.1`
*"LLM은 무슨 일이 일어났는지 절대 추측하게 두면 안 된다. 침묵 실패는 환각된 관측과 낭비된 반복으로 이어진다."* 열거된 상황: 코드 블록 없음 · 형식이 깨졌지만 해석함(어떻게 해석했는지 설명) · 타임아웃으로 출력이 부분적 · 크기 제한으로 잘림 · 편집이 문법 오류를 냄.

→ 우리 노드도 **모든 퇴화 경로에 타입 있는 사유를 반환**한다: 검색 0건 · 관련도 미달 · 컨텍스트 절단 · 스키마 위반. → **M4**

### 구조화 출력 (출처 `01`)

#### 13. 프롬프트로 구조화 출력을 기대하는 건 신뢰 불가 — `01 §V.3.3`
> *"당신의 솔루션은 모델이 프롬프트로부터 올바른 JSON을 자발적으로 생성하는 것에 의존해서는 안 된다. 함수 정의로 모델에 프롬프트를 주고 구조화된 출력을 기대하는 것은 신뢰할 수 없으며, **우리가 여기서 개발하기를 기대하는 역량이 아니다.**"*

42는 이걸 로짓 마스킹(constrained decoding)으로 풀게 한다. 우리는 그 **원칙**만 가져온다 — **프롬프트가 아니라 코드가 스키마를 보증한다.** 구현은 **검증 → 복구 → 거부** 사다리로 fail-closed. 무음 통과 금지. (직접 구현하지 않는 이유는 [아래](#의도적으로-안-가져오는-것)) → **M4**

#### 14. 신뢰성을 수치로 보고 — `01 §V.5`
**100% 유효 JSON** · **90%+ 정확한 함수 선택과 인자 추출**. 즉 구조화 출력의 신뢰성 자체가 측정 대상이다. 우리 eval에는 현재 retrieval 지표뿐이다. → **스키마 유효율 · 라벨 선택 정확도** 추가. → **M3 · M4**

#### 15. 작은 모델 + 제약 ≈ 큰 모델 — `01 §V.5`
*"Qwen3-0.6B는 5억 파라미터뿐이지만 적절한 constrained decoding으로 훨씬 큰 모델에 필적하는 신뢰성을 얻는다. 이는 원시 모델 크기보다 구조적 안내가 강력함을 보여준다."* → 판정 노드에 **작은/싼 모델 경로**를 둔다. [저비용 배포](03-scope-and-narrative.md#7-배포--비용-제약)를 직접 뒷받침. → **M4 · M7**

### 공통 위생 (`01`·`02`·`03` 전부)

#### 16. 리포 위생과 영문 README
- **Makefile**: `install` · `run` · `debug` · `clean` · `lint` (`01 §IV.2`, `02 §V.2`)
- **타입 힌트 + mypy** 통과, PEP 257 docstring (`01 §IV.1`, `02 §V.1`)
- **모든 에러를 우아하게** — *"리뷰 중 처리되지 않은 예외로 죽으면 비기능으로 간주된다"* (`01 §IV.1`)
- **영문 README 고정 섹션**: Description · Instructions · **Resources(+ AI를 어디에 썼는지 명시)** · System architecture · Design decisions · **Challenges faced** · Performance analysis · Testing strategy · Example usage (`01 §VI`, `02 §VIII`, `03 §VII` — 셋이 거의 동일하게 요구)

현재 `README.md`는 `# TBA` 한 줄이다. → **이 섹션 목록을 그대로 채용.** → **M6**

#### 17. 보너스는 mandatory가 다 통과한 뒤에만 — `02 §IX`
> *"보너스는 mandatory 파트 전체가 검증된 뒤에만 채점된다. mandatory가 완전히 통과하기 전까지 보너스는 전혀 평가되지 않는다."*

→ **릴리즈 원칙으로 채용.** [00-plan §3](00-plan.md#3-릴리즈-원칙). → **전체**

---

## 의도적으로 안 가져오는 것

전부 **자체 판단 근거**다. "42에서 따로 한다"가 아니다 — 42는 안 하기로 했다.

| 안 가져오는 것 | 이유 |
|---|---|
| `03`의 **코드 실행 샌드박스 · SWE-bench · MBPP** | 문서 RAG 시스템과 도메인이 무관하다. 넣으면 flagship의 초점([retrieval 품질·eval·가드레일](03-scope-and-narrative.md))이 흐려진다 |
| `01`의 **로짓 마스킹 직접 구현** | transformers·outlines·pytorch를 **금지당한 상태에서만** 성립하는 학습 과제다. 실제 프로바이더는 이미 스키마 보증 구조화 출력을 제공한다 → 직접 구현이 정당화되지 않는다. **원칙(#13)은 가져오고 구현만 fail-closed 사다리로** |
| **GraphRAG** | 시간. 단 문서에 "다음 확장"으로 명시한다 — 아래 시장 근거가 희소가치로 지목했으므로 **인지하고 있음은 보여준다** |

---

## 시장 근거

> 2026-08 기준 웹 리서치 종합. 위 17항목 중 무엇을 R1에 넣을지의 판단 근거.

### 3층 구조 — 뭐가 기본이고 뭐가 차별점인가

**🎫 Table stakes (입장권 — 여기선 안 갈린다)** RAG + vector DB(pgvector/Qdrant/Weaviate) · LangChain/LangGraph/LlamaIndex · FastAPI + Docker · LLM API(OpenAI/Claude/**Mistral**/Gemini) · 프롬프트 엔지니어링 · structured output → **우리는 이 층을 거의 다 갖췄다. "지원 자격"이지 "합격 사유"가 아니다.**

**⭐ 진짜 차별점 (hireable 신호 — 여기서 갈린다)** — 모든 소스가 일치
- **"Production RAG is a search-quality problem"** — retrieval 품질을 **측정·개선**하는 능력이 **#1 차별점**
- **Evaluation** — hallucination rate, 다수 테스트 케이스, RAGAS, 회귀 감지
- **README writeup** — *"chunk size ablation, retrieval evaluation, what failed and why"* (리크루터 6~7초 스캔에서 이기는 것)
- **Observability** — Langfuse/Arize, cost optimization
- **Production signals** — 실패 처리, 데이터 구조화, 배포(노트북 아님), 시스템 연결

→ **42-02가 요구하는 recall@k·성능예산·ablation(#1~#4)과, 42-03이 요구하는 관측성·예산·벤치마크 리포트(#8·#9·#11)가 정확히 이 층이다.** 그래서 R1에 넣는다.

**🚀 앞서가는 트렌드 (희소성 = 강한 차별화)**
- **Agentic RAG** — plan → retrieve → critique → rewrite 루프 (우리 CRAG가 첫발)
- **GraphRAG / Knowledge Graph** — *"most searched-for architecture this quarter"*. 핵심: *"engineers want GraphRAG but don't know how to implement it"* → 할 줄 알면 희소가치. **단 시간이 없다 → 언급만**
- **MCP** — 툴/메모리 표준 프로토콜 → **42-03이 필수로 요구(#7). 이전의 "범위 밖" 결정을 뒤집은 근거**

### 파리/유럽 특화

- **회사:** Mistral, Doctolib, Alan, Qonto, Hugging Face 등 스케일업
- **급여:** 65~180K€ gross (Paris 스케일업 up to 170K€ + stock), 2026 +12~15% 상승
- **명시 스택:** Langfuse/Arize(observability) · LangSmith/RAGAS(eval) · vector DB · LangGraph
- **어필 포인트:** **Mistral을 provider로 넣으면 로컬 어필**(→ #10). RAGAS 평가·observability를 명시적으로 원함

### GitHub 유사 프로젝트 패턴

**포화된 도메인 (도메인만으론 차별화 X):** legal RAG · medical guidelines · generic docs chat **우리 방향 검증:** `rag-evals` — *"CI-friendly RAG eval: retrieval metrics, LLM-as-judge, regression gate that fails your build"* → **"eval/retrieval 품질을 star로"가 독립 프로젝트로 존재 = 이 각도가 시장에서 통한다.**

### 한 줄 결론

> 기본 스택은 흔하다. **차별점은 "retrieval 품질을 데이터로 증명"**. 도메인으론 차별화 안 된다 — 차별화는 **"어떻게 만들었나"**(eval·품질·가드레일·대비 데모)다.

### 출처

- [kore1 — How to Hire RAG Engineers 2026](https://www.kore1.com/hire-rag-engineers-2026/)
- [dextralabs — 10 RAG Projects That Teach Retrieval](https://dextralabs.com/blog/rag-projects-retrieval/)
- [searchqualify — AI Skills EU Job Listings 2026](https://searchqualify.com/blog/ai-skills-employers-actually-want-2026-eu-job-listings)
- [dev.to — 5 AI Portfolio Projects That Get You Hired 2026](https://dev.to/klement_gunndu/5-ai-portfolio-projects-that-actually-get-you-hired-in-2026-5bpl)
- [getintalent — AI Engineer Paris (LLM/RAG/agents)](https://getintalent.com/metiers/ai-engineer/)
- [hyperight — GraphRAG & MCP New Standard 2026](https://hyperight.com/agentic-data-architecture-graphrag-mcp-2026/)
- [neo4j — Agentic RAG](https://neo4j.com/blog/agentic-ai/what-is-agentic-rag/)
