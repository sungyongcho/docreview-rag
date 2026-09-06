# 프로젝트 Docstring 작성 기준

이 문서는 이 저장소의 Python docstring 단일 기준이다. Docstring 작업은 성능 최적화와 독립적으로 수행한다. 사용자가 `docstring` 작성·수정·검수를 요청하면 `docs/optimize`의 최적화 기록 유무와 관계없이 이 문서를 따라 대상 소스를 갱신한다.

## 1. 적용 범위

- 모듈, 클래스, Protocol, 공개 함수, 최상위 함수와 메서드의 docstring에 적용한다.
- 실행 동작을 바꾸지 않는 문서 작업이어도 소스의 실제 시그니처·예외·반환값과 일치해야 한다.
- 최적화 과정에서 코드를 변경했다면 같은 작업에서 docstring도 갱신한다. 나중 작업으로 미루지 않는다.
- 튜토리얼이나 최적화 문서에 해당 코드가 기록돼 있으면 최종 소스와 함께 동기화한다.
- 설명은 영어로 작성한다. 한국어 설명은 주변 Markdown 문서에서 제공한다.

## 2. 어느 형식을 사용할까

- 공개 함수와 동작이 복합적인 최상위 함수·메서드는 NumPyDoc 형식을 사용한다.
- 입력 검증, 트랜잭션, I/O 경계, 동시성, 캐시, 정렬 또는 외부 공급자 계약이 있으면 비공개 함수라도 NumPyDoc으로 설명한다.
- 이름과 구현만으로 명확한 짧은 비공개 헬퍼는 한 줄 요약을 사용할 수 있다.
- 중첩 헬퍼는 전체 NumPyDoc이 흐름을 가리는 경우 한 줄짜리 영어 docstring을 사용한다.
- Protocol과 추상 메서드는 구현이 아니라 구조 계약을 간결하게 설명한다.
- `__init__` 등 특수 메서드는 클래스 docstring이 계약을 충분히 설명하면 별도 장문 docstring을 반복하지 않는다.

## 3. NumPyDoc 섹션

적용 가능한 섹션만 아래 순서로 사용한다.

```python
def func(value: str) -> int:
    """Return the validated result for one input.

    Parameters
    ----------
    value : str
        Nonempty input consumed by the operation.

    Returns
    -------
    int
        Validated result produced from ``value``.

    Raises
    ------
    ValueError
        If ``value`` is empty.

    Notes
    -----
    State, ordering, transaction, concurrency, or compatibility constraints that a
    caller or future implementation must preserve.
    """
```

- 첫 줄은 명령형이 아닌 간결한 동작 요약으로 작성하고 마침표로 끝낸다.
- `Parameters`에는 시그니처에 실제로 존재하는 인자만 선언 순서대로 적는다.
- `Returns`에는 실제 반환 타입과 호출자가 받는 의미를 적는다. `None`을 억지로 설명하지 않는다.
- `Yields`를 사용하는 제너레이터에서는 `Returns` 대신 `Yields`를 사용한다.
- `Raises`에는 코드가 실제로 발생시키거나 명시적으로 전달하는 예외만 적는다.
- `Notes`에는 구현 해설이 아니라 반드시 보존해야 하는 경계와 실패 조건을 적는다.
- 타입 이름은 시그니처와 일치시킨다. 정적 타입 계약과 런타임 검증 타입이 다르면 그 이유를 설명한다.

## 4. 클래스와 모듈

- 모듈 docstring은 파일의 책임과 중요한 의존성 경계를 설명한다.
- 클래스 docstring은 객체가 보존하는 상태, 생성 비용, 외부 자원 로딩 시점과 상호 교환할 수 없는 계약을 설명한다.
- 지연 로딩 클래스는 객체 생성과 실제 자원 로딩이 분리된다는 사실을 명시한다.
- Pydantic 모델·dataclass·Protocol은 필드 나열을 반복하지 않고 그 타입이 막는 잘못된 상태를 설명한다.

## 5. 작성 금지 사항

- 함수명이나 타입 어노테이션을 자연어로 그대로 반복하지 않는다.
- 코드에 없는 예외, fallback, 성능 특성 또는 부작용을 만들어내지 않는다.
- 측정하지 않은 성능 향상을 주장하지 않는다.
- `Any`, `type: ignore`, 모호한 “object” 표현으로 정적 타입 문제를 숨긴 뒤 docstring으로 정당화하지 않는다.
- 현재 동작과 다른 미래 계획을 완료된 계약처럼 적지 않는다.
- `Parameters`, `Returns`, `Raises`, `Notes`를 빈 문장으로 채우지 않는다.

## 6. 동기화와 검증

Docstring을 변경한 뒤 다음을 확인한다.

```bash
uv run ruff check <대상 Python 파일>
uv run ruff format --check <대상 Python 파일>
uv run pytest <대상 집중 테스트>
git diff --check
```

- Ruff의 `D` 규칙과 프로젝트의 NumPy convention을 기준으로 한다.
- 시그니처, docstring의 타입 이름, 실제 반환값과 예외를 다시 대조한다.
- 코드 블록을 포함한 튜토리얼이 있으면 `scripts/check_doc_code.py` 또는 해당 동기화 검사도 실행한다.
- 최적화 상세 문서의 `[수정코드]`가 있으면 정식 소스의 docstring까지 일치시킨다.
