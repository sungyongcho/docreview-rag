# M2 구현 — 검색, 근거에서 바깥으로 쌓기

## 데이터베이스에 9,172개 청크가 있다. 이제 찾아야 한다

M1이 끝났다. PostgreSQL에 문서 20개와 청크 9,172개가 들어 있고, 모든 청크가 원문 좌표와 인용 레이블을 달고 있다. `embedding` 열은 전부 `NULL`이다.

이제 "NVIDIA의 2024년 위험 요인이 뭐야?"라는 질문에 관련 청크를 찾아줘야 한다.

검색 코드는 **그럴듯하게 만들기는 쉽고 믿을 수 있게 만들기는 어렵다.** 임베딩 라이브러리를 붙이고 코사인 유사도 상위 10개를 뽑으면 30분이면 동작한다. 문제는 그게 정말 좋은지 아무도 모른다는 것이다.

그래서 이 장은 순서를 이렇게 잡는다. **근거 한 조각의 정체성을 먼저 고정하고**, 성격이 다른 두 검색 경로를 각각 만든 뒤, 마지막에야 하나의 요청으로 조립한다.

## 왜 검색 경로가 둘인가

벡터 검색 하나로 끝내지 않는 이유가 있다. 두 방식이 잘하는 게 다르다.

| | 벡터 검색 (밀집) | 어휘 검색 (희소) |
|---|---|---|
| 방식 | 의미 임베딩 코사인 유사도 | PostgreSQL 전문 검색 |
| 강점 | 표현이 달라도 찾는다 | 정확한 용어·숫자·고유명사 |
| 약점 | `26,974` 같은 숫자에 약하다 | 동의어를 모른다 |

10-K 검색에서는 둘 다 필요하다. "공급망 위험"처럼 표현이 다양한 질문에는 벡터가 낫고, "Item 7A"나 특정 금액처럼 정확한 토큰에는 어휘 검색이 낫다.

그래서 둘을 따로 만들고 **RRF(Reciprocal Rank Fusion)** 로 합친다. 점수를 섞는 게 아니라 **순위**를 섞는데, 그 이유는 M2.5에서 다룬다.

## 이 장에서 만들 것

| 단계 | 개념 | 소스 | 기본 테스트 |
|---|---|---|---|
| M2.1 | 근거와 필터는 엄격한 값 | `types.py` | `test_01_contract.py` |
| M2.2 | 임베딩은 비동기 공급자 경계 | `embeddings.py` | `test_02_embeddings.py` |
| M2.3 | 밀집 검색은 정확한 코사인 SQL | `vector.py` | `test_03_vector.py` |
| M2.4 | 어휘 검색은 PostgreSQL FTS | `lexical.py` | `test_04_lexical.py` |
| M2.5 | 융합은 순위를 사용 | `hybrid.py` | `test_05_hybrid.py` |
| M2.6 | 재순위화는 선택적 공급자 | `rerank.py` | `test_06_rerank.py` |
| M2.7 | 프로덕션 구성이 하나의 세션을 소유 | `service.py`, `__main__.py` | `test_07_service.py` |
| M2.8 | 새 데이터베이스에서 pgvector를 먼저 활성화 | `bootstrap.py` | `test_08_postgres.py` |

요청 하나가 흐르는 길은 이렇다.

```text
null Chunk.embedding -> embed_missing_chunks -> populated document vectors

query + filters -> embedding provider -> vector_search  ---+
query + filters ---------------------> lexical_search ---+-> rrf_fuse -> RetrievalResult

candidate hits + optional provider -> rerank_hits
bootstrap_schema -> pgvector extension -> tables -> live PostgreSQL proof
```

두 검색 경로는 **순위 융합에서만 만난다.** 그전까지는 서로를 모른다. 덕분에 각각 따로 테스트하고 따로 교체할 수 있다. 재순위화는 별도 도우미이고, 기본 서비스는 RRF 이후 `RetrievalResult`에서 끝난다.

## 시작 조건

잠긴 환경을 설치하고 M1.4 경계부터 검증한다.

```bash
uv sync --group dev
uv run pytest tests/db -q
```

이 장의 참조 테스트는 데이터베이스 없이 PostgreSQL SQL을 컴파일해서 검증한다. M2.8만 실제 데이터베이스를 3초 프로브하고, 연결이 안 되면 그 테스트만 건너뛴다.

체크포인트마다 설계상의 압력을 먼저 읽고, 정식 `app/...` 경로에 코드를 작성한 다음 바로 아래 명령을 실행한다. 언제나 코드가 테스트보다 먼저 나온다. `zero`에서 직접 작업하고 `_mine.py`를 만들거나 테스트 대상을 우회하지 않는다.


---

## 튜토리얼 — 아홉 번에 나눠 만든다

M2는 파일 열두 개를 만든다. 한 번에 앉아서 끝낼 분량이 아니라, 한 번에 하나씩 끝내고 테스트로 닫는 아홉 구간으로 나눠 뒀다. 각 문서는 **읽고 구현하는 데 30분 안쪽**을 목표로 한다.

| 문서 | 다루는 구간 | 만드는 파일 | 대략 |
|---|---|---|---|
| [1. 계약](tutorial/01-contracts.md) | M2.1 | `types.py`, 임시 `__init__.py` | 20분 |
| [2. 임베딩](tutorial/02-embeddings.md) | M2.2 | `embeddings.py` | 30분 |
| [3. 검색 경로](tutorial/03-retrieval-paths.md) | M2.3–M2.4 | `vector.py`, `lexical.py` | 30분 |
| [4. 융합](tutorial/04-fusion.md) | M2.5–M2.6 | `hybrid.py`, `rerank.py` | 25분 |
| [5. 서비스](tutorial/05-service.md) | M2.7 | `service.py`, `__main__.py`, `__init__.py` | 30분 |
| [6. 라이브 PostgreSQL](tutorial/06-live-postgres.md) | M2.8 + 전체 인수 | 새 파일 없음 | 20분 |
| [7. BM25](tutorial/07-bm25.md) | M2.9 | `bm25.py`, 단어 통계 테이블 | 35분 |
| [8. 로컬 임베딩](tutorial/08-local-embeddings.md) | M2.10 | `sbert.py` | 30분 |
| [9. cross-encoder](tutorial/09-cross-encoder.md) | M2.11 | `cross_encoder.py` | 30분 |

순서대로 따라간다. 각 구간 끝의 집중 테스트가 통과하지 않으면 다음으로 넘어가지 않는다.

아래 [완성 기준본](#완성-기준본--정식-구현-전체)은 학습을 건너뛰는 지름길이 아니라 **자기 구현을 맞춰 보는 기준**이다. 각 구간을 끝낸 뒤에 대조하고, 그 전에는 열지 않는다.

---

## 열한 구간을 똑같이 어렵게 읽지 않는다

열한 개라 많아 보이지만 성격이 셋으로 갈린다. 그 구분을 먼저 잡아 두면 어디에 시간을 쓸지가 정해진다.

| 성격 | 체크포인트 | 학습 행동 |
|---|---|---|
| 계약 선언 | M2.1 | **모델 선언 작성** — 어떤 잘못된 상태가 표현 불가능해지는지만 확인 |
| 알고리즘 | M2.3, M2.4, M2.5, M2.9 | 질의를 **직접 구현** — 여기에 시간을 쓴다 |
| 경계와 배치 | M2.2, M2.6, M2.7, M2.8, M2.10, M2.11 | **구조 작성 후 호출 순서 검토** |

시간을 아껴야 한다면 M2.5의 RRF에 가장 오래 머문다. 나머지 열이 전부 그 한 번의 합산을 위한 준비다.

## 처음 만나는 개념

RAG가 처음이라면 아래 넷은 이 장에서 처음 볼 가능성이 높다. 코드를 읽기 전에 한 번 정리해 둔다.

**임베딩.** 텍스트를 고정 길이 실수 벡터로 바꾼 것이다. 이 프로젝트에서는 청크 하나가 384개의 숫자가 된다. 이 숫자들은 사람이 해석할 수 있는 값이 아니고, 의미가 비슷한 텍스트끼리 벡터 공간에서 가까워지도록 학습된 모델의 출력일 뿐이다. 중요한 성질은 하나다 — **같은 모델로 만든 벡터끼리만 비교가 성립한다.** 문서를 A 모델로, 질문을 B 모델로 임베딩하면 두 벡터는 아무 관계가 없다.

**코사인 유사도.** 두 벡터가 이루는 각도로 유사도를 잰다. 길이가 아니라 방향만 본다. 긴 문단과 짧은 문장이 같은 주제를 말하면 길이는 달라도 방향은 비슷하므로, 텍스트 길이에 휘둘리지 않는다. 값은 −1에서 1 사이이고 1에 가까울수록 비슷하다.

**밀집과 희소.** 임베딩 검색을 밀집(dense)이라 부른다. 벡터의 거의 모든 자리에 0이 아닌 값이 들어 있기 때문이다. 반대로 어휘 검색은 어휘 사전 크기의 벡터에서 실제 등장한 단어 자리만 값이 있어 희소(sparse)하다. 이름은 저장 형태에서 왔지만, 실제 차이는 **의미로 찾느냐 글자로 찾느냐**다.

**재순위화(rerank).** 위 두 검색은 질문과 문서를 **각각 따로** 벡터로 만들어 비교한다(bi-encoder). 빠르지만 질문과 문서를 나란히 놓고 읽지는 못한다. 재순위화 모델은 질문과 후보를 **함께** 입력받아 관련성을 다시 매긴다(cross-encoder). 정확하지만 후보 하나마다 모델을 호출해야 해서 비싸다. 그래서 상위 후보 몇 개에만 쓴다. 이 장에서는 경계만 만들고 켜지 않는다 — 켤지 말지는 M3에서 측정으로 정한다.

## M2.1 — 근거를 흐릴 수 없게 만든다

검색 결과 하나가 무엇인지 먼저 고정한다. 히트는 청크 ID와 점수만이 아니라 소스 좌표와 인용 레이블을 함께 들고 다니고, 어느 필드도 나중에 채워 넣을 수 없다. 필터도 같은 원칙이라 ticker와 연도는 자유 문자열이 아니라 검증된 값이다. 이 계약이 흔들리면 뒤의 모든 순위가 무엇에 대한 순위인지 말할 수 없게 된다.

**문서:** [1. 계약](tutorial/01-contracts.md) · **통과 기준:** `uv run pytest tests/retrieval/test_01_contract.py -q`

## M2.2 — 공급자 I/O와 영속화를 분리한다

임베딩은 네트워크 호출이고 저장은 트랜잭션이다. 이 둘이 겹치면 느린 HTTP 응답을 기다리는 동안 데이터베이스 트랜잭션이 열린 채로 남는다. 그래서 호출과 저장을 배치 단위로 갈라 놓고, 그 사이에 청크 텍스트가 바뀌었을 가능성을 stale 가드로 막는다. 결정론적 오프라인 공급자를 함께 만드는 이유도 여기 있다 — 테스트가 네트워크에 의존하면 검색 품질을 측정할 수 없다.

**문서:** [2. 임베딩](tutorial/02-embeddings.md) · **통과 기준:** `uv run pytest tests/retrieval/test_02_embeddings.py -q`

## M2.3 — 정확한 코사인 검색을 기준선으로 세운다

첫 벡터 검색은 근사 인덱스 없이 정확한 코사인으로 만든다. 9,172개 규모에서는 전수 비교가 충분히 빠르고, 더 중요하게는 **근사 인덱스를 나중에 켤 때 비교할 기준이 생긴다.** HNSW 같은 근사 인덱스는 속도를 얻는 대신 정답 이웃 일부를 놓치는데, 기준선이 없으면 얼마나 놓치는지 말할 수 없다. 여기서 그 기준선을 만든다.

**문서:** [3. 검색 경로](tutorial/03-retrieval-paths.md) · **통과 기준:** `uv run pytest tests/retrieval/test_03_vector.py -q`

## M2.4 — 안전한 어휘 검색 바닥을 깐다

벡터 검색은 `26,974` 같은 정확한 토큰에 약하다. PostgreSQL 전문 검색이 그 바닥을 받친다. 여기서 조심할 것은 질의 문자열 처리다. 사용자 입력을 그대로 전문 검색 문법에 넣으면 구문 오류로 요청 전체가 죽는다. 그래서 입력을 토큰으로 쪼개 안전하게 조립한다.

**문서:** [3. 검색 경로](tutorial/03-retrieval-paths.md) · **통과 기준:** `uv run pytest tests/retrieval/test_04_lexical.py -q`

## M2.5 — 점수가 아니라 순위를 합친다

두 검색기의 점수는 단위가 다르다. 코사인은 −1에서 1 사이이고 전문 검색 순위는 상한이 없다. 이 둘을 정규화해서 더하면 정규화 방식이 결과를 좌우하고, 한쪽 검색기의 점수 분포가 바뀌는 순간 융합 결과가 조용히 흔들린다. RRF는 점수를 아예 버리고 **순위만** 쓴다. 각 목록에서 r번째면 `1 / (rrf_k + r)`를 기여하고, 그 합으로 다시 정렬한다. 단위가 없으니 정규화도 필요 없다.

**문서:** [4. 융합](tutorial/04-fusion.md) · **통과 기준:** `uv run pytest tests/retrieval/test_05_hybrid.py -q`

## M2.6 — 재순위화는 선택으로 남긴다

재순위화 경계는 만들지만 기본 경로에서 켜지 않는다. 켜면 좋아 보이지만 호출당 비용과 지연이 붙고, **좋아졌는지 지금은 측정할 수 없다.** 측정 장치는 M3에서 만든다. 그때까지는 교체 가능한 경계로만 두고, 기본 서비스는 RRF 결과에서 끝난다.

**문서:** [4. 융합](tutorial/04-fusion.md) · **통과 기준:** `uv run pytest tests/retrieval/test_06_rerank.py -q`

## M2.7 — 프로덕션 요청 하나로 조립한다

앞의 조각들을 하나의 요청으로 묶는다. 핵심은 세션 소유권이다. 벡터 검색과 어휘 검색이 각자 세션을 열면 같은 요청 안에서 서로 다른 스냅샷을 볼 수 있다. 그래서 구성 단계가 세션 하나를 만들어 양쪽에 건네고, 검색 함수들은 세션을 만들지 않는다.

**문서:** [5. 서비스](tutorial/05-service.md) · **통과 기준:** `uv run pytest tests/retrieval/test_07_service.py -q`

## M2.8 — PostgreSQL을 부트스트랩하고 끝까지 증명한다

앞의 일곱 구간은 데이터베이스 없이 SQL을 컴파일해서 검증했다. 마지막으로 실제 PostgreSQL에 붙여 전체 경로를 한 번 통과시킨다. 새 데이터베이스에서는 pgvector 확장을 먼저 켜야 테이블이 만들어지므로, 부트스트랩 순서 자체가 이 구간의 내용이다.

**문서:** [6. 라이브 PostgreSQL](tutorial/06-live-postgres.md) · **통과 기준:** `uv run pytest tests/retrieval/test_08_postgres.py -q`

## M2.9 — 말뭉치 통계로 순위를 매기고, 그다음 측정한다

M2.4의 어휘 바닥은 문서 하나를 고립시켜 채점한다. BM25는 그 바닥이 볼 수 없는 것을 더한다. 한 단어가 코퍼스 전체에서 얼마나 희소한지, 반복이 얼마나 빨리 값어치를 멈춰야 하는지, 청크의 길이가 그 청크를 얼마나 부풀리는지다. 그 뒤의 통계는 전부 이미 존재하는 `content_tsv` 열에서 파생한다.

**문서:** [7. BM25](tutorial/07-bm25.md) · **통과 기준:** `uv run pytest tests/retrieval/test_09_bm25.py -q`

## M2.10 — 이유가 생긴 다음에 의존성을 진다

M2.9까지는 머신러닝 의존성이 하나도 없이 돈다. 이 구간에서 PyTorch를 설치하고, 손에 있는 하드웨어가 아니라 워크로드를 보고 백엔드를 고르고, 로컬 이중 인코더를 임베딩 경계 뒤에 넣는다. 가장 중요한 교훈은 이 구간이 새로 만드는 실패다. 두 공급자의 벡터는 같은 공간에 있지 않은데 섞어도 아무것도 발생하지 않는다.

**문서:** [8. 로컬 임베딩](tutorial/08-local-embeddings.md) · **통과 기준:** `uv run pytest tests/retrieval/test_10_sbert.py -q`

## M2.11 — M2.6이 비워 둔 경계를 채운다

cross-encoder는 질문과 문서를 따로가 아니라 같이 읽는다. 더 정확하고 후보마다 순전파가 한 번씩 든다. 그 값이 검색을 2단계로 만든다. 먼저 싸고 넓게, 다음에 비싸고 좁게다. 붙이는 비용은 선택적 매개변수 하나이고, 다섯 체크포인트 전에 그어 둔 경계가 돌려주는 몫이다.

**문서:** [9. cross-encoder](tutorial/09-cross-encoder.md) · **통과 기준:** `uv run pytest tests/retrieval/test_11_cross_encoder.py -q`

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **문서와 질문을 반드시 같은 임베딩 경로에 태워야 하는 이유는 무엇인가?**
  - **답:** 같은 모델이 만든 벡터만 같은 공간에서 비교할 수 있다. 서로 다른 모델을 쓰면 코사인 유사도에 의미가 없다.
- **네트워크 호출과 트랜잭션이 겹치면 정확히 무엇이 위험해지는가?**
  - **답:** 느리거나 실패한 네트워크 I/O를 기다리는 동안 데이터베이스 잠금과 연결을 오래 점유하고, 타임아웃 하나가 그 트랜잭션에서 끝낸 작업까지 모두 롤백할 수 있다.
- **근사 인덱스를 처음부터 켜지 않은 이유는 무엇인가?**
  - **답:** 근사 인덱스가 놓친 실제 이웃의 수를 측정하려면 정확 검색 기준선이 먼저 필요하다. 현재 코퍼스 크기에서는 전체 스캔 비용도 감당할 수 있다.
- **점수를 정규화해서 더하는 방식이 RRF보다 나쁜 이유는 무엇인가?**
  - **답:** 벡터 점수와 어휘 점수는 단위가 다르고, 정규화 결과는 질의마다 달라지는 점수 분포에 좌우된다. RRF는 순위만 결합하므로 두 문제를 피한다.
- **검색 함수가 세션을 직접 만들면 무엇이 깨지는가?**
  - **답:** 호출자가 트랜잭션 범위를 통제할 수 없고, 검색을 요청의 다른 작업과 같은 세션에서 묶어 처리할 수도 없다.
- **재순위화를 만들어 놓고 켜지 않은 근거는 무엇인가?**
  - **답:** 재순위화는 비용과 지연 시간을 늘리지만 M2에는 이 코퍼스에서 효과가 있다는 근거가 없고, 현재 M3 실험 행렬도 이를 측정하지 않는다. 향후 실험이 재순위화 실험군을 명시적으로 추가할 때까지 경계를 꺼 두면 불필요한 비용을 피할 수 있다.

## 이 모듈이 다음 모듈에 넘기는 것

M2가 끝나면 질문 하나로 근거 청크를 찾을 수 있다. 그런데 **그게 좋은 결과인지는 아직 모른다.** 이 장에서 미뤄둔 결정들이 그래서 전부 M3로 넘어간다.

| M2가 만든 것 | 받는 곳 | 거기서 하는 일 |
|---|---|---|
| `retrieve()` 서비스 진입점 | **M4** | 워크플로의 retrieve 노드 |
| `RetrievalResult.hits` | **M4** | LLM에 주는 근거 |
| `component_rankings` | **M3** | 어느 검색기가 기여했는지 분석 |
| `RetrievalFilters` | **M5** | API 요청의 ticker·연도 필터 |
| 정확 코사인 기준선 | **M3** | 근사 인덱스 도입 시 비교 대상 |
| `rrf_k` 기본값 60 | **M3** | 어블레이션 파라미터 |
| `RerankProvider` 경계 (미사용) | **M3** | 켤지 말지를 측정으로 결정 |

M2에서 세 번이나 "M3에서 재본다"고 미뤘다. HNSW를 안 건 것, 재순위화를 안 켠 것, `rrf_k`를 60으로 둔 것. 전부 **측정 없이는 결정할 수 없는 것들**이다.

다음 장 M3는 그 측정 장치를 만든다. 골든 답변을 청크 ID가 아니라 **소스 좌표 범위**로 정의하는 게 핵심인데, 그래야 청크 크기를 바꿔가며 비교할 수 있다. M1.3에서 인용을 좌표 기반으로 설계한 이유가 여기서 마지막으로 값을 한다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M2.1 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/__init__.py`

<!-- file: app/retrieval/__init__.py -->
```python
"""Public contracts and production entry points for the retrieval milestone."""

from app.retrieval.bm25 import TermStatCounts, backfill_term_stats, bm25_search
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingBackfillResult,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search, rrf_fuse
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.sbert import SentenceTransformerEmbeddingProvider
from app.retrieval.service import ComponentRankings, RetrievalResult, retrieve
from app.retrieval.types import ChunkHit, ChunkKind, RetrievalFilters, sort_hits
from app.retrieval.vector import vector_search

__all__ = [
    "DEFAULT_RRF_K",
    "ChunkHit",
    "ChunkKind",
    "ComponentRankings",
    "CrossEncoderReranker",
    "DeterministicEmbeddingProvider",
    "EmbeddingBackfillResult",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "RerankProvider",
    "RetrievalFilters",
    "RetrievalResult",
    "SentenceTransformerEmbeddingProvider",
    "TermStatCounts",
    "backfill_term_stats",
    "bm25_search",
    "embed_missing_chunks",
    "get_embedding_provider",
    "hybrid_search",
    "lexical_search",
    "rerank_hits",
    "retrieve",
    "rrf_fuse",
    "sort_hits",
    "vector_search",
]
```

#### 생성 또는 교체 `app/retrieval/types.py`

<!-- file: app/retrieval/types.py -->
```python
"""Shared value objects and deterministic ordering for retrieval results."""

from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

ChunkKind = Literal["text", "table"]

ChunkId = Annotated[StrictInt, Field(gt=0)]
DocId = Annotated[StrictStr, Field(min_length=1, max_length=32)]
Ticker = Annotated[StrictStr, Field(min_length=1, max_length=16)]
FiscalYear = Annotated[StrictInt, Field(gt=0)]
Form = Annotated[StrictStr, Field(min_length=1, max_length=16)]
Item = Annotated[StrictStr, Field(min_length=1, max_length=8)]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Score = Annotated[StrictFloat, Field(allow_inf_nan=False)]


class ChunkHit(BaseModel):
    """One scored database chunk with human and machine citation data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: ChunkId
    doc_id: DocId
    item: Item | None
    kind: ChunkKind
    citation: Annotated[StrictStr, Field(min_length=1)]
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]
    source_sha256: SourceSha256
    body: Annotated[StrictStr, Field(min_length=1)]
    context_header: StrictStr
    index_text: Annotated[StrictStr, Field(min_length=1)]
    score: Score

    @model_validator(mode="after")
    def validate_source_and_index_text(self) -> Self:
        """Reject invalid spans and indexed text detached from its evidence."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")

        expected = f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
        if self.index_text != expected:
            raise ValueError("index_text must equal context_header plus body")
        return self


class RetrievalFilters(BaseModel):
    """Optional exact-match restrictions shared by every retrieval strategy.

    Values within a field are alternatives, while populated fields are combined.
    Empty tuples mean that the corresponding database dimension is unrestricted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_ids: tuple[DocId, ...] = ()
    tickers: tuple[Ticker, ...] = ()
    fiscal_years: tuple[FiscalYear, ...] = ()
    forms: tuple[Form, ...] = ()
    items: tuple[Item | None, ...] = ()
    kinds: tuple[ChunkKind, ...] = ()

    @field_validator("doc_ids", "tickers", "forms", mode="after")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Remove duplicates and make equivalent string filters serialize equally."""
        return tuple(sorted(set(values)))

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def canonicalize_years(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        """Remove duplicate years and store them in ascending order."""
        return tuple(sorted(set(values)))

    @field_validator("items", mode="after")
    @classmethod
    def canonicalize_items(cls, values: tuple[str | None, ...]) -> tuple[str | None, ...]:
        """Canonicalize Item filters while retaining support for unnumbered sections."""
        return tuple(sorted(set(values), key=lambda item: (item is not None, item or "")))

    @field_validator("kinds", mode="after")
    @classmethod
    def canonicalize_kinds(cls, values: tuple[ChunkKind, ...]) -> tuple[ChunkKind, ...]:
        """Canonicalize kinds in the schema's text-then-table order."""
        order = {"text": 0, "table": 1}
        return tuple(sorted(set(values), key=order.__getitem__))


def sort_hits(hits: Iterable[ChunkHit]) -> list[ChunkHit]:
    """Return hits in deterministic relevance order without mutating the input.

    Higher scores sort first. Equal scores use the stable source citation identity,
    followed by the database chunk id as a final unique tie-breaker.
    """
    return sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_01_contract.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.2 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/embeddings.py`

<!-- file: app/retrieval/embeddings.py -->
```python
"""Async embedding providers and resumable PostgreSQL embedding backfill."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import math
from numbers import Real
import re
import unicodedata

from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk


def _texts(values: Sequence[str]) -> list[str]:
    """Return validated, materialized embedding inputs."""
    texts = list(values)
    if any(not isinstance(text, str) or not text for text in texts):
        raise ValueError("embedding inputs must be nonempty strings")
    return texts


def validate_embeddings(
    values: Sequence[Sequence[float]], *, expected_count: int, dimensions: int
) -> list[list[float]]:
    """Validate provider output before it crosses the database boundary."""
    if dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")
    if len(values) != expected_count:
        raise ValueError(
            f"embedding provider returned {len(values)} vectors for {expected_count} inputs"
        )

    vectors: list[list[float]] = []
    for position, value in enumerate(values):
        if len(value) != dimensions:
            raise ValueError(
                f"embedding {position} has dimension {len(value)}, expected {dimensions}"
            )
        vector: list[float] = []
        for component in value:
            if isinstance(component, bool) or not isinstance(component, Real):
                raise ValueError(f"embedding {position} contains a nonnumeric component")
            number = float(component)
            if not math.isfinite(number):
                raise ValueError(f"embedding {position} contains a non-finite component")
            vector.append(number)
        vectors.append(vector)
    return vectors


class EmbeddingProvider(ABC):
    """Async provider boundary shared by query and document embeddings."""

    dimensions: int

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch in caller order."""

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query through the same model and validation path."""
        return (await self.embed_documents([text]))[0]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Stable token-hashing vectors for tests and local exercises."""

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.dimensions = dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Hash normalized alphanumeric tokens into unit-length bag-of-words vectors."""
        inputs = _texts(texts)
        vectors: list[list[float]] = []
        for text in inputs:
            normalized = unicodedata.normalize("NFKC", text).casefold()
            tokens = re.findall(r"[^\W_]+", normalized)
            if not tokens:
                tokens = ["<empty>"]
            vector = [0.0] * self.dimensions
            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                dimension = int.from_bytes(digest[:8], "big") % self.dimensions
                sign = 1.0 if digest[8] & 1 else -1.0
                vector[dimension] += sign
            norm = math.sqrt(sum(component * component for component in vector))
            if norm == 0.0:
                digest = hashlib.sha256(" ".join(tokens).encode("utf-8")).digest()
                vector[int.from_bytes(digest[:8], "big") % self.dimensions] = 1.0
                norm = 1.0
            vectors.append([component / norm for component in vector])
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider with explicit output dimensions."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        dimensions: int = 384,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
    ) -> None:
        if not model:
            raise ValueError("embedding model must be nonempty")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.model = model
        self.dimensions = dimensions
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed one batch and restore caller order from response indices."""
        inputs = _texts(texts)
        if not inputs:
            return []

        response = await self._client.embeddings.create(
            input=inputs,
            model=self.model,
            dimensions=self.dimensions,
            encoding_format="float",
        )
        by_index: dict[int, Sequence[float]] = {}
        for item in response.data:
            if not isinstance(item.index, int) or item.index in by_index:
                raise ValueError("embedding provider returned invalid response indices")
            by_index[item.index] = item.embedding
        if set(by_index) != set(range(len(inputs))):
            raise ValueError("embedding provider returned incomplete response indices")
        ordered = [by_index[index] for index in range(len(inputs))]
        return validate_embeddings(
            ordered,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )


def get_embedding_provider(
    settings: Settings | None = None, *, client: AsyncOpenAI | None = None
) -> EmbeddingProvider:
    """Build the configured provider without doing work at import time."""
    configured = settings or get_settings()
    if configured.embedding_provider == "deterministic":
        return DeterministicEmbeddingProvider(configured.embed_dim)
    if configured.embedding_provider == "sbert":
        # Imported here, not at module scope: app.retrieval.sbert imports this
        # module for the provider base class and its validation helpers.
        from app.retrieval.sbert import SentenceTransformerEmbeddingProvider

        return SentenceTransformerEmbeddingProvider(
            model=configured.sbert_model,
            dimensions=configured.embed_dim,
        )
    api_key = configured.openai_api_key.get_secret_value() if configured.openai_api_key else None
    return OpenAIEmbeddingProvider(
        model=configured.embedding_model,
        dimensions=configured.embed_dim,
        client=client,
        api_key=api_key,
    )


@dataclass(frozen=True, slots=True)
class PendingEmbedding:
    """One immutable database input selected for embedding."""

    chunk_id: int
    index_text: str


@dataclass(frozen=True, slots=True)
class EmbeddingBackfillResult:
    """Observable result of a resumable embedding backfill."""

    selected: int
    embedded: int
    skipped_stale: int
    batches: int


async def _missing_batch(session: AsyncSession, batch_size: int) -> list[PendingEmbedding]:
    """Load one stable batch and close its transaction before provider I/O."""
    async with session.begin():
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.index_text)
                .where(Chunk.embedding.is_(None))
                .order_by(Chunk.id)
                .limit(batch_size)
            )
        ).all()
    return [PendingEmbedding(chunk_id=row.id, index_text=row.index_text) for row in rows]


async def _store_batch(
    session: AsyncSession,
    pending: Sequence[PendingEmbedding],
    vectors: Sequence[Sequence[float]],
) -> int:
    """Store current vectors and reject rows changed while the provider was running."""
    embedded = 0
    async with session.begin():
        for item, vector in zip(pending, vectors, strict=True):
            result = await session.execute(
                update(Chunk)
                .where(
                    Chunk.id == item.chunk_id,
                    Chunk.embedding.is_(None),
                    Chunk.index_text == item.index_text,
                )
                .values(embedding=list(vector))
            )
            if result.rowcount == 1:
                embedded += 1
    return embedded


async def embed_missing_chunks(
    session: AsyncSession,
    provider: EmbeddingProvider,
    *,
    batch_size: int | None = None,
) -> EmbeddingBackfillResult:
    """Embed all currently missing chunks in bounded, resumable batches."""
    effective_batch_size = get_settings().embedding_batch_size if batch_size is None else batch_size
    if effective_batch_size <= 0:
        raise ValueError("embedding batch size must be positive")
    if session.in_transaction():
        raise RuntimeError("embed_missing_chunks requires a session without an active transaction")

    selected = embedded = skipped_stale = batches = 0
    while pending := await _missing_batch(session, effective_batch_size):
        batches += 1
        selected += len(pending)
        vectors = await provider.embed_documents([item.index_text for item in pending])
        vectors = validate_embeddings(
            vectors,
            expected_count=len(pending),
            dimensions=provider.dimensions,
        )
        stored = await _store_batch(session, pending, vectors)
        embedded += stored
        skipped_stale += len(pending) - stored

    return EmbeddingBackfillResult(
        selected=selected,
        embedded=embedded,
        skipped_stale=skipped_stale,
        batches=batches,
    )
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_02_embeddings.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.3 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/vector.py`

<!-- file: app/retrieval/vector.py -->
```python
"""Filtered, deterministic pgvector cosine retrieval."""

from collections.abc import Sequence
import math
from numbers import Real
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM, Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters


def validate_query_vector(values: Sequence[float], *, dimensions: int = DIM) -> list[float]:
    """Return a finite vector whose shape matches the database column."""
    if len(values) != dimensions:
        raise ValueError(f"query vector has dimension {len(values)}, expected {dimensions}")
    vector: list[float] = []
    for component in values:
        if isinstance(component, bool) or not isinstance(component, Real):
            raise ValueError("query vector contains a nonnumeric component")
        number = float(component)
        if not math.isfinite(number):
            raise ValueError("query vector contains a non-finite component")
        vector.append(number)
    return vector


def _filtered_statement(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    """Apply exact-match chunk and document filters with AND semantics."""
    if filters.tickers or filters.fiscal_years or filters.forms:
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    if filters.doc_ids:
        statement = statement.where(Chunk.doc_id.in_(filters.doc_ids))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates = []
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        statement = statement.where(or_(*item_predicates))
    if filters.kinds:
        statement = statement.where(Chunk.kind.in_(filters.kinds))
    if filters.tickers:
        statement = statement.where(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        statement = statement.where(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        statement = statement.where(Document.form.in_(filters.forms))
    return statement


def vector_search_statement(
    query_vector: Sequence[float],
    *,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build the exact cosine query used by runtime and SQL contract tests."""
    if k <= 0:
        raise ValueError("vector search k must be positive")
    vector = validate_query_vector(query_vector)
    restrictions = filters or RetrievalFilters()
    distance = Chunk.embedding.cosine_distance(vector).label("distance")
    statement = select(Chunk, distance).where(Chunk.embedding.is_not(None))
    statement = _filtered_statement(statement, restrictions)
    return statement.order_by(
        distance.asc(),
        Chunk.doc_id.asc(),
        Chunk.source_sha256.asc(),
        Chunk.start_char.asc(),
        Chunk.end_char.asc(),
        Chunk.id.asc(),
    ).limit(k)


async def vector_search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Return complete chunk evidence ordered by cosine similarity."""
    if k < 0:
        raise ValueError("vector search k must not be negative")
    if k == 0:
        return []

    statement = vector_search_statement(query_vector, k=k, filters=filters)
    rows = (await session.execute(statement)).all()
    return [
        ChunkHit(
            chunk_id=chunk.id,
            doc_id=chunk.doc_id,
            item=chunk.item,
            kind=chunk.kind,
            citation=chunk.citation,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            source_sha256=chunk.source_sha256,
            body=chunk.body,
            context_header=chunk.context_header,
            index_text=chunk.index_text,
            score=1.0 - float(distance),
        )
        for chunk, distance in rows
    ]
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_03_vector.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.4 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/lexical.py`

<!-- file: app/retrieval/lexical.py -->
```python
"""PostgreSQL full-text lexical retrieval.

This is the project's mandatory lexical baseline. It uses PostgreSQL full-text
search with cover-density ranking; ``ts_rank_cd`` is not literal BM25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters

TEXT_SEARCH_CONFIG = "english"

# ``ts_rank_cd`` normalization bitmask (PostgreSQL, "Ranking Search Results").
# Bit 4 divides the rank by the mean harmonic distance between extents, so query
# terms that appear close together outrank the same terms scattered apart; bit 1
# divides by ``1 + log(document length)``, so a long chunk stuffed with one common
# term cannot outrank a short chunk that actually answers. With the default of 0,
# rank degenerates into occurrence counting and, measured on the golden suite,
# recall@5 is exactly zero; 4|1 is the best-scoring native combination.
TS_RANK_NORMALIZATION = 4 | 1


def _filter_predicates(filters: RetrievalFilters) -> tuple[ColumnElement[bool], ...]:
    """Translate the shared exact-match filters to composable SQL predicates."""
    predicates: list[ColumnElement[bool]] = []
    if filters.doc_ids:
        predicates.append(Chunk.doc_id.in_(filters.doc_ids))
    if filters.tickers:
        predicates.append(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        predicates.append(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        predicates.append(Document.form.in_(filters.forms))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(Chunk.kind.in_(filters.kinds))
    return tuple(predicates)


def lexical_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build a safe PostgreSQL FTS statement ranked by cover density.

    ``websearch_to_tsquery`` accepts raw user text without exposing ``to_tsquery``
    syntax errors, and SQLAlchemy binds ``query`` as a value instead of interpolating
    it. But its output joins every content lexeme with ``&``: a natural-language
    question like "What was the total revenue reported for fiscal 2024?" becomes
    five AND-ed stems, and only a chunk containing all five matches. On this corpus
    that describes almost no chunk, and the baseline silently returns nothing.

    The statement therefore relaxes the parsed query before using it. The tsquery's
    text form quotes each lexeme and can never contain ``&`` inside one, so
    rewriting ``&`` to ``|`` and reparsing with ``to_tsquery`` turns the conjunction
    into a disjunction while leaving quoted phrases (``<->``) intact. Matching any
    query term is enough to become a candidate, and ``TS_RANK_NORMALIZATION`` makes
    the ranking prefer chunks where more of the query co-occurs closely over chunks
    that merely repeat one common term. One semantic is knowingly weakened: an
    explicit ``-term`` exclusion is relaxed along with everything else.

    PostgreSQL FTS is the lexical baseline here; this statement does not implement BM25.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    active_filters = filters or RetrievalFilters()
    parsed = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)
    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, func.replace(cast(parsed, Text), "&", "|"))
    score = func.ts_rank_cd(Chunk.content_tsv, tsquery, TS_RANK_NORMALIZATION).label("score")
    return (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.doc_id,
            Chunk.item,
            Chunk.kind,
            Chunk.citation,
            Chunk.start_char,
            Chunk.end_char,
            Chunk.source_sha256,
            Chunk.body,
            Chunk.context_header,
            Chunk.index_text,
            score,
        )
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(Chunk.content_tsv.op("@@")(tsquery), *_filter_predicates(active_filters))
        .order_by(
            score.desc(),
            Chunk.doc_id.asc(),
            Chunk.source_sha256.asc(),
            Chunk.start_char.asc(),
            Chunk.end_char.asc(),
            Chunk.id.asc(),
        )
        .limit(k)
    )


async def lexical_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Run the PostgreSQL FTS baseline and return typed, deterministically ordered hits.

    The returned score is the native ``ts_rank_cd`` cover-density score, not BM25
    and not a probability. Fusion must consume its rank instead of comparing this
    value directly with another retrieval strategy's score.
    """
    result = await session.execute(lexical_statement(query, k, filters))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_04_lexical.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.5 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/hybrid.py`

<!-- file: app/retrieval/hybrid.py -->
```python
"""Rank-only reciprocal rank fusion and thin hybrid orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.retrieval.types import ChunkHit, RetrievalFilters, sort_hits

DEFAULT_RRF_K = 60

SearchCallable = Callable[[str, int, RetrievalFilters], Awaitable[list[ChunkHit]]]


@dataclass(slots=True)
class _FusedHit:
    hit: ChunkHit
    score: float = 0.0


def _unique_ranked_hits(hits: Sequence[ChunkHit]) -> list[ChunkHit]:
    """Keep the first occurrence of each chunk so one list contributes one rank."""
    seen: set[int] = set()
    unique: list[ChunkHit] = []
    for hit in hits:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            unique.append(hit)
    return unique


def rrf_fuse(
    vector_hits: Sequence[ChunkHit],
    lexical_hits: Sequence[ChunkHit],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Fuse ranked lists by reciprocal rank, keyed by database ``chunk_id``.

    Source scores are intentionally ignored because vector similarity and PostgreSQL
    FTS cover-density scores have unrelated scales. Each list contributes
    ``1 / (rrf_k + rank)`` once per chunk, where rank is one-based.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused: dict[int, _FusedHit] = {}
    for ranking in (vector_hits, lexical_hits):
        for rank, hit in enumerate(_unique_ranked_hits(ranking), start=1):
            contribution = 1.0 / (rrf_k + rank)
            entry = fused.get(hit.chunk_id)
            if entry is None:
                fused[hit.chunk_id] = _FusedHit(hit=hit, score=contribution)
            else:
                entry.score += contribution

    hits = [entry.hit.model_copy(update={"score": entry.score}) for entry in fused.values()]
    return sort_hits(hits)[:k]


async def hybrid_search(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    vector_search: SearchCallable,
    lexical_search: SearchCallable,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Retrieve two candidate lists and combine them with rank-only RRF.

    Injected callables let the production adapter close over its session, embedder,
    and vector query preparation. Calls are awaited sequentially so both adapters may
    safely share one SQLAlchemy ``AsyncSession``.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    limit = candidate_k if candidate_k is not None else k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    active_filters = filters or RetrievalFilters()

    vector_hits = await vector_search(query, limit, active_filters)
    lexical_hits = await lexical_search(query, limit, active_filters)
    return rrf_fuse(vector_hits, lexical_hits, k, rrf_k=rrf_k)
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_05_hybrid.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.6 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/rerank.py`

<!-- file: app/retrieval/rerank.py -->
```python
"""Optional async reranking behind a dependency-free provider boundary."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
import math
from numbers import Real

from app.retrieval.types import ChunkHit, sort_hits


class RerankProvider(ABC):
    """Provider boundary for scoring query/document pairs."""

    @abstractmethod
    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Return one relevance score per document in caller order."""


def _scores(values: Sequence[float], *, expected_count: int) -> list[float]:
    """Validate provider scores before replacing immutable hit scores."""
    if len(values) != expected_count:
        raise ValueError(f"reranker returned {len(values)} scores for {expected_count} hits")
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("reranker returned a nonnumeric score")
        score = float(value)
        if not math.isfinite(score):
            raise ValueError("reranker returned a non-finite score")
        scores.append(score)
    return scores


async def rerank_hits(
    query: str,
    hits: Sequence[ChunkHit],
    *,
    provider: RerankProvider | None = None,
    top_k: int = 5,
) -> list[ChunkHit]:
    """Optionally rescore top candidates and return deterministic top-k hits."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("rerank query must be nonempty")
    if top_k < 0:
        raise ValueError("rerank top_k must not be negative")
    if top_k == 0 or not hits:
        return []
    if provider is None:
        return sort_hits(hits)[:top_k]

    scores = _scores(
        await provider.score(query, [hit.index_text for hit in hits]),
        expected_count=len(hits),
    )
    rescored = [
        hit.model_copy(update={"score": score}) for hit, score in zip(hits, scores, strict=True)
    ]
    return sort_hits(rescored)[:top_k]
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_06_rerank.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.7 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/service.py`

<!-- file: app/retrieval/service.py -->
```python
"""Production composition for deterministic hybrid retrieval."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf, LexicalRanker, get_settings
from app.db.models import DIM
from app.retrieval.bm25 import BM25_IDF_VARIANTS, bm25_search
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.language import detect_query_language
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

RankedChunkId = Annotated[int, Field(gt=0)]
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def _normalize_query(query: str) -> str:
    """Expand the common R&D abbreviation for embedding and PostgreSQL FTS parity."""
    return RESEARCH_AND_DEVELOPMENT.sub("research development", query)


class ComponentRankings(BaseModel):
    """Ranked chunk identities from each retrieval component, without raw scores."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vector: tuple[RankedChunkId, ...]
    lexical: tuple[RankedChunkId, ...]


class RetrievalResult(BaseModel):
    """Fused evidence plus inspectable rank-only component provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
    component_rankings: ComponentRankings


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    reranker: RerankProvider | None = None,
    route_by_language: bool | None = None,
    lexical_ranker: LexicalRanker | None = None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
) -> RetrievalResult:
    """Run vector then lexical search through one session and fuse their ranks.

    The component adapters close over the same ``AsyncSession``. They are awaited
    sequentially by ``hybrid_search`` because concurrent use of one session is unsafe.
    Component scores stay inside their native lanes; only ranked chunk identities are
    exposed beside the fused hits. An omitted candidate limit expands to
    ``max(20, 4 * k)`` at this production boundary.

    With no reranker the fused list is truncated to ``k`` by fusion itself, which is
    the M2.7 behaviour. Supplying one turns the request into two stages: fusion keeps
    the full candidate list, and the reranker rescores it and returns the top ``k``.
    Retrieval therefore goes wide cheaply first, then narrow expensively.

    Reranked hits carry cross-encoder scores rather than fusion scores. Component
    rankings are unaffected because they record what each retriever proposed, not
    what survived reranking.

    ``route_by_language`` resolves from ``Settings.query_language_routing`` when it is
    omitted. With routing on and a Korean query, the lexical component is skipped and
    ranking is vector-only. The lexical index is built with the ``english`` text-search
    configuration, so that component contributes nothing for Korean anyway; asking it
    anyway costs a database round trip and, worse, gives fusion a component whose
    silence is indistinguishable from a considered "no candidates". A skipped component
    is visible instead: ``ComponentRankings.lexical`` is empty, so the taken route can
    be read off the result rather than inferred from the configuration.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    limit = max(20, 4 * k) if candidate_k is None else candidate_k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    settings = get_settings()
    active_lexical_ranker = settings.lexical_ranker if lexical_ranker is None else lexical_ranker
    active_bm25_k1 = settings.bm25_k1 if bm25_k1 is None else bm25_k1
    active_bm25_b = settings.bm25_b if bm25_b is None else bm25_b
    if active_lexical_ranker not in ("ts_rank_cd", "bm25"):
        raise ValueError("lexical_ranker must be 'ts_rank_cd' or 'bm25'")
    if active_bm25_k1 <= 0:
        raise ValueError("bm25_k1 must be positive")
    if not 0 <= active_bm25_b <= 1:
        raise ValueError("bm25_b must be between 0 and 1")
    active_bm25_idf = settings.bm25_idf if bm25_idf is None else bm25_idf
    if active_bm25_idf not in BM25_IDF_VARIANTS:
        raise ValueError("bm25_idf must be 'lucene' or 'robertson'")
    normalized_query = _normalize_query(query)
    active_routing = (
        settings.query_language_routing if route_by_language is None else route_by_language
    )
    skip_lexical = active_routing and detect_query_language(normalized_query) == "ko"

    active_provider = provider or get_embedding_provider()
    if active_provider.dimensions != DIM:
        raise ValueError(
            f"embedding provider dimension {active_provider.dimensions} does not match "
            f"database dimension {DIM}"
        )

    vector_hits: list[ChunkHit] = []
    lexical_hits: list[ChunkHit] = []

    async def vector_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        query_vector = await active_provider.embed_query(component_query)
        hits = await vector_search(
            session,
            query_vector,
            k=component_k,
            filters=component_filters,
        )
        vector_hits.extend(hits)
        return hits

    async def lexical_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        if skip_lexical:
            return []
        if active_lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                component_query,
                component_k,
                component_filters,
                k1=active_bm25_k1,
                b=active_bm25_b,
                idf=active_bm25_idf,
            )
        else:
            hits = await lexical_search(
                session,
                component_query,
                component_k,
                component_filters,
            )
        lexical_hits.extend(hits)
        return hits

    fused = await hybrid_search(
        normalized_query,
        limit if reranker is not None else k,
        filters,
        vector_search=vector_component,
        lexical_search=lexical_component,
        candidate_k=limit,
        rrf_k=rrf_k,
    )
    if reranker is not None:
        fused = await rerank_hits(
            normalized_query,
            fused,
            provider=reranker,
            top_k=k,
        )
    return RetrievalResult(
        hits=tuple(fused),
        component_rankings=ComponentRankings(
            vector=tuple(hit.chunk_id for hit in vector_hits),
            lexical=tuple(hit.chunk_id for hit in lexical_hits),
        ),
    )
```

#### 생성 또는 교체 `app/retrieval/__main__.py`

<!-- file: app/retrieval/__main__.py -->
```python
"""Command-line acceptance path for the M2 retrieval service."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
import json
from typing import Literal

from app.config import BM25Idf, LexicalRanker, Settings, get_settings
from app.db.bootstrap import bootstrap_schema
from app.db.session import Session, engine
from app.retrieval.bm25 import TermStatCounts, backfill_term_stats
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve

ProviderName = Literal["deterministic", "openai", "sbert"]


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse retrieval acceptance arguments."""
    parser = argparse.ArgumentParser(description="Run exact hybrid retrieval over PostgreSQL.")
    parser.add_argument("--query", required=True, help="Nonempty retrieval query.")
    parser.add_argument("-k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai", "sbert"),
        help=(
            "Override EMBEDDING_PROVIDER for this command. Stored embeddings are only "
            "comparable with query embeddings from the same provider, so switching "
            "requires re-embedding every chunk with --embed-missing on an empty column."
        ),
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Rescore fused candidates with a local cross-encoder before truncating to k.",
    )
    parser.add_argument(
        "--lexical-ranker",
        choices=("ts_rank_cd", "bm25"),
        help="Override LEXICAL_RANKER for this command.",
    )
    parser.add_argument(
        "--bm25-k1",
        type=float,
        help="Override BM25_K1; must be positive.",
    )
    parser.add_argument(
        "--bm25-b",
        type=float,
        help="Override BM25_B; must be between 0 and 1.",
    )
    parser.add_argument(
        "--bm25-idf",
        choices=("lucene", "robertson"),
        help="Override BM25_IDF; 'robertson' can score common terms negatively.",
    )
    parser.add_argument(
        "--rebuild-bm25-stats",
        action="store_true",
        help="Create missing schema objects and atomically rebuild BM25 term statistics.",
    )
    return parser.parse_args(argv)


def _provider_settings(settings: Settings, provider: ProviderName | None) -> Settings:
    """Return settings with an optional validated command-line provider override."""
    if provider is None:
        return settings
    return settings.model_copy(update={"embedding_provider": provider})


def _payload(
    *,
    query: str,
    provider: str,
    backfill: EmbeddingBackfillResult | None,
    result: RetrievalResult,
    lexical_ranker: LexicalRanker = "ts_rank_cd",
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
    bm25_idf: BM25Idf = "lucene",
    bm25_stats: TermStatCounts | None = None,
) -> dict[str, object]:
    """Build stable JSON output while keeping component scores private."""
    return {
        "query": query,
        "provider": provider,
        "lexical_ranker": lexical_ranker,
        "bm25_k1": bm25_k1 if lexical_ranker == "bm25" else None,
        "bm25_b": bm25_b if lexical_ranker == "bm25" else None,
        "bm25_idf": bm25_idf if lexical_ranker == "bm25" else None,
        "bm25_stats": asdict(bm25_stats) if bm25_stats is not None else None,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [hit.model_dump(mode="json") for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    """Run optional embedding backfill and one retrieval request."""
    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    lexical_ranker = args.lexical_ranker or settings.lexical_ranker
    bm25_k1 = settings.bm25_k1 if args.bm25_k1 is None else args.bm25_k1
    bm25_b = settings.bm25_b if args.bm25_b is None else args.bm25_b
    bm25_idf = args.bm25_idf or settings.bm25_idf
    if args.rebuild_bm25_stats:
        await bootstrap_schema(engine)
    async with Session() as session:
        backfill = None
        bm25_stats = None
        if args.rebuild_bm25_stats:
            bm25_stats = await backfill_term_stats(session)
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            reranker=CrossEncoderReranker() if args.rerank else None,
            lexical_ranker=lexical_ranker,
            bm25_k1=bm25_k1,
            bm25_b=bm25_b,
            bm25_idf=bm25_idf,
        )
    return _payload(
        query=args.query,
        provider=settings.embedding_provider,
        backfill=backfill,
        result=result,
        lexical_ranker=lexical_ranker,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        bm25_idf=bm25_idf,
        bm25_stats=bm25_stats,
    )


def main() -> None:
    """Run the M2 acceptance command and print machine-readable evidence."""
    print(json.dumps(asyncio.run(_run(arguments())), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_07_service.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.8 — 완성 체크포인트

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_08_postgres.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.9 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/bm25.py`

<!-- file: app/retrieval/bm25.py -->
```python
"""Deterministic PostgreSQL BM25 retrieval over stored full-text lexemes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

from sqlalchemy import (
    Float,
    Integer,
    Select,
    SQLColumnExpression,
    String,
    bindparam,
    cast,
    delete,
    func,
    select,
    text,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf
from app.db.models import Chunk, ChunkLength, ChunkTerm, Document, LexemeStat
from app.retrieval.lexical import TEXT_SEARCH_CONFIG, _filter_predicates
from app.retrieval.types import ChunkHit, RetrievalFilters

DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75
DEFAULT_BM25_IDF: BM25Idf = "lucene"
BM25_IDF_VARIANTS: tuple[BM25Idf, ...] = ("lucene", "robertson")


@dataclass(frozen=True, slots=True)
class TermStatCounts:
    """Committed row counts for one complete BM25 statistic rebuild."""

    terms: int
    chunks: int
    lexemes: int


async def backfill_term_stats(session: AsyncSession) -> TermStatCounts:
    """Atomically rebuild every BM25 statistic from ``chunks.content_tsv``.

    The function owns one transaction so readers observe either the previous
    complete statistic set or the new one. The source-table lock prevents a
    concurrent chunk write from producing a mixed-corpus snapshot, while the
    derived-table lock serializes competing rebuilds without blocking readers.
    """
    if session.in_transaction():
        raise RuntimeError("backfill_term_stats requires a session without an active transaction")

    async with session.begin():
        await session.execute(text("LOCK TABLE chunks IN SHARE MODE"))
        await session.execute(
            text("LOCK TABLE chunk_terms, chunk_lengths, lexeme_stats IN SHARE ROW EXCLUSIVE MODE")
        )
        await session.execute(delete(ChunkTerm))
        await session.execute(delete(ChunkLength))
        await session.execute(delete(LexemeStat))

        await session.execute(
            text(
                "INSERT INTO chunk_terms (chunk_id, lexeme, tf) "
                "SELECT c.id, t.lexeme, cardinality(t.positions) "
                "FROM chunks AS c CROSS JOIN LATERAL unnest(c.content_tsv) AS t "
                "WHERE t.positions IS NOT NULL AND cardinality(t.positions) > 0"
            )
        )
        await session.execute(
            text(
                "INSERT INTO chunk_lengths (chunk_id, dl) "
                "SELECT chunk_id, SUM(tf) FROM chunk_terms GROUP BY chunk_id"
            )
        )
        await session.execute(
            text(
                "INSERT INTO lexeme_stats (lexeme, df) "
                "SELECT lexeme, COUNT(*) FROM chunk_terms GROUP BY lexeme"
            )
        )

        row = (
            await session.execute(
                select(
                    select(func.count()).select_from(ChunkTerm).scalar_subquery().label("terms"),
                    select(func.count()).select_from(ChunkLength).scalar_subquery().label("chunks"),
                    select(func.count()).select_from(LexemeStat).scalar_subquery().label("lexemes"),
                )
            )
        ).one()
        counts = TermStatCounts(
            terms=int(row.terms),
            chunks=int(row.chunks),
            lexemes=int(row.lexemes),
        )

    return counts


def _idf_expression(
    variant: BM25Idf,
    corpus_size: SQLColumnExpression[int],
    document_frequency: SQLColumnExpression[int],
) -> SQLColumnExpression[float]:
    """Return the SQL inverse document frequency for one lexeme.

    Both published variants are available because they disagree about common
    terms. Robertson's original is ``ln((N - df + 0.5) / (df + 0.5))``, which turns
    negative once a lexeme appears in more than half the corpus; a chunk is then
    penalised for containing it, and on a small corpus that inverts the ranking
    outright. Lucene adds one before the logarithm, so its idf never drops below
    zero and a common term merely stops contributing. Lucene is the default for
    that reason; Robertson stays selectable because the difference is the whole
    lesson.

    ``df`` is clamped to the corpus size because a lexeme cannot occur in more
    chunks than exist. The clamp only bites on stale statistics: deleting chunks
    cascades their ``chunk_terms`` and ``chunk_lengths`` rows away but leaves
    ``lexeme_stats`` untouched, and an unclamped Robertson numerator would then go
    negative and make PostgreSQL raise on ``ln`` of a nonpositive argument.
    """
    if variant not in BM25_IDF_VARIANTS:
        raise ValueError("idf must be 'lucene' or 'robertson'")
    size = cast(corpus_size, Float)
    df = func.least(cast(document_frequency, Float), size)
    ratio = (size - df + 0.5) / (df + 0.5)
    if variant == "lucene":
        return func.ln(1.0 + ratio)
    return func.ln(ratio)


def _validated_parameters(query: str, k: int, k1: float, b: float) -> tuple[float, float]:
    """Validate public BM25 inputs and return normalized numeric parameters."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    if isinstance(k1, bool) or not isinstance(k1, Real):
        raise ValueError("k1 must be a finite positive number")
    if isinstance(b, bool) or not isinstance(b, Real):
        raise ValueError("b must be a finite number between 0 and 1")

    normalized_k1 = float(k1)
    normalized_b = float(b)
    if not math.isfinite(normalized_k1) or normalized_k1 <= 0:
        raise ValueError("k1 must be a finite positive number")
    if not math.isfinite(normalized_b) or not 0 <= normalized_b <= 1:
        raise ValueError("b must be a finite number between 0 and 1")
    return normalized_k1, normalized_b


def bm25_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
) -> Select[Any]:
    """Build a bound BM25 query with shared filters and deterministic ordering."""
    normalized_k1, normalized_b = _validated_parameters(query, k, k1, b)
    active_filters = filters or RetrievalFilters()

    query_terms = select(
        func.unnest(
            func.tsvector_to_array(
                func.to_tsvector(
                    TEXT_SEARCH_CONFIG,
                    bindparam("bm25_query", value=query, type_=String()),
                )
            )
        ).label("lexeme")
    ).subquery("bm25_query_terms")
    corpus = select(
        func.count(ChunkLength.chunk_id).label("n"),
        func.avg(ChunkLength.dl).label("avgdl"),
    ).subquery("bm25_corpus")

    k1_param = bindparam("bm25_k1", value=normalized_k1, type_=Float())
    b_param = bindparam("bm25_b", value=normalized_b, type_=Float())
    document_length = cast(ChunkLength.dl, Float)
    idf_term = _idf_expression(idf, corpus.c.n, LexemeStat.df)
    length_norm = 1.0 - b_param + b_param * document_length / corpus.c.avgdl
    saturation = (ChunkTerm.tf * (k1_param + 1.0)) / (ChunkTerm.tf + k1_param * length_norm)
    score = cast(func.sum(idf_term * saturation), Float).label("score")

    scores = (
        select(ChunkTerm.chunk_id.label("chunk_id"), score)
        .select_from(ChunkTerm)
        .join(query_terms, query_terms.c.lexeme == ChunkTerm.lexeme)
        .join(LexemeStat, LexemeStat.lexeme == ChunkTerm.lexeme)
        .join(ChunkLength, ChunkLength.chunk_id == ChunkTerm.chunk_id)
        .join(corpus, true())
        .group_by(ChunkTerm.chunk_id)
        .subquery("bm25_scores")
    )

    return (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.doc_id,
            Chunk.item,
            Chunk.kind,
            Chunk.citation,
            Chunk.start_char,
            Chunk.end_char,
            Chunk.source_sha256,
            Chunk.body,
            Chunk.context_header,
            Chunk.index_text,
            scores.c.score,
        )
        .select_from(Chunk)
        .join(scores, scores.c.chunk_id == Chunk.id)
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(*_filter_predicates(active_filters))
        .order_by(
            scores.c.score.desc(),
            Chunk.doc_id.asc(),
            Chunk.source_sha256.asc(),
            Chunk.start_char.asc(),
            Chunk.end_char.asc(),
            Chunk.id.asc(),
        )
        .limit(bindparam("bm25_k", value=k, type_=Integer()))
    )


async def bm25_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
) -> list[ChunkHit]:
    """Rank chunks by BM25 and return complete, deterministically ordered hits."""
    result = await session.execute(bm25_statement(query, k, filters, k1=k1, b=b, idf=idf))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_09_bm25.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.10 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/sbert.py`

<!-- file: app/retrieval/sbert.py -->
```python
"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from app.retrieval.embeddings import EmbeddingProvider, _texts, validate_embeddings

# The multilingual sibling of the default model. It outputs 384 dimensions natively,
# so it drops into ``Settings.sbert_model`` without touching ``embed_dim``, the
# ``Vector(384)`` column, or any migration — the difference is entirely in the space
# the vectors live in, where Korean and English text sit near each other.
MULTILINGUAL_SBERT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class _EmbeddingMatrix(Protocol):
    """Array-like sentence-transformer output used by the provider boundary."""

    def tolist(self) -> list[list[float]]:
        """Return the encoded batch as nested Python floats."""
        ...


class _SentenceEncoder(Protocol):
    """Structural type for the lazily imported sentence-transformer."""

    def get_sentence_embedding_dimension(self) -> int | None:
        """Return the model output width when the model reports one."""
        ...

    def encode(
        self,
        sentences: Sequence[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> _EmbeddingMatrix:
        """Encode one batch with the options required by this provider."""
        ...


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Local sentence-transformer embeddings behind the shared provider boundary.

    The model runs inside this process, so after the weights are cached there is no
    API key and no network call. ``sentence_transformers`` is imported lazily, which
    keeps ``app.retrieval`` importable when the project is installed without a torch
    backend extra.

    A local model is not interchangeable with a hosted one. Vectors produced here do
    not share a space with vectors produced by another model, so switching providers
    requires re-embedding every chunk. Mixing them yields no error, only meaningless
    neighbours.
    """

    def __init__(
        self,
        *,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimensions: int = 384,
        batch_size: int = 32,
    ) -> None:
        if not model:
            raise ValueError("embedding model must be nonempty")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        if batch_size <= 0:
            raise ValueError("embedding batch size must be positive")
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._encoder: _SentenceEncoder | None = None

    def _load(self) -> _SentenceEncoder:
        """Import and construct the encoder once, then reuse it.

        Raises
        ------
        RuntimeError
            If no torch backend extra is installed.
        ValueError
            If the model's output width does not match the database column.
        """
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; run one of "
                "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
            ) from exc

        encoder = cast(_SentenceEncoder, SentenceTransformer(self.model))
        reported = encoder.get_sentence_embedding_dimension()
        if reported != self.dimensions:
            raise ValueError(
                f"model {self.model!r} produces {reported} dimensions, "
                f"but this database stores {self.dimensions}"
            )
        self._encoder = encoder
        return encoder

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode a batch off the event loop and validate before returning."""
        inputs = _texts(texts)
        if not inputs:
            return []

        encoder = self._load()

        def _encode() -> list[list[float]]:
            """Run the synchronous, CPU-bound forward pass in a worker thread."""
            return encoder.encode(
                inputs,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).tolist()

        vectors = await asyncio.to_thread(_encode)
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M2.11 — 완성 체크포인트

#### 생성 또는 교체 `app/retrieval/cross_encoder.py`

<!-- file: app/retrieval/cross_encoder.py -->
```python
"""Cross-encoder reranking provider for the M2.6 boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from app.retrieval.rerank import RerankProvider


class _CrossEncoderModel(Protocol):
    """Structural type for the lazily imported cross-encoder."""

    def predict(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
    ) -> Sequence[float]:
        """Score query/document pairs in caller order."""
        ...


class CrossEncoderReranker(RerankProvider):
    """Rerank with a cross-encoder that reads the query and document together.

    The vector path in M2.3 is a bi-encoder: it embeds the query and the chunk
    separately and compares the two vectors afterwards, so the two texts never meet
    inside the model. That separation is what makes it cheap enough to run over the
    whole corpus, and also what limits its accuracy.

    A cross-encoder concatenates the query and one document into a single input and
    returns one relevance score. It reads both together, which is more accurate and
    costs one forward pass per candidate. That price is only affordable on a short
    list, which is why reranking runs after fusion rather than instead of it.

    The returned scores are raw logits. They are not probabilities, they are not
    bounded, and they are not comparable with cosine similarity or with BM25.
    """

    def __init__(
        self,
        *,
        model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        batch_size: int = 32,
    ) -> None:
        if not model:
            raise ValueError("reranker model must be nonempty")
        if batch_size <= 0:
            raise ValueError("reranker batch size must be positive")
        self.model = model
        self.batch_size = batch_size
        self._encoder: _CrossEncoderModel | None = None

    def _load(self) -> _CrossEncoderModel:
        """Import and construct the cross-encoder once, then reuse it."""
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; run one of "
                "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
            ) from exc

        self._encoder = cast(_CrossEncoderModel, CrossEncoder(self.model))
        return self._encoder

    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Score every query/document pair off the event loop, in caller order."""
        pairs = [(query, document) for document in documents]
        if not pairs:
            return []

        encoder = self._load()

        def _predict() -> list[float]:
            """Run the synchronous, CPU-bound forward passes in a worker thread."""
            return [float(value) for value in encoder.predict(pairs, batch_size=self.batch_size)]

        return await asyncio.to_thread(_predict)
```

체크포인트를 실행한다.

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
