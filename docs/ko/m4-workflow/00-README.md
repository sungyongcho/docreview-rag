# M4 개요 — 증거 검증 워크플로

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

M4는 모델이 스스로 증거 규칙을 정하지 못하도록 통제하면서 순위가 매겨진 공시 문서 청크를 검증된 답변으로 변환합니다. 구현은 다음 세 경계를 분리합니다.

1. `app.llm`은 엄격한 구조화 출력, 한 번의 복구, 타입이 지정된 거부를 담당합니다. 2. `app.observability`는 누적 예산, 원시 추적, 영속성 매핑을 담당합니다. 3. `app.workflow`는 순수 상태 전이와 얇은 오케스트레이션을 담당합니다.

경로는 `retrieve -> grade -> check -> report`입니다. 증거가 없거나 불충분하면 불필요한 모델 호출을 건너뛰면서도 타입이 지정된 `NOT_IN_DOCS` 보고서를 생성합니다.

## 읽는 순서

1. [측정 결과](01-findings.md)는 이 체크아웃에서 확정한 결정을 설명합니다. 2. [규범 명세](02-spec.md)는 상태, 노드, 실패, 예산 계약을 정의합니다. 3. [빌드 튜토리얼](03-build.md)은 의존성 순서에 따라 구현을 살펴봅니다. 4. [버그 기록](04-bugs.md)은 함정과 이를 방지하는 코드 경계를 기록합니다. 5. [검증](05-verify.md)은 모든 인수 조건을 실행 가능한 명령에 대응시킵니다.

## 계층별 경로

| 계층 | 목표 | 주요 파일 | 중단 조건 |
|---|---|---|---|
| M4.1 | 실패 시 닫히는 구조화 공급자 | `app/llm/` | 잘못된 출력을 한 번 복구한 뒤 거부 |
| M4.2 | 추적 및 예산 출처 | `app/observability/` | 소진 시 `budget_exceeded` 반환 |
| M4.3a | 엄격한 상태 및 사유 | `app/workflow/types.py` | 모든 성능 저하 경로에 타입이 지정된 사유 존재 |
| M4.3b | 순수 노드 전이 | `app/workflow/nodes.py` | 인용 가드가 결정론적으로 동작 |
| M4.3c | 얇은 오케스트레이션 | `app/workflow/runner.py` | 전체 오프라인 워크플로 테스트 스위트 통과 |
| M4.4 | 엄격한 디코딩 경계 | `app/llm/provider.py` | 스키마를 벗어난 형태가 생성되지 않음 |

## 정렬 가능한 체크포인트 경로

### M4.1 — 엄격한 공급자 경계

- 선행 조건: M3.4 단계의 출처 연계 검색 계약을 사용할 수 있어야 합니다.
- 파일: `app/llm/`, `tests/workflow/test_01_schemas.py`, `tests/workflow/test_02_provider.py`.
- 정규 명령:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_01_schemas.py tests/workflow/test_02_provider.py -q
  ```

- 예상 결과: 네트워크 호출 없이 `31 passed`.
- 중단 조건: 잘못된 구조화 출력을 최대 한 번 복구한 뒤, 추적에 사용할 수 있는 메타데이터와 함께 타입이 지정된 거부로 반환합니다.
### M4.2 — 관찰 가능한 누적 실패

- 선행 조건: M4.1 단계의 엄격한 공급자 결과가 완성되어야 합니다.
- 파일: `app/observability/`, 필수 DB 실행/추적 모델, `tests/workflow/test_03_observability.py`.
- 정규 명령:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_03_observability.py -q
  ```

- 예상 결과: 네트워크 호출 없이 `21 passed`.
- 중단 조건: 엄격한 추적이 결정론적으로 누적되고, 예산이 0이거나 소진되면 `budget_exceeded`를 반환하며, 영속성 계층은 자격 증명을 저장하지 않고 출처 정보를 유지합니다.
### M4.3 — 증거 검증 워크플로

- 선행 조건: M4.1 및 M4.2 단계를 완료해야 합니다.
- 파일: `app/workflow/`, `tests/workflow/test_04_nodes.py`, `tests/workflow/test_05_runner.py`.
- 정규 명령:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_04_nodes.py tests/workflow/test_05_runner.py -q
  ```

- 예상 결과: 네트워크 호출 없이 `21 passed`.
- 중단 조건: 도달 가능한 모든 경로가 엄격한 보고서 또는 타입이 지정된 실패를 반환하고, 조작된 인용이 남을 수 없으며, 누적 예산 소진 시 이전 추적을 보존합니다.
### M4.4 — 엄격한 디코딩 경계

- 선행 조건: M4.1부터 M4.3까지 완료해야 합니다.
- 파일: `app/llm/provider.py`, `app/llm/__init__.py`, `tests/workflow/test_07_structured_outputs.py`.
- 정규 명령:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_02_provider.py tests/workflow/test_07_structured_outputs.py -q
  ```

- 예상 결과: 네트워크 호출 없이 `21 passed`.
- 중단 조건: 기본 요청이 엄격한 `text.format`을 실어 보내고, 지원되지 않는 스키마 구조는 경로와 함께 빌드 시점에 실패하며, validate-repair 루프가 두 요청 경로를 계속 보호합니다.
## 오프라인 빠른 시작

```bash
uv run pytest -o addopts="" tests/workflow -q
uv run ruff check app/llm app/observability app/workflow tests/workflow
uv run ruff format --check app/llm app/observability app/workflow tests/workflow
uv run python scripts/check_doc_code.py docs/en/m4-workflow docs/ko/m4-workflow
```

위 명령은 모두 유료 서비스를 호출하지 않습니다. 실제 OpenAI 스모크 테스트에는 세 가지 명시적 환경 변수가 필요하며, [검증](05-verify.md#6-선택적-실제-공급자-게이트)에 별도의 수동 게이트로 문서화되어 있습니다.

## LangGraph 의존성이 없는 이유

잠긴 환경에는 `langgraph`가 없습니다. 새 오케스트레이션 의존성을 추가하면 네 가지 상태로 이루어진 경로는 바뀌지 않은 채 런타임과 튜토리얼 범위만 늘어나므로, M4는 동등한 타입 기반 비동기 러너를 사용합니다. 러너에는 순서 제어, 의존성 호출, 노드 실행 전 가드 하나만 포함되며 상태 변환은 일반적인 순수 함수로 유지됩니다.

이는 의도적인 로컬 호환성 결정이지, LangGraph가 일반적으로 부적합하다는 주장이 아닙니다. 나중에 해당 의존성을 도입하더라도 네 개의 순수 노드 함수가 안정적인 마이그레이션 경계가 됩니다.

## 완료의 의미

머신 검증 완료는 결정론적 스키마 처리, 증거 필터링, 인용 식별자, 누적 토큰 거부, 추적 보존, 정규 경로 직접 가져오기, 문서 동기화를 입증합니다. 실제 모델의 품질을 입증하거나 유료 호출을 허가하지 않으며, M3에서 측정한 기반 검색 품질에 대한 검토를 대체하지도 않습니다.
