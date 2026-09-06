# M4.4 튜토리얼 9 — 스키마는 프롬프트가 아니라 디코딩에 강제한다

튜토리얼 3에서 만든 공급자는 이미 잘못된 출력에서 살아남는다. 파싱하고, 한 번 고치고, 그래도 안 되면 거부한다. 그런데 이 방어의 비용 구조를 들여다볼 필요가 있다. **repair 경로는 잘못된 응답의 비용을 이미 지불한 뒤에야 실행되므로, 스키마 실패 한 번은 곧 추가 요청 한 번이고 — 단 한 번의 repair가 또 실패하면 실행은 거부로 끝난다.**

스키마를 강제할 수 있는 두 번째 지점이 있다. 프롬프트보다 아래, 디코딩 그 자체다.

**선행 조건:** 튜토리얼 1–8이 끝나 `uv run pytest tests/workflow/test_04_nodes.py tests/workflow/test_05_runner.py -q`가 통과해야 한다.

### 계층이 둘이고, 보장도 둘이다

언어 모델은 토큰을 하나씩 내놓고, API는 매 단계에서 선언된 JSON 스키마를 벗어나는 토큰 전부를 마스킹할 수 있다. 이것이 constrained decoding이다. 유효하지 않은 이어쓰기의 확률을 0으로 만들어 버리므로 잘못된 형태의 출력은 애초에 생성될 수 없다. OpenAI는 이를 strict structured outputs로 노출한다 — `text.format` 페이로드에 `"strict": true`를 실어 보내는 방식이다.

> **개념 — 토큰 마스킹에는 닫힌 문법이 필요하다**
>
> 매 단계에서 모델은 어휘 전체의 토큰마다 확률을 내놓고, API는 스키마를 컴파일한 형태로 들고서 현재 위치에서 아직 합법인 이어쓰기가 정확히 무엇인지 안다 — 여기서는 닫는 중괄호, 저기서는 따옴표, 다음은 알려진 키 이름 집합 중 하나. 마스킹이란 샘플링 전에 그 밖의 모든 것을 0으로 만드는 일이다.
>
> "정확히"라는 말이 요구 조건의 전부다. 마스크는 위치마다 합법인 이어쓰기의 집합에서 계산되므로, 그 집합은 유한하고 미리 알려져 있어야 한다. `additionalProperties`를 열어 둔 객체는 다음 자리에서 어떤 키 이름이든 합법이라고 선언하는 셈이고 — 모든 것을 담은 집합은 아무것도 마스킹하지 못한다. 선택적 키도 같은 방식으로 무너진다. 어떤 키가 나와도 되고 안 나와도 된다면 그 키를 내는 것과 객체를 닫는 것이 둘 다 합법이라, 문법은 우리가 의존하는 필드를 더는 강제할 수 없다.
>
> 이것이 곧 구현할 두 재작성 규칙 — 모든 객체를 닫고, 모든 키를 필수로 — 으로 이어지는 인과 고리다. 스타일 취향이 아니라, JSON 스키마를 토큰 단위 마스크가 강제할 수 있는 것으로 바꾸는 최소 조건이다.

OpenAI의 예전 `json_object` 모드를 써 봤다면 그 모드가 약속하지 않았던 것부터 짚어야 한다. 문법적으로 유효한 JSON 객체 하나가 나온다는 것뿐, 키와 타입에 대한 보장은 없었다. strict structured outputs는 `json_schema` 변형에 `"strict": true`를 더한 것이고, 스키마 자체가 문법이 된다. 이름의 함정도 하나 있다. Responses API에서 이 파라미터는 `text.format`인데, 예전 chat completions API는 같은 개념을 `response_format`이라고 불렀다. 이 파일이 임포트하는 SDK 타입 `ResponseFormatTextJSONSchemaConfigParam`에는 그 옛 계보의 이름이 아직 남아 있다.

이 보장은 실재하지만 좁다. **strict 디코딩이 약속하는 것은 문법과 형태 — 선언된 키와 타입을 정확히 갖춘, 파싱 가능한 JSON — 까지이고 그 이상이 아니다. `SUPPORTED` 라벨에 인용이 하나 이상 필요하다는 규칙은 필드 사이에 걸쳐 있어서 문법이 알 수 없다.** 필드를 가로지르는 불변조건은 튜토리얼 1에서 작성한 Pydantic 검증기의 몫으로 남는다.

| | 디코딩 계층 (strict format) | 애플리케이션 계층 (validate-repair) |
|---|---|---|
| 보장하는 것 | 파싱 가능한 JSON, 선언된 키와 타입 | 필드를 가로지르는 비즈니스 불변조건 |
| 볼 수 없는 것 | 라벨–인용 상호배타, 공백 텍스트 규칙 | 모델이 아예 내놓지 않은 것 — 도착한 최종 값만 검증한다 |
| 실패 시점 | 생성 도중, 쓰레기에 비용을 내기 전 | 완성된 응답이 도착한 뒤 |
| 적용 범위 | strict 모드를 지원하는 공급자 | deterministic을 포함한 모든 공급자 |

그래서 두 계층은 대안 관계가 아니다. **strict format은 repair가 막으려던 실패 계급 자체를 제거하고, validate-repair 루프는 문법이 표현할 수 없는 모든 불변조건과 strict 모드가 아예 없는 모든 공급자를 지키는 바깥 방어로 남는다.**

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `_strict_schema` | 재작성 규칙을 **직접 구현** | 디코딩이 강제할 수 있는 스키마의 조건 |
| `strict_response_format` | **경계 페이로드 작성** | 우리의 계약이 API 파라미터가 되는 지점 |
| `_request` 분기 | **경계 변환 검토** | 두 경로가 하나의 중립 레코드로 수렴하는 이유 |

### 1. strict 모드가 스키마에 요구하는 것

strict 디코딩은 완전히 닫을 수 있는 문법에 대해서만 토큰을 마스킹할 수 있다. 알 수 없는 키를 허용하는 열린 객체에는 닫힌 문법이 없다. 기본값이 있는 필드는 더 미묘한 이유로 실패한다. 아래 재작성은 모든 키를 `required`에 넣으므로 모델이 그 필드를 실제로 생략할 길은 어차피 없다 — 그런데 스키마에 `default`가 남아 있으면 생략해도 된다는 약속이 계속 걸려 있는 셈이다. 문법이 강제하는 것과 스키마가 약속하는 것이 어긋난 채 조용히 출하되는 것, 이 함수가 거부하는 것이 바로 그 모순이다.

strict 스키마를 손으로 직접 쓰지 않고 Pydantic 모델에서 유도하는 이유는 무엇인가. 모델 클래스가 이미 두 강제 계층 — 디코딩 시점의 형태(이 튜토리얼)와 검증 시점의 불변조건(튜토리얼 1) — 의 단일 진실 공급원이기 때문이다. 손으로 쓴 스키마는 같은 계약의 두 번째 선언이고, 두 선언은 반드시 어긋난다. 누군가 `AnswerDecision`에 필드를 추가하면서 JSON 쌍둥이를 잊는 순간 문법은 검증기와 조용히 어긋난다. `model_json_schema()`는 그 표류를 구조적으로 불가능하게 만들고, 재작성은 생성된 스키마를 strict하게 만드는 일만 맡는다.

#### `app/llm/provider.py` 확장 — strict 재작성

**학습 행동 — 재작성 규칙 구현:** 재귀를 먼저 작성한 뒤, 어떤 구조는 재작성이 아니라 거부해야 하는지 판단한다.

<!-- src: app/llm/provider.py::_strict_schema,strict_response_format -->
```python
def _strict_schema(node: object, path: str) -> None:
    """Rewrite one JSON-schema node in place to satisfy strict decoding rules."""
    if isinstance(node, list):
        for index, child in enumerate(node):
            _strict_schema(child, f"{path}[{index}]")
        return
    if not isinstance(node, dict):
        return
    for keyword in ("allOf", "oneOf", "not"):
        if keyword in node:
            raise ValueError(f"strict schema does not support {keyword} at {path}")
    if "default" in node:
        raise ValueError(f"strict schema does not support defaults at {path}")
    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False
        node["required"] = list(node.get("properties", {}))
    for keyword in ("properties", "$defs"):
        for name, child in node.get(keyword, {}).items():
            _strict_schema(child, f"{path}.{name}")
    for keyword in ("items", "prefixItems", "anyOf"):
        if keyword in node:
            _strict_schema(node[keyword], f"{path}.{keyword}")


def strict_response_format(schema: type[BaseModel]) -> ResponseFormatTextJSONSchemaConfigParam:
    """Return the strict ``text.format`` payload that constrains decoding to one schema.

    Strict structured outputs move schema enforcement from prompting into decoding:
    the API masks every token that would leave the declared JSON schema, so the
    response is guaranteed to parse and to carry exactly the declared keys. The
    guarantee covers syntax and shape only — business invariants such as label and
    citation exclusivity still run in the Pydantic validators downstream.

    Parameters
    ----------
    schema : type[BaseModel]
        Pydantic model describing the required completion payload.

    Returns
    -------
    ResponseFormatTextJSONSchemaConfigParam
        OpenAI ``text.format`` payload with every object closed and required.

    Raises
    ------
    ValueError
        If the generated JSON schema uses a construct strict mode cannot enforce.
    """
    json_schema = schema.model_json_schema()
    _strict_schema(json_schema, "$")
    return {
        "type": "json_schema",
        "name": schema.__name__,
        "schema": json_schema,
        "strict": True,
    }
```

**코드에서 꼭 볼 것**

- 모든 객체를 `additionalProperties: false`로 닫고 모든 프로퍼티를 `required`로 만든다. **문법이 토큰을 마스킹하려면 유효한 키의 집합이 유한하고 알려져 있어야 하므로, strict 모드는 열린 객체와 선택적 키를 설계상 거부한다.** `AnswerDecision`에 재작성을 돌리면 `required`에는 선언된 네 키 — `label`, `answer`, `citation_chunk_ids`, `reason` — 가 선언 순서 그대로 담긴다.
- `default`는 재작성하지 않고 거부한다. 재작성이 이미 모든 키를 필수 목록에 넣으므로 기본값이 있는 필드라도 모델이 실제로 생략할 길은 없다 — 진짜 희생자는 정직함이다. 기본값을 조용히 지우면 스키마가 약속하는 내용이 아무 통보 없이 바뀌기 때문이다. 테스트는 이 실패를 글자 단위로 못 박는다. `label` 필드 하나에 기본값을 준 모델은 `strict schema does not support defaults at $.label`을 일으키고, 모든 재귀 호출에 꿰여 내려가는 `path` 인자는 오직 이 메시지가 문제 노드를 지목할 수 있게 하기 위해 존재한다.
- `allOf`, `oneOf`, `not`은 문제 경로를 메시지에 담아 거부하는데, `anyOf`는 재귀해 들어가 살려 둔다. 이 비대칭이 함수에서 가장 흥미로운 결정이다. `anyOf`는 "이 가지들 중 하나"라는 뜻이라 디코더가 한 가지에 전념해 그 안에서 계속 마스킹하면 된다. `oneOf`는 "정확히 한 가지에만 부합"을 뜻하는데, 이는 출력이 부합하지 않는 가지들에 대한 주장이라 토큰 단위 마스크로는 검사할 수 없다. `allOf`는 여러 문법의 교집합을 동시에 요구하고, `not`은 아예 부정이다. 요청을 만드는 시점의 실패가 호출 뒤의 공급자 오류보다 싸다 — 그리고 이 비대칭이, `X | None` 타입 필드가 Pydantic에서 두 가지짜리 `anyOf`로 컴파일되어 그대로 통과하는 이유다.
- 재귀는 `$defs`도 순회한다. `ChunkRelevance` 같은 중첩 모델이 `RelevanceJudgment` 안에 있어도 루트와 똑같이 닫힌다.

> **개념 — 제자리 변형, 그리고 그것이 여기서 안전한 이유**
>
> `_strict_schema`는 `None`을 반환한다. 받은 딕셔너리를 그 자리에서 고친다. 변형은 보통 설계에서 사과부터 하게 되는 부분이므로, 여기서는 왜 사과할 것이 없는지 말해 둘 가치가 있다. 이 딕셔너리는 `schema.model_json_schema()`가 호출될 때마다 새로 만들어 주는 것이라 다른 코드가 참조를 쥐고 있을 수 없고, 따라서 변형이 누구에게도 영향을 주지 못한다. 테스트 스위트는 이것을 희망이 아니라 사실로 못 박는다. 같은 모델로 `strict_response_format`을 두 번 부르면 두 페이로드가 같다 — 한 호출의 변형이 다음 호출로 새어 나간다면 성립할 수 없는 등식이다.
>
> 두 번째 파라미터도 따로 언급할 가치가 있다. `path`는 탐색에 쓰이지 않는다. 재귀는 자기 위치를 항상 알고 있다. 이 파라미터는 오직 거부가 어디서 일어났는지 말할 수 있게 하기 위해 존재한다. "스키마 어딘가"가 아니라 `$.label`이다. 노드를 지목하는 오류 메시지는 디버깅 세션을 한 줄짜리 수정으로 바꿔 놓는다.

> **개념 — `$defs`와 `$ref`: Pydantic이 중첩 모델을 숨겨 두는 곳**
>
> Pydantic은 중첩 모델의 스키마를 그 모델을 쓰는 필드 자리에 펼쳐 넣지 않는다. 정의를 최상위 `$defs` 표로 끌어올리고 필드 자리에는 포인터만 남긴다. `RelevanceJudgment`의 스키마를 생성해 `grades` 필드를 보면, `items` 항목은 `{"$ref": "#/$defs/ChunkRelevance"}`가 전부다 — 프로퍼티도, 타입도, 재작성이 닫을 것이 아무것도 없다.
>
> 재귀가 `properties`를 타고 내려가는 것만으로는 부족하고 `$defs`를 형제 키로 순회해야 하는 이유가 이것이다. 프로퍼티 트리만 따라가는 순회자는 `$ref` 노드에 도착해 고칠 것이 없음을 확인하고 돌아설 것이고, strict를 자처하는 페이로드 안에 `ChunkRelevance`는 열린 채로 남는다. 테스트 파일의 중첩 단언이 정확히 이것을 검사한다. `$defs` 아래의 정의가 루트와 똑같이 닫히고 전부 필수가 되는지 확인한다.

스키마 딕셔너리의 일생은 한 문장에 다 들어가는데, 그 무엇도 살아남지 않는다는 점 때문에 오히려 서술할 가치가 있다. `strict_response_format` 안에서 `schema.model_json_schema()`로 태어나고, 모든 객체가 닫힐 때까지 제자리에서 변형되고, `text.format` 페이로드로 포장된다 — 이름표는 모델 클래스의 `__name__`이다. 전선에 직렬화된 뒤에는 버려진다. 캐시되지도 저장되지도 않는다. `_request`가 호출마다 다시 만들고, repair 시도도 예외가 아니다. 결정론 테스트가 중요한 이유가 정확히 여기에 있다. 매 요청 재생성이 올바른 것은 두 번 만든 결과가 같다고 보장될 때뿐이다. 설계 회고도 하나 있다. 반환 타입 `ResponseFormatTextJSONSchemaConfigParam`은 SDK의 `TypedDict`이고, 함수는 평범한 딕셔너리 리터럴을 반환해 그것을 구조적으로 만족시킨다 — 튜토리얼 5의 `Protocol`과 같은 구조적 타이핑을, 관측성 이음매가 아니라 API 경계에 적용한 것이다.

`strict_response_format`은 `app/llm/__init__.py`가 이 파일에서 내보내는 이름 가운데 밑줄 없는 유일한 함수이기도 하다. 공급자 클래스들이 함께 나가고, 밑줄로 시작하는 아홉 개의 도우미는 전부 비공개로 남는다. 이 경계선은 의도된 것이다. strict를 지원하는 다른 공급자용 어댑터를 직접 만드는 호출자에게 필요한 것은 페이로드 빌더이지, 파싱이나 예산 내부가 아니다.

먼저 헤더에 새 줄 하나를 더한다 — 아래 반환 주석이 SDK의 strict 포맷 타입을 필요로 한다:

```python
from openai.types.responses import ResponseFormatTextJSONSchemaConfigParam
```

### 2. 분기는 둘, 중립 레코드는 하나

#### `app/llm/provider.py` 검토 — 요청 분기

**학습 행동 — 경계 변환 검토:** 두 분기를 공유 `RawProviderResponse` 조립까지 따라가며 무엇이 절대 변하지 않는지 확인한다.

튜토리얼 3은 이 클래스를 SDK 파싱 형태로 만들었다. 생성자와 `_request`를 최종형으로 교체한다 — strict 기본 경로에, `structured_output=False`가 탈출구다:

<!-- src: app/llm/provider.py::OpenAILLMProvider -->
```python
class OpenAILLMProvider(LLMProvider):
    """OpenAI Responses API adapter with injected-client offline testability.

    By default every request carries a strict ``text.format`` built by
    :func:`strict_response_format`, so schema conformance is enforced at decoding
    time. ``structured_output=False`` keeps the legacy SDK-parsed path for models
    or gateways that do not support strict mode; either way the shared
    validate-repair loop in :meth:`LLMProvider.complete` remains the outer guard.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        model_name: str,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        api_url: str = "https://api.openai.com/v1/responses",
        structured_output: bool = True,
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip() or not api_url.strip():
            raise ValueError("model_name and api_url must not be blank")
        super().__init__(clock=clock)
        self.model_name = model_name
        self.api_url = api_url
        self._structured_output = structured_output
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        if self._structured_output:
            response = await self._client.responses.create(
                model=self.model_name,
                instructions=prompt.system,
                input=prompt.user,
                text={"format": strict_response_format(schema)},
                max_output_tokens=budget.max_output_tokens,
                store=False,
            )
        else:
            response = await self._client.responses.parse(
                model=self.model_name,
                instructions=prompt.system,
                input=prompt.user,
                text_format=schema,
                max_output_tokens=budget.max_output_tokens,
                store=False,
            )
        parsed = getattr(response, "output_parsed", None)
        response_output_text = getattr(response, "output_text", "")
        if isinstance(response_output_text, str) and response_output_text:
            output_text = response_output_text
        elif isinstance(parsed, BaseModel):
            output_text = parsed.model_dump_json()
        elif parsed is not None:
            output_text = json.dumps(parsed, allow_nan=False, separators=(",", ":"))
        else:
            output_text = ""
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("OpenAI response did not include token usage")
        return RawProviderResponse(
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=getattr(response, "id", None),
            refusal=_openai_refusal(response),
        )
```

먼저 두 SDK 진입점부터 구분해야 한다. 반환 형태가 다르기 때문이다. `responses.create`는 날것의 호출이다. `text.format` 페이로드를 받고 문자열인 `output_text`를 돌려준다. `responses.parse`는 SDK의 편의 래퍼다. Pydantic 클래스 자체를 `text_format`으로 받고 이미 검증된 인스턴스인 `output_parsed`를 돌려준다. 기본 경로는 `responses.create`를 `text={"format": strict_response_format(schema)}`와 함께 호출한다 — 이 분기는 위의 교체와 함께 도착하고, 그 분기가 부르는 도우미가 방금 구현한 함수다. `structured_output=False`는 strict를 지원하지 않는 게이트웨이와 모델을 위해 `responses.parse` 경로를 유지하는데, `_request`는 어느 분기가 실행됐는지에 무관심하도록 짜여 있다. `output_text`를 우선하고, 파싱 경로에서는 `output_parsed`를 다시 직렬화하는 폴백을 거쳐, 두 분기 모두 하나의 `RawProviderResponse`로 나간다. 호출 이후의 모든 것 — 거부 매핑, 사용량 추출, 중립 레코드 — 은 공유되고, `complete`의 validate-repair 루프가 두 경로를 모두 감싼다.

저 플래그 하나에 설계 질문이 둘 숨어 있다. 왜 호출별 파라미터가 아니라 생성자 플래그인가. strict 지원 여부는 개별 요청의 속성이 아니라 이 공급자가 묶인 모델-게이트웨이 조합의 속성이기 때문이다. 호출별 스위치를 허용하면 같은 공급자가 주는 보장에 대해 두 호출 지점이 서로 다르게 믿을 수 있게 되는데, 그 보장이야말로 이 장치의 존재 이유다. 그리고 왜 옵트인이 아니라 옵트아웃(`structured_output: bool = True`)인가. strict 경로는 동작하는 환경에서라면 엄밀히 더 안전하기 때문이다. 옵트인 플래그는 누군가 잊어버리는 플래그이고, 잊은 대가는 이 튜토리얼이 서두에 세워 둔 바로 그 실패 계급 — 비용을 치른 쓰레기와 repair 요청 — 이다. 기본값이 권장안을 코드로 새기고, 탈출구는 그것이 필요한 환경을 위해 남는다.

strict 보장이 정확히 어디서 끝나는지 이름 붙여 두는 것도 도움이 된다. 보장은 API의 디코더에서 시작해 `RawProviderResponse.output_text`에 담기는 문자열까지 유효하다 — 거기까지는 마스크가 형태를 보증한다. `complete`가 그 문자열을 `_parse_output`에 넘기는 순간부터 모든 보장은 우리 것이다. 중복 키를 거부하는 우리의 JSON 파싱, 우리의 strict Pydantic 검증, 우리의 필드 간 불변조건. 어댑터는 전선이 약속을 지켰다고 가정하지 않는다 — strict 모드가 없는 것처럼 다시 검증한다.

**strict 경로에서 repair 루프는 죽은 코드가 아니다. 필드를 가로지르는 불변조건, strict 모드가 없는 공급자, 그리고 format 파라미터를 조용히 무시하는 게이트웨이에 대한 유일한 방어다.** 심층 방어란 안쪽 보장이 바깥 보장을 지울 핑계가 되지 않는다는 뜻이다.

테스트 스위트는 이 문장을 단언으로 두지 않고 증명한다. `test_repair_loop_still_guards_the_strict_path`에서 가짜 strict 엔드포인트는 처음에 `{"label":"SUPPORTED"}`를 돌려준다 — 디코딩은 되지만 나머지 필수 필드가 전부 빠진, format 파라미터를 무시한 게이트웨이가 내놓을 법한 출력이다. 결과는 그래도 `ok`이고, `retries`는 1, 기록된 호출은 정확히 둘이다. 바깥 루프가 위반을 잡아 strict 디코딩 아래에서 고친 것이다. 파일에서 가장 날카로운 단언은 가장 조용한 단언이다. 두 번째 요청의 `text` 페이로드가 첫 번째와 동일하다. repair 시도 역시 strict로 디코딩되며, 첫 시도와 두 번째 시도 사이에 바뀌는 것은 프롬프트뿐이다. 이 등식 하나가 이 튜토리얼 서두의 불변조건에 대한 가장 좋은 증거이고, 서두의 비용 주장도 실측으로 못 박는다. 스키마 실패 한 번의 대가는 정확히 추가 요청 하나였다.

공개 표면이 마지막 이름을 얻는다. `app/llm/__init__.py`를 최종형으로 교체한다 — 튜토리얼 3 버전보다 import 한 줄과 `__all__` 항목 하나가 많다:

```python
"""Strict LLM schemas and provider boundaries for M4."""

from app.llm.provider import (
    DeterministicLLMProvider,
    LLMProvider,
    MockLLMProvider,
    OpenAILLMProvider,
    strict_response_format,
)
from app.llm.schemas import (
    AnswerDecision,
    AnswerLabel,
    BudgetExceeded,
    ChunkRelevance,
    CompletionFailure,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    ProviderResult,
    ProviderStatus,
    RawProviderResponse,
    RelevanceJudgment,
    SchemaRejected,
    StrictSchema,
    TokenPricing,
)

__all__ = [
    "AnswerDecision",
    "AnswerLabel",
    "BudgetExceeded",
    "ChunkRelevance",
    "CompletionFailure",
    "DeterministicLLMProvider",
    "LLMProvider",
    "MockLLMProvider",
    "OpenAILLMProvider",
    "Prompt",
    "ProviderBudget",
    "ProviderMetadata",
    "ProviderRefusal",
    "ProviderResult",
    "ProviderStatus",
    "RawProviderResponse",
    "RelevanceJudgment",
    "SchemaRejected",
    "StrictSchema",
    "TokenPricing",
    "strict_response_format",
]
```

이 업그레이드 전후로 `tests/workflow/test_02_provider.py`는 그대로 초록이다 — 어댑터 테스트가 두 스키마 바인딩 메커니즘 중 어느 쪽이든 받아들인다 — 그리고 `tests/workflow/test_07_structured_outputs.py`가 strict 기본값을 못 박는다.


### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/workflow/test_02_provider.py tests/workflow/test_07_structured_outputs.py -q
```

위 명령은 지금 두 파일에서 21개의 테스트를 수집한다. `tests/workflow/test_07_structured_outputs.py`의 다섯 개는 아래 표의 행과 일대일로 대응한다 — 116줄의 테스트, 다섯 개의 계약, 군더더기는 없다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 기본값이 있는 필드를 가진 모델 | 디코딩이 강제할 수 없는 구조는 빌드 시점에 경로와 함께 실패한다 |
| 중첩 `$defs` 스키마 | 닫기 규칙이 루트만이 아니라 모든 객체에 적용된다 |
| 기본 어댑터 호출 | strict `text.format` 페이로드가 실제로 전송된다 |
| `structured_output=False` | 레거시 SDK 파싱 경로가 그대로 남아 있다 |
| strict 경로의 스키마 위반 텍스트 | 안쪽 보장이 실패해도 바깥 repair 루프가 실행된다 — `test_repair_loop_still_guards_the_strict_path`가 끝까지 증명한다 |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 그 답을 소유한 계층과 연결해 설명해 본다.

- **repair가 대부분 고쳐 주는데도 스키마 실패가 비싼 이유는 무엇인가?**
  - **답:** repair가 보기 전에 잘못된 응답의 비용이 이미 지불되므로 실패마다 완전한 요청 하나가 추가되고, 두 번째 실패는 여전히 거부로 끝난다.
- **strict 디코딩이 보장하는 것과 절대 보장할 수 없는 것은 무엇인가?**
  - **답:** 문법과 형태 — 선언된 키와 타입을 정확히 갖춘 파싱 가능한 JSON — 를 보장한다. 라벨–인용 상호배타 같은 필드 간 규칙은 문법에 보이지 않으므로 검증기에 남는다.
- **모든 객체를 닫고 모든 키를 필수로 만들어야 하는 이유는 무엇인가?**
  - **답:** 토큰 마스킹에는 유한하고 알려진 유효 이어쓰기 집합이 필요한데, 열린 객체와 선택적 키는 "그 밖의 무언가"를 유효한 완성으로 만든다.
- **`default`를 조용히 제거하지 않고 거부하는 이유는 무엇인가?**
  - **답:** 지우면 스키마의 약속이 말없이 바뀐다. 거부하면 모델 소유자가 문제 경로를 손에 쥐고 빌드 시점에 결정하게 된다.
- **strict 경로에서도 validate-repair 루프가 살아남는 이유는 무엇인가?**
  - **답:** strict 모드는 형태만, 그것도 지원하는 공급자에서만 보장한다. 바깥 루프는 필드 간 불변조건과 비-strict 공급자, 오동작하는 게이트웨이를 계속 지킨다.

---

[← 이전: 러너](08-runner.md) · [모듈 개요](../03-build.md)
