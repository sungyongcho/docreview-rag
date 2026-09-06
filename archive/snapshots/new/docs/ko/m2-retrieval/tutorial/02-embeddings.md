# M2.2 튜토리얼 2 — 네트워크 호출과 데이터베이스 트랜잭션을 분리한다

튜토리얼 1에서 검색 결과 타입을 정의했지만, 데이터베이스의 청크 9,172개는 아직 `embedding IS NULL` 상태다. 이 튜토리얼에서 그 열을 채운다.

작업 자체는 세 동작으로 끝난다. 벡터가 비어 있는 행을 읽고, 임베딩 API를 호출하고, 결과를 저장한다. 여기서 지켜야 할 조건이 셋이다.

**첫째, 문서와 질문을 같은 모델로 임베딩해야 한다.** 문서를 A 모델로, 질문을 B 모델로 임베딩하면 두 벡터는 서로 다른 공간에 놓인다. 코사인 유사도(cosine similarity)는 이때도 값을 반환하지만, 그 값은 두 텍스트의 의미적 거리를 나타내지 않는다. 그래서 질문 임베딩도 문서 임베딩과 **같은 경로를 통과**하게 만든다.

**둘째, 테스트가 네트워크에 의존하면 안 된다.** OpenAI를 호출하는 테스트는 느리고, 호출마다 비용이 발생하고, 오프라인에서 실행할 수 없다. 그래서 결정론적(deterministic) 가짜 공급자가 필요하다. 다만 난수를 반환하는 공급자로는 검색 순위를 검증할 수 없으므로, 이 공급자는 **어휘 중복(lexical overlap)을 벡터 거리에 반영**해야 한다.

**셋째, 느린 네트워크 호출과 데이터베이스 트랜잭션이 겹치면 안 된다.** 이 조건이 이 튜토리얼의 핵심 설계 결정이고, 7단계 직전에 따로 다룬다.

**선행 조건:** 튜토리얼 1의 `uv run pytest tests/retrieval/test_01_contract.py -q`가 통과해야 한다.

## 무엇을 작성하고 어디를 직접 구현할까

M2.2는 `app/retrieval/embeddings.py` 한 파일을 일곱 구간으로 나누어 작성한다. 파일은 벡터를 만드는 공급자 경계와, 만든 벡터를 저장하는 백필(backfill) 두 부분으로 나뉜다.

여기서 만드는 공급자는 둘뿐이고 둘 다 모델을 올리지 않는다. 하나는 API를 호출하고 하나는 텍스트를 해싱한다. 로컬 모델은 [튜토리얼 8](08-local-embeddings.md)의 M2.10에서 등장한다. 그것이 요구하는 의존성을 질 이유가 생긴 다음이다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더 | **구조 작성** | 이 파일이 걸친 두 경계 |
| `validate_embeddings` | 출력 계약을 **직접 구현** | 모든 공급자가 데이터베이스에 닿기 전에 만족해야 할 조건 |
| `EmbeddingProvider` | **설계 결정 확인** | 상속으로 질문과 문서를 한 경로에 묶는 방법 |
| `DeterministicEmbeddingProvider` | 해싱 알고리즘을 **직접 구현** | 오프라인 공급자가 어휘 중복을 보존해야 하는 이유 |
| `OpenAIEmbeddingProvider`와 `get_embedding_provider` | **구조 작성 후 경계 변환 검토** | 응답 인덱스로 호출자 순서를 복원하는 방법 |
| `PendingEmbedding`과 `EmbeddingBackfillResult` | **레코드 선언 작성** | 재개 가능한 작업이 반환해야 하는 값 |
| `_missing_batch`, `_store_batch`, `embed_missing_chunks` | 트랜잭션 분할을 **직접 구현** | I/O를 트랜잭션 밖에 두는 방법과 stale 가드가 막는 상태 |

## 1. 모듈 헤더

### `app/retrieval/embeddings.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록이 이 파일의 두 영역을 보여준다. 한쪽은 해시와 텍스트 정규화, 다른 쪽은 SQLAlchemy 세션과 ORM 모델이다.

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
```

## 2. 모든 공급자가 통과하는 검증기 하나

공급자 구현은 한 종류가 아니다. 원격 API를 호출하는 구현, 테스트용 가짜 구현, 나중에 교체될 구현이 모두 같은 자리에 들어온다. 그리고 어느 구현이 반환했든 그 벡터는 PostgreSQL의 `Vector(384)` 열에 저장된다.

검증을 공급자마다 두면 검사 기준이 구현별로 갈라진다. 한 구현이 차원 검사를 빠뜨리면 잘못된 길이의 벡터가 그대로 데이터베이스로 향하고, 그 벡터는 저장 시점이 아니라 검색 결과가 이상해질 때 발견된다.

**출력 검증은 공급자 안이 아니라 데이터베이스 경계 바로 앞 한 곳에 둔다.** 모든 공급자가 같은 함수를 통과하므로 검사 기준이 하나로 유지된다.

### `app/retrieval/embeddings.py` 확장 — 공유 출력 검증

**학습 행동 — 출력 계약 구현:** `_texts`는 주어진 대로 작성하고, `validate_embeddings`는 직접 구현한다. 각 `raise` 문이 공급자가 계약을 어기는 방식 하나에 대응한다.

<!-- src: app/retrieval/embeddings.py::_texts,validate_embeddings -->
```python
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
```

### `float`과 `Real`은 서로 대신 쓰는 타입이 아니다

이 코드에는 `float`과 `Real`이 함께 남아 있지만 역할은 겹치지 않는다.

- `Sequence[float]`은 정상적인 공급자가 반환해야 하는 값의 **정적 타입 계약**이다. `embed_query()`의 `list[float]`이 벡터 검색 함수까지 Pylance 오류 없이 이어지는 기준이다.
- `isinstance(component, Real)`은 실행 중 실제로 받은 객체가 숫자인지 확인하는 **런타임 검증**이다. 타입 힌트는 실행 중 잘못 들어온 문자열이나 `bool`을 막지 못하므로 이 검사는 그대로 필요하다.

Python 실행 환경에서는 `isinstance(1.0, Real)`이 참이지만, [공식 typeshed의 `numbers.pyi`](https://github.com/python/typeshed/blob/main/stdlib/numbers.pyi)는 정적 타입 검사기가 `float`을 `numbers.Real`의 하위 타입으로 보지 않는다고 명시한다. 그래서 함수 인자를 `Sequence[Real]`로 선언하면 정상적인 `list[float]`을 넘길 때도 Pylance가 거부한다.

이 프로젝트의 규칙은 간단하다. **함수 시그니처와 정규화된 결과에는 `float`, 실제 값의 숫자 여부를 검사하는 `isinstance`에는 `Real`을 사용한다.** 이는 속도를 높이는 최적화가 아니라 런타임 검증과 정적 타입 계약을 일치시키는 수정이다.

**코드에서 꼭 볼 것**

- `list(values)`가 첫 줄이다. `_texts`는 입력을 먼저 리스트로 복사한다. 제너레이터를 그대로 두면 뒤따르는 문자열 검사가 항목을 소진하므로 공급자에게는 빈 입력이 전달된다.
- `isinstance(component, bool)`을 별도로 거부한다. Python에서 `bool`은 `int`의 하위 클래스이므로, 이 검사가 없으면 `True`가 수치 성분으로 통과해 `1.0`으로 저장된다.
- `math.isfinite`가 NaN과 무한대를 차단한다. NaN이 들어간 벡터는 거리 비교 결과가 모두 거짓이 되므로, 해당 청크는 오류 없이 검색 결과에서만 사라진다.
- 개수 검사는 공급자가 반환한 리스트 길이를 호출자가 넘긴 `expected_count`와 비교한다. 몇 개를 요청했는지 아는 쪽은 공급자가 아니라 호출자다.

## 3. 공급자 경계

도입부의 첫 번째 조건, 즉 문서와 질문을 같은 모델로 임베딩해야 한다는 규칙은 주석으로 적어 두는 방식으로는 지켜지지 않는다.

이 규칙은 다음 두 변경에서 깨진다. 하나는 문서 임베딩에 캐시를 붙이면서 질문은 캐시를 건너뛰도록 질문 전용 경로를 추가하는 경우다. 다른 하나는 짧은 입력에 더 싼 엔드포인트를 제공하는 공급자로 바꾸면서 질문만 그 엔드포인트로 보내는 경우다. 각 변경은 그 자체로는 합리적이지만, 결과적으로 질문 벡터를 문서 벡터와 다른 공간에 놓는다.

이때 유사도 계산은 실패하지 않는다. 값은 계속 나오고 순위도 매겨진다. 다만 그 순위가 질문과 문서의 의미적 거리를 반영하지 않을 뿐이다. 출력 검증기도 이 상태를 잡지 못한다. 벡터의 개수와 차원은 정상이기 때문이다.

**따라서 질문 전용 임베딩 경로를 애초에 정의할 수 없도록 클래스 구조로 막는다.**

### `app/retrieval/embeddings.py` 확장 — 공급자 경계

**학습 행동 — 설계 결정 확인:** 이 클래스는 짧다. 어느 메서드가 추상이고 어느 메서드가 아닌지가 핵심이다.

<!-- src: app/retrieval/embeddings.py::EmbeddingProvider -->
```python
class EmbeddingProvider(ABC):
    """Async provider boundary shared by query and document embeddings."""

    dimensions: int

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch in caller order."""

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query through the same model and validation path."""
        return (await self.embed_documents([text]))[0]
```

추상 메서드는 `embed_documents` 하나뿐이다. **`embed_query`는 추상 메서드가 아니라 그 배치 메서드를 호출하는 구체 메서드이므로, 하위 클래스는 질문만 다른 모델이나 다른 엔드포인트로 보내는 경로를 새로 정의할 수 없다.** 질문과 문서가 같은 모델과 같은 검증을 통과한다는 조건을 주석이 아니라 상속 구조가 보장한다.

## 4. 결정론적 공급자

오프라인 공급자가 난수 벡터를 반환하면 같은 질문과 같은 청크 사이의 거리가 실행마다 달라진다. 벡터를 만드는 데는 성공하지만, 검색 순위를 확인하는 테스트는 실행할 때마다 다른 결과를 얻는다.

**난수를 반환하는 오프라인 공급자로는 질문과 어휘가 겹치는 청크가 상위에 오는지 검증할 수 없다. 오프라인 공급자는 무작위가 아니라 어휘 중복을 벡터 거리로 바꾸는 규칙을 따라야 한다.**

텍스트를 토큰으로 나누고 각 토큰을 부호가 있는 버킷에 해싱하면, 같은 단어를 공유하는 텍스트끼리 같은 차원에 값이 쌓여 내적이 커진다.

### `app/retrieval/embeddings.py` 확장 — 결정론적 공급자

**학습 행동 — 해싱 알고리즘 구현:** 정규화, 토큰화, 버킷 해싱, 벡터 정규화 네 단계를 순서대로 직접 구현한다.

<!-- src: app/retrieval/embeddings.py::DeterministicEmbeddingProvider -->
```python
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
```

**코드에서 꼭 볼 것**

- `unicodedata.normalize("NFKC", text).casefold()`가 토큰화보다 먼저 실행된다. 서로 다른 filing에서 온, 눈으로는 같은 텍스트가 같은 토큰으로 해싱되려면 이 순서여야 한다.
- 부호 `sign`은 `digest[8] & 1`로 결정한다. 부호가 없으면 모든 토큰이 값을 더하기만 하므로 긴 텍스트의 벡터가 한 방향으로 몰리고, 유사도가 어휘 중복 대신 텍스트 길이를 반영한다.
- `norm == 0.0` 분기는 실행되지 않는 코드가 아니다. 부호가 있는 버킷은 정확히 상쇄되어 0이 될 수 있고, 그 값으로 나누면 NaN이 나온다. 그 벡터는 `validate_embeddings`에서 거부되므로, 이 분기가 없으면 백필이 그 청크에서 멈춘다.
- `tokens = ["<empty>"]`는 영숫자 토큰이 하나도 없는 텍스트에 고정 토큰 하나를 넣는다. 이 처리가 없으면 해당 텍스트의 벡터가 전부 0이 되어 정규화 단계에서 0으로 나누게 된다.

## 5. OpenAI 공급자와 공급자 선택

배치 임베딩 API는 텍스트 리스트를 받아 벡터 리스트를 반환한다. 응답을 도착한 순서대로 읽어 입력과 짝지어도 대부분 정상 동작한다. 응답이 대개 요청 순서대로 오기 때문이다.

문제는 API가 응답 순서를 보장하지 않는다는 점이다. 순서가 한 번 어긋나면 40번 청크의 벡터가 41번 청크의 행에 저장된다. 이때 벡터 자체는 정상이다. 개수도 맞고, 차원도 맞고, 성분도 모두 유한하다. 그래서 `validate_embeddings`도 이 응답을 통과시킨다. 벡터의 형태에는 그 벡터가 어느 텍스트에서 나왔는지에 대한 정보가 없다.

이 손상은 예외를 발생시키지 않는다. 검색은 계속 결과를 반환하고, 반환된 근거만 질문과 무관해진다. 겉으로 드러나는 신호는 M3 평가 점수가 설명되지 않는 폭으로 떨어지는 것뿐이다.

**응답 항목이 함께 실어 보내는 인덱스로 호출자 순서를 복원하고, 그 인덱스가 모든 입력 위치를 정확히 한 번씩 덮지 않으면 저장을 중단한다.**

### `app/retrieval/embeddings.py` 확장 — OpenAI 공급자와 선택

**학습 행동 — 구조 작성 후 경계 변환 검토:** 생성자는 기계적이다. `embed_documents`가 호출자 순서를 복원하는 부분만 자세히 본다.

<!-- src: app/retrieval/embeddings.py::OpenAIEmbeddingProvider,get_embedding_provider -->
```python
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
```

**코드에서 꼭 볼 것**

- 응답을 도착 순서로 읽지 않고 `by_index` 사전으로 다시 배열한다. 순서가 어긋난 채 저장되면 모든 벡터가 다른 청크에 붙고, 벡터의 형태만 검사하는 테스트로는 이 손상을 잡을 수 없다.
- 이 사전을 검사 두 개가 지킨다. 하나는 정수가 아니거나 이미 사용된 인덱스를 거부하고, 다른 하나는 인덱스 집합이 모든 입력 위치를 덮는지 확인한다.
- `client`를 주입할 수 있다. 덕분에 테스트가 네트워크 없이 이 공급자의 응답 처리 경로를 실행한다.
- `get_embedding_provider`는 import 시점이 아니라 호출 시점에 설정을 읽는다. 그래서 테스트가 설정 객체를 직접 넘겨 공급자 선택을 검증할 수 있다. M1.4에서 시드 CLI가 `app.db.session` import를 함수 안으로 미룬 것과 같은 이유다.

## 6. 재개 가능한 작업이 반환해야 하는 값

청크 9,172개를 임베딩하는 작업은 호출 비용이 들고, 중간에 중단될 수 있고, 여러 번 실행된다. 이 작업이 완료 여부만 보고하면 실행 후에 두 가지를 확인할 수 없다. 선택한 행을 모두 저장했는지, 저장하지 못한 행이 있다면 그것이 오류인지 정당한 건너뜀인지다.

로그를 사후에 읽어 두 가지를 판단하는 것은 추정이다.

**작업은 선택한 행 수와 저장한 행 수를 각각 반환하고, 두 수의 차이를 건너뛴 행 수로 설명해야 한다.**

### `app/retrieval/embeddings.py` 확장 — 백필 레코드

**학습 행동 — 레코드 선언 작성:** 카운터는 네 개다. 각 카운터가 실행 후 어떤 질문에 답하는지 확인하며 작성한다.

<!-- src: app/retrieval/embeddings.py::PendingEmbedding,EmbeddingBackfillResult -->
```python
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
```

**코드에서 꼭 볼 것**

- `PendingEmbedding`은 `index_text`를 `chunk_id`와 함께 보관한다. 이 사본이 7단계의 stale 가드가 비교할 기준값이다.
- `selected`와 `embedded`는 별도 카운터다. 두 값이 다를 때 `skipped_stale`이 그 차이를 설명하므로 저장하지 못한 행이 조용히 묻히지 않는다.

## 트랜잭션을 연 채로 API를 호출하면 안 된다

가장 단순한 백필 구현은 읽기, API 호출, 쓰기를 트랜잭션 하나 안에서 처리한다.

```
begin transaction
  → read the null rows
  → call OpenAI          ← several seconds here
  → UPDATE with results
commit
```

이 구현도 동작은 한다. 그러나 **네트워크 왕복이 끝날 때까지 대상 행의 잠금이 유지되고, API 호출이 타임아웃되면 트랜잭션 전체가 롤백되어 같은 트랜잭션에서 이미 성공한 임베딩 결과까지 사라진다.** 청크 9,172개를 배치로 처리하면 잠금 시간이 누적되고, 같은 행을 갱신하는 다른 시드 작업은 그동안 멈춰 있다.

그래서 트랜잭션을 **짧게 끊고 그 사이에 I/O를 둔다.**

```
[transaction 1]  read one null batch and close immediately
                  ↓
[no transaction] request embeddings (slow, fallible, paid)
                  ↓
[transaction 2]  UPDATE only rows still null with unchanged index_text
```

이 분할이 두 가지를 보장한다.

**재개 가능성(resumability).** 작업이 중간에 중단되어도 이미 커밋된 배치는 남는다. 다시 실행하면 남아 있는 null 행부터 이어서 처리한다. M1.4에서 `embedding` 열을 nullable로 정의한 결정이 여기서 재개 지점을 제공한다.

**경합 안전성.** 임베딩을 계산하는 사이에 누군가 해당 filing을 다시 시드하면 청크 텍스트가 바뀐다. 그 시점부터 계산이 끝난 벡터는 이전 텍스트의 벡터다. **두 번째 트랜잭션의 UPDATE는 `still null and index_text unchanged` 두 조건을 함께 검사한다. 앞의 조건은 다른 실행이 이미 채운 행을 막고, 뒤의 조건은 공급자를 호출하는 동안 텍스트가 바뀐 행을 막는다.**

두 번째 조건이 없으면 이전 텍스트의 벡터가 현재 텍스트의 행을 덮어쓴다. 이 상태에서는 예외도 로그도 남지 않고, 해당 청크의 검색 결과만 본문과 어긋난다.

## 7. 짧은 트랜잭션 둘과 그 사이의 I/O

### `app/retrieval/embeddings.py` 확장 — 경계가 정해진 두 트랜잭션

**학습 행동 — 트랜잭션 분할 구현:** 두 함수를 직접 구현한다. 각 함수는 짧은 트랜잭션 하나씩만 소유하고, 어느 쪽도 공급자 I/O를 수행하지 않는다.

<!-- src: app/retrieval/embeddings.py::_missing_batch,_store_batch -->
```python
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
```

**코드에서 꼭 볼 것**

- `return` 문이 `_missing_batch`에서 `async with` 블록 바깥에 있다. 그래서 호출자가 공급자 I/O를 시작하는 시점에는 읽기 트랜잭션이 이미 닫혀 있다.
- `.order_by(Chunk.id)`가 각 배치를 안정적인 구간으로 만든다. 정렬이 없으면 반복되는 `LIMIT` 질의가 같은 행을 다시 읽거나 일부 행을 건너뛸 수 있다.
- `_store_batch`의 WHERE 절은 조건 세 개를 함께 검사한다. `Chunk.embedding.is_(None)`은 다른 실행이 이미 채우지 않았다는 조건이고, `index_text` 비교는 공급자를 호출하는 동안 텍스트가 바뀌지 않았다는 조건이다.
- 거부된 쓰기는 `result.rowcount == 1`로 감지한다. 조건에 맞는 행이 없으면 예외가 아니라 갱신 행 수 0이 반환되므로, 카운터로만 이 상태를 관측할 수 있다.
- `strict=True`를 붙인 `zip`은 공급자가 배치 크기와 다른 개수의 벡터를 반환했을 때 그 자리에서 실패한다. 이 옵션이 없으면 짧은 쪽에 맞춰 조용히 잘린다.

## 8. 백필 루프

### `app/retrieval/embeddings.py` 완성 — 재개 가능한 루프

**학습 행동 — 루프 불변조건 구현:** 카운터와 루프 조건이 이 함수의 전부다. 작성한 뒤 같은 인자로 다시 실행해도 중복 작업이 없는지 확인한다.

<!-- src: app/retrieval/embeddings.py::embed_missing_chunks -->
```python
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

**코드에서 꼭 볼 것**

- `session.in_transaction()`이면 여기서 실패시키는 이유는 M1.4와 같다. 바깥 트랜잭션이 열려 있으면 내부의 모든 `session.begin()`이 세이브포인트가 되어 배치마다 커밋된다는 전제가 사라지고, 재개 가능성도 함께 사라진다.
- 루프 조건은 남은 개수를 세지 않고 매번 null 행을 다시 질의한다. 그래서 중단된 실행을 이어서 처리할 수 있고, 저장에 성공한 행은 null이 아니게 되므로 루프가 종료된다.
- 공급자 내부에서 이미 호출했더라도 `validate_embeddings`가 루프에서 한 번 더 실행된다. 이 루프는 직접 작성하지 않은 공급자 구현이 계약을 지켰다고 가정하지 않는다.
- 오래된(stale) 행은 재시도하지 않고 건너뛴다. 그 행은 null로 남으므로 다음 실행이 바뀐 텍스트로 다시 선택한다.

여기까지 작성하면 `app/retrieval/embeddings.py`가 완성된다. 여덟 개 코드 블록을 순서대로 이어 붙인 것이 그대로 체크포인트 파일이다.

## 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/retrieval/test_02_embeddings.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 어긋난 벡터 개수 또는 차원 | 모든 공급자가 하나의 출력 형태를 만족한다. |
| NaN·무한대·불리언 성분 | 사용할 수 없는 벡터가 데이터베이스에 닿지 않는다. |
| 뒤섞인 OpenAI 응답 인덱스 | 벡터가 다른 청크에 붙지 않는다. |
| 설정된 공급자 이름 | 공급자 선택이 import 시점 작업 없이 설정을 따른다. |
| 공급자 I/O 도중 바뀐 텍스트 | 이전 텍스트의 벡터가 현재 텍스트를 덮어쓰지 않는다. |
| 부분 실패 후 재실행 | 이미 커밋된 배치를 다시 계산하지 않는다. |

구현이 끝나면 개수, 순서, 차원, 유한성, 공급자 선택, 오래된 쓰기 방지를 검증하는 모든 임베딩 테스트가 네트워크 없이 통과해야 한다.

출력 형태 테스트나 오래된 쓰기 방지 테스트가 하나라도 실패하면 M2.2를 완료로 판단하지 않는다.

벡터 개수나 차원에서 실패하면 공유 검증기부터 확인한다. 백필에서 실패하면 공급자 I/O가 두 트랜잭션 사이에서 실행되는지, 그리고 UPDATE 조건에 비어 있는 임베딩과 변경되지 않은 `index_text`가 모두 포함되는지 확인한다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **`embed_query`가 추상 메서드가 아닌 이유는 무엇인가?**
  - **답:** `embed_query`는 `embed_documents`에 위임하는 편리한 기본값이므로 단순한 하위 클래스는 배치 임베딩만 구현하면 된다. 하지만 하위 클래스가 재정의할 수 있으므로 상속이 강제하는 보장은 아니라 관례다.
- **난수를 반환하는 오프라인 공급자로는 무엇을 검증할 수 없는가?**
  - **답:** 난수 벡터는 어휘 중첩을 보존하지 않으므로 관련 텍스트가 무관한 텍스트보다 높은 순위에 오는지 검색 테스트로 확인할 수 없다.
- **`by_index`로 순서를 복원하는 것이 막는 손상은 무엇인가?**
  - **답:** API 응답 순서가 요청 순서와 다를 때 한 텍스트의 벡터를 다른 텍스트나 청크에 저장하는 손상을 막는다.
- **API 호출이 하나의 긴 트랜잭션 안에서 일어나면 정확히 무엇을 잃는가?**
  - **답:** 네트워크를 기다리는 내내 잠금을 점유하고, 타임아웃 하나로 성공한 모든 배치가 롤백되어 재개 가능한 진행 상태를 잃는다.
- **마지막 UPDATE가 반드시 포함해야 하는 두 조건은 무엇이고 각각 무엇을 막는가?**
  - **답:** 임베딩이 여전히 null이어야 한다는 조건은 다른 작업의 결과를 덮어쓰지 않게 하고, `index_text`가 그대로라는 조건은 변경 전 텍스트로 만든 낡은 벡터의 저장을 막는다.

---

[← 이전: 계약](01-contracts.md) · [모듈 개요](../03-build.md) · [다음 →: 검색 경로](03-retrieval-paths.md)
