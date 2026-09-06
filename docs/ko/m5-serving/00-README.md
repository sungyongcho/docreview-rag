# M5 개요 — 타입 기반 서빙

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

M5는 M2 검색 서비스와 M4 보호 워크플로를 세 가지 실행 가능한 경계로 전환합니다. 바로 엄격한 HTTP 리소스, 결정론적 CLI, 컨테이너 런타임입니다. 기본 경로는 오프라인에서도 안전합니다. 결정론적 임베딩이 CLI와 Compose의 기본값이며, HTTP 리뷰는 LLM 공급자와 명시적 예산이 주입될 때까지 타입이 지정된 `503` 응답으로 요청을 거부합니다.

## M5의 구성

| 단계 | 책임 | 참조 구현 |
|---|---|---|
| M5.1 | 엄격한 요청, 응답, 오류, 리소스 라우트 | `app/api/schemas.py`, `app/api/routes/` |
| M5.2 | 명시적 CLI, 임포트 시 안전한 애플리케이션 팩토리, 컨테이너 토폴로지 | `app/cli.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml` |
| M5.3 | 데이터베이스 기반 M2/M4 구성과 인터페이스 간 검증 | `app/api/runtime.py`, `tests/api/test_08_integration.py` |

## 읽는 순서

1. [측정 결과](01-findings.md)에서 통합 설계 결정을 설명합니다. 2. [규범 명세](02-spec.md)에서 서빙 계약을 확정합니다. 3. [정렬 가능한 빌드 가이드](03-build.md)는 누적 게이트와 함께 M5.1 단계에서 M5.3 단계까지 진행합니다. 4. [버그와 함정](04-bugs.md)은 최종 코드를 형성한 실패 사례를 기록합니다. 5. [검증](05-verify.md)은 정확한 오프라인 인수 절차를 담고 있습니다.

## 오프라인 빠른 시작

```bash
uv sync --group dev
docker compose up -d db
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli retrieve --query "NVDA 2024 R&D" -k 3
uv run python -m app.cli serve --host 127.0.0.1 --port 8000
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/openapi.json
```

검색 명령에는 기존에 데이터가 채워진 루프백 PostgreSQL 코퍼스가 필요합니다. 명시적 옵션으로 해당 동작을 요청하지 않는 한 시딩이나 변경을 수행하지 않으며 유료 공급자를 호출하지도 않습니다.

## 완료 체크포인트

```bash
uv run pytest -o addopts="" tests/api -q
uv run pytest -o addopts="" -q
```

이 소스 리비전의 예상 결과는 M5에서 `40 passed`, 전체 저장소에서 `691 passed, 1 skipped`입니다. 건너뛴 테스트는 명시적으로 선택해야 실행되는 실시간 OpenAI 워크플로 테스트이며, 이 M5 인수 과정에서는 유료 또는 실시간 공급자 호출을 실행하지 않았습니다.
