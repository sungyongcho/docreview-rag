# M4 검증

의존성 순서대로 인수 검사를 실행합니다. 첫 번째 실패에서 중단하십시오. 상위 계층은 하위 계약을 고칠 수 없습니다.

## 1. 기반 테스트

```bash
uv run pytest -o addopts="" tests/workflow/test_01_schemas.py tests/workflow/test_02_provider.py -q
uv run pytest -o addopts="" tests/workflow/test_03_observability.py -q
```

첫 번째 명령은 엄격한 스키마, 복구, 공급자 거부, 명시적 호출 예산, 오프라인 OpenAI 어댑터 매핑을 검증합니다. 두 번째 명령은 추적/보고서 누적, 노드 실행 전 단일 가드, Decimal 비용 추정치, 비밀 값을 안전하게 처리하는 영속성 매핑, DB 모델을 검증합니다.

## 2. 순수 노드 테스트

```bash
uv run pytest -o addopts="" tests/workflow/test_04_nodes.py -q
```

필수 결과:

- 빈 검색 결과가 타입이 지정된 부재를 생성합니다.
- 중복되거나 문서 몫 상한에 걸리거나 잘린 증거가 계속 표시됩니다.
- 알 수 없거나 누락된 평가가 기록됩니다.
- 검색된 관련 청크 ID만 인용 필터링을 통과합니다.
- 인용 없는 지원 답변의 등급을 낮춥니다.
- 보고서가 완전한 머신 인용 식별자를 노출합니다.

## 3. 결정론적 러너 테스트

```bash
uv run pytest -o addopts="" tests/workflow/test_05_runner.py -q
```

필수 경로:

| 시나리오 | 상태 | 노드 경로 |
|---|---|---|
| 지원 증거 | `ok` | `retrieve, grade, check, report` |
| 빈 증거 | `ok` | `retrieve, report` |
| 관련 없는 증거 | `ok` | `retrieve, grade, report` |
| 평가 스키마 거부 | `schema_rejected` | `retrieve, grade` |
| 값이 영인 예산 | `budget_exceeded` | 비어 있음 |
| 평가가 토큰 상한을 소진 | `budget_exceeded` | `retrieve, grade` |
| 검색기 오류 | `error` | `retrieve` |

## 4. 전체 오프라인 워크플로 게이트

```bash
uv run pytest -o addopts="" tests/workflow -q
```

이 소스 리비전의 예상 체크포인트:

```text
78 passed, 1 skipped
```

건너뛰는 테스트 하나는 `test_06_openai_live.py`입니다. 이는 예상된 결과이며 통과로 바꾸어 기록해서는 안 됩니다.

## 5. 정규 패키지 게이트

이전 절의 명령은 `app.llm`, `app.observability`, `app.workflow`를 직접 가져옵니다. 단계별 구현 중에는 누락된 기호 때문에 테스트를 건너뛸 수 있지만, 인수 시에는 완전한 예상 체크포인트를 충족해야 합니다.

## 6. 선택적 실제 공급자 게이트

일반 인수 검사 중에는 실행하지 마십시오. 유료 API 호출이 발생할 수 있으며, 사람의 명시적 승인, 유효한 키, 모델 접근 권한이 필요합니다.

```bash
RUN_OPENAI_WORKFLOW_LIVE=1 OPENAI_WORKFLOW_MODEL="approved-model" OPENAI_API_KEY="your-key" uv run pytest -o addopts="" tests/workflow/test_06_openai_live.py -q
```

이 작업에서는 해당 명령을 실행하지 않았습니다. 테스트를 건너뛰었다는 사실은 옵트인 게이트가 닫혀 있다는 것만 입증합니다.

## 7. 저장소 품질 게이트

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_doc_code.py
git diff --check
```

전체 테스트 스위트의 정확한 개수를 코디네이터 인계에 기록하십시오. 실제 PostgreSQL 테스트는 기존 루프백 가용성 가드에서 데이터베이스를 사용할 수 없다고 판단한 경우에만 건너뛸 수 있으며, 유료 공급자 테스트는 암묵적으로 실행되어서는 안 됩니다.

## 8. 계약과 테스트 대응표

| 계약 | 주요 증거 |
|---|---|
| 엄격한 모델 출력과 한 번의 복구 | `test_01_schemas.py`, `test_02_provider.py` |
| 누적 노드 실행 전 예산 | `test_03_observability.py`, `test_05_runner.py` |
| 증거 없음은 `NOT_IN_DOCS`를 의미 | `test_04_nodes.py`, `test_05_runner.py` |
| 알 수 없는 인용 제거 | `test_04_nodes.py` |
| 인용 없는 지원 답변의 등급 하향 | `test_04_nodes.py`, `test_05_runner.py` |
| 스키마 거부 시 추적 보존 | `test_05_runner.py` |
| 영속성 계층에서 프롬프트/원시 형식의 출력을 안전하게 보존 | `test_03_observability.py`, `test_05_runner.py` |
| 실제 호출에는 명시적 동의 필요 | `test_06_openai_live.py` |

## 실패 분류

| 증상 | 경계 | 첫 조치 |
|---|---|---|
| 잘못된 객체가 파싱됨 | M4.1 스키마/공급자 경계 | 엄격한 JSON 파싱과 복구 횟수 검사 |
| 원시 출력 누락 | M4.2 추적 매핑 | 노드 전이 전에 공급자 메타데이터 검사 |
| 증거 없이 모델 호출 | M4.3 라우팅 | 검색 후 단락 처리 검사 |
| 조작된 인용이 남음 | M4.3 검사 노드 | `relevant_chunk_ids`와 비교 |
| 호출 사이에 예산 초기화 | M4.3 러너 | 누적 `steps`와 남은 허용량 검사 |
| 인용 본문 일부만 존재 | M4.3 검색 노드 | 전체 청크 단위 컨텍스트 선택 강제 |
| 정규 패키지를 가져오지 못함 | 패키지 구조 | `app.llm`과 `app.workflow`의 문서화된 공개 항목 검사 |
| 문서 불일치 | 소스 마커 | `--fix`로 문서 검사기를 실행한 뒤 차이 검토 |
