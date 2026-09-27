# 2. 공시 도구를 stdio·HTTP로 연결하기

[전체 진행표](README.md) · 이전: [작은 MCP 서버](01-small-mcp-server.md) · 다음: [LangChain](03-langchain-models-and-tools.md)

목표는 같은 세 공시 도구를 두 transport로 제공하면서 검색 범위와 출처 식별자를 보존하는 것이다.

## 읽을 코드와 계약

| 파일 | 재사용할 책임 |
|---|---|
| [filings.py](../app/agent/tools/filings.py) | `SearchFilingsParams`, `FetchChunkParams`, `CompareYearsParams`, 도구 실행 |
| [registry.py](../app/agent/tools/registry.py) | 도구 정의, 입력 검증, 오류 경계 |
| [evidence.py](../app/contracts/evidence.py) | `EvidenceCitation` |
| [service.py](../app/retrieval/search/service.py) | 실제 검색 |
| [test_filings.py](../tests/agent/tools/test_filings.py) | 도구의 현재 동작·실패 사례 |
| [live_postgres.py](../tests/live_postgres.py) | 폐기용 DB와 테스트별 schema 격리 |

## 직접 할 일

1. 아래 결과 계약을 입력 타입과 함께 적고, 기존 도메인 로직을 연결한다.
2. SDK가 입력 스키마를 자동 생성해도 기존 입력 모델과 의미가 어긋나지 않는지 비교한다. 같은 규칙을 별도 상수·분기 두 벌로 만들지 않는다.
3. stdio에서 도구 발견 → 검색 → 반환된 청크 조회 → 연도 비교를 수행한다.
4. 같은 서버를 로컬 Streamable HTTP로 제공하고 SDK 클라이언트로 반복한다. 기존 DEV 서비스와 충돌하지 않는 loopback 포트를 사용한다.
5. 서버 startup/shutdown, DB session, MCP session 수명을 확인한다. 동시 호출이 같은 변경 가능한 DB session을 공유하지 않게 한다.

| 도구 | 입력의 핵심 | 결과에서 확인할 것 |
|---|---|---|
| `search_filings` | 질문, 회사, 회계연도, 서식, k | hits와 각 hit의 완전한 출처 식별자 |
| `fetch_chunk` | chunk ID | 원문 body, 문서·청크·구간·원문 해시 |
| `compare_years` | 질문, 회사, 서로 다른 2~4개 연도 | 연도별 hits, 특정 연도에 근거가 없는 경우 |

`chunk_id`만 맞는 결과는 충분하지 않다. `doc_id`, `source_sha256`, `start_char`, `end_char`, citation을 함께 보존한다. 모델에 전달하는 요약문과 검증에 쓰는 원문 식별자를 혼동하지 않는다.

## 가장 중요한 실습: 범위가 넓어지는 호출

현재 `FetchChunkParams`는 chunk ID만 받는다. 이 타입 자체가 웹에서 선택한 회사·연도를 강제해주지는 않는다. 또 검색 인자의 필터를 생략하면 요청 범위까지 자동 상속된다고 가정할 수 없다.

선택한 범위를 신뢰 가능한 서버 측 실행 문맥으로 고정하고, 도구 인자는 그 범위 안에서만 유효하도록 설계한다. 범위 밖 요청을 명시적으로 거부하거나, 허용된 부분집합으로 제한하는 규칙을 하나로 정해 테스트한다. 단순히 필터를 없애 전체 검색으로 바꾸는 동작은 허용하지 않는다.

특히 MCP가 별도 프로세스·HTTP 서비스로 실행되면 Python 프로세스 안의 문맥이 저절로 전달되지 않는다. 문맥 전달과 서버 검증 경계를 먼저 설명하고 구현한다. 모델이 전달한 `scope`를 그대로 신뢰해서는 안 된다.

## 실패 재현과 검증

| 사례 | 보장할 동작 |
|---|---|
| 존재하지 않는 chunk ID | 명확한 도구 실패 |
| 범위 밖 실제 chunk ID | 근거 본문을 반환하지 않음 |
| 정상 범위지만 검색 결과 없음 | 성공한 빈 검색 결과 |
| 중복 연도 / 연도 하나 / k 범위 위반 | 도메인 입력 검증 실패 |
| DB 또는 임베딩 제공자 실패 | 검색 결과 없음과 구분, 비밀 없는 진단 |
| 클라이언트 종료 / 서버 종료 | session과 프로세스 정리 |

먼저 도구 단위 검사를 실행한다.

```bash
.venv/bin/pytest tests/agent/tools tests/agent/test_mcp_server.py -q
```

실제 DB 확인은 **폐기용 PostgreSQL을 따로 준비하고** `DOCREVIEW_TEST_DATABASE_URL`을 그 DB로 지정한 뒤 실행한다. 이 fixture는 schema를 생성·삭제한다. 사용자 공시 DB를 테스트 대상으로 사용하지 않는다.

```bash
.venv/bin/pytest tests/retrieval/test_01_postgres_retrieval.py -m live_postgres --require-live-postgres -q
```

위 기존 검색 테스트만으로 새 MCP의 DB 통합이 검증되지는 않는다. `tests/agent/`의 미사용 번호를 확인해 실제 MCP+검색 통합 테스트를 추가하고 같은 marker와 필수 옵션으로 실행한다. stdio·실제 HTTP 소켓 검증을 각각 남기며, in-process transport 결과와 구분한다.

FastAPI 결합과 lifespan은 [SDK의 ASGI 안내](https://py.sdk.modelcontextprotocol.io/run/asgi/)를 읽고 설치 버전에 맞춘다. 외부 공개와 OAuth는 6단계에서 진행한다.

## 통과 기준

- [ ] 실제 세 도구가 stdio와 Streamable HTTP에서 발견·호출된다.
- [ ] 실습용 도구는 제품 도구 목록에서 제거했다.
- [ ] 출처 식별자와 요청 범위가 두 transport 모두에서 보존된다.
- [ ] 검색 결과 없음·잘못된 범위·존재하지 않는 문서·실행 실패를 구분한다.
- [ ] 실제 공시 검색과 격리 DB 통합 결과를 각각 설명한다.
