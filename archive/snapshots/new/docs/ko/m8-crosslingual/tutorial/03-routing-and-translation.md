# M8.3 튜토리얼 3 — 아이디어 둘을 실험군으로 들여보낸다

이제 한국어 질문이 영어 인덱스를 만났을 때 무슨 일이 벌어지는지 보여 주는 이전 표가 있다. 수정안이 둘 떠오른다. 답할 수 없는 구성 요소에게 묻기를 그만두거나, 답할 수 있도록 질문을 번역하거나다. 둘 다 그럴듯하고, **자기 이름을 단 실험군으로 행렬에 들어오지 않은 그럴듯한 검색 아이디어는 개선이 아니라 믿음이다.** 이 문서는 언어 감지를 만들고, 라우팅을 운영 질의 경로에 연결하고, 기존 fail-closed 공급자 경계를 통해 번역을 더한다.

**선행 조건:** M8.2 완료, `uv run pytest tests/crosslingual/test_02_crosslingual.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| `detect_query_language` | 문자 스캔을 **구현한다** | 비율이 아니라 존재 — 그리고 모델 없음 |
| `retrieve(route_by_language=...)` | 생략을 **구현한다** | 생략된 구성 요소는 관찰 가능해야 한다 |
| `translate_query` | fail-closed 호출을 **구현한다** | 분해가 폴백하는 자리에서 번역은 예외를 던진다 |
| `make_crosslingual_retriever` | 래퍼를 **작성한다** | 처리는 래퍼이지 결코 하니스의 분기가 아니다 |

### 1. 감지에는 모델이 필요 없다

떠오르는 구현들은 전부 지루한 쪽보다 나쁘다. 언어 감지 라이브러리는 의존성이자 확률이고, LLM 호출은 질의마다 드는 돈과 지연이며, 다수 문자 휴리스틱은 신중해 보이지만 여기서는 적극적으로 틀린다. 이 코퍼스에 관한 진짜 한국어 질문은 `AMD의 7nm 공급 위험`처럼 생겼기 때문이다 — 한국어 조사 몇 개를 둘러싼 티커, 단위, 숫자가 라틴 문자다. **다수 문자 규칙은 이 모듈이 존재하는 이유인 바로 그 질의들을 영어로 분류한다.**

#### `app/retrieval/language.py` 생성 — 스캔

**학습 행동 — 문자 스캔을 구현한다:** 루프를 쓰기 전에 어떤 유니코드 범위가 중요한지 정하고, 각각이 왜 나타날 수 있는지 말한다.

<!-- src: app/retrieval/language.py::HANGUL_SYLLABLES,HANGUL_JAMO,HANGUL_COMPATIBILITY_JAMO,HANGUL_RANGES,contains_hangul,detect_query_language -->
```python
HANGUL_SYLLABLES = (0xAC00, 0xD7A3)
HANGUL_JAMO = (0x1100, 0x11FF)
HANGUL_COMPATIBILITY_JAMO = (0x3130, 0x318F)
HANGUL_RANGES = (HANGUL_SYLLABLES, HANGUL_JAMO, HANGUL_COMPATIBILITY_JAMO)


def contains_hangul(text: str) -> bool:
    """Return whether any character of ``text`` is a Hangul syllable or jamo."""
    return any(start <= ord(character) <= end for character in text for start, end in HANGUL_RANGES)


def detect_query_language(query: str) -> QueryLanguage:
    """Classify one nonblank query as Korean or English.

    Any Hangul makes the query Korean. Korean questions about this corpus are
    mixed by nature — ``"AMD의 7nm 공급 위험"`` carries a ticker, a unit, and a
    number in Latin script — so a majority-script rule would route exactly the
    queries this module exists to route. The rule is therefore presence, not
    proportion, and it is deliberately asymmetric: an English query never
    contains Hangul, so no English query can be misrouted.

    The blank rejection mirrors ``retrieve`` and ``lexical_statement``: a query
    that carries no language at all is a caller error, not a default to English.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    return "ko" if contains_hangul(query) else "en"
```

**코드에서 꼭 볼 것**

- 범위는 하나가 아니라 셋이다. 완성형 음절은 보통 보게 되는 것이고, 조합용 자모는 분해(NFD) 입력에서 오며, 호환 자모는 자음이나 모음 하나를 그대로 내보내는 입력기에서 온다. **셋을 모두 훑는다는 것은 질의가 자기 문자로 분류되고, 클라이언트가 텍스트를 어떻게 정규화했는지에 의존하지 않는다는 뜻이다.**
- 규칙은 의도적으로 비대칭이다. 영어 질의에는 한글이 없으므로 어떤 영어 질의도 잘못 라우팅될 수 없다. 이 분류기의 위험은 전부 한쪽에 산다.
- 빈 질의는 영어로 기본값을 잡는 대신 예외를 던지며, `retrieve`와 같다. 언어가 전혀 없는 질의는 호출자 오류다.

### 2. 생략은 경로이고, 무시는 추측이다

#### `app/config.py` 확장 — 필드 하나, 기본값 꺼짐

**학습 행동 — 설정을 더한다:** 왜 `false`로 출하하는지 설명하는 주석을 쓴다.

```python
# The lexical index is built with the "english" text-search configuration, so a
# Korean query produces no lexical candidates and hybrid fusion silently degrades
# to the vector arm. Enabling this makes retrieve() skip the lexical component for
# a Korean query instead, which is observable in ComponentRankings. Off by default:
# M8 measures the collapse before changing the shipped query path.
query_language_routing: bool = False
```

#### `app/retrieval/service.py` 확장 — 매개변수와 생략

**학습 행동 — 생략을 구현한다:** 새 형태를 발명하는 대신 M2.6이 `reranker`에 쓴 형태를 따른다.

```python
active_routing = (
    settings.query_language_routing if route_by_language is None else route_by_language
)
skip_lexical = active_routing and detect_query_language(normalized_query) == "ko"
```

플래그는 질의가 정규화된 직후에 한 번 해석되고, lexical 구성 요소가 그것을 읽는다.

```python
if skip_lexical:
    return []
```

**코드에서 꼭 볼 것**

- `route_by_language: bool | None = None`은 생략됐을 때 `Settings`에서 해석된다. M2.6이 리랭커에 쓴 3상태 패턴과 같아서, 호출 지점이 전역 설정을 건드리지 않고 테스트에서 어느 쪽 동작이든 강제할 수 있다.
- 생략은 융합을 단락시키는 대신 lexical 구성 요소에서 빈 리스트를 반환한다. **그러면 결과의 `ComponentRankings.lexical`이 비어 있으므로, 어떤 경로를 탔는지를 설정에서 추론하는 대신 응답에서 읽어 낼 수 있다.** 흔적을 남기지 않는 생략은 실행됐는데 아무것도 못 찾은 구성 요소와 구분되지 않는다.
- 감지는 *정규화된* 질의 위에서 돌므로, 라우팅은 리트리버가 보는 것과 같은 문자열을 본다.
- 설정은 `false`로 출하한다. M8은 출하된 경로를 바꾸기 전에 측정한다.

### 3. 분해가 폴백하는 자리에서 번역은 예외를 던진다

#### `app/retrieval/translate.py` 생성 — 계약

**학습 행동 — fail-closed 호출을 구현한다:** `decompose_query`와 한 줄씩 대조하고 차이를 이름 붙인다.

<!-- src: app/retrieval/translate.py::QueryTranslationError,QueryTranslation -->
```python
class QueryTranslationError(RuntimeError):
    """One translation request refused, failed validation, or stayed non-English."""


class QueryTranslation(StrictSchema):
    """One structured translation of a query into the corpus language."""

    translated_query: Annotated[StrictStr, Field(min_length=1)]
    source_language: QueryLanguage

    @model_validator(mode="after")
    def reject_blank_translation(self) -> Self:
        """Reject a whitespace-only translation instead of passing it downstream."""
        if not self.translated_query.strip():
            raise ValueError("translated_query must not be blank")
        return self
```

<!-- src: app/retrieval/translate.py::translate_query -->
```python
async def translate_query(
    query: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> QueryTranslation:
    """Translate one query into English, or raise rather than return the original.

    The provider is injected, never read from ``Settings``. A translation arm costs
    money and adds a network hop to the query path, so it can only be switched on by
    a caller that already holds a provider — a configuration flag could turn it on
    everywhere, including inside a request that never asked for it.

    Unlike ``decompose_query``, this call does not fall back to the input on failure.
    Decomposition is an optimization over a query the retriever can already run; a
    failed translation would leave the Korean query to be scored as if it had been
    translated, and the measured number would then describe an arm that never ran.

    Raises
    ------
    QueryTranslationError
        If the provider refuses, exhausts its budget, fails schema validation after
        one repair, or returns a query that still contains Hangul.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    prompt = Prompt(system=TRANSLATE_SYSTEM_PROMPT, user=query)
    result = await llm_provider.complete(prompt, QueryTranslation, provider_budget)
    if result.status != "ok" or result.parsed is None:
        raise QueryTranslationError(f"query translation failed: {result.status}")
    translation = result.parsed
    if detect_query_language(translation.translated_query) != "en":
        raise QueryTranslationError("translated query is not English")
    return translation
```

**코드에서 꼭 볼 것**

- 공급자와 예산은 매개변수이며 `Settings`에서 절대 읽지 않는다. **설정 플래그는 요청하지 않은 요청 안에 유료 네트워크 호출을 넣을 수 있지만, 필수 인자는 그럴 수 없다.**
- M9.5의 `decompose_query`는 어떤 실패에서든 원래 질문을 반환하고, 거기서는 그것이 옳다. 분해는 리트리버가 이미 실행할 수 있는 질의 위의 최적화이기 때문이다. 여기서는 반대가 옳다. 조용한 폴백은 번역되지 않은 한국어 질의를 번역된 것처럼 채점하고, 보고된 숫자는 실행된 적 없는 실험군을 묘사하게 된다.
- 마지막 검사는 *출력*에 `detect_query_language`를 다시 쓴다. 유효한 JSON 봉투에 한국어 질의를 그대로 되돌려주는 모델은 스키마 검증을 통과하고 이 줄에서 실패한다.
- 나머지는 `StrictSchema`와 기존 `LLMProvider.complete` 경계가 처리한다. 새 공급자도, 새 재시도 정책도, 새 예산 타입도 없다.

### 4. 처리는 래퍼이지 분기가 아니다

#### `app/evals/crosslingual.py` 확장 — 세 개의 질의 경로

**학습 행동 — 래퍼를 작성한다:** 셋 중 어느 것이 `make_retriever`를 거치지 않는지, 그리고 그것이 테스트에 무엇을 뜻하는지 짚는다.

<!-- src: app/evals/crosslingual.py::make_crosslingual_retriever -->
```python
def make_crosslingual_retriever(
    session: AsyncSession,
    arm: CrosslingualArm,
    *,
    provider: EmbeddingProvider | None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one arm's query handling on top of the unmodified M3 retriever factory.

    Every handling value is a wrapper, never a fork of the harness: ``direct`` is
    ``make_retriever`` itself, ``routed`` is the same production ``retrieve`` call
    with language routing switched on, and ``translated`` rewrites the query before
    handing it to the direct arm. The comparison is therefore between query paths,
    not between evaluation code paths.
    """
    if arm.handling == "direct":
        return make_retriever(
            session,
            strategy=arm.strategy,
            provider=provider,
            lexical_ranker=arm.lexical_ranker,
            candidate_k=arm.candidate_k,
            rrf_k=arm.rrf_k,
            filters=filters,
        )

    if arm.handling == "routed":

        async def routed(query: str, k: int) -> Sequence[ChunkHit]:
            result = await retrieve(
                session,
                query,
                provider=provider,
                k=k,
                candidate_k=arm.candidate_k,
                filters=filters,
                rrf_k=arm.rrf_k,
                route_by_language=True,
                lexical_ranker=arm.lexical_ranker,
            )
            return result.hits

        return routed

    if llm_provider is None or provider_budget is None:
        raise ValueError("translated handling requires an LLM provider and a budget")
    inner = make_retriever(
        session,
        strategy=arm.strategy,
        provider=provider,
        lexical_ranker=arm.lexical_ranker,
        candidate_k=arm.candidate_k,
        rrf_k=arm.rrf_k,
        filters=filters,
    )

    async def translated(query: str, k: int) -> Sequence[ChunkHit]:
        translation = await translate_query(
            query,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        if translation_log is not None:
            translation_log.record(query, translation)
        return await inner(translation.translated_query, k)

    return translated
```

**코드에서 꼭 볼 것**

- 세 래퍼 모두 M3 하니스가 이미 받는 것과 같은 `Retriever` 콜러블을 반환한다. **비교는 질의 경로 사이에서 일어나지 평가 코드 경로 사이에서 일어나지 않는다 — `app/evals/retrieval_eval.py`의 무엇도 언어가 존재한다는 사실을 배우지 않는다.**
- `routed`는 `retrieve`를 직접 호출하며 `make_retriever`를 쓰지 않는다. 라우팅은 운영 질의 경로의 성질이고 그것이 측정 대상 코드이기 때문이다. 그 결과는 실제로 영향이 있다. routed 실험군에서 리트리버를 가짜로 만드는 테스트는 `retrieve`를 가짜로 만들어야 하며, 아니면 라이브 세션에 닿는다.
- `translated`는 다시 쓴 질의를 모두 로그에 기록한다. 번역 실험군은 이 행렬에서 유일하게 비결정론적인 부분이고, 아무도 재구성할 수 없는 질의에 대한 보고 점수는 증거가 아니다.
- 번역 실험군은 공급자와 예산 없이 만들어지기를 거부한다. 조용히 유료 호출이 되는 기본값은 없다.

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q
```

기대 결과: 네트워크 없이 `22 passed` — 감지와 라우팅 15개, 번역 7개다.

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| `AMD의 매출` 같은 문자 혼용 질의 | 언어를 정하는 것은 비율이 아니라 존재다 |
| 조합용 자모나 호환 자모 | 한글 범위 셋을 모두 훑는다 |
| 빈 질의 | 감지는 영어로 기본값을 잡는 대신 예외를 던진다 |
| 영어 질의에 라우팅이 켜진 채로 남음 | 한국어 질의만 lexical 구성 요소를 생략한다 |
| 거부하거나 한국어를 돌려주는 공급자 | 번역은 입력을 반환하는 대신 예외를 던진다 |
| 공급자 없이 만들어진 번역 실험군 | 어떤 기본 경로도 유료 호출이 될 수 없다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **언어 규칙은 왜 비율이 아니라 존재인가?**
  - **답:** 여기서 진짜 한국어 질문은 티커와 단위를 둘러싼 문자 혼용이므로, 다수 규칙은 라우팅이 필요한 바로 그 질의들을 영어로 분류한다.
- **라우팅은 왜 결과를 버리지 않고 구성 요소를 생략하는가?**
  - **답:** 비어 있는 `ComponentRankings.lexical`이 결과 안에서 경로를 관찰 가능하게 만든다. 조용히 버리면 실행됐는데 아무것도 못 찾은 구성 요소와 구분되지 않는다.
- **`translate_query`는 왜 `decompose_query`가 폴백하는 자리에서 예외를 던지는가?**
  - **답:** 폴백은 번역되지 않은 질의를 번역된 것처럼 채점하므로, 그 숫자는 실행된 적 없는 실험군을 묘사하게 된다.

---

[← 이전: 붕괴를 측정한다](02-measuring-the-collapse.md) · [모듈 개요](../03-build.md) · [다음: 동등성 게이트 →](04-parity-gate.md)
