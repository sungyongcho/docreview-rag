# M1.3 검증

## 완료 기준

- 공시 20개의 모든 본문 Block이 기준 소스 안의 유효한 구간을 가진다.
- 공시와 모든 Chunk가 같은 `source_sha256`를 가진다.
- 텍스트 본문은 인용된 소스 조각의 순서 보존 부분 수열이다.
- 렌더링 가능한 소스 표 하나가 정확히 하나의 표 청크가 된다.
- 표 헤더 토큰은 소스에 존재하고 데이터 행 순서는 보존된다.
- 제목이 아닌 모든 소스 본문 Block이 정확히 한 청크에 소비된다.
- 청크 구간은 겹치지 않고 소스 순서이며 ordinal은 빈틈없다.
- 문서별·전체 청크 수가 골든 기준선과 같다.
- 소스 코드 블록과 상수값은 정규 로컬 파일이 있으면 해당 파일과 일치하고, 없으면 고정된 `reference_revision` 참조와 일치한다.

## 테스트 대응표

| 파일 | 검증 대상 | 개수 |
|---|---|---:|
| `test_01_contract.py` | 설정, 불변 스키마, 안전하게 실패하는 구간 | 7 |
| `test_02_block_spans.py` | 기준 리더, 해시, Block 왕복 검증 | 5 |
| `test_03_text.py` | 소스 식별자, 문단, 소스 그룹/문맥, INTC 코퍼스, 순서, 중첩 | 10 |
| `test_04_tables.py` | 소스 표와 청크 1:1, 구간, 행 너비 | 4 |
| `test_05_roundtrip.py` | 텍스트/표 출처 추적, 범위, 정확히 한 번 | 4 |
| `test_06_golden.py` | 문서별·전체 코퍼스 기준선 | 2 |
| 합계 | M1.3 스위트 | 32 |

## 기준선

| 종류 | 개수 |
|---|---:|
| 텍스트 청크 | 8,083 |
| 표 청크 | 1,089 |
| 전체 청크 | 9,172 |

## 명령

```bash
uv run pytest tests/chunk -q
uv run python scripts/check_doc_code.py
uv run ruff check --no-fix app tests scripts
uv run pytest -q
```

전체 스위트 숫자는 M1.4 테스트가 합쳐진 최종 실행 결과를 저장소 최상위 계획에 기록한다. 이 문서의 고정 계약은 M1.3 스위트의 32개 통과와 문서 20개의 골든 기준선이다.

## 눈으로 확인

```bash
uv run python -m app.ingestion.chunk --doc NVDA-FY2024 --limit 3
uv run python -m app.ingestion.chunk --doc INTC-FY2022 --kind table --limit 2
```

- 문맥 헤더와 본문이 빈 줄로 분리되는가?
- 합성 제목이 본문에 삽입되지 않았는가?
- 표 청크가 완전한 마크다운 표인가?
- 구간이 소스 범위 안의 반개방 구간인가?
- ordinal이 출력 순서대로 증가하는가?

## 실패 시 우선 확인

| 증상 | 우선 확인 |
|---|---|
| Block 구간 누락 | `read_source()`, `line_offsets()`, `block_source_spans()` |
| INTC 중첩/문맥 누출 | xref `source_group`, `source_heading`, `section_units()` 초기화 |
| 표 왕복 검증 실패 | M1.2 rowspan/colspan 전개와 소스 표 1:1 정책 |
| 소스 해시 불일치 | 기준 리더 외 다른 경로로 파일을 읽었는지 확인 |
| ordinal 순서 실패 | `chunk_filing()`의 안정적 구간 정렬과 번호 재부여 |
| 골든 개수 변화 | 정책 변경이 의도됐는지 확인하고 findings/bugs를 함께 갱신 |

## 정규 구현 채점

```bash
uv run pytest tests/chunk -v
```

각 튜토리얼 계층을 마칠 때마다 이 명령을 실행합니다. 구현 중에는 누락된 심벌 때문에 테스트를 건너뛸 수 있지만, 완료 시 `app/ingestion/chunk.py`에서 32개 테스트를 모두 통과해야 합니다.
