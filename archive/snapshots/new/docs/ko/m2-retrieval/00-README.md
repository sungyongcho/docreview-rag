# M2 개요 — 하이브리드 검색

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

M2는 M1.4 단계에서 생성한 출처 인용이 포함된 PostgreSQL 청크를 결정론적 검색 결과로 변환합니다. 색인 텍스트를 임베딩하고, 정확한 pgvector 코사인 검색과 PostgreSQL 전문 검색을 실행하며, 역순위 융합(RRF)으로 두 순위를 결합하고, 모든 결과에 완전한 인용 정보를 유지합니다.

## 한 문장 계약

`query + filters -> query embedding -> exact vector rank + lexical rank -> RRF -> cited hits`

런타임 결과에는 벡터 및 어휘 검색의 청크 ID 순위도 포함됩니다. 코사인 유사도와 `ts_rank_cd`의 고유 값은 서로 척도가 다르므로, 구성 요소 출처 정보에는 이 점수를 추가하지 않습니다.

## M2에 포함되는 내용

| 단계 | 책임 | 참조 구현 |
|---|---|---|
| M2.1 | 엄격한 인용 검색 결과 및 필터 계약 | `app/retrieval/types.py` |
| M2.2 | 결정론적 임베딩 공급자와 OpenAI 임베딩 공급자, 재개 가능한 백필 | `app/retrieval/embeddings.py` |
| M2.3 | 정확한 pgvector 코사인 검색 | `app/retrieval/vector.py` |
| M2.4 | 안전한 PostgreSQL 전문 검색 | `app/retrieval/lexical.py` |
| M2.5 | 순위만 사용하는 RRF | `app/retrieval/hybrid.py` |
| M2.6 | 선택적 재순위화 공급자 경계 | `app/retrieval/rerank.py` |
| M2.7 | 단일 세션 프로덕션 구성과 JSON CLI | `app/retrieval/service.py`, `app/retrieval/__main__.py` |
| M2.8 | pgvector 부트스트랩과 실제 PostgreSQL 검증 | `app/db/bootstrap.py`, `tests/retrieval/test_08_postgres.py` |
| M2.9 | 직접 작성한 BM25 순위 실험군 | `app/retrieval/bm25.py` |
| M2.10 | 로컬 sentence-transformer 임베딩 공급자 | `app/retrieval/sbert.py` |
| M2.11 | cross-encoder 재순위화 공급자 | `app/retrieval/cross_encoder.py` |

## 읽는 순서

1. [측정 결과](01-findings.md)에서는 이 구현이 해당 공급자, 검색 방식, 경계를 사용하는 이유를 설명합니다. 2. [규범 명세](02-spec.md)에서는 코드와 테스트가 보존해야 하는 계약을 정의합니다. 3. [계층별 빌드 가이드](03-build.md)에서는 개념부터 소스 코드와 누적 테스트까지 단계적으로 진행합니다. 4. [버그와 설계 함정](04-bugs.md)에는 증상, 근본 원인, 수정 사항, 회귀 방지책을 기록합니다. 5. [검증](05-verify.md)에서는 인수 명령, 테스트 구성표, 실패 분류 방법을 제공합니다.

## 빠른 시작: 결정론적 오프라인 공급자

PostgreSQL만 시작하고 스키마를 생성해 시드 데이터를 넣은 다음, 임베딩이 null인 항목을 결정론적 토큰 해시 공급자로 채웁니다.

```bash
docker compose up -d db
uv run python -m app.ingestion.seed --create-schema
uv run python -m app.retrieval --provider deterministic --embed-missing --query "NVDA 2024 R&D" -k 3
```

첫 검색 명령은 임베딩이 null인 행만 백필합니다. 이후 쿼리에서는 `--embed-missing`을 생략할 수 있습니다.

```bash
uv run python -m app.retrieval --provider deterministic --query "NVDA 2024 R&D" -k 3 --candidate-k 20
```

JSON 출력에는 완전한 검색 결과와 두 구성 요소의 순위 목록이 들어 있습니다. 검색 결과에는 `chunk_id`, 인용, 반열린 출처 범위, 출처 해시, 근거 본문, 합성 문맥, 색인 텍스트, 융합된 RRF 점수가 포함됩니다.

## OpenAI 공급자

M2는 명시적인 384차원 출력을 사용하는 `text-embedding-3-small`을 사용합니다. 동일한 공급자로 새 임베딩 집합을 채우고 쿼리합니다.

```bash
EMBEDDING_PROVIDER=openai OPENAI_API_KEY="your-key" uv run python -m app.retrieval --embed-missing --query "NVDA 2024 R&D" -k 3 --candidate-k 20
```

현재 스키마는 임베딩 공급자의 식별 정보를 저장하지 않습니다. 결정론적 벡터를 OpenAI 쿼리 벡터로 검색하거나 그 반대로 검색해서는 안 됩니다. 말뭉치 백필과 쿼리에는 같은 공급자를 사용해야 하며, 공급자를 변경하려면 명시적으로 다시 구축하거나 마이그레이션해야 합니다.

## 기준선의 경계

- 벡터 검색은 정확한 코사인 검색입니다. M2는 HNSW 또는 IVFFlat 인덱스를 생성하지 않습니다.
- 어휘 검색은 PostgreSQL `websearch_to_tsquery`를 논리합으로 완화한 뒤 extent 거리·길이 정규화를 건 `ts_rank_cd`로 순위를 매기며, 문자 그대로의 BM25가 아닙니다. 실제 BM25는 M2.9에서 두 번째 실험군으로 등장합니다.
- 로컬 모델은 선택 사항입니다. `import app.retrieval`에는 torch 백엔드가 필요 없고, M2.10과 M2.11은 공급자를 실제로 쓸 때만 가중치를 읽습니다.
- 재순위화는 호출자가 리랭커를 넘기지 않는 한 꺼져 있습니다. M2.11이 경계를 채우고 켤지 말지는 M3.4가 결정합니다.
- RRF는 구성 요소의 고유 점수가 아니라 1부터 시작하는 순위를 결합합니다.
- 서비스는 구성 요소별로 `max(20, 4 * k)`개의 후보를 요청하며, 호출자가 `--candidate-k`를 명시하면 해당 값을 사용합니다.
- 하나의 `AsyncSession`을 벡터 검색과 어휘 검색이 순차적으로 공유합니다.
- 재순위화는 선택적 실험군이며 기본 인수 경로에는 포함되지 않습니다.
- `--create-schema`는 새 스키마에 없는 객체를 생성하며, 마이그레이션 도구가 아닙니다.

## 직접 구현 경로

각 정식 알고리즘 모듈은 [빌드 가이드](03-build.md)의 순서대로 직접 만듭니다. 패키지가 존재한 뒤 필요한 심볼이 없으면 해당 테스트를 건너뛰므로 집중 테스트 모음을 진행 현황판처럼 사용할 수 있습니다.
