# M5 명세

이 문서는 규범적입니다. 코드, 테스트, CLI 출력, OpenAPI, 컨테이너 동작은 이 계약을 유지해야 합니다.

## 1. 서빙 경계

M5는 세 가지 진입점을 거치는 하나의 동기 요청 경로를 제공합니다.

```text
CLI or HTTP -> strict input -> M2 retrieval -> optional M4 workflow -> typed output
```

R1에는 작업자 큐나 Redis 서비스가 포함되지 않습니다. API는 각 작업을 기다린 뒤 최종 리소스나 타입이 지정된 실패를 반환합니다.

## 2. HTTP 리소스

애플리케이션은 다음 리소스를 노출합니다.

| 메서드 | 경로 | 리소스 |
|---|---|---|
| `GET` | `/health` | 프로세스 활성 상태 |
| `POST` | `/retrieve` | 순위와 인용이 포함된 근거 |
| `GET` | `/documents` | 수집된 공시 문서 모음 |
| `POST` | `/ingest` | 동기식 매니페스트 수집 |
| `POST` | `/review` | 보호된 M4 워크플로 실행 |
| `GET` | `/runs/{run_id}` | 영속화된 실행 |
| `GET` | `/runs/{run_id}/traces` | 순서가 지정된 공급자 트레이스 |
| `GET` | `/eval` | 영속화된 평가 리소스 |

모든 요청 본문은 엄격하며 알 수 없는 필드를 금지합니다. 검증은 안정적인 오류 봉투를 사용하고 트레이스백이나 제출된 비밀을 절대 반환하지 않습니다.

## 3. 근거 계약

모든 CLI 또는 HTTP 검색 결과는 정확히 다음 공개 필드를 노출합니다.

```text
chunk_id, doc_id, item, kind, citation, start_char, end_char,
source_sha256, body, context_header, score
```

구간은 비어 있지 않은 반개방 구간입니다. 소스 해시는 소문자 16진수 SHA-256 형식입니다. `index_text`와 구성 요소 고유의 검색 점수는 내부에 유지됩니다.

## 4. 런타임 구성

`RuntimeApiServices`는 API 요청마다 하나의 `AsyncSession`을 엽니다. 직접 검색은 해당 세션으로 M2 서비스를 호출하며, 공급자가 명시적으로 주입되지 않으면 결정론적 임베딩을 기본값으로 사용합니다. 리뷰는 같은 세션 위에서 M2 검색기를 클로저로 만들고 M4를 호출한 뒤 검색 읽기 트랜잭션을 끝내고, 실행과 트레이스를 원자적으로 영속화합니다.

수집은 데이터베이스 작업 전에 전체 로컬 코퍼스를 준비하고 검증하며, 누락된 테이블을 명시적으로 부트스트랩한 뒤 M1의 멱등적 원자 업서트에 위임합니다. 프로세스 시작 시 구성된 코퍼스를 암묵적으로 변경하지 않습니다.

## 5. 공급자와 비용 안전성

CLI 검색은 결정론적 임베딩을 기본값으로 사용합니다. Compose는 `EMBEDDING_PROVIDER=deterministic`을 설정합니다. OpenAI 임베딩을 사용하려면 명시적 CLI 공급자 옵션 또는 외부 런타임 구성이 필요합니다.

HTTP 리뷰에는 주입된 LLM 공급자와 명시적 `ProviderBudget`이 필요합니다. 기본 애플리케이션은 `503 provider_unavailable`로 리뷰를 거부하며, 환경에 API 키가 존재한다는 이유만으로 지출이 활성화되지 않습니다.

## 6. 타입이 지정된 실패

| 실패 | HTTP 또는 CLI 동작 |
|---|---|
| 빈 쿼리, 0인 `k`, 잘못된 요청 | 타입이 지정된 입력 실패 |
| 누락되었거나 손상된 매니페스트 | 타입이 지정된 파일/클라이언트 실패 |
| 데이터베이스 사용 불가 | 연결 세부 정보 없는 `database_unavailable` |
| 공급자 사용 불가 | 자격 증명 없는 `provider_unavailable` |
| 예기치 않은 라우트 예외 | 정보를 노출하지 않는 `internal_error` |
| 워크플로 예산 소진 | HTTP 429 응답이 포함된 구조화된 실행 결과 |
| 워크플로 스키마 거부 | HTTP 502 응답이 포함된 구조화된 실행 결과 |

## 7. 런타임 및 컨테이너 계약

`create_app()`은 데이터베이스 조회나 공급자 호출을 수행하지 않습니다. `/health`는 프로세스 활성 상태를 검사합니다. Compose는 이름이 지정된 PostgreSQL 코퍼스 볼륨을 보존하고 PostgreSQL이 정상 상태가 될 때까지 기다리며, Redis나 작업자 서비스를 포함하지 않고 루트가 아닌 사용자로 애플리케이션을 실행합니다.

## 8. 인수 계약

루프백 Uvicorn 소켓을 제외하면 정규 인수 과정은 결정론적이며 오프라인입니다.

```bash
uv run pytest -o addopts="" tests/api -q
docker compose config --quiet
uv run python scripts/check_doc_code.py docs/en/m5-serving docs/ko/m5-serving
```

전체 저장소 게이트에는 기존의 선택적 실시간 OpenAI 건너뛰기가 포함됩니다. 어떤 M5 명령도 이 건너뛰기를 실시간 호출로 암묵적으로 전환해서는 안 됩니다.
