# M1.4 개요 — 멱등 PostgreSQL 시드

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

M1.4 단계는 파싱한 SEC 공시(20)와 해당 M1.3 청크 전체를 검증된 데이터베이스 레코드로 변환한 뒤, 결정론적 PostgreSQL 업서트로 코퍼스를 영속화한다. 이 작업은 원자적이며 안전하게 다시 실행할 수 있다. 임베딩은 생성하지 않는다.

## 한 문장 계약

`manifest -> ParsedFiling -> Chunk -> validated records -> one PostgreSQL transaction`

문서 행은 불변 소스 스냅샷을 고정하고 `Not applicable`과 같은 xref 전용 증거를 포함한 파서/Item 상태 메타데이터를 보존한다. 각 청크 행은 소스 증거, 합성 검색 문맥, 결합된 인덱스 텍스트, 반개방 소스 구간을 보존한다.

## 영속화 경계

| 값 | 의미 |
|---|---|
| `body` | 인용할 수 있는 소스 파생 증거 |
| `context_header` | 공시, Item, 제목으로 만든 합성 문맥 |
| `index_text` | `context_header + "\n\n" + body`, 문맥이 비었으면 `body` |
| `content` | `index_text`의 ORM 호환 별칭이며 두 번째 열이 아님 |
| `[start_char, end_char)` | 기준 디코딩 소스에 대한 Python 문자 좌표 |
| `source_sha256` | 해당 좌표를 소유하는 정확한 소스 스냅샷의 식별자 |
| `parse_status` | 문서 수준 파서 검증 결과 |
| `item_index` | Item별 상태와 참조 소스를 포함한 원본 xref 항목 |
| `content_tsv` | PostgreSQL이 `index_text`로 생성한 영어 검색 벡터 |
| `embedding` | null을 허용하는 M2 필드이며 M1.4 단계는 이를 생성하지 않음 |

## 재실행 동작

- 문서는 `doc_id` 충돌 시 영속화된 메타데이터 전체를 업데이트한다.
- 청크는 `(doc_id, ordinal)` 충돌 시 내용과 출처 추적 정보를 업데이트한다.
- 트랜잭션을 열기 전에 ordinal이 빈틈없는지 검증한다.
- 오래된 후행 ordinal은 같은 트랜잭션 안에서 삭제한다.
- 기존 임베딩은 `index_text`가 바뀌지 않았을 때만 보존한다. 텍스트가 바뀌면 임베딩을 `NULL`로 설정하여 M2가 오래된 벡터를 제공하지 못하게 한다.
- 어느 명령문이든 실패하면 코퍼스 배치 전체를 롤백한다.

## 읽는 순서

1. [측정 결과](01-findings.md) 2. [규범 명세](02-spec.md) 3. [계층별 빌드 가이드](03-build.md) 4. [버그와 설계 함정](04-bugs.md) 5. [검증 증거](05-verify.md)

## 빠른 시작

PostgreSQL 없이 집중형 테스트를 실행합니다.

```bash
uv run pytest tests/db -q
```

저장소 환경을 통해 PostgreSQL을 시작한 뒤 같은 명령을 다시 실행하면 선택적 통합 테스트가 활성화된다. 새 스키마에 시드 데이터를 넣으려면 다음 명령을 사용한다.

```bash
uv run python -m app.ingestion.seed --create-schema
```

`--create-schema`는 누락된 테이블만 생성한다. 스키마 마이그레이션 도구가 아니며 기존 테이블 정의를 변경하지 않는다.

각 튜토리얼 계층을 마칠 때마다 같은 정규 명령을 다시 실행합니다. 누락된 시드 계층 심벌은 구현할 때까지 문제없이 건너뜁니다. 공유 M1.4 스키마가 연습의 고정 입력이므로 모델 테스트는 계속 통과합니다.

## 책임 경계

M1.3 단계는 파싱, 청크 본문, 검색 문맥, 소스 좌표를 담당한다. M1.4 단계는 그 값을 검증하고 영속화한다. M2는 임베딩 생성을 담당하며 임베딩이 null인 행만 다시 채운다. 이 마일스톤은 임베딩 공급자를 가져오거나 모델을 요청하지 않는다.
