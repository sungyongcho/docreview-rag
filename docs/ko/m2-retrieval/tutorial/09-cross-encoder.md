# M2.11 튜토리얼 9 — cross-encoder 재순위화

**선행 조건:** 튜토리얼 8의 `uv run pytest tests/retrieval/test_10_sbert.py -q`가 통과한다.

M2.6은 재순위화 경계를 만들고 의도적으로 비워 뒀다. 다섯 체크포인트 뒤인 지금에서야 그 자리를 채울 모델이 설치됐으니, 여기가 빈 자리에 주인이 들어오는 지점이다.

모델은 M2.10과 같은 계열이다. 바뀌는 것은 질문과 문서가 만나는 지점 하나이고, 이 장의 나머지 전부가 그 차이 하나에서 따라 나온다.

## 이번 체크포인트에서 다룰 파일

| 구분 | 경로 | 역할 |
|---|---|---|
| 확인만 | `app/retrieval/rerank.py` | M2.6에서 만든 `RerankProvider`와 `rerank_hits` 경계 확인 |
| 생성 | `app/retrieval/cross_encoder.py` | 지연 로딩하는 cross-encoder 공급자 구현 |
| 수정 | `app/retrieval/service.py` | 선택적 reranker를 받아 전체 후보를 재순위화하도록 배선 |
| 수정 | `app/retrieval/__main__.py` | `--rerank` 인자와 공급자 생성·전달 추가 |
| 수정 | `app/retrieval/__init__.py` | `CrossEncoderReranker`를 공개 패키지 표면에 export |
| 확인 | `tests/retrieval/test_11_cross_encoder.py` | 공급자와 서비스·CLI 배선 계약 검증 |

개념 그림과 실행 명령은 파일에 복사하지 않는다. `cross_encoder.py`의 세 메서드 블록은 모두 `CrossEncoderReranker` 클래스 안에 두고, 서비스 코드는 별도로 표시된 `service.py`에만 반영한다.

## 이중 인코더가 할 수 없는 일

M2.10은 이중 인코더 구조로 끝났다. 각 텍스트가 모델을 혼자 통과하고 둘은 그 뒤에 벡터로 만난다. 그 분리가 검색 경로 전체를 감당 가능하게 만들었다.

동시에 그것은 넘을 수 없는 한계이기도 하다. **모델은 질문과 문서를 같은 시점에 본 적이 없다.** 무엇을 물어볼지 모르는 채로 청크를 384개 숫자로 압축하고, 무엇이 저장돼 있는지 모르는 채로 질문을 384개 숫자로 압축한다. 둘을 함께 읽어야 알 수 있는 미묘함은 비교가 시작되기도 전에 사라진다.

### 둘을 같이 읽는다

cross-encoder는 두 텍스트를 하나의 입력으로 이어 붙이고 그 쌍에 대해 모델을 한 번 돌린다.

#### 파일 수정 없음 — bi-encoder와 cross-encoder 구조 비교

```text
bi-encoder (M2.3)
    query    ──> [model] ──> vector ─┐
                                     ├─> cosine similarity ─> score
    document ──> [model] ──> vector ─┘

cross-encoder (M2.11)
    query    ─┐
              ├─> [model] ──> score
    document ─┘
```

저장할 벡터가 없다. 출력은 그 특정 쌍에 대한 관련도 점수이고, 두 절반 사이에 어텐션이 온전히 걸린 채로 양쪽을 읽은 모델이 만들어낸다.

|  | 이중 인코더 | cross-encoder |
|---|---|---|
| 모델이 도는 대상 | 각 텍스트 하나씩 | 쌍을 통째로 |
| 결과물 | 재사용 가능한 벡터 | 쌍 하나에 대한 점수 |
| 문서 사전 계산 | 가능 | **불가능** |
| 질의당 비용 | 순전파 1회 | **후보마다 1회** |
| 정확도 | 낮다 | 높다 |

### 비용이 순서를 정한다

마지막 두 행을 붙여서 읽는다. 그 둘이 설계의 전부다.

cross-encoder는 아무것도 미리 계산할 수 없다. 점수는 질의가 도착해야 비로소 존재하므로 문서에 대해 준비해 둘 것이 없다. 9,172 청크를 채점한다는 것은 **질의마다** 순전파를 9,172번 돈다는 뜻이다.

감당할 수 없는 비용이고, 재순위화가 검색을 대체하지 않는 이유다. 검색 뒤에 붙는다.

#### 파일 수정 없음 — 2단계 검색 흐름 읽기

```text
stage 1   vector + lexical + RRF   9,172 chunks -> 20 candidates    cheap, wide
stage 2   cross-encoder            20 candidates -> 5 hits          expensive, narrow
```

**2단계 검색이 존재하는 이유는 정확한 모델은 넓게 돌리기에 너무 비싸고 값싼 모델은 혼자 쓰기에 너무 무디기 때문이다.** 각 단계가 상대의 약점을 덮는다. 1단계의 임무는 재현율이다. 2단계는 건네받은 것의 순서만 바꿀 수 있으므로, 1단계가 놓친 것은 영영 잃는다.

## M2.6이 비워 둔 자리

여기서 `rerank.py`는 하나도 바뀌지 않는다. 돌아가서 읽어 보라. `RerankProvider`가 선언한 메서드는 하나이고, 그 시그니처가 이미 이 장을 전제하고 있다.

#### 확인만 `app/retrieval/rerank.py` — 수정하지 않음

```python
async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
    """Return one relevance score per document in caller order."""
```

질문과 문서가 **함께**, 한 번의 호출로 도착한다. 이중 인코더라면 이런 것이 필요 없다. 문서는 색인 시점에, 질문은 따로 임베딩했을 것이다. **이 메서드의 모양이 곧 cross-encoder의 모양이고**, 뒤에 넣을 것이 아무것도 없던 M2.6에서 이미 정해졌다.

공급자 경계란 그런 것이다. 결정은 일찍 내려지고 구현은 늦게 도착하며, 그 사이의 코드는 어느 쪽이 어느 쪽인지 끝내 알지 못한다.

## 구현

`app/retrieval/cross_encoder.py`가 새 모듈인 이유는 `sbert.py`와 같다. `rerank.py`는 백엔드 없이도 import되어야 하고, 파일을 분리하면 그 성질이 눈에 보인다.

### 1. 생성과 지연 로딩

#### 생성 `app/retrieval/cross_encoder.py` — 모듈 헤더

```python
"""Cross-encoder reranking provider for the M2.6 boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence

from app.retrieval.rerank import RerankProvider
```

**코드에서 볼 것**

- import 목록이 M2.10의 교훈을 반복한다. `sentence_transformers`가 거기 없으므로 `import app.retrieval`은 여전히 torch 백엔드를 요구하지 않는다.
- 프로젝트 import는 `RerankProvider` 하나뿐이다. 이 파일 전체가 M2.6이 그은 경계 뒤에 서기 위해 존재하고, 헤더가 이미 그렇게 말하고 있다.

#### 수정 `app/retrieval/cross_encoder.py` — `CrossEncoderReranker.__init__`

```python
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
    self._encoder: object | None = None
```

**코드에서 확인할 것**

- 기본값은 MS MARCO로 학습된 모델이다. 실제 검색 질의로 만든 구절 순위 데이터 세트이고, 여기서 하는 일이 정확히 그 작업이다. 범용 모델이 기본값이 아닌 이유다.
- `dimensions` 필드가 없다. 벡터가 없기 때문이다. 없다는 사실 자체가 핵심이다. 이 모델이 만드는 것 중 저장되는 것은 하나도 없다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "constructing or rejects_invalid"
```

- `test_constructing_reranker_loads_no_model`
- `test_reranker_rejects_invalid_construction`

### 2. 모델을 처음 필요로 할 때 한 번만 읽는다

#### 수정 `app/retrieval/cross_encoder.py` — `CrossEncoderReranker._load`

```python
def _load(self) -> object:
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

    self._encoder = CrossEncoder(self.model)
    return self._encoder
```

`CrossEncoder` import를 메서드 안에 두는 이유는 M2.10과 같다. 패키지를 import하거나 공급자를 생성하는 것만으로 선택적 머신러닝 의존성을 요구하거나 모델 가중치를 읽어서는 안 된다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "missing_extra or constructs_the_model_once"
```

- `test_missing_extra_raises_an_actionable_runtime_error`
- `test_load_constructs_the_model_once`

### 3. 점수는 로짓이다

#### 수정 `app/retrieval/cross_encoder.py` — `CrossEncoderReranker.score`

```python
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

**코드에서 확인할 것**

- 기본 모델인 `cross-encoder/ms-marco-MiniLM-L-6-v2`가 반환하는 것은 날것의 로짓이다. 확률이 **아니고**, 어떤 범위로도 묶여 있지 않으며, 음수인 경우도 잦다. 이건 크로스 인코더 일반의 성질이 아니라 이 모델의 성질이다. 시그모이드 헤드로 학습한 모델은 0에서 1 사이 값을 내놓고, 그런 모델로 갈아끼울 때 경계를 손대야 해서는 안 된다. 그래서 M2.6의 검증기는 각 점수가 유한하다는 것만 요구한다. 0에서 1로 제한했다면 이 경계가 애초에 받으려던 공급자를 거부했을 것이다.
- `batch_size`는 일의 총량을 바꾸지 않는다. 모델은 여전히 후보 쌍마다 순전파를 한 번씩 돌고, 배치 크기는 그중 몇 쌍을 한 번에 모델로 넘길지만 정한다. **비용은 융합이 넘긴 후보 수가 정하며, 리랭킹 비용을 조절하는 손잡이가 `candidate_k`이지 `batch_size`가 아닌 이유가 그것이다.**
- 이 점수는 코사인 유사도와도 BM25와도 비교할 수 없다. 서로 맞지 않는 세 번째 척도이고, M2.5가 값이 아니라 순위를 융합해 대비해 둔 상황이 이것이다.
- `pairs`는 호출자 순서로 만들고 `predict`가 그 순서를 보존한다. 경계가 약속한 바다. 여기서 순서가 바뀌면 모든 점수가 조용히 엉뚱한 검색 결과에 붙는다.
- 순전파를 워커 스레드로 보내는 이유는 M2.10의 인코더와 같다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "score_preserves or empty_candidate"
```

- `test_score_preserves_pair_order_and_runs_predict_off_loop`
- `test_empty_candidate_list_does_not_load_a_model`

## 서비스에 배선한다

M2.7은 요청 하나를 조립하고 융합 결과를 `k`로 잘랐다. 리랭커가 있으면 잘라내기 전의 후보 묶음을 남겨야 한다.

`app/retrieval/service.py`에서 `RerankProvider`와 `rerank_hits`를 import하고, `retrieve`의 keyword-only 매개변수에 `reranker: RerankProvider | None = None`을 추가한 다음 아래 절단 지점을 교체한다.

#### 수정 `app/retrieval/service.py` — `retrieve`

```python
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
```

**코드에서 확인할 것**

- 리랭커가 없으면 융합이 예전과 똑같이 `k`로 자른다. **M2.7의 동작과 비슷한 것이 아니라 동일하다.** 리랭커를 꺼 둔 채로 두어도 안전한 근거가 이것이다.
- 있으면 융합이 `limit`개를 남기고 리랭커가 `k`로 자른다. 리랭커에게 `k`개만 건네면 더 낫게 만들 수도 없는 다섯 개의 순서만 뒤섞게 된다. 아무 일도 하지 않는 리랭커를 만드는 가장 흔한 방법이다.
- `rerank_hits`는 그대로 호출한다. 검증도, 결정론적 정렬도, top-k 절단도 전부 M2.6에서 작성됐고 여기서 다시 쓰는 것은 하나도 없다.
- 구성 요소 순위는 여전히 각 검색기가 제안한 것을 기록한다. 재순위화에서 살아남은 것이 아니다. 최종 답이 아니라 검색을 서술하는 값이다.

서비스만 바꾸면 CLI에서는 이 경로를 켤 수 없다. `app/retrieval/__main__.py`에 `--rerank` flag를 추가하고 참일 때 `CrossEncoderReranker`를 생성해 `retrieve(reranker=...)`로 전달한다. `app/retrieval/__init__.py`에도 새 클래스 import와 `__all__` 항목을 추가한다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q -k "m27 or rescores or component_rankings or cli_accepts or public_surface"
```

- `test_no_reranker_keeps_the_m27_behaviour`
- `test_reranker_rescores_the_full_candidate_pool_then_truncates`
- `test_component_rankings_record_proposals_not_rerank_survivors`
- `test_cli_accepts_rerank_flag`
- `test_public_surface_exports_cross_encoder`

## 집중 테스트와 테스트가 지키는 계약

#### 실행 `tests/retrieval/test_11_cross_encoder.py`

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q
```

| 테스트가 깨뜨리는 값 | 지켜지는 계약 |
|---|---|
| 후보 묶음 대신 `k`개를 받는 리랭커 | 재순위화가 실제로 결과를 바꿀 수 있다. |
| `k`보다 길거나 짧은 결과 | 호출자가 정한 개수를 지킨다. |
| 리랭커를 `None`으로 둔 결과가 달라짐 | M2.7의 동작이 그대로 보존된다. |
| 재순위화 생존자로 잘린 구성 요소 순위 | 출처가 답이 아니라 검색을 서술한다. |
| 범위로 제한된 점수 | 로짓도 유효한 공급자 출력이다. |

넘어가는 기준은 단순하다. 리랭커를 끄는 것만으로 결과가 달라진다면, 리랭커가 융합이 만든 것보다 적은 후보를 본다면, 붙이려고 `hybrid.py`나 `rerank.py`를 수정해야 했다면 M2.11을 받아들이지 않는다.

## 경계가 버텼음을 확인한다

M2.6이 주장했지만 검증할 수 없었던 것이 이것이다. 인수 경로를 양쪽으로 실행한다.

#### 실행 — reranker를 켠 검색 CLI 확인

```bash
uv run python -m app.retrieval --query "NVDA 2024 R&D" --k 5 --rerank
```

구조가 다르고 점수 척도도 다른 두 번째 모델이 통째로 검색에 참여하게 됐다. 그것을 허용하려고 바꾼 것을 세어 보라. 새 파일 두 개와 선택적 매개변수 하나다. `hybrid.py`, `rerank.py`, `vector.py`, `lexical.py`는 손대지 않았다.

**순서가 바뀐 것을 개선으로 읽지 않는다.** 순서가 달라졌다는 것은 리랭커가 돌았다는 증거일 뿐 그 이상이 아니다. 이 코퍼스에서 더 잘 찾는지는 M3.4가 답할 질문이고, 거기서 두 실험군을 골든셋에 대고 재서 재현율과 MRR과 지연 시간으로 문서에 적을 기본값을 고른다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **cross-encoder는 왜 아무것도 미리 계산할 수 없나?**
  - **답:** 출력이 질의와 문서 한 쌍에 대한 점수라서, 질의가 도착하기 전에는 계산할 대상 자체가 존재하지 않는다.
- **재순위화는 왜 검색을 대체하지 않고 뒤에 붙나?**
  - **답:** 후보마다 순전파가 한 번씩 들어가는데, 스무 개에는 감당되지만 9,172개에는 감당되지 않는다.
- **1단계가 책임지는 것 중 2단계가 고칠 수 없는 것은?**
  - **답:** 재현율이다. 리랭커는 건네받은 것의 순서만 바꿀 수 있으므로 검색이 놓친 것은 계속 빠져 있다.
- **공급자 점수를 0에서 1로 제한했다면 왜 잘못이었나?**
  - **답:** cross-encoder는 범위가 없고 음수도 흔한 로짓을 반환하므로 범위 검사가 정작 쓰려던 공급자를 거부한다.
- **리랭커가 `candidate_k`개를 받고 `k`개를 받지 않는 이유는?**
  - **답:** 융합이 버렸을 후보까지 봐야 재순위화가 결과를 바꿀 수 있기 때문이다.
- **이 경계를 채우면서 다른 곳에서 바꿔야 했던 것은?**
  - **답:** 없다. 서비스의 선택적 매개변수 하나뿐이고 융합에도, 재순위화에도, 두 검색 경로에도 수정이 없다.

---

**다음:** M2가 끝났다. [빌드 가이드로 돌아간 뒤](../03-build.md) [M3 평가](../../m3-evals/00-README.md)로 넘어간다. 거기서 이 모듈이 만든 모든 실험군이 마침내 측정된다.
