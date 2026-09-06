# M5 검증

의존성 순서대로 게이트를 실행하고 첫 번째 실패에서 중단합니다. 참조 경로는 오프라인에서도 안전하며 환경 자격 증명만으로 공급자를 활성화하지 않습니다.

## 1. 의존성 및 잠금 게이트

```bash
uv lock --check
uv run python -c "from importlib.metadata import version; print({name: version(name) for name in ('fastapi', 'starlette', 'httpx', 'uvicorn')})"
```

이 인수 과정에서 예상되는 잠금 버전은 FastAPI 0.141.1, Starlette 0.52.1, HTTPX 0.28.1, Uvicorn 0.52.1 버전입니다.

## 2. M5.1 HTTP 계약

```bash
uv run pytest -o addopts="" tests/api/test_01_schemas.py tests/api/test_02_errors.py tests/api/test_03_resources.py tests/api/test_04_operations.py tests/api/test_05_routes.py -q
```

예상 결과: `23 passed`.

## 3. M5.2 CLI 및 런타임 계약

```bash
uv run pytest -o addopts="" tests/api/test_06_cli.py tests/api/test_07_runtime.py -q
uv run python -m app.cli --help
docker compose config --quiet
docker compose build app
```

예상 결과: `14 passed`. 도움말에 `retrieve`, `ingest`, `serve`가 표시되고, Compose는 Redis나 작업자 서비스 없이 파싱되며, 잠금된 루트가 아닌 사용자용 애플리케이션 이미지가 빌드됩니다.

## 4. M5.3 통합 계약

```bash
uv run pytest -o addopts="" tests/api/test_08_integration.py -q
uv run pytest -o addopts="" tests/api -q
```

예상 결과: 먼저 `3 passed`, 이어서 `40 passed`. 통합 계층은 M2 검색, M4 리뷰, 실행 영속화, 공유 CLI/HTTP 근거, 실패 시 닫히는 리뷰, 활성 상태, OpenAPI를 검증합니다. 이 과정에서 제외되는 작업: 데이터베이스 또는 공급자 I/O.

## 5. 로컬 HTTP 스모크 테스트

한 터미널에서 런타임을 시작합니다.

```bash
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli serve --host 127.0.0.1 --port 8000 --log-level warning
```

다른 터미널에서 검사합니다.

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/openapi.json > /tmp/m5-openapi.json
uv run python -c "import json; data=json.load(open('/tmp/m5-openapi.json')); assert {'/health','/retrieve','/review'} <= set(data['paths'])"
```

예상 결과: 상태 확인은 `{"status":"ok"}`를 반환하고 OpenAPI에는 단언한 세 경로가 포함됩니다. 이 검사는 루프백 소켓만 사용하며 공급자 또는 데이터베이스 요청을 수행하지 않습니다.

## 6. 선택적 로컬 데이터베이스 스모크 테스트

이 게이트에는 기존에 데이터가 채워진 코퍼스가 필요하며 공급자 인수 과정에는 포함되지 않습니다.

```bash
docker compose up -d db
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli retrieve --query "NVDA 2024 R&D" -k 3
curl --fail --silent --show-error -X POST http://127.0.0.1:8000/retrieve -H "Content-Type: application/json" -d '{"query":"NVDA 2024 R&D","k":3}'
```

루프백 PostgreSQL을 사용할 수 없거나 코퍼스/스키마 상태가 최신이 아니면 이를 정직하게 건너뜁니다. 건너뛴 로컬 데이터베이스 검사를 통과한 검색 스모크 테스트로 해석해서는 안 됩니다.

## 7. 전체 저장소 게이트

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check app/api app/cli.py app/main.py tests/api
uv run python scripts/check_doc_code.py docs/en/m5-serving docs/ko/m5-serving
docker compose config --quiet
docker compose build app
git diff --check
```

예상 결과: `691 passed, 1 skipped`, 이후 정적 검사, 문서, 구성, 차이 검사가 모두 깨끗하게 통과합니다. 건너뛴 항목은 `tests/workflow/test_06_openai_live.py`이며, 선택 실행 방식의 공급자 게이트는 닫힌 상태로 유지되었습니다.

## 8. 정규 API 게이트

```bash
uv run pytest -o addopts="" tests/api -q
```

테스트는 `app.api`를 직접 가져옵니다. 단계별 구현 중에는 누락된 심벌 때문에 테스트를 건너뛸 수 있지만, 인수 시에는 집중형 테스트 모음을 완전히 통과해야 합니다.

## 실패 분류

| 증상 | 먼저 검사할 경계 |
|---|---|
| CLI와 HTTP의 근거가 다름 | `EvidenceHit.from_chunk_hit()` 및 `cli._evidence_payload()` |
| 도메인 라우트가 항상 503 응답을 반환함 | 기본 `RuntimeApiServices`를 `create_app()`에 주입하는 경로 |
| 리뷰가 예기치 않게 공급자를 호출함 | 런타임 공급자/예산 생성자 쌍 |
| 검색이 데이터베이스 URL을 누출함 | 타입이 지정된 SQLAlchemy 예외 변환 |
| PostgreSQL이 없을 때 상태 확인이 실패함 | 활성 상태 라우트는 서비스를 호출해서는 안 됨 |
| Compose에서 기존 코퍼스가 사라짐 | `pg_data` 볼륨 및 `db` 서비스 |
| TestClient 경고가 다시 나타남 | Starlette 제약 및 잠금 해석 |
| 문서 소스가 어긋남 | `scripts/check_doc_code.py` 출력 |
