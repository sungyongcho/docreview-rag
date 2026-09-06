# M7 검증

다음 게이트를 순서대로 실행하고 첫 번째 실패에서 중단하십시오. 모든 인수 과정은 모델 공급자와 외부 배포 계정에 대해 오프라인으로 수행됩니다.

## 1. 릴리스 정책과 통합

```bash
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY RUN_LIVE_OPENAI_TEST
uv sync --locked --extra demo
uv run pytest -o addopts="" tests/release tests/demo tests/api -q
```

측정된 집중 테스트 결과는 `67 passed`입니다. 릴리스 테스트 21 개, 데모 테스트 6개, API 테스트 40 개가 포함됩니다. 데이터베이스나 공급자 네트워크 호출은 필요하지 않습니다.

## 2. Ruff와 소유 범위 형식 검사

```bash
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
```

예상 결과: 린트를 전역적으로 통과하고 M7 소유의 모든 Python 파일이 형식화되어 있습니다.

## 3. 잠금과 Compose

```bash
uv lock --check
uv sync --locked --extra demo --dry-run
docker compose config --quiet
```

예상 결과: 잠금이 최신이고 동기화에서 변경할 항목이 없으며 공급자 키를 렌더링하지 않고 Compose가 해석됩니다.

## 4. 로컬 릴리스 애플리케이션 스모크 테스트

```bash
DOCREVIEW_MODE=canned uv run --extra demo uvicorn app.release.space:app --host 127.0.0.1 --port 7860 --workers 1 --log-level warning
```

다른 터미널에서 다음을 실행합니다.

```bash
curl --fail --silent --show-error http://127.0.0.1:7860/health
curl --fail --silent --show-error http://127.0.0.1:7860/release
curl --fail --silent --show-error http://127.0.0.1:7860/
```

예상 결과: 상태 확인은 미리 준비된 모드를 보고하고, 릴리스 메타데이터는 `openai_enabled=false`를 보고하며, 랜딩 페이지는 Gradio입니다. `Ctrl-C`로 서버를 중단하십시오.

## 5. 컨테이너 빌드와 스모크 테스트

```bash
docker compose build app
docker build --file deploy/huggingface/Dockerfile --tag docreview-m7-space:local .
docker run --rm --publish 127.0.0.1:7860:7860 --name docreview-m7-space-local docreview-m7-space:local
```

다른 터미널에서 다음을 실행합니다.

```bash
curl --fail --silent --show-error http://127.0.0.1:7860/health
curl --fail --silent --show-error http://127.0.0.1:7860/
```

예상 결과: 두 이미지를 모두 빌드하고 Space 이미지가 미리 준비된 상태 확인과 UI를 반환합니다. 이는 로컬 이미지 증명이며 외부 Hugging Face 배포가 아닙니다.

## 6. 채워진 전체 저장소 회귀 테스트

```bash
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY RUN_LIVE_OPENAI_TEST
uv run pytest -o addopts="" -q
```

측정 결과는 `718 passed, 1 skipped`이며 111.31 초가 걸렸습니다. 건너뛴 항목은 명시적으로 선택 실행하는 실제 OpenAI 워크플로 테스트입니다. 이 값은 이전 단계 결과를 계산해서 얻지 말고 전체 실행에서 가져와야 합니다.

## 7. 문서화와 언어

```bash
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
uv run pytest -o addopts="" tests/test_doc_sync.py -q
git diff --check
```

예상 결과: 소스 블록, 본문의 상수, 상대 링크가 동기화되고 문서 동기화 테스트를 통과하며 공백 오류가 남지 않습니다.

## 8. 임시 클린 아카이브

```bash
scripts/verify_clean_checkout.sh
```

스크립트는 Git으로 선택한 소스를 생성된 임시 디렉터리에 복사하고, 무시된 credentials/corpus/cache 상태를 제외하며, 새 가상 환경을 만들고, 집중 release/demo/API 테스트 67 개, 린트, 소유 범위 형식, 문서, Compose 검증을 실행하고, 두 이미지를 빌드하고, 무작위 루프백 포트에서 미리 준비된 health/UI 스모크 테스트를 수행합니다. 자체적으로 만든 정확한 임시 산출물만 제거합니다.

## 9. 자격 증명이 필요한 경로는 실행하지 않음

명시적으로 승인된 로컬 런타임 리뷰에서는 키를 파일에 쓰지 않고 입력하십시오.

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY
printf '\n'
export OPENAI_API_KEY
export DOCREVIEW_MODE=runtime
uv run --extra demo uvicorn app.release.space:app --host 127.0.0.1 --port 7860 --workers 1 --log-level warning
unset OPENAI_API_KEY
```

M7 인수 과정에서는 이 명령을 실행하지 않았습니다. 구성되어 있고 로컬에 있는 데이터베이스와 코퍼스도 필요합니다. 승인하기 전에 모델 액세스와 날짜가 명시된 가격 구성을 다시 확인하십시오.

## M7 완료 기록

| 게이트 | 결과 |
|---|---|
| 집중 release/demo/API | 67 개 통과 |
| 전체 오프라인 회귀 테스트 | 718 개 통과, 1 개 건너뜀, 111.31 초 소요 |
| Ruff와 소유 범위 형식 | 전역 린트 통과. 소유 파일 14 개 형식화 |
| 문서 동기화 | 소스 블록 90 개, 본문 상수 14 개, 링크 369 개를 문서 66 개에서 동기화. 동기화 테스트 1 개 통과 |
| 잠금과 Compose | 잠금 최신. 설치된 패키지 83 개 변경 없음. Compose 구성 통과 |
| Compose 애플리케이션 이미지 | 로컬 빌드 통과 |
| Hugging Face 이미지와 미리 준비된 스모크 테스트 | 로컬 빌드 통과. 미리 준비된 상태 확인과 Gradio UI 통과 |
| 임시 클린 아카이브 | 새 잠금 동기화, 집중 테스트 67 개, lint/format/docs, 두 빌드, 루프백 스모크 테스트 통과 |
| 실제 공급자 호출 | 실행하지 않음. 명시적인 자격 증명과 승인 필요 |
| 외부 publish/account 변경 | 실행하지 않음 |
| 다음 마일스톤 | M8 교차 언어 검색 |
