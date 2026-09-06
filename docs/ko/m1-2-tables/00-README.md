# M1.2 개요 — SEC 표 HTML → 마크다운

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

> 입력: M1.1 `Block(kind="table").html` 출력: 검색용 마크다운 문자열 상태: 공시 20개, 표 Block 1,200개, 테스트 33개

## 한 문장

**SEC 표의 물리적 레이아웃 열을 제거하고 숫자·행·헤더 의미를 보존한 마크다운을 만드는 순수 변환기다.**

## 파이프라인

1. `rowspan`과 `colspan`을 밀집 격자로 전개한다. 2. 내용이 전혀 없는 행과 열을 제거한다. 3. `$`와 `%` 전용 열을 값 열에 읽는 순서대로 병합한다. 4. `<th>` 없이도 선두 헤더 행을 형태로 추론한다. 5. 파이프 문자를 이스케이프하고 직사각형 마크다운으로 직렬화한다.

## 읽는 순서

| 순서 | 문서 | 목적 |
|---|---|---|
| 1 | [01-findings.md](01-findings.md) | 코퍼스 실측과 설계 근거 |
| 2 | [02-spec.md](02-spec.md) | 입력·출력·불변식·비범위 |
| 3 | [03-build.md](03-build.md) | L1~L7 구현 순서와 실제 코드 |
| 4 | [04-bugs.md](04-bugs.md) | 실패 원인과 회귀 방지 |
| 5 | [05-verify.md](05-verify.md) | 테스트·골든·수동 확인 |

## 빠른 검증

```bash
uv run pytest tests/ingestion/test_09_tables.py -q
uv run python -m scripts.measure_tables
uv run python -m app.ingestion.tables --doc NVDA-FY2024
uv run pytest tests/ingestion/test_09_tables.py -v
```

## 확정 결정

- `Block.text`를 바꾸지 않는다. 파서 커버리지와 표 렌더링을 분리한다.
- 괄호음수는 원문 표기 그대로 보존한다.
- 레이아웃 전용 표는 빈 문자열로 내려보낸다.
- M1.3은 표 마크다운을 소스가 인용된 청크 하나로 보존한다.
- 실측 재생성 코드는 `scripts/measure_tables.py`, 회귀 기준선은 `tests/ingestion/golden.py`가 소유한다.
