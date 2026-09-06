# M6 검증

의존성 순서대로 게이트를 실행하고 첫 번째 실패에서 중단합니다. 모든 M6 인수 과정은 오프라인에서도 안전합니다. 스크린샷은 선택 사항이며 실행 가능한 증거를 대신할 수 없습니다.

## 1. 잠긴 데모 의존성

```bash
uv sync --locked --extra demo --dry-run
uv run --extra demo python -c "from importlib.metadata import version; print(version('gradio'))"
```

예상 결과: 잠긴 해석이 변경 없이 성공하고 설치된 Gradio 버전을 출력합니다. 이 게이트를 통과시키기 위해 임의 패키지를 설치하지 마십시오.

## 2. M6.1 집중 계약

```bash
uv run pytest -o addopts="" tests/demo -q
```

측정된 M6.1 결과는 `6 passed`입니다. 테스트에서는 지원/미지원 상태의 미리 준비된 동작, 안전한 렌더링, 주입된 서비스, 런타임 쿼리 위임, 필터, 타입이 지정된 실패 시 닫히는 서비스 오류를 다룹니다.

## 3. M6.1 실제 루프백 실행과 종료

```bash
uv run --extra demo python - <<'PY'
from app.demo import build_demo

demo = build_demo()
_, local_url, _ = demo.launch(
    server_name="127.0.0.1",
    server_port=7861,
    prevent_thread_lock=True,
    quiet=True,
)
print(local_url)
demo.close()
PY
```

측정 결과: `http://127.0.0.1:7861/`이 반환되었고 서버가 정상적으로 종료되었습니다. 이는 로컬 UI 실행을 입증합니다. 실제 `RetrievalResult` 회귀는 이와 별도로 주입형 런타임/데모 어댑터 계약을 입증합니다.

## 4. M6.2 문서와 링크

```bash
make docs
git diff --check
```

예상 결과: 소스 앵커 블록, 설명문 상수, 상대 링크가 동기화됩니다. `tests/test_doc_sync.py`에서 `1 passed`가 보고되며 추적 중인 차이에 공백 오류가 없습니다.

## 5. 미리 준비된 모드 고지

```bash
rg -n "canned fixture|synthetic|not evidence|placeholder" README.md docs/en/m6-demo docs/ko/m6-demo docs/en/failure-analysis.md docs/ko/failure-analysis.md
```

예상 결과: 루트 랜딩 페이지와 M6 문서에서는 합성 Acme 픽스처를 커밋된 SEC 말뭉치와 명시적으로 구분하고 스크린샷 자리표시자를 증거가 아니라고 표시합니다.

## 6. 실제 로컬 말뭉치 표면

이 선택적 로컬 게이트에는 Docker가 필요하며 로컬 데이터베이스만 변경할 수 있습니다.

```bash
docker compose up -d db
uv run python -m app.cli ingest --manifest data/corpus/manifest.json --create-schema
uv run python -m app.cli retrieve --query "NVDA 2024 R&D" --provider deterministic --embed-missing -k 3
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli serve --host 127.0.0.1 --port 8000 --log-level warning
```

다른 터미널에서 다음을 실행합니다.

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/openapi.json
```

예상 결과: 수집은 매니페스트 결과를 보고하고, 검색은 인용된 JSON 증거를 출력하며, 상태 확인은 `{"status":"ok"}`를 반환하고 OpenAPI를 사용할 수 있습니다. 이 게이트를 건너뛰는 것은 런타임/데모 통합 결과를 통과한 것으로 간주되지 않습니다.

## 7. M6.3 최종 저장소 게이트

```bash
uv run pytest -o addopts="" tests/demo -q
uv run pytest -o addopts="" tests/demo tests/api/test_08_integration.py -q
uv run pytest -o addopts="" -q
uv run ruff check --no-fix app tests scripts
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
git diff --check
```

측정 결과: 표면 간 통합에서 `9 passed`, 전체 스위트에서 `697 passed, 1 skipped`가 보고되었으며 모든 명령어가 통과했습니다. 실제 공급자 테스트만 건너뜁니다. 전체 통과 수는 M5.3 이전 결과에서 계산하지 않고 직접 측정했습니다.

## 8. 정규 프레젠테이션 게이트

집중 프레젠테이션 계약과 튜토리얼 동기화를 직접 진행 상황 게이트로 사용합니다.

```bash
uv run pytest -o addopts="" tests/demo -q
uv run python scripts/check_doc_code.py docs/en/m6-demo docs/ko/m6-demo
```

## 9. 스크린샷 릴리스 게이트

텍스트 자리표시자를 교체하기 전에 다음을 실행합니다.

```bash
rg -n "canned fixture|local runtime retrieval|local runtime review" README.md docs/en/m6-demo docs/ko/m6-demo
uv run pytest -o addopts="" tests/demo -q
```

예상 결과: 선택한 모드 표기가 문서에 있으며 같은 리비전에서 집중 스위트가 통과합니다. 쿼리, 인용, 원문 범위, 해시, 청크 ID, 추적/비용 상태, 비밀 부재 여부를 캡처에서 직접 검사하십시오.

## M6 승인 기록

| 게이트 | 결과 |
|---|---|
| 선택적 의존성과 잠금 | 존재함, 잠긴 드라이런 성공 |
| Compose 구성 | `docker compose config --quiet` 통과 |
| 집중 M6.1 스위트 | 6개 통과 |
| Gradio 빌드와 루프백 | 빌드됨, `127.0.0.1:7861`에서 실행 후 종료 |
| 런타임 반환 타입 결합 | 실제 `RetrievalResult.hits` 회귀, 집중 데모+API 통합 9개 통과 |
| 포트폴리오 문서 | 문서 6개 전체와 아키텍처/평가/실패 보고서 |
| 문서 동기화 | 소스 블록 90 건, 설명문 상수 14 건, 링크 353 건을 문서 60 건에서 동기화, 문서 동기화 테스트 1 건 통과 |
| 전체 회귀 | 697개 통과, 1개 건너뜀 |
| 레거시 정리 | 추적 중인 `old/` 파일 22개 제거, `old/.env`는 M6에서 보존 후 승인된 정리 과정에서 제거, `scripts/` 보존 |
| 최종 스크린샷 | 의도적으로 없음, 자리표시자가 증거가 아님을 명시 |
| 다음 마일스톤 | 배포 준비가 된 릴리스 M7 |
