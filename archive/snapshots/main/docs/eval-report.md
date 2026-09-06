# Evaluation Report

## 1. 검색 평가 (Retrieval, Step 9)

**골든셋:** `golden/retrieval_questions.json` — 16문항, 각 질문에 정답 섹션(`doc_id §section`) 라벨.
**지표:**
- **hit_rate@k** (recall@k): top-k 안에 정답 섹션이 하나라도 있는 문항 비율
- **MRR** (Mean Reciprocal Rank): 첫 정답의 순위 `1/rank`의 평균 — 정답을 얼마나 위에 올렸나

**실행:** `EMBEDDING_PROVIDER=st uv run python -m app.evals.retrieval_eval`

### 결과 (k=5, n=16)

| config | hit_rate | MRR |
| --- | --- | --- |
| vector (pgvector 코사인) | 0.938 | 0.875 |
| lexical (tsvector/ts_rank, OR) | 1.000 | 0.927 |
| hybrid (vector + lexical, RRF) | 1.000 | 0.896 |
| **hybrid + rerank (cross-encoder)** | **1.000** | **1.000** |

### 해석

1. **hybrid + rerank가 명백한 승자** — MRR 1.000, 즉 16문항 **전부 정답을 1위**로 반환. 최종 파이프라인으로 채택.
2. **"하이브리드가 항상 낫다"는 이 데이터에선 거짓** — `hybrid`(MRR 0.896)가 `lexical` 단독(0.927)보다 **낮다**. 벡터 검색이 상대적으로 노이지해서 RRF 융합 순위를 끌어내렸다. → 하이브리드의 가치는 "매 쿼리 최고점"이 아니라 **rerank가 밟고 올라설 발판** 제공에 있다.
3. **rerank 레이어가 결정적으로 검증됨** — 같은 hybrid 후보를 cross-encoder로 재정렬하니 MRR 0.896 → 1.000. 이 프로젝트에서 리랭킹을 넣은 근거.
4. **vector 단독은 1문항을 top-5에서도 놓침**(hit_rate 0.938). 렉시컬이 정확 용어/숫자에 강해 이를 메운다 — 하이브리드를 쓰는 이유.

### 한계 (정직)

- **n=16, 합성 데이터.** 질문 어휘가 정답 섹션과 겹치는 경향이 있어 렉시컬 단독도 hit_rate 1.0을 찍는다. MRR 1.0은 "파이프라인이 건전하다"는 신호이지 프로덕션급 정확도 증명이 아니다.
- 더 어렵거나 패러프레이즈된 질문(어휘 안 겹침)에선 벡터·하이브리드의 상대적 이점이 커질 것으로 예상. 이 평가는 이 코퍼스의 특성을 반영한다.

### 미뤄둔 결정 판정

- **fusion 방식:** hybrid + rerank 채택 (MRR 1.0).
- **rerank 채택 여부:** yes (0.896 → 1.000).
- **빈-헤딩 섹션 인덱싱:** 유지 — 모든 config에서 hit_rate 1.0이라 검색을 해치지 않음.

---

## 2. 판정 평가 (Claim, Step 13)

**골든셋:** `golden/claim_support_cases.json` — 16주장, 4라벨 각 4개(하드 네거티브 포함).
**지표:** 라벨 정확도 + 4×4 혼동행렬 + **하드 네거티브 정확도**(SUPPORTED 아닌 것 = 지어내기 유혹을 얼마나 막나).
**실행:** `PRIMARY_LLM_PROVIDER=openai uv run python -m app.evals.claim_eval` (모델: gpt-4.1-mini)

### 결과 (n=16)

| 지표 | 값 |
| --- | --- |
| accuracy | 0.875 (14/16) |
| hard-negative accuracy | 0.833 (10/12) |

혼동행렬 (행=골든, 열=예측):

| 골든 \ 예측 | SUP | CON | NID | PART |
| --- | --- | --- | --- | --- |
| SUPPORTED | **4** | | | |
| CONTRADICTED | | **4** | | |
| **NOT_IN_DOCS** | | | **4** | |
| PARTIALLY_SUPPORTED | | 2 | | **2** |

### 해석
- **NOT_IN_DOCS 4/4 완벽** — 문서에 없는 주장을 단 하나도 SUPPORTED로 지어내지 않음. 이 프로젝트 논지(가드레일)의 정량 증거.
- SUPPORTED·CONTRADICTED 각 4/4.
- **유일 오류: PARTIALLY_SUPPORTED 2건 → CONTRADICTED.** 부분 모순을 전체 모순으로 collapse. **오류 방향이 안전**(오승인이 아니라 엄격). 상세 → `docs/failure-analysis.md`.

## 3. 체크리스트 평가 (Checklist, Step 13)

**골든셋:** `golden/review_checklist_cases.json` — 4 시나리오, 항목별 요건 PASS/FAIL + overall.
**지표:** item 정확도 + overall 정확도.
**실행:** `PRIMARY_LLM_PROVIDER=openai uv run python -m app.evals.checklist_eval` (gpt-4.1-mini)

### 결과 (n=4 시나리오, 12 항목)

| 지표 | 값 |
| --- | --- |
| item accuracy | 0.917 (11/12) |
| overall accuracy | 1.000 (4/4) |

| 시나리오 | 항목 | overall(골든→예측) |
| --- | --- | --- |
| RC-001 | 3/3 | PASS → PASS ✓ |
| RC-002 | 2/2 | FAIL → FAIL ✓ |
| RC-003 | 3/4 | FAIL → FAIL ✓ |
| RC-004 | 3/3 | FAIL → FAIL ✓ |

### 해석
- **overall 4/4 완벽** — 시나리오 전체 판정(PASS/FAIL)이 다 맞음.
- item 11/12 — RC-003에서 항목 1개 오판. 단 overall은 "요건 하나라도 FAIL이면 FAIL"이라 그 오판이 결과를 뒤집지 않음(golden도 FAIL).

## 4. 회귀 (Regression)
`app/evals/regression.py` — 지표를 `evals/baseline.json`에 저장하고 다음 실행과 델타 비교. 음수 델타 = 회귀.
