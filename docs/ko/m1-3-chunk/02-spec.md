# M1.3 명세

## 1. 입력 계약

`chunk_filing()`은 M1.1의 `ParsedFiling`을 받는다. 양수 `source_length`와 소문자 16진수 64자리 `source_sha256`가 없으면 구간이 어떤 불변 소스 스냅샷에 속하는지 증명할 수 없으므로 빈 결과를 반환하지 않고 `ValueError`로 실패한다.

- 공시: `source_length`, `source_sha256`
- Block: `kind`, `text`, 선택적 `html`
- Block 출처 추적 정보: `source_pos`, `end_pos`, `source_group`, `source_heading`

좌표 하나라도 없거나, 역방향·중첩·문서 범위 밖이거나, 한 청크 후보가 여러 소스 그룹을 가로지르면 추정하지 않고 `ValueError`로 실패한다.

## 2. 좌표 계약

- 원문은 정확한 바이트를 UTF-8로 디코딩하며 범용 줄바꿈 변환을 하지 않는다.
- `start_char`, `end_char`는 디코딩한 Python 문자열의 유니코드 코드 포인트 인덱스다.
- 구간은 `[start_char, end_char)` 반열림 구간이다.
- `source_sha256`는 정확한 소스 바이트의 SHA-256이다.
- 인용 식별자는 최소 `(doc_id, source_sha256, start_char, end_char)`다.

## 3. 출력 계약

`Chunk`는 불변 값 객체다.

| 필드 | 의미 |
|---|---|
| `doc_id` | 고정 코퍼스 문서 ID |
| `item` | SEC Item 또는 `None` |
| `kind` | `text` 또는 `table` |
| `ordinal` | 현재 구체화 결과의 문서 내 빈틈없는 순서 |
| `body` | 소스에서 파생된 증거 |
| `context_header` | 공시, Item, 제목으로 만든 합성 검색 문맥 |
| `citation` | 사람이 읽는 공시 + Item 레이블 |
| `start_char`, `end_char` | 기준 소스의 반개방 구간 |
| `source_sha256` | 좌표가 속한 소스 스냅샷 |
| `content` | 인덱싱용 `context_header + body` 계산 속성 |

ordinal은 재청킹 때 바뀌므로 영구 인용 키가 아니다.

## 4. 텍스트 청킹 불변식

1. Item, 표, 서술 제목, `source_group`을 넘지 않는다. 2. 문단 내부를 자르지 않는다. 3. 목표보다 긴 문단은 하나의 대형 청크로 둔다. 4. 각 소스 본문 Block은 정확히 한 텍스트 청크에 소비된다. 5. 본문 토큰은 인용된 소스 조각의 가시 토큰이 이루는 순서 보존 부분 수열이다. 6. 제목은 본문에 복사하지 않고 `context_header`로 전달한다.

## 5. 표 청킹 불변식

1. M1.2 `table_to_markdown()`이 빈 값을 반환하면 레이아웃 전용 표로 보고 버린다. 2. 렌더링 가능한 소스 표 하나는 정확히 하나의 표 청크가 된다. 3. 표 청크 구간은 그 소스 표의 구간과 정확히 같다. 4. 마크다운 헤더 토큰은 소스 토큰 멀티셋에 포함된다. 5. 데이터 행 토큰은 소스 안에서 원래 순서를 유지한다. 6. 행 수준 소스 좌표 없이 표 행을 분할하지 않는다.

## 6. 순서와 중첩 불변식

- 결과는 `(start_char, end_char)` 기준의 안정적인 소스 순서다.
- ordinal은 `0..len(chunks)-1`이다.
- 서로 다른 청크 구간은 겹치지 않는다.
- 제목이 아닌 모든 소스 본문 Block은 정확히 한 청크가 소비한다.

## 7. 설정과 실패 계약

| 입력 | 결과 |
|---|---|
| `target_text_chars <= 0` | `ValueError` |
| 소스 길이/해시 누락 또는 오류 | `ValueError` |
| Block 구간 누락·역전·중첩 | `ValueError` |
| 소스 그룹 혼합 | `ValueError` |
| 문서 길이 밖 구간 | `ValueError` |
| 빈 문단 | 청크 없음 |
| 레이아웃 전용 표 | 청크 없음 |
| 목표보다 긴 문단/표 | 경계를 보존한 대형 청크 |

## 8. 다음 마일스톤으로 넘기는 것

- M1.4: 문서/청크 기본 키, 트랜잭션, 멱등 업서트
- M3: 토크나이저 기준 최적 텍스트 목표와 검색 어블레이션 실험
- 후속 출처 추적 작업: 표 행 단위 소스 좌표와 안전한 행 분할
- M5/M6: 인용 API와 소스 뷰어 UI
