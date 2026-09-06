# M2 검증

다음 순서로 검사를 실행합니다. 실패는 책임이 있는 가장 작은 계층에 연결된 상태로 유지되며, 실제 데이터베이스 경로를 결정론적 단위 테스트 범위와 구분할 수 있습니다.

## 1. 집중형 검색 테스트 모음

```bash
uv run pytest -o addopts="" tests/retrieval -q
```

PostgreSQL을 사용할 수 있으면 모든 테스트가 통과합니다. 실제 픽스처는 루프백 프로젝트 데이터베이스 URL만 허용하고, `localhost`를 `127.0.0.1`로 정규화하며, 하나의 이벤트 루프에서 3초 프로브와 테스트를 수행합니다. PostgreSQL이 없으면 해당 테스트를 건너뛰지만, 모든 SQL 컴파일, 공급자, 융합, 서비스, CLI, 부트스트랩 순서 테스트는 계속 실행됩니다.

## 2. 테스트 구성표

| 테스트 파일 | 검증 내용 |
|---|---|
| `test_01_contract.py` | 엄격한 인용 검색 결과, 정규 필터, 안정적인 동점 판정, 공개 패키지 항목 |
| `test_02_embeddings.py` | 결정론적 벡터, OpenAI 요청/정렬, 출력 검증, 재개 가능한 백필 |
| `test_03_vector.py` | 정확한 코사인 SQL, null 제외, 필터, 완전한 검색 결과 매핑, HNSW 없음 |
| `test_04_lexical.py` | 안전한 웹 검색 분석, 범위 밀도 순위화, 필터, 완전한 투영 |
| `test_05_hybrid.py` | 순위만 사용하는 RRF, 중복 제거, 결정론적 동점, 순차 주입 |
| `test_06_rerank.py` | 선택적 공급자, 완전한 색인 텍스트, 점수 검증, 결정론적 대체 동작 |
| `test_07_service.py` | 하나의 세션, 정확한 순서, 약어 일치, 구성 요소 ID, 공개 항목, CLI 페이로드 |
| `test_08_postgres.py` | 스키마 전 확장 순서와 선택적 실제 벡터 + FTS + RRF 검증 |

계층 순서와 기본 테스트는 [빌드 단계 구성표](03-build.md)에 있습니다.

## 3. 실제 데이터베이스 부트스트랩과 말뭉치

데이터베이스 서비스만 시작합니다.

```bash
docker compose up -d db
docker compose ps db
```

없는 스키마 객체를 생성하고 고정 말뭉치를 시드합니다.

```bash
uv run python -m app.ingestion.seed --create-schema
```

도우미는 테이블 생성 전에 pgvector를 활성화합니다. 현재 스키마와 말뭉치에서는 명령을 반복해도 안전하지만, 이전 테이블 정의를 위한 마이그레이션은 아닙니다.

애플리케이션 상태를 변경하지 않고 확인합니다.

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SELECT count(*) FROM documents;
SELECT count(*) FROM chunks;
SELECT count(*) FROM chunks WHERE embedding IS NOT NULL;
SELECT count(*)
FROM pg_indexes
WHERE tablename = 'chunks' AND indexdef ILIKE '%hnsw%';
```

M2 백필 전에는 null이 아닌 임베딩 개수가 0이어야 합니다. M2 전체에서 HNSW 개수도 0으로 유지되어야 합니다.

## 4. 결정론적 오프라인 인수 테스트

null 벡터를 채우고 마일스톤 쿼리를 문자 그대로 실행합니다.

```bash
uv run python -m app.retrieval --provider deterministic --embed-missing --query "NVDA 2024 R&D" -k 3
```

JSON 응답에서 다음 항목을 모두 확인합니다.

- `provider`는 `deterministic`입니다.
- 백필 개수는 내부적으로 일관됩니다.
- 첫 번째 검색 결과는 `NVDA-FY2024`에 속합니다.
- 모든 검색 결과에는 양수인 청크 ID, 인용, 유효한 반열린 범위, 출처 해시, 본문, 문맥, 색인 텍스트가 있습니다.
- `component_rankings.vector`와 `component_rankings.lexical`에는 청크 ID만 들어 있습니다.
- 어떤 구성 요소 순위에도 점수가 들어 있지 않습니다.

쿼리 전용 경로를 검증하기 위해 백필 없이 반복합니다.

```bash
uv run python -m app.retrieval --provider deterministic --query "NVDA 2024 R&D" -k 3 --candidate-k 20
```

기록된 정확한 말뭉치 결과는 [조사 결과 F11](01-findings.md#f11--기록된-검증-근거)에 있습니다.

## 5. OpenAI 공급자 검증

단위 테스트는 가짜 비동기 클라이언트를 사용해 네트워크 접근 없이 정확한 요청 형태를 검증합니다. 유효한 키를 구성하면 이 제한된 실제 프로브가 키나 벡터를 출력하지 않고 현재 SDK와 공급자 응답을 검증합니다.

```bash
uv run python - <<'PY'
import asyncio
import math

from app.config import get_settings
from app.retrieval.embeddings import get_embedding_provider


async def main() -> None:
    settings = get_settings().model_copy(update={"embedding_provider": "openai"})
    provider = get_embedding_provider(settings)
    vector = await provider.embed_query("M2 retrieval verification")
    print(f"dimensions={len(vector)}")
    print(f"finite={all(math.isfinite(value) for value in vector)}")
    print(f"l2_norm={math.sqrt(sum(value * value for value in vector)):.9f}")


asyncio.run(main())
PY
```

결정론적 공급자로 채운 데이터베이스에 OpenAI 쿼리를 실행하지 마세요. 실제 OpenAI 말뭉치 인수 테스트에는 새로 만들거나 명시적으로 다시 구축한 OpenAI 임베딩 집합이 필요합니다.

## 6. 저장소 검사

자동 수정 없이 린트를 실행합니다.

```bash
uv run ruff check --no-fix app tests scripts
```

문서 소스 및 링크 동기화를 실행합니다.

```bash
uv run python scripts/check_doc_code.py
```

전체 회귀 테스트 모음을 실행합니다.

```bash
uv run pytest -o addopts="" -q
```

마지막으로 공백과 충돌 표시를 확인합니다.

```bash
git diff --check
```

## 7. 완료 체크리스트

- [x] `ChunkHit`은 완전한 근거, 문맥, 인용, 해시, 출처 범위를 보존합니다.
- [x] 필터와 점수가 같은 결과의 정렬은 결정론적입니다.
- [x] 오프라인 공급자는 안정적이고 정규화되어 있으며, 384 차원이고 네트워크를 사용하지 않습니다.
- [x] OpenAI는 `text-embedding-3-small`에 384 float 차원을 지정해 요청합니다.
- [x] 누락 벡터 백필은 제한되어 있고, 재개 가능하며, 오래된 쓰기에 안전합니다.
- [x] 벡터 검색은 정확한 코사인 검색이며 null 임베딩을 제외합니다.
- [x] PostgreSQL FTS는 안전한 웹 검색 분석과 범위 밀도 순위화를 사용합니다.
- [x] RRF는 고유 점수를 무시하고 청크 ID 식별자를 사용합니다.
- [x] 선택적 재순위화는 별도 의존성이 없는 공급자 경계 뒤에 유지됩니다.
- [x] 프로덕션 구성은 하나의 세션을 순차적으로 사용합니다.
- [x] 구성 요소 출처 정보는 원시 점수 없이 순위를 공개합니다.
- [x] 후보 깊이를 생략하면 서비스 경계에서 `max(20, 4 * k)`로 확장됩니다.
- [x] `R&D`의 임베딩 및 어휘 의미가 일치합니다.
- [x] 스키마 부트스트랩은 `create_all`보다 먼저 pgvector를 활성화합니다.
- [x] M3 전에는 HNSW 인덱스가 없습니다.
- [x] `python -m app.retrieval`이 결정론적 인수 경로를 완료합니다.

## 8. 실패 분류

| 증상 | 담당 가능성이 높은 영역 | 첫 확인 사항 |
|---|---|---|
| `type "vector" does not exist` | 부트스트랩 또는 데이터베이스 권한 | 스키마 소유자로 확장 쿼리 실행 |
| 데이터베이스 테스트 건너뜀 | 로컬 서비스 가용성 | `docker compose ps db` |
| 잘못된 벡터 차원 | 공급자/구성/모델 불일치 | 공급자 차원을 `app.db.models.DIM`과 비교 |
| 벡터 검색 결과 없음 | 누락되거나 호환되지 않는 임베딩 | null이 아닌 개수와 공급자 식별 정보 확인 |
| `R&D`에 대한 어휘 검색 결과 없음 | 서비스 정규화를 우회함 | 저수준 경로를 따로 호출하지 말고 `app.retrieval.retrieve` 호출 |
| 같은 세션의 동시성 오류 | 서비스 구성 | `gather`를 제거하고 벡터 다음 어휘 순서 유지 |
| 점수가 같은 결과의 순서가 불안정함 | SQL 또는 순수 정렬 동점 판정 | 여섯 필드 정렬 계약과 비교 |
| OpenAI 인증 오류 | 자격 증명 또는 계정 권한 | 키를 노출하지 않고 제한된 공급자 프로브 실행 |
| OpenAI 쿼리가 관련 없는 말뭉치 결과를 반환함 | 임베딩 공간 혼합 | 관련성을 평가하기 전에 하나의 공급자로 다시 구축 |
| 문서 동기화 불일치 | 복사한 소스 블록이 달라짐 | 문서화된 동기화 검사기를 실행하고 첫 심볼 불일치 확인 |

검색 품질 실패에 대응해 HNSW를 추가하지 마세요. 근사 인덱스는 지연 시간을 개선하지만 재현율을 낮출 수 있으므로, 기준선을 변경하기 전에 M3에서 둘 다 측정해야 합니다.
