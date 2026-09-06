# M9.4 튜토리얼 4 — 도구는 얇게 유지한다

에이전트에게는 호출할 것이 필요하다. 이 문서는 M2 검색을 타입이 있는 도구 셋으로 감싼다 — 그리고 규율은 전적으로 부정형이다: **도구는 인자를 안으로, 근거를 밖으로 번역할 뿐이고, 그 이상의 지능은 M3가 측정할 수 있는 `app/retrieval`에 속한다.**

**선행 조건:** M9.3 완료, `uv run pytest tests/agent/test_04_loop.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| 파라미터 모델 | **인자 계약을 직접 작성한다** | 엄격 스키마는 기본값이 아니라 `X \| None`을 강제한다 |
| 페이로드·근거 헬퍼 | 번역 계층을 **구현한다** | 근거 id는 추출되는 것이지 발명되는 것이 아니다 |
| `build_default_registry` | 배선을 **구현한다** | 도구 셋, 새 검색 로직은 0 |

### 1. 인자는 제안이 아니라 계약이다

#### `app/agent/builtin_tools.py` 생성 — 파라미터 모델

**학습 행동 — 인자 계약을 직접 작성한다:** 각 필드에 대해 그 제약이 막는 실패를 이름 붙여 본다.

<!-- src: app/agent/builtin_tools.py::ToolParams,CompareYearsParams -->
```python
class ToolParams(BaseModel):
    """Closed base for tool parameters so unknown arguments always fail."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchFilingsParams(ToolParams):
    """Arguments for one hybrid retrieval call."""

    query: Annotated[str, Field(min_length=1)]
    k: Annotated[int, Field(gt=0, le=20)] | None
    tickers: tuple[str, ...] | None
    fiscal_years: tuple[int, ...] | None
    forms: tuple[str, ...] | None


class FetchChunkParams(ToolParams):
    """Arguments for reading one retrieved chunk in full."""

    chunk_id: Annotated[int, Field(gt=0)]


class CompareYearsParams(ToolParams):
    """Arguments for retrieving the same question across fiscal years."""

    query: Annotated[str, Field(min_length=1)]
    ticker: Annotated[str, Field(min_length=1, max_length=16)]
    fiscal_years: tuple[int, ...]
    k: Annotated[int, Field(gt=0, le=10)] | None

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def validate_years(cls, years: tuple[int, ...]) -> tuple[int, ...]:
        """Require a real comparison: two to four distinct years."""
        if not 2 <= len(years) <= 4:
            raise ValueError("fiscal_years must contain two to four years")
        if len(set(years)) != len(years):
            raise ValueError("fiscal_years must be unique")
        return years
```

**코드에서 꼭 볼 것**

- 모든 선택 필드는 스키마 의미의 기본값이 없는 `X | None`이다 — **엄격 function 스키마는 모든 키를 요구하므로, "선택"은 "모델이 명시적으로 null을 넘겨야 한다"는 뜻이지 "모델이 생략해도 된다"는 뜻이 절대 아니다.** M4.4가 만났던 그 엄격 스키마의 귀결이 도구 쪽에서 다시 도착한 것이다.
- `k`는 20으로, 연도는 넷으로 상한이 있다: 값을 고르는 것은 모델이므로, 과요청을 멈추는 곳은 스키마다 — 모델의 행동을 코드 리뷰하는 것이 아니라.
- `CompareYearsParams`는 연도의 개수와 유일성을 모델 자체에서 검증하므로, 말이 안 되는 비교는 dispatch 계층이 관찰로 중계할 메시지와 함께 경계에서 실패한다.

### 2. 페이로드는 제 근거를 스스로 싣는다

#### `app/agent/builtin_tools.py` 확장 — 페이로드 성형과 근거 추출

**학습 행동 — 번역 계층을 구현한다:** M2의 `ChunkHit` 하나가 페이로드 dict와 근거 id가 되기까지를 따라간다.

<!-- src: app/agent/builtin_tools.py::_hit_payload,_chunk_evidence -->
```python
def _hit_payload(hit: ChunkHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "citation": hit.citation,
        "score": hit.score,
        "snippet": hit.index_text[:SNIPPET_CHARS],
    }


def _search_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return tuple(hit["chunk_id"] for hit in output["hits"])


def _compare_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return tuple(hit["chunk_id"] for year in output["years"] for hit in year["hits"])


def _chunk_evidence(output: dict[str, Any]) -> tuple[int, ...]:
    return (output["chunk_id"],)
```

**코드에서 꼭 볼 것**

- 스니펫은 `SNIPPET_CHARS`로, 본문은 `BODY_CHARS`로 잘린다. 모델의 컨텍스트도 예산이다. 공시 전문을 쏟아내는 도구는 모두의 예산을 대신 써 버린다.
- 각 추출기는 자기 페이로드 형태만 안다. **루프는 어떤 chunk id가 인용 가능한 근거가 됐는지를 이 추출기들에게서 배운다 — 튜토리얼 3에서 만든 인용 게이트의 공급 쪽이다.**
- 페이로드는 모든 히트에 `chunk_id`, `doc_id`, 사람이 읽는 citation을 유지하므로, 이후의 `final_answer`는 재조회 없이 인용할 수 있다.

### 3. 배선이 도구의 전부다

#### `app/agent/builtin_tools.py` 확장 — 기본 레지스트리

**학습 행동 — 배선을 구현한다:** 각 실행 함수의 본문이 번역 더하기 M2 호출 하나뿐인지 확인한다.

<!-- src: app/agent/builtin_tools.py::build_default_registry -->
```python
def build_default_registry(
    session: AsyncSession,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> ToolRegistry:
    """Register the built-in filing tools over one caller-owned session.

    Every tool is a thin typed wrapper: retrieval semantics stay in M2, and the
    tools only decide which arguments the model may vary and which payload
    fields become evidence.
    """

    async def search_filings(params: SearchFilingsParams) -> dict[str, Any]:
        result = await retrieve(
            session,
            params.query,
            provider=embedding_provider,
            k=params.k or DEFAULT_SEARCH_K,
            candidate_k=candidate_k,
            filters=RetrievalFilters(
                tickers=params.tickers or (),
                fiscal_years=params.fiscal_years or (),
                forms=params.forms or (),
            ),
            rrf_k=rrf_k,
        )
        return {"hits": [_hit_payload(hit) for hit in result.hits]}

    async def fetch_chunk(params: FetchChunkParams) -> dict[str, Any]:
        chunk = await session.get(Chunk, params.chunk_id)
        if chunk is None:
            raise ValueError(f"chunk {params.chunk_id} does not exist")
        return {
            "chunk_id": chunk.id,
            "doc_id": chunk.doc_id,
            "citation": chunk.citation,
            "context_header": chunk.context_header,
            "body": chunk.body[:BODY_CHARS],
        }

    async def compare_years(params: CompareYearsParams) -> dict[str, Any]:
        years: list[dict[str, Any]] = []
        for fiscal_year in sorted(params.fiscal_years):
            result = await retrieve(
                session,
                params.query,
                provider=embedding_provider,
                k=params.k or 3,
                candidate_k=candidate_k,
                filters=RetrievalFilters(
                    tickers=(params.ticker,),
                    fiscal_years=(fiscal_year,),
                ),
                rrf_k=rrf_k,
            )
            years.append(
                {
                    "fiscal_year": fiscal_year,
                    "hits": [_hit_payload(hit) for hit in result.hits],
                }
            )
        return {"ticker": params.ticker, "years": years}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search_filings",
            description=(
                "Hybrid-search the 10-K corpus and return scored, citable chunks. "
                "Optional tickers, fiscal_years, and forms narrow the corpus; "
                "null means unrestricted."
            ),
            parameters=SearchFilingsParams,
            run=search_filings,
            evidence_ids=_search_evidence,
        )
    )
    registry.register(
        Tool(
            name="fetch_chunk",
            description="Read one previously retrieved chunk in full by its chunk_id.",
            parameters=FetchChunkParams,
            run=fetch_chunk,
            evidence_ids=_chunk_evidence,
        )
    )
    registry.register(
        Tool(
            name="compare_years",
            description=(
                "Run the same question against one ticker across two to four "
                "fiscal years and return the evidence grouped by year."
            ),
            parameters=CompareYearsParams,
            run=compare_years,
            evidence_ids=_compare_evidence,
        )
    )
    return registry
```

**코드에서 꼭 볼 것**

- `search_filings`와 `compare_years`는 둘 다 서로 다른 필터로 M2의 `retrieve`에 닿고, `fetch_chunk`는 기본 키 조회다. 새 랭킹도, 새 스코어링도 없다.
- `compare_years`는 연도마다 필터된 검색을 한 번씩 돌리고 나란히 반환한다 — 비교라는 지능은 양쪽 결과를 다 읽을 수 있는 모델의 몫으로 남는다.
- **도구에 더 똑똑한 검색이 필요해 보인다면, 그것은 M3 평가가 딸린 `app/retrieval`의 기능 요청이다 — 어떤 하니스도 측정하지 않는 곳에 숨긴 사설 랭킹이 아니라.** 튜토리얼 5가 정확히 이것을 올바른 방식으로 한다.

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/agent/test_05_builtin_tools.py -q
```

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 검증을 건너뛴 인자 | M2에 닿는 필터는 정확히 검증된 그것이다 |
| id와 citation이 없는 페이로드 | 모든 히트는 하류에서 인용 가능하게 남는다 |
| 페이로드와 어긋나는 근거 id | 인용 게이트의 공급 쪽이 정직하게 유지된다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **이 스키마들에서 "선택"은 왜 "명시적 null"이 되는가?**
  - **답:** 엄격 스키마는 모든 키를 요구하므로 선택성은 생략이 아니라 타입으로 표현돼야 한다 — 도구 쪽에서 본 M4.4의 규칙이다.
- **잘라내기는 왜 도구의 책임인가?**
  - **답:** 도구 출력은 모델 입력이 된다. 무제한 페이로드는 루프의 토큰 가드가 지키려는 바로 그 컨텍스트 예산을 써 버린다.
- **더 똑똑한 검색 랭킹은 어디에 속하고, 왜 여기는 아닌가?**
  - **답:** M3 하니스 아래의 `app/retrieval`이다 — 도구 안의 로직은 측정되지 않는 로직이고, 이 저장소는 측정되지 않은 랭킹을 배송하지 않는다.

---

[← 이전: 루프](03-loop.md) · [모듈 개요](../03-build.md) · [다음: 분해 →](05-decomposition.md)
