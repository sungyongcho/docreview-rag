# M4.1 튜토리얼 3 — 공급자 구현과 공개 표면

튜토리얼 2는 모듈 수준 함수 일곱 개 — 파서, 예산 판정, 복구 프롬프트 빌더 — 를 만들었지만, 그 함수들을 부르는 코드는 아직 없다. 각 함수는 질문 하나에만 답할 뿐 언제 실행될지는 스스로 정하지 않는다. 이 공백은 사소하지 않다. 호출 순서가 고정되어 있지 않으면, 예산을 이미 넘긴 호출의 완벽하게 파싱된 답을 호출자가 그대로 사용하는 것도, 남은 한도로 감당할 수 없는 복구 요청에 비용을 지불하는 것도 막을 수 없다.

이 문서는 호출 순서를 정확히 한 곳에 고정하는 추상 클래스 `LLMProvider`와 그 위의 구현 두 개를 만든다. 이 파일이 세우는 불변조건은 이렇다. 인자가 타입 가드를 통과한 뒤에는 `_request`가 던진 어떤 예외도 `complete()` 밖으로 나가지 않는다 — 호출이 어떻게 끝나든 호출자는 `ProviderResult` 하나를 돌려받는다. 경계 자체를 잘못 쓰는 경우 — 타입이 틀린 인자, 거꾸로 가는 시계 — 는 의도적으로 예외를 던진다. 그것은 실행 결과가 아니라 프로그래밍 오류이기 때문이다.

**선행 조건:** 튜토리얼 2에서 `llm/provider.py`의 판정 함수를 작성한 상태여야 한다. 테스트는 이 문서 끝에서 함께 돈다.

### 추상 클래스가 하는 일과 하지 않는 일

`LLMProvider`는 요청을 직접 보내지 않는다. `_request`가 추상 메서드이고, `complete()`는 그 메서드를 최대 두 번 호출하면서 검증, 예산 확인, 복구를 처리한다.

> **개념 — 템플릿 메서드**
>
> 이 구조에는 고전적인 이름이 있다. 템플릿 메서드 패턴이다. 기반 클래스가 알고리즘 전체를 구체 메서드 하나로 구현하고, 달라지는 단계 하나만 추상 구멍으로 남긴다. 하위 클래스는 그 구멍만 채우고 알고리즘은 그대로 물려받는다.
>
> 여기서 알고리즘은 검증-예산-복구 루프이고, 구멍은 요청 전송 그 자체다. 재시도 정책이 기반 클래스에만 존재하므로, 오프라인 하위 클래스로 한 번 증명하면 모든 하위 클래스에 대해 증명된다. 성실함이 아니라 구조가 보장한다.
>
> 이 패턴은 실패 방식에도 이름을 붙인다. 구멍 대신 구체 메서드를 재정의하는 하위 클래스는 이 문서가 쌓는 보장을 전부 잃는다.

**요청 전송만 하위 클래스에 두었으므로 결정론적 공급자와 OpenAI 공급자가 같은 재시도 정책을 사용한다.** 테스트가 결정론적 공급자로 검증한 복구 동작이 실제 공급자에도 그대로 적용된다. M2.2가 임베딩에서 정확히 같은 삼각형을 만들었다 — 추상 기반 `EmbeddingProvider`, 오프라인 대역 `DeterministicEmbeddingProvider`, 네트워크 어댑터 `OpenAIEmbeddingProvider`. 하나의 추상 구멍으로 하나의 정책을 사는 구조를 코드베이스가 두 번째로 반복하는 것이다.

여기서 추상은 권고가 아니라 강제다. `ABC`와 `@abstractmethod` 덕분에 `LLMProvider` 자체를 인스턴스화하면 `TypeError`가 나고, 테스트 파일은 `isabstract(LLMProvider)` 단언으로 시작한다 — 기반 클래스는 오직 상속되기 위해서만 존재한다.

### 예산은 시도마다 줄어든다

`complete()`의 루프 첫 줄이 `remaining`을 계산한다. 두 번째 시도에 넘기는 예산은 **첫 시도가 이미 사용한 양을 뺀 나머지**다.

**이 계산이 없으면 복구 호출이 원래 한도를 처음부터 다시 받으므로, 한 번의 요청이 최대 예산의 두 배까지 사용할 수 있다.**

이 성질은 주장으로 끝나지 않고 측정된다. 테스트 스위트의 예산은 입력 1,000 토큰, 출력 100 토큰에서 시작하고, 첫 시도가 10과 5를 쓴다. 테스트는 공급자의 기록 장치에서 두 번째 요청이 받은 한도를 직접 읽는다: `provider.budgets[1].max_input_tokens == 990`이고 `max_output_tokens == 95`다(`tests/workflow/test_02_provider.py:117-118`). 직접 재현해 본다.

```bash
uv run pytest tests/workflow/test_02_provider.py -k repairs_once -q
```

> **개념 — 동결된 모델과 model_copy**
>
> `ProviderBudget`는 `StrictSchema`를 상속하고, 그 설정은 동결(frozen)이다. 동결된 Pydantic 모델은 생성 이후의 속성 대입을 거부하므로 남은 한도를 제자리에서 빼 내려갈 수 없다 — `model_copy(update=...)`가 바뀐 필드만 반영한 새 인스턴스를 만들고, 호출자의 원본은 그대로 남는다.
>
> 그대로 남는 원본이 핵심이다. 루프는 언제나 호출자가 승인한 예산에서 빼기를 시작하지, 앞선 반복이 이미 줄여 놓은 값에서 시작하지 않는다. 그래서 한도가 조금씩 어긋나며 표류할 수 없다.
>
> 정직한 주의 하나. `model_copy`는 검증을 건너뛰고 update 값을 그대로 믿는다. 여기서 안전한 이유는 복구 게이트가 먼저 돌기 때문이다 — `_repair_budget_failure`가 `>=`를 쓰므로, 두 번째 시도는 남은 한도가 확실히 양수일 때만 시작된다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `LLMProvider.complete` | 호출 순서를 **직접 구현** | 검증·예산·복구가 놓이는 순서 |
| `DeterministicLLMProvider` | **구조 작성** | 네트워크 없이 경계를 테스트하는 법 |
| `OpenAILLMProvider` | **경계 변환 검토** | SDK 응답을 중립 레코드로 바꾸는 지점 |
| `app/llm/__init__.py` | **구조 작성** | M4.1이 공개하는 표면 |

### 1. 검증·예산·복구가 놓이는 순서

#### `app/llm/provider.py` 확장 — 공급자 경계

**학습 행동 — 호출 순서 구현:** `for attempt in (1, 2)` 루프를 직접 구현하고, 여섯 개의 반환 지점을 모두 추적한다 — 호출이 예외를 던지면 `provider_error`, 명시적 거부면 `provider_refused`, 서로 다른 두 자리(호출 직후, 복구 직전)의 `budget_exceeded`, 두 번째 파싱 실패 뒤의 `schema_rejected`, 그리고 `ok`다.

<!-- src: app/llm/provider.py::LLMProvider -->
```python
class LLMProvider(ABC):
    """One async provider boundary for structured, budgeted completion calls."""

    provider_name: str
    model_name: str
    api_url: str

    def __init__(self, *, clock: Clock = time.perf_counter_ns) -> None:
        self._clock = clock

    @abstractmethod
    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        """Return one provider-neutral raw response without retrying."""

    async def complete[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> ProviderResult[OutputT]:
        """Validate, repair once after schema failure, then refuse explicitly."""
        if not isinstance(prompt, Prompt):
            raise TypeError("prompt must be a Prompt value")
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError("schema must be a Pydantic model class")
        if not isinstance(budget, ProviderBudget):
            raise TypeError("budget must be a ProviderBudget value")

        current_prompt = prompt
        raw_outputs: list[str] = []
        request_ids: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_request_time_ms = 0.0

        for attempt in (1, 2):
            remaining = budget.model_copy(
                update={
                    "max_input_tokens": budget.max_input_tokens - total_input_tokens,
                    "max_output_tokens": budget.max_output_tokens - total_output_tokens,
                    "max_cost_usd": budget.max_cost_usd
                    - budget.pricing.estimate(total_input_tokens, total_output_tokens),
                }
            )
            started = self._clock()
            try:
                raw = await self._request(current_prompt, schema, remaining)
            except Exception as error:
                elapsed_ms = (self._clock() - started) / 1_000_000
                if elapsed_ms < 0:
                    raise ValueError("clock must be monotonic") from error
                total_request_time_ms += elapsed_ms
                raw_outputs.append("")
                failure = ProviderRefusal(
                    status="provider_error",
                    message=f"{type(error).__name__}: {error}",
                    attempts=attempt,
                )
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )
            elapsed_ms = (self._clock() - started) / 1_000_000
            if elapsed_ms < 0:
                raise ValueError("clock must be monotonic")
            total_request_time_ms += elapsed_ms
            raw_outputs.append(raw.output_text)
            if raw.request_id is not None:
                request_ids.append(raw.request_id)
            total_input_tokens += raw.input_tokens
            total_output_tokens += raw.output_tokens
            estimated_cost = budget.pricing.estimate(
                total_input_tokens,
                total_output_tokens,
            )

            if raw.refusal is not None:
                failure = ProviderRefusal(
                    status="provider_refused",
                    message=raw.refusal,
                    attempts=attempt,
                )
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            if failure := _budget_failure(
                budget,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                estimated_cost_usd=estimated_cost,
                attempts=attempt,
            ):
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            parsed, errors = _parse_output(raw.output_text, schema)
            if parsed is None:
                if attempt == 1:
                    if failure := _repair_budget_failure(
                        budget,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        estimated_cost_usd=estimated_cost,
                    ):
                        return self._failed_result(
                            failure,
                            raw_outputs=raw_outputs,
                            request_ids=request_ids,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            request_time_ms=total_request_time_ms,
                            budget=budget,
                        )
                    current_prompt = _repair_prompt(prompt, raw.output_text, errors)
                    continue
                failure = SchemaRejected(errors=errors)
                return self._failed_result(
                    failure,
                    raw_outputs=raw_outputs,
                    request_ids=request_ids,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    request_time_ms=total_request_time_ms,
                    budget=budget,
                )

            assert not errors
            metadata = self._metadata(
                raw_outputs=raw_outputs,
                request_ids=request_ids,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                request_time_ms=total_request_time_ms,
                budget=budget,
            )
            return ProviderResult(status="ok", parsed=parsed, refusal=None, metadata=metadata)

        raise AssertionError("completion attempt loop ended unexpectedly")

    def _metadata(
        self,
        *,
        raw_outputs: Sequence[str],
        request_ids: Sequence[str],
        input_tokens: int,
        output_tokens: int,
        request_time_ms: float,
        budget: ProviderBudget,
    ) -> ProviderMetadata:
        return ProviderMetadata(
            provider=self.provider_name,
            model_name=self.model_name,
            api_url=self.api_url,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=budget.pricing.estimate(input_tokens, output_tokens),
            request_time_ms=request_time_ms,
            retries=len(raw_outputs) - 1,
            request_ids=tuple(request_ids),
            llm_output=raw_outputs[-1],
            raw_outputs=tuple(raw_outputs),
        )

    def _failed_result[OutputT: BaseModel](
        self,
        failure: CompletionFailure,
        *,
        raw_outputs: Sequence[str],
        request_ids: Sequence[str],
        input_tokens: int,
        output_tokens: int,
        request_time_ms: float,
        budget: ProviderBudget,
    ) -> ProviderResult[OutputT]:
        metadata = self._metadata(
            raw_outputs=raw_outputs,
            request_ids=request_ids,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_time_ms,
            budget=budget,
        )
        return ProviderResult(
            status=failure.status,
            parsed=None,
            refusal=failure,
            metadata=metadata,
        )
```

**코드에서 꼭 볼 것**

- `remaining`은 시도마다 **원본** `budget`과 누적 사용량으로부터 다시 계산한다. `budget.model_copy(update=...)`가 **이미 사용한 양을 뺀** 한도를 두 번째 호출에 전달한다 — 위에서 측정한 990/95가 그 값이다.
- 판정 순서는 거부, 예산, 파싱이다. 모델이 거부했다면 파싱할 출력이 없고, 예산을 넘겼다면 파싱이 성공해도 결과를 사용할 수 없다. **결과를 무효로 만드는 조건부터 먼저 확인한다.**
- `_repair_budget_failure`는 복구 프롬프트를 보내기 **전에** 호출된다. 남은 예산이 없으면 복구 요청 자체를 보내지 않는다.
- `except Exception`이 의도적으로 넓다. 미래의 `_request` 구현이 무엇을 던질지 기반 클래스는 알 수 없다 — 결정론적 공급자는 큐가 비면 `RuntimeError`를 던지고, OpenAI 어댑터는 SDK 오류를 그대로 올린다 — 그래서 빠져나오는 모든 예외가 타입 있는 `provider_error`가 되고, `message`에 원래 예외의 타입 이름이 남는다. 인자 가드를 통과한 뒤라면 호출자는 항상 `ProviderResult`를 받는다. 실패를 숨기는 것이 아니라 가두는 것이다.
- `raw_outputs`는 **모든** 경로에서 늘어난다 — 예외 경로도 반환 직전에 `""`를 덧붙인다. 이 빈 문자열이 구조를 지탱한다. `ProviderMetadata`는 빈 튜플을 거부하고 원시 출력 개수가 재시도 횟수 더하기 1이기를 요구하므로, 이 한 줄이 없으면 실패한 호출을 기록할 방법 자체가 없다. 예외 테스트가 종착 상태를 못 박는다: `metadata.raw_outputs == ("",)`.
- `request_ids`는 응답이 실제로 id를 담아 왔을 때만 덧붙인다. 그래서 시도 횟수와 id 개수가 다를 수 있고, 메타데이터 검증기가 개수 일치 대신 id가 원시 출력보다 **많아지는 것**만 금지하는 이유가 이것이다.
- `total_request_time_ms`는 두 시도에 걸쳐 누적되므로, 복구된 호출의 기록된 지연 시간은 요청 두 개의 **합**이다. 결정론적 테스트 시계는 시도마다 정확히 1밀리초를 내놓고, 스위트는 단일 시도 경로에서 `request_time_ms == 1.0`, 복구 경로에서 `2.0`을 단언한다 — 저장된 트레이스를 읽을 때 이 사실을 기억해야 한다.
- 복구를 위해 `current_prompt`만 다시 바인딩되고 `prompt`는 원본에 고정되어 있다. 복구 프롬프트는 언제나 원본 사용자 텍스트에 오류를 더해 만들어진다 — 이미 복구된 프롬프트 위에 다시 쌓는 일이 없다 — 그래서 시도가 거듭돼도 지시문이 중첩되지 않는다.
- 예산 가드가 한 줄로 읽히는 것은 왈러스 연산자 덕분이다. `if failure := _budget_failure(...)`가 판정 결과를 대입하고 같은 표현식에서 검사한다. `None`은 거짓으로 평가되므로 통과한 판정은 조용히 지나간다.
- 실패 경로에서도 `total_*` 값을 그대로 전달한다. 실패한 호출이 사용한 토큰과 소요 시간이 메타데이터에 남는다.
- `elapsed_ms < 0` 검사가 예외 경로에도 있다. 실패한 호출의 소요 시간도 같은 기준으로 검증한다.

### 2. 네트워크 없이 경계를 테스트한다

#### `app/llm/provider.py` 확장 — 결정론적 공급자

**학습 행동 — 구조 작성:** 이 공급자가 재현하는 동작과 재현하지 않는 동작을 구분해 확인한다.

<!-- src: app/llm/provider.py::DeterministicLLMProvider,MockLLMProvider -->
```python
class DeterministicLLMProvider(LLMProvider):
    """Queue-backed offline provider for deterministic tests and canned runs."""

    provider_name = "deterministic"
    api_url = "deterministic://local"

    def __init__(
        self,
        responses: Sequence[RawProviderResponse],
        *,
        model_name: str = "deterministic-mock",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        if any(not isinstance(response, RawProviderResponse) for response in responses):
            raise TypeError("responses must contain RawProviderResponse values")
        super().__init__(clock=clock)
        self.model_name = model_name
        self._responses = list(responses)
        self._prompts: list[Prompt] = []
        self._budgets: list[ProviderBudget] = []

    @property
    def prompts(self) -> tuple[Prompt, ...]:
        """Return prompts in request order for deterministic assertions."""
        return tuple(self._prompts)

    @property
    def budgets(self) -> tuple[ProviderBudget, ...]:
        """Return remaining budgets supplied to each deterministic request."""
        return tuple(self._budgets)

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
        del schema
        self._prompts.append(prompt)
        self._budgets.append(budget)
        if not self._responses:
            raise RuntimeError("deterministic provider response queue is empty")
        return self._responses.pop(0)


MockLLMProvider = DeterministicLLMProvider
```

**코드에서 꼭 볼 것**

- "결정론적"이라는 이름이 약속하는 것은 재생(replay)이지 순수 함수가 아니다. `_request`는 출력을 고를 때 프롬프트를 전혀 보지 않는다. `del schema`가 무시하는 매개변수임을 의도적으로 표시하고, 프롬프트와 예산을 기록한 뒤, 응답은 `self._responses.pop(0)` — 테스트가 미리 채워 둔 FIFO 큐에서 나온다. 같은 프롬프트를 두 번 보내면 큐의 첫 번째, 그다음 두 번째 응답이 돌아온다.
- 복구 경로를 테스트할 수 있게 만드는 것이 바로 이 큐다. 잘못된 응답 하나와 올바른 응답 하나를 채워 두면 `complete()` 호출 한 번이 실패-복구-성공 궤적 전체를 밟는다. 프롬프트에서 출력을 계산하는 대역이라면 같은 프롬프트에 서로 다른 두 결과를 각본으로 짤 수 없다.
- 기록 장치가 나머지 절반의 가치다. `prompts`와 `budgets`가 `complete()`가 실제로 보낸 것을 순서대로 드러낸다 — 스위트가 복구 프롬프트에 검증 오류와 직전 출력이 글자 그대로 들어 있는지, 두 번째 예산이 990/95로 줄었는지 단언할 수 있는 근거다.
- 큐가 비면 `RuntimeError`가 난다. 이것도 기능이다. 이 예외가 `except Exception` 경로를, 그러니까 `complete()`의 예외 처리 분기를 네트워크 없이 그대로 밟게 해 준다. 예외 테스트가 응답 목록을 비운 채 이 공급자를 만드는 이유가 정확히 그것이다.
- 여기서 가격이 0인 것이 아니다. 가격은 애초에 공급자에 있지 않다. `TokenPricing`은 호출자의 `ProviderBudget`에 실린다 — 스위트의 결정론적 예산은 토큰을 백만 개당 2달러와 10달러로 매기고, 그래서 정상 경로가 입력 100 토큰과 출력 20 토큰에 대해 추정 비용 `Decimal("0.0004")`를 단언할 수 있다. `priced` 가드가 `_repair_budget_failure` 안에서 지키는 것은, 뒤에 어떤 공급자가 있든, 가격이 전부 0인 **예산**이다.

`MockLLMProvider = DeterministicLLMProvider`는 하위 클래스가 아니라 순수한 별칭이다. 두 이름이 같은 클래스 객체를 가리키므로 동작도 `isinstance` 검사 결과도 동일하다. 본래 이름은 중요한 성질 — 결정론적 재생 — 을 말하고, 별칭은 관례적인 테스트 대역 이름을 찾는 독자를 위해 남겨 둔 것이다. 지금 이 별칭을 임포트하는 테스트나 앱 코드는 없다. 다음 절의 공개 표면만 이 이름을 다시 내보낸다.

### 3. SDK 응답을 중립 레코드로 바꾼다

#### `app/llm/provider.py` 완성 — OpenAI 공급자

**학습 행동 — 경계 변환 검토:** `_openai_refusal`이 SDK 응답의 어느 위치를 확인하는지 살펴본다.

아래 클래스가 M4.1의 완성형이다. 튜토리얼 9의 strict 업그레이드는 생성자와 `_request`만 교체한다. 나머지 — `complete()`, 판정 함수들, 거절 매핑 — 는 글자 그대로 유지된다.

```python
def _openai_refusal(response: object) -> str | None:
    for output in getattr(response, "output", ()):
        for content in getattr(output, "content", ()):
            if getattr(content, "type", None) == "refusal":
                refusal = getattr(content, "refusal", None)
                if isinstance(refusal, str) and refusal.strip():
                    return refusal
    return None


class OpenAILLMProvider(LLMProvider):
    """OpenAI Responses API adapter with injected-client offline testability."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        model_name: str,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        api_url: str = "https://api.openai.com/v1/responses",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip() or not api_url.strip():
            raise ValueError("model_name and api_url must not be blank")
        super().__init__(clock=clock)
        self.model_name = model_name
        self.api_url = api_url
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def _request[OutputT: BaseModel](
        self,
        prompt: Prompt,
        schema: type[OutputT],
        budget: ProviderBudget,
    ) -> RawProviderResponse:
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
        if usage is None:
            raise ValueError("OpenAI response did not include token usage")
        return RawProviderResponse(
            output_text=output_text,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            request_id=getattr(response, "id", None),
            refusal=_openai_refusal(response),
        )
```

> **개념 — SDK 가장자리의 덕 타이핑**
>
> `_openai_refusal`도, `_request`에서 응답을 읽는 후반부도 OpenAI 응답 타입을 임포트하지 않는다. `getattr`로 객체를 한 단계씩 더듬으며 매 단계 기본값을 두고, 각 속성이 존재하는지와 쓸 만한 모양인지만 묻는다.
>
> 대가는 실재한다. 타입 검사기가 이 코드를 SDK의 실제 응답 클래스와 대조해 줄 수 없으므로, 새 SDK 버전의 모양 변화는 리뷰 시점이 아니라 실행 시점에 드러난다.
>
> 그 위험을 되사는 것이 마지막의 명시적 검사다. 토큰 사용량은 `isinstance(input_tokens, int)`를 통과해야 하고, 통과하지 못하면 어댑터가 예외를 던진다 — 그 예외를 `complete()`가 받아 타입 있는 `provider_error`로 돌려준다. 모양의 기습은 조용히 틀린 숫자가 아니라 기록된 실패로 강등된다.

**코드에서 꼭 볼 것**

- `_openai_refusal`은 응답 구조를 단계적으로 확인하며 탐색한다. SDK 버전에 따라 거부가 실리는 위치가 달라져도 거부를 놓치면 안 된다 — 놓친 거부는 빈 출력으로 파싱 단계에 흘러들어 스키마 실패로 잘못 보고된다.
- **토큰 수는 응답에서 읽고 직접 세지 않는다. 청구 금액의 기준이 공급자의 집계이므로, 자체 집계가 청구서와 어긋나는 순간 모든 예산 판정이 실제 돈에 대해 틀린 말을 하게 된다.**
- 사용량 누락 가드는 측정되어 있다. `test_openai_adapter_rejects_missing_usage_as_typed_provider_error`가 `usage=None`인 가짜 응답을 밀어 넣고, 실행이 기록된 토큰 0으로 `provider_error`로 끝나는 것을 단언한다 — 사용량을 지어내지도 않고, 죽지도 않는다.
- Responses API는 채팅형 API가 메시지 배열 하나에 담던 프롬프트를 두 개의 전송 필드로 나눈다. `prompt.system`은 `instructions`로, `prompt.user`는 `input`으로 보낸다. `Prompt` 값 하나가 들어가 매개변수 둘로 나가는, 직접적이고 손실 없는 대응이다.
- `store=False`가 **두 분기 모두**에 실린다. 이 옵션은 해당 교환을 API의 서버 측 응답 저장에서 제외한다 — 끄지 않으면 응답이 보존되어 id로 다시 조회할 수 있다. 공시 문서 텍스트가 이 호출을 지나가므로, 남는 사본은 이 시스템이 직접 기록하는 것 하나뿐이어야 한다는 의도적 입장이다. 다만 이것은 조회 가능한 저장 상태를 좁히는 것이지, 벤더의 데이터 취급 전체를 끄는 스위치는 아니다.
- `client`와 `api_key`가 공존하는 것은 상대하는 호출자가 다르기 때문이다. 테스트는 가짜 `client`를 주입하고 주입된 객체가 이긴다(`client or AsyncOpenAI(api_key=api_key)`). 운영에서는 `api_key`를 넘겨 어댑터가 실제 클라이언트를 만들게 한다. 생성자 하나에 청중 둘, 테스트에는 네트워크가 없다.
- `api_url`은 아무것도 라우팅하지 않는다. 요청이 실제로 어디로 가는지는 SDK 클라이언트가 정하고, 이 문자열은 트레이스가 어댑터가 호출한다고 믿었던 엔드포인트를 말할 수 있도록 메타데이터에 기록될 뿐이다. 이 값을 바꿔도 요청은 다른 곳으로 가지 않는다 — 시도해 보기 전에 알아 두어야 할 사실이다.
- `_request`는 스키마를 SDK 파싱 경로인 `text_format`으로 보낸다. 튜토리얼 9가 이 생성자와 `_request`를 strict 디코딩 기본 경로로 교체한다. 여기서 타이핑하는 것 중 버려지는 것은 없다 — `complete()`와 모든 판정 함수는 그 업그레이드에서 그대로 살아남는다.

> **개념 — 경계가 사 주는 것**
>
> `RawProviderResponse` 생성 — `_request`의 맨 아래 — 이 경계선이다. 그 줄 위에는 OpenAI의 타입이 살고, 아래에는 이 프로젝트의 타입만 존재한다. 튜토리얼 2의 모든 판정과 `complete()`의 모든 분기는 중립 레코드 위에서만 동작하고, SDK 객체를 만지는 일이 없다.
>
> 한 가지 귀결이 이 문서 전체의 결실이다. 공급자를 교체한다는 것은 `_request` 하나를 새로 써서 `RawProviderResponse`로 끝나게 만드는 일이다. 완성 루프도, 그 정책을 검증하는 테스트도, 하류의 어떤 것도 손대지 않는다.

### 4. M4.1이 공개하는 표면

#### `app/llm/__init__.py` 생성 — 공개 API

**학습 행동 — 구조 작성:** 밑줄로 시작하는 판단 함수가 하나도 공개되지 않는다는 점을 확인한다.

```python
"""Strict LLM schemas and provider boundaries for M4."""

from app.llm.provider import (
    DeterministicLLMProvider,
    LLMProvider,
    MockLLMProvider,
    OpenAILLMProvider,
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
]
```

튜토리얼 9가 `strict_response_format`이 생기는 시점에 이 표면에 이름 하나를 더한다. 그때까지는 이것이 공개 API의 완성형이다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/workflow/test_01_schemas.py tests/workflow/test_02_provider.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 두 번 연속 스키마를 놓친 출력 | 복구는 한 번뿐이고 그 뒤는 타입 있는 거부다. |
| 첫 시도가 예산을 다 쓴 경우 | 복구 호출이 예산을 두 배로 쓰지 않는다. |
| 호출 자체가 던진 예외 | 호출자가 항상 `ProviderResult`를 받는다. |
| `NaN`이 든 모델 출력 | JSON 표준 밖 값이 파싱을 통과하지 않는다. |
| 실패한 호출의 토큰 수 | 실패도 예산 집계에 들어간다. |

`tests/workflow/test_02_provider.py`에는 테스트 함수 13개가 있고, 위 표의 계약 다섯 개는 각각 이름 있는 테스트에 대응한다. 두 번 연속 스키마를 놓치는 경우는 `test_second_schema_failure_returns_typed_rejection_without_third_call`, 예산을 다 쓴 첫 시도는 `test_repair_does_not_start_after_the_first_attempt_exhausts_budget`, 호출이 던진 예외는 `test_provider_exception_becomes_typed_error_without_fake_usage`, `NaN`이 든 출력은 `test_non_strict_json_is_repaired_instead_of_silently_interpreted`, 실패한 호출의 토큰 집계는 `test_explicit_usage_and_cost_budgets_fail_closed`다.

파일 전체에서 눈여겨볼 단언이 하나 있다. `metadata.retries == 1`이 서로 다른 세 경로에 등장한다 — 복구 후 성공, 복구 후 두 번째 실패, 비표준 JSON 복구. 복구는 한 번뿐이라는 정책은 docstring의 문장이 아니라 세 방향에서 측정된 사실이다.

`isinstance` 가드 셋이 `complete()` 맨 위에 있는 값어치도 테스트가 보여준다. `test_provider_boundary_rejects_untyped_prompt_budget_and_mock_responses`가 프롬프트 모양의 dict와 예산 모양의 dict를 넘기고, 둘 다 요청이 만들어지기 전에 `TypeError`로 거부되는 것을 단언한다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **`complete()`가 거부·예산·파싱을 이 순서로 보는 이유는 무엇인가?**
  - **답:** 거부된 응답은 파싱할 값이 없고, 예산을 넘긴 결과는 파싱에 성공해도 쓸 수 없으므로 더 결정적인 실패부터 처리한다.
- **`remaining`을 다시 계산하지 않으면 최악의 경우 얼마를 쓰는가?**
  - **답:** 두 시도에 각각 원래 허용량이 주어져 최초 예산의 최대 두 배를 쓸 수 있다.
- **결정론적 공급자와 OpenAI 공급자가 공유하는 것은 무엇인가?**
  - **답:** `LLMProvider`의 검증, 예산, 실패 처리, 한 번의 복구 정책을 공유하며 실제 요청 어댑터만 다르다.
- **토큰 수를 우리가 세지 않고 응답에서 읽는 이유는 무엇인가?**
  - **답:** 공급자가 응답에 기록한 사용량이 실제 과금에 쓰이는 권위 있는 수치이기 때문이다.
- **예외를 밖으로 내보내지 않는 것이 호출자에게 무엇을 보장하는가?**
  - **답:** 호출 자체가 실패해도 타입화된 `ProviderResult`를 항상 받고, 그 안의 `provider_error`로 실패를 확인하게 한다. 따라서 공급자별 예외를 따로 처리할 필요가 없다.
- **`complete()`는 몇 가지 방식으로 반환하며, 그중 둘이 같은 상태를 공유하는 이유는 무엇인가?**
  - **답:** 여섯 가지다 — `provider_error`, `provider_refused`, 두 자리에서 나오는 `budget_exceeded`, `schema_rejected`, `ok`. 예산 종료 둘은 상태는 같지만 튜토리얼 2의 서로 다른 판정에서 나온다. 이미 쓴 비용에 대한 판정과 한 번 더 부를 여유에 대한 판정이다.

---

[← 이전: 파싱과 예산](02-provider.md) · [모듈 개요](../03-build.md) · [다음: 관측 타입 →](04-observability-types.md)
