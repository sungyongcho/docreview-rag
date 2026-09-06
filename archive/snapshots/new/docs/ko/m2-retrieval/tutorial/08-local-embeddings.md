# M2.10 튜토리얼 8 — 로컬 임베딩 모델

**선행 조건:** 튜토리얼 7의 `uv run pytest tests/retrieval/test_09_bm25.py -q`가 통과한다.

지금까지 임베딩은 전부 API 호출로 만들었다. 의도한 선택이었고, 이 체크포인트에서 그 선택을 다시 본다. 모델을 프로세스 안에서 직접 돌린다.

이 장은 트랜스포머를 한 번도 직접 올려본 적 없다고 가정한다. 임베딩 모델이 무엇인지에서 출발해, 이 프로젝트가 왜 아홉 체크포인트를 지나서야 설치하는지 설명하고, 습관이 아니라 측정으로 백엔드를 골라 PyTorch를 설치한 다음, 두 번째 임베딩 공급자가 만들어내는 실패 모드로 끝난다.

## 이번 체크포인트에서 다룰 파일

| 구분 | 경로 | 역할 |
|---|---|---|
| 수정 | `pyproject.toml` | CPU·CUDA·ROCm 선택 extra와 패키지 index 선언 |
| 자동 갱신 | `uv.lock` | 선택 가능한 로컬 모델 의존성 해석 결과 기록 |
| 수정 | `app/config.py` | `sbert` provider 이름과 모델 설정 추가 |
| 생성 | `app/retrieval/sbert.py` | 지연 로딩하는 로컬 임베딩 공급자 구현 |
| 수정 | `app/retrieval/embeddings.py` | 설정에 따라 SBERT 공급자를 만드는 factory 분기 추가 |
| 수정 | `app/retrieval/__main__.py` | CLI의 provider 선택지에 `sbert` 추가 |
| 수정 | `app/retrieval/__init__.py` | 새 공급자를 공개 패키지 표면에 export |
| 확인 | `tests/retrieval/test_10_sbert.py` | 실제 모델 없이 공급자와 배선 계약을 검증하는 집중 테스트 |

개념 그림과 실행 명령은 파일에 복사하지 않는다. 구현 블록은 바로 위에 적힌 경로에 넣고, `sbert.py`의 메서드 블록들은 모두 `SentenceTransformerEmbeddingProvider` 클래스 안에 둔다.

## 임베딩 모델을 처음 올려본다면

M2.2는 임베딩을 "텍스트를 고정 길이 벡터로 바꾼 것"이라고 설명했다. 하는 일은 그게 맞다. 그 벡터를 만드는 것이 신경망이고, **어떤 신경망이냐가 검색 경로의 어떤 설정보다 결과를 크게 좌우한다.**

BERT는 문장을 읽고 벡터를 **토큰마다 하나씩** 내놓는다. 문장 하나가 아니다. 두 문장을 비교하려면 그 토큰 벡터들을 어떻게든 하나로 합쳐야 하는데, 떠오르는 방법들이 잘 듣지 않는다. BERT의 토큰 벡터를 평균 내면 단어 벡터를 평균 낸 것보다 조금 나은 수준의 문장 유사도가 나온다.

**SBERT는 그 합친 벡터가 실제로 쓸모 있도록 BERT를 미세 조정한 것이다.** 비슷하다고 알려진 문장 쌍의 벡터는 가까이 당기고 다른 쌍은 밀어내는 방식으로 학습한다. 구조는 거의 그대로고 학습 목표가 바뀐다. Sentence-BERT라는 이름이 가리키는 바가 이것이다.

### 이중 인코더라는 구조

구조에서 중요한 것은 질문과 문서가 어디서 만나느냐다.

#### 파일 수정 없음 — bi-encoder 구조 읽기

```text
query    ──> [model] ──> vector ─┐
                                 ├─> cosine similarity ─> score
document ──> [model] ──> vector ─┘
```

각 텍스트가 모델을 **따로** 통과한다. 둘은 그 뒤에 벡터 두 개로만 만나고, 만나는 방식은 산술 연산이다. 이것을 **이중 인코더(bi-encoder)**라고 부른다.

이 분리가 검색 경로 전체를 가능하게 한다. 문서는 미리 한 번 임베딩해서 저장해 두면 되고, 질의 시점에는 질문만 모델을 통과하며, 검색은 저장된 벡터에 대한 거리 계산이 된다. 9,172 청크를 임베딩하는 비용은 한 번만 든다.

이 모양을 기억해 둔다. M2.11이 바로 이 배치를 바꾸고, 거기서 나오는 결과들이 전부 이 모양에서 따라 나온다.

## 왜 지금까지 API였나

M2.2에서 로컬 모델을 올릴 수도 있었다. 그러지 않았고, 그 이유는 모델링이 아니라 패키징 판단이므로 밝혀둘 값이 있다.

로컬 모델은 PyTorch를 끌고 온다. 수백 메가바이트에, 플랫폼마다 다른 빌드에, 컨테이너 이미지가 몇 배로 커진다. 이걸 M2.2에서 짊어졌다면 이후 모든 체크포인트가 그 무게를 지고 갔을 것이다. 모델과 아무 상관 없는 단계들까지 포함해서다.

**M2.1부터 M2.9까지는 머신러닝 의존성이 하나도 없이 돈다.** 파싱, 청킹, 적재, 벡터 검색, 어휘 검색, 융합, BM25가 전부 그것 없이 동작한다. 우연이 아니고, 이 장이 늦게 오는 이유다.

규칙으로 옮기면 이렇다. **의존성은 처음 언급되는 체크포인트가 아니라 실제로 필요해지는 체크포인트에서 진다.**

## PyTorch를 설치한다

### 측정으로 백엔드를 고른다

PyTorch는 서로 배타적인 빌드 여러 개로 배포된다. 자기 GPU에 맞는 것을 고르고 싶어지는데, 워크로드를 알기 전까지는 참는다.

| 작업 | 규모 |
|---|---|
| 재순위화 (M2.11) | 질의당 후보 20개 남짓에 6층 MiniLM |
| 임베딩 백필 | 9,172 청크, 한 번 실행 |

둘 다 작다. 이 정도 배치는 연산량보다 호출당 오버헤드가 지배하고, 내장 GPU는 시스템 메모리를 공유하므로 대역폭 이점도 없다. **이 프로젝트의 기본 백엔드는 CPU이고**, 이는 차선책이 아니라 측정에 따른 결정이다.

AMD 내장 그래픽에는 두 번째 이유가 하나 더 있다. 이 칩들에 대한 지원은 오고 있지만 아직 완결되지 않았다. 일부 대상에는 컨볼루션 데이터베이스가 배포되지 않고, 사람들이 흔히 손대는 환경 변수 우회는 동작하는 대신 머신을 하드락시킨다고 보고돼 있다. **머신을 잠글 수도 있는 백엔드는 백엔드가 아니다.**

### uv로 백엔드를 전환한다

설치 명령을 문서에 적어두는 대신, 백엔드들을 프로젝트에 선언하고 uv가 하나를 고르게 한다.

#### 수정 `pyproject.toml`

```toml
[project.optional-dependencies]
cpu = ["torch>=2.12", "sentence-transformers>=3.0"]
cu130 = ["torch>=2.12", "sentence-transformers>=3.0"]
rocm = ["torch>=2.12", "sentence-transformers>=3.0", "triton-rocm>=3.7"]

[tool.uv]
conflicts = [
    [{ extra = "cpu" }, { extra = "cu130" }, { extra = "rocm" }],
]

[tool.uv.sources]
torch = [
    { index = "pytorch-cpu", extra = "cpu" },
    { index = "pytorch-cu130", extra = "cu130" },
    { index = "pytorch-rocm", extra = "rocm" },
]
triton-rocm = [
    { index = "pytorch-rocm", extra = "rocm" },
]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[[tool.uv.index]]
name = "pytorch-rocm"
url = "https://download.pytorch.org/whl/rocm7.2"
explicit = true
```

**설정에서 확인할 것**

- `conflicts`는 백엔드 두 개가 동시에 잡히면 uv가 하나를 조용히 골라 해결하는 대신 **거부**하게 만든다. 한 환경에 PyTorch 빌드가 둘 있는 상황은 한참 뒤에 알 수 없는 import 오류로 나타나는 종류의 버그다.
- ROCm torch wheel은 `triton-rocm`의 정확한 버전을 요구한다. 이 패키지를 `rocm` extra에 직접 선언하고 같은 공식 index로 보내야 `explicit = true`인 상태에서도 uv가 전이 의존성을 찾을 수 있다.
- `explicit = true`는 `tool.uv.sources`가 이 인덱스로 보내지 않은 패키지를 이 인덱스가 제공하지 못하게 막는다. 없으면 인덱스가 PyPI의 무관한 패키지를 가릴 수 있다.
- 백엔드는 잠금 파일에 정답 하나로 기록되지 않고 설치할 때마다 골라진다. 노트북과 배포 대상이 프로젝트를 고치지 않고도 달라질 수 있는 이유다.

#### 실행 — CPU extra 설치 및 `uv.lock` 갱신

```bash
uv sync --extra cpu
```

어떤 빌드가 들어왔는지 확인한다.

#### 실행 — 설치된 PyTorch 빌드 확인

```bash
uv run python -c "import torch; print(torch.__version__)"
```

`+cpu`가 붙었다면 CPU 빌드다. 연산 플랫폼 이름이 붙었다면 그 빌드가 설치된 것이고, 그건 대응하는 하드웨어와 드라이버가 있을 때만 쓸모가 있다. **CUDA가 없는 머신의 CUDA 빌드는 오류가 아니다. GPU를 한 번도 쓰지 않으면서 수 기가바이트를 차지할 뿐이다.**

## 이 체크포인트가 새로 만드는 실패 모드

코드를 쓰기 전에 읽는다. 예외가 아니라 **틀린 답**을 만들어내는 부분이기 때문이다.

임베딩 벡터는 그 자체로는 아무 의미가 없다. **그 벡터를 만든 모델과의 관계에서만** 의미를 갖는다. 서로 다른 모델은 폭이 같으면서 아무 관계 없는 공간에 사는 벡터를 만든다.

데이터베이스는 청크당 384개의 숫자를 저장한다. 어떤 모델이 만들었는지는 저장하지 않는다. 그래서 다음 순서가 가능하다.

#### 파일 수정 없음 — 잘못된 임베딩 공간 혼합 흐름 읽기

```text
1. Embed 9,172 chunks with the API provider     -> 384 numbers per chunk
2. Switch the provider to the local model
3. Embed the query locally                      -> 384 numbers
4. Compare                                      -> a number comes back
```

4단계는 성공한다. 384차원 벡터 두 개의 코사인 유사도는 언제나 계산된다. **결과는 무의미하고, 어디서도 문제를 보고하지 않는다.** 검색 품질이 무너지는 동안 테스트는 전부 통과하고 로그 한 줄 남지 않는다.

**임베딩 공급자를 바꾸려면 코퍼스 전체를 다시 임베딩해야 한다.** 부분 이전도 없고 섞인 상태로 동작하는 경우도 없다. 명세가 데이터베이스 임베딩 집합과 그에 대한 모든 질의가 하나의 공급자를 써야 한다고 못박은 것이 이 상황을 막기 위해서다.

코드가 이걸 완전히 막을 수는 없지만, 볼 수 있는 한 가지는 거부할 수 있다. 폭이 열과 맞지 않는 모델이다.

## 구현

`app/retrieval/sbert.py`는 `app/retrieval/embeddings.py`에 덧붙이는 대신 새 모듈로 만든다. 이유는 의존성 방향이다. 공급자 경계는 PyTorch가 설치되지 않은 상태에서도 import되어야 하고, 모델을 다루는 코드를 별도 파일에 두면 그 성질이 사실일 뿐 아니라 눈에 보이게 된다.

### 1. 생성은 값싸게 유지한다

#### 생성 `app/retrieval/sbert.py` — 모듈 헤더

```python
"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence

from app.retrieval.embeddings import EmbeddingProvider, _texts, validate_embeddings
```

**코드에서 볼 것**

- import 목록이 곧 교훈이다. `sentence_transformers`가 거기 없다. 모듈은 표준 라이브러리와 M2.2의 공급자 경계만 import하고, 그 부재가 torch 백엔드가 없는 기계에서도 `import app.retrieval`이 동작하게 만드는 요인이다.
- `EmbeddingProvider`, `_texts`, `validate_embeddings`는 `embeddings.py`에서 온다. 그래서 이 공급자는 자기만의 것을 새로 쓰는 대신 다른 모든 공급자와 같은 입력 처리와 출력 검증을 물려받는다.

#### 수정 `app/retrieval/sbert.py` — `SentenceTransformerEmbeddingProvider.__init__`

```python
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
    self._encoder: object | None = None
```

**코드에서 확인할 것**

- `_encoder`가 `None`으로 시작한다. 이 공급자를 생성해도 **가중치를 읽지 않고** 디스크에 손대지 않는다. 팩토리나 테스트나 CLI 인자 파서에서 객체를 만드는 일이 계속 공짜여야 한다.
- `all-MiniLM-L6-v2`가 기본값인 이유는 정확히 384차원을 내놓기 때문이다. `DIM`과 기존 열에 맞으므로 도입에 마이그레이션이 필요 없다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "constructing or rejects_invalid or defaults_match"
```

- `test_constructing_provider_loads_no_model`
- `test_provider_rejects_invalid_construction`
- `test_provider_defaults_match_the_database_column`

### 2. 한 번만 읽고, 쓸모 있게 실패한다

#### 수정 `app/retrieval/sbert.py` — `SentenceTransformerEmbeddingProvider._load`

```python
def _load(self) -> object:
    """Import and construct the encoder once, then reuse it."""
    if self._encoder is not None:
        return self._encoder

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed; run one of "
            "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
        ) from exc

    encoder = SentenceTransformer(self.model)
    reported = encoder.get_sentence_embedding_dimension()
    if reported != self.dimensions:
        raise ValueError(
            f"model {self.model!r} produces {reported} dimensions, "
            f"but this database stores {self.dimensions}"
        )
    self._encoder = encoder
    return encoder
```

**코드에서 확인할 것**

- import가 **함수 안에** 있다. 모듈 최상단에 두면 백엔드 extra 없이 설치한 사람에게 `import app.retrieval`이 깨진다. 대부분의 사람이 대부분의 시간에 그 상태다.
- `ImportError`를 고치는 명령이 담긴 `RuntimeError`로 바꾼다. 맨 `ModuleNotFoundError`는 무언가 없다는 것만 알려주지 무엇을 하라는 말은 하지 않는다.
- 폭 검사는 이 코드가 실제로 잡을 수 있는 유일한 불일치다. 폭이 틀린 모델은 여기서 걸리지만, 폭이 **맞고** 공간이 다른 모델은 아예 탐지되지 않는다. 앞 절이 존재하는 이유다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "missing_extra or wrong_dimension"
```

- `test_missing_extra_raises_an_actionable_runtime_error`
- `test_load_rejects_a_model_with_the_wrong_dimension`

### 3. 이벤트 루프를 막지 않는다

#### 수정 `app/retrieval/sbert.py` — `SentenceTransformerEmbeddingProvider.embed_documents`

```python
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

**코드에서 확인할 것**

- `encode`는 동기이고 연산 위주다. 코루틴 안에서 그냥 호출하면 그 시간 동안 이벤트 루프 전체가 멈춰 프로세스의 다른 요청이 전부 얼어붙는다. `asyncio.to_thread`가 이를 워커로 옮긴다.
- API 공급자가 가려주던 차이가 이것이다. 네트워크 호출을 await하면 제어권이 넘어가지만, 모델을 돌리는 것은 따로 손쓰지 않는 한 아무것도 넘겨주지 않는다.
- `validate_embeddings`는 다른 두 공급자가 쓰는 그 함수다. 새 공급자에게 새 검증 경로를 주지 않는다. 한 공급자의 검사가 약하면 그건 전체의 구멍이다.
- `normalize_embeddings=True`는 결정론적 공급자가 이미 하는 것과 맞춘 것이고, 저장되는 벡터를 하나의 척도에 둔다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "embed_documents or empty_batch or shared_validation"
```

- `test_embed_documents_reuses_the_model_and_runs_encode_off_loop`
- `test_empty_batch_does_not_load_a_model`
- `test_provider_output_still_passes_through_shared_validation`

### 4. 팩토리로 연결한다

#### 수정 `app/retrieval/embeddings.py` — `get_embedding_provider`

```python
if configured.embedding_provider == "sbert":
    # Imported here, not at module scope: app.retrieval.sbert imports this
    # module for the provider base class and its validation helpers.
    from app.retrieval.sbert import SentenceTransformerEmbeddingProvider

    return SentenceTransformerEmbeddingProvider(
        model=configured.sbert_model,
        dimensions=configured.embed_dim,
    )
```

이름 하나가 필요 이상으로 혼란을 준다. `uv sync`로 설치되는 배포판 이름은 하이픈이 들어간 `sentence-transformers`이고, `pyproject.toml`과 무엇을 설치하라고 알려 주는 메시지에 들어가야 하는 이름이 그것이다. 파이썬에서 import하는 모듈 이름은 밑줄이 들어간 `sentence_transformers`다. **배포판 대신 모듈 이름을 적은 `RuntimeError`는 존재하지 않는 패키지 이름으로 독자를 보낸다.**

여기서 import를 미루는 것은 PyTorch 때문이 아니다. `sbert.py`가 기반 클래스를 얻으려고 `embeddings.py`를 import하므로, 최상단에서 되돌려 import하면 순환이 된다. 필요한 한 자리에서만 미뤄 해결한다.

factory 분기만 추가해서는 설정과 CLI가 `sbert` 값을 받아들이지 못한다. `app/config.py`의 provider `Literal`과 모델 설정, `app/retrieval/__main__.py`의 `ProviderName` 및 `--provider` 선택지, `app/retrieval/__init__.py`의 import와 `__all__`도 위 파일 지도대로 함께 수정한다.

#### 실행 — 이 단계의 테스트

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "factory or cli_accepts or public_surface"
```

- `test_factory_builds_configured_sbert_provider_without_loading_model`
- `test_cli_accepts_sbert_provider`
- `test_public_surface_exports_sbert_provider`

## 집중 테스트와 테스트가 지키는 계약

#### 실행 `tests/retrieval/test_10_sbert.py`

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q
```

| 테스트가 깨뜨리는 값 | 지켜지는 계약 |
|---|---|
| 모듈 최상단의 `sentence_transformers` import | 백엔드 없이도 패키지가 import된다. |
| 생성자에서 읽는 가중치 | 공급자를 만드는 일이 공짜로 유지된다. |
| `DIM`과 폭이 다른 공급자 | 벡터가 언제나 열에 맞는다. |
| `ModuleNotFoundError`로 보고되는 백엔드 부재 | 오류가 고치는 명령을 알려준다. |
| 이 공급자만의 별도 검증 경로 | 하나의 검증이 모든 공급자를 덮는다. |

넘어가는 기준은 단순하다. `import app.retrieval`이 백엔드 extra를 요구한다면, 공급자를 생성하는 것만으로 무언가를 내려받는다면, 코퍼스를 비우지 않고 다시 임베딩했다면 M2.10을 받아들이지 않는다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **SBERT는 BERT에서 무엇을 바꿨나?**
  - **답:** 구조가 아니라 학습 목표를 바꿨고, 그래서 문장 하나로 합친 벡터가 문장끼리 비교 가능해졌다.
- **이중 인코더 구조는 무엇을 얻고 무엇을 잃나?**
  - **답:** 문서를 미리 한 번 임베딩해 저장할 수 있어 검색이 거리 계산이 되지만, 질문과 문서가 모델 안에서 만나지 못한다.
- **이 프로젝트는 왜 아홉 번째 체크포인트에 와서야 PyTorch를 설치하나?**
  - **답:** 의존성은 실제로 필요해지는 체크포인트에서 지는데, 그 전 어느 단계도 필요로 하지 않았다.
- **uv 설정에 `conflicts`가 왜 필요한가?**
  - **답:** 한 환경에 PyTorch 백엔드가 둘 잡히면 조용히 하나로 해결하는 대신 거부하게 만든다.
- **코퍼스를 한 공급자로 임베딩하고 다른 공급자로 질의하면 무슨 일이 일어나나?**
  - **답:** 유사도는 여전히 계산되고 오류도 나지 않으므로 검색 품질만 조용히 무너진다. 코퍼스를 다시 임베딩해야 한다.
- **인코더를 왜 워커 스레드에서 돌리나?**
  - **답:** 동기이고 연산 위주라 코루틴 안에서 호출하면 프로세스의 다른 모든 작업에 대해 이벤트 루프를 막는다.

---

**다음:** [튜토리얼 9](09-cross-encoder.md)는 모델은 그대로 두고 질문과 문서가 만나는 지점을 바꾼다. 그러면 검색이 2단계가 된다.
