# 강의·영상 학습 자료 정리

> 기준: **취업(AI/백엔드 엔지니어) 지식 극대화.** 금액 무관(구매 후 무제한). 시간이 진짜 제약이므로 "취업 ROI/시간"으로 판단.

## 결론 (먼저)

| 자료 | 결정 | 한 줄 이유 |
| --- | --- | --- |
| **인프런: AI 에이전트로 구현하는 RAG (LangGraph)** — URL2 | ✅ **구매 #1 (최우선)** | 에이전트=현재 취업 최고 수요. 프로젝트 Step 11 필수. **전부 새 지식** |
| **인프런: RAG마스터 기초~고급 (평가)** — URL1 | ✅ **구매 #2 (강력 추천)** | 평가 엄밀성(LLM-as-Judge, NDCG/mAP) + 고급검색(쿼리확장·맥락압축). **지식 갭 메움**, Step 13에 직결 |
| **인프런: GraphRAG (Neo4j)** — URL3 | ❌ **스킵 (지금은)** | 지식그래프=니치 + Neo4j/Cypher 큰 시간투자 + 현재 벡터-RAG 트랙과 직교. 그래프 role 노릴 때 재고 |
| freeCodeCamp / KodeKloud / deeplearning.ai (무료) | 참고 | 이미 봄. 아래 참조 |

> **이전 plan은 "LangGraph 하나만"이었음. 취업 렌즈 + 무제한 접근으로 재평가 → URL1 추가.** URL1은 우리가 손으로 구현한 걸 검증 + 우리가 안 한 것(LLM-as-Judge, NDCG, 쿼리확장, 맥락압축, 다국어)을 채운다.

---

## 1. 무료 영상 (이미 봄 / 참고용)

| 영상 | 역할 | 프로젝트 매핑 |
| --- | --- | --- |
| **KodeKloud RAG Crash Course lab** (`swvzKSOEluc`) | RAG 한 바퀴 손 감각 | Step 1 (lab 재현) |
| **freeCodeCamp "Learn RAG From Scratch"** (LangChain, `sVcwVQRHIc8`) | 개념 지도(얕음): indexing/routing/retrieval/generation | Step 2~3 개념. Step 6부터 도움 안 됨 |
| **deeplearning.ai RAG module 2** | TF-IDF / BM25 직관 | Step 6 개념 보강 (RRF·tsvector 구현은 없음) |

→ **Step 6부터 무료 영상은 말라붙는다.** 그 지점부터 유료 강의(아래) + docs + 직접 구현.

---

## 2. 구매 강의 상세 + 섹션→스텝 매핑

### ✅ 구매 #1 — AI 에이전트로 구현하는 RAG (LangGraph) [URL2]
- **구매 시점:** Step 10 끝나고 **즉시** (Step 11 직전, just-in-time)
- **왜 취업:** 에이전트/LangGraph는 지금 채용 시장 최고 수요. Self/Corrective/Adaptive RAG, ReAct, HITL = "AI 에이전트 엔지니어" JD 단골

| 섹션 | 내용 | 우선순위 | 프로젝트 |
| --- | --- | --- | --- |
| §2 Tool Calling / Agent | 도구 호출, custom tool, vector store as tool, agent | 🟡 취업엔 중요(tool calling), 우리 프로젝트는 tool-heavy 아님 | 배경 |
| **§3~4 LangGraph 기본** (StateGraph, 조건부 엣지, Reducer, Feedback Loop) | | 🔴 **필수** | **Step 11 핵심** |
| §5 ReAct 에이전트 (Tool/ToolNode, MemorySaver) | | 🟡 취업 배경, 우리 프로젝트 선택 | 참고 |
| **§6 Adaptive / Self / Corrective RAG, Sub-graph, HITL** | | 🔴 **중요** | **Step 11 "advanced behavior"** + 향후 개선 |
| §7 Final Project (법률 문서 에이전트 RAG) | | 🟢 참고 | 통합 예시 |

### ✅ 구매 #2 — RAG마스터: 기초부터 고급까지 (평가) [URL1]
- **구매 시점:** Step 9~13 즈음 (평가 파트가 지금 우리 작업과 겹침). **선택 시청** — 이미 손으로 구현한 기초는 배속/스킵
- **왜 취업:** 대부분 "RAG 만들 줄"은 아는데 **"엄밀히 평가할 줄"은 드물다** → 차별점. LLM-as-Judge는 실무 필수

| 섹션 | 내용 | 우선순위 | 프로젝트 |
| --- | --- | --- | --- |
| §1~2 intro / RAG 컴포넌트 (loader·splitter·embedding·vectorstore·retriever·LLM) | | 🟢 이미 앎 → 배속/스킵 | 리뷰 |
| §3 LCEL (Prompt+LLM+**PydanticOutputParser**, Runnable) | | 🟡 구조화 출력 관련 | Step 10 참고 |
| §4 데이터 처리·임베딩 (다양한 loader, **semantic chunking**, OpenAI/HF/Ollama 임베딩, **다국어 RAG**) | | 🟡 다국어·시맨틱청킹은 새 지식 | 향후 |
| **§5 벡터스토어 + IR 평가** (Chroma/FAISS, BM25Retriever, **Hybrid(EnsembleRetriever)**, 테스트셋 합성, **Hit Rate / MRR / Precision·Recall / mAP / NDCG**) | | 🔴 **핵심** | **Step 9** (검증 + mAP·NDCG 확장) |
| **§6 고급 검색** (**쿼리 확장** Multi-Query/Decomposition, **Re-rank** Cross-Encoder/LLM, **맥락 압축** Contextual Compression) | | 🔴 **중요** | **Step 7(rerank)** + 향후 쿼리개선/압축 |
| **§7 LLM 답변 평가** (정량: Embedding Distance/Cross-Encoder/Rouge + **LLM-as-Judge**: QA/Criteria Eval) | | 🔴 **핵심** | **Step 13** (claim/답변 평가) |

### ❌ 스킵 — GraphRAG (Neo4j) [URL3]
- Neo4j·Cypher·지식그래프·Text2Cypher·프로젝트 4개(뉴스/ETF/10K/법률). 내용 좋지만:
  - **니치**: 벡터-RAG보다 채용 수요 좁음(지금은)
  - **큰 시간투자**: Cypher 문법 + Neo4j 인프라 = 별도 트랙
  - **직교**: 우리 프로젝트(pgvector 하이브리드)와 겹침 거의 0
- → **지금 스킵. 그래프 DB/지식그래프 role을 구체적으로 노릴 때 재고.**

---

## 3. 시청 전략 (공통)

1. **Just-in-time**: 쓰기 직전에 본다. LangGraph는 Step 11 직전, 평가 파트는 Step 9·13 즈음.
2. **선택 시청**: 이미 손으로 구현한 건(loader/splitter/embedding/vectorstore/hybrid/rerank 기초) 배속·스킵. **새 지식에 시간 몰기.**
3. **Gradio 챕터는 이제 Step 17(데모)에 쓸 거라 봐도 됨** — 원래 "백엔드라 스킵"이었지만, Phase B 데모를 Gradio+HF Spaces로 확정(plan Step 17). 강의의 Gradio 예시가 그대로 참고됨. (챗봇 히스토리 등 우리 데모에 불필요한 건 여전히 스킵)
4. **우선순위**: URL2 §3~4, §6 → URL1 §5, §6, §7 순으로 "🔴" 먼저.

## 4. 취업 관점 한 줄 요약
> **URL2(에이전트/LangGraph)** = 지금 가장 뜨거운 수요 스킬 + 프로젝트 필수. **URL1(평가)** = 남들이 약한 "평가 엄밀성" 차별점. 둘이면 "만들 줄 + 평가할 줄 + 에이전트화할 줄" 아는 현대 RAG 엔지니어 셋이 완성된다. **GraphRAG는 나중.**
