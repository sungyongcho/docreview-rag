# M7.3 튜토리얼 4 — "내 컴퓨터에서는 되는데"를 걸러내기

지금까지의 모든 테스트는 작성자의 작업 트리에서 통과했다. 작업 트리에는 저장소에 없는 상태가 함께 존재한다.

개발 환경이 가리는 조건은 다음과 같다.

| 감춰지는 것 | 다른 사람에게 생기는 일 |
|---|---|
| Git에 커밋되지 않은 파일 | 클론에 없어서 import가 실패한다 |
| 락 파일과 어긋난 로컬 패키지 | 의존성 해석이 달라진다 |
| `.gitignore`된 `.env` 속 비밀 | 설정이 비어 기동에 실패한다 |
| 이미 떠 있는 DB 컨테이너 | 맨바닥에서 시작하면 순서가 안 맞는다 |
| 캐시된 빌드 산출물 | 클린 빌드가 실패한다 |

**이 조건들은 작성자의 환경에서는 드러나지 않고, 저장소를 클론한 다른 환경에서 처음 실패로 나타난다.**

M7.3은 이를 배포 전에 확인한다. **Git이 추적하는 파일과 무시 대상이 아닌 untracked 파일만** 임시 아카이브로 복사하고, 새 가상환경에서 릴리스 게이트를 전부 다시 실행한다. 공급자 자격증명은 실행 전에 명시적으로 해제한다.

이 스크립트가 통과해야 저장소를 클론한 환경에서 같은 결과가 나온다고 말할 수 있다.

**선행 조건:** 튜토리얼 3의 `uv run pytest tests/release/test_05_assets.py -q`가 통과해야 한다.

### 이 스크립트가 증명하지 *않는* 것

이 스크립트에는 한계가 하나 있다. 파일 수집이 다음과 같이 동작한다.

```text
git ls-files --cached --others --exclude-standard
```

`--others`가 붙어 있으므로 **무시 대상이 아닌 untracked 파일까지 아카이브에 포함된다.** 즉 현재 커밋만으로 구성한 체크아웃을 검증하는 것이 아니다.

예를 들어 `app/config.py`와 `app/db/`가 untracked 상태라면 그 파일들도 아카이브에 들어간다. **따라서 이 스크립트가 통과해도 HEAD 커밋만으로 같은 결과가 나온다는 것은 증명되지 않는다.** 커밋 완전성까지 확인하려면 작업 트리에 untracked 파일이 없는지를 따로 검사해야 한다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 파일 수집 | **설계 결정 확인** | 무엇이 포함되고 무엇이 빠지는가 |
| 자격증명 해제 | 격리를 **직접 구현** | 비밀 없이 도는지 확인하는 법 |
| 게이트 실행 | **구조 작성 후 호출 순서 검토** | 싼 검사부터 도는 순서 |
| `trap` 정리 | 정리 범위를 **직접 구현** | 이 실행이 만든 것만 지우는 법 |

### 1. 클린 소스 검증기

#### `scripts/verify_clean_checkout.sh` 생성 — 클린 체크아웃 검증

**학습 행동 — 구조 작성 후 호출 순서 검토:** 게이트 실행 순서를 직접 정해 보고, `trap`이 무엇을 정리하고 무엇을 남기는지 확인한다.

<!-- file: scripts/verify_clean_checkout.sh -->
```bash
#!/usr/bin/env bash
set -euo pipefail

M7_SOURCE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
M7_TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/docreview-m7-clean.XXXXXX")
M7_ARCHIVE_ROOT="$M7_TEMP_ROOT/repository"
M7_FILE_LIST="$M7_TEMP_ROOT/files.list"
M7_PROJECT="docreview_m7_${$}"
M7_SPACE_IMAGE="docreview-m7-space:${$}"
M7_SPACE_CONTAINER="docreview-m7-space-${$}"

cleanup() {
    docker rm -f "$M7_SPACE_CONTAINER" >/dev/null 2>&1 || true
    if [[ -d "$M7_ARCHIVE_ROOT" ]]; then
        docker compose --project-directory "$M7_ARCHIVE_ROOT" \
            -p "$M7_PROJECT" down --volumes --remove-orphans --rmi local \
            >/dev/null 2>&1 || true
    fi
    docker image rm "$M7_SPACE_IMAGE" >/dev/null 2>&1 || true
    case "$M7_TEMP_ROOT" in
        "${TMPDIR:-/tmp}"/docreview-m7-clean.*) rm -rf -- "$M7_TEMP_ROOT" ;;
        *) printf 'Refusing to remove unexpected temporary path: %s\n' "$M7_TEMP_ROOT" >&2 ;;
    esac
}
trap cleanup EXIT INT TERM

mkdir -p "$M7_ARCHIVE_ROOT"
while IFS= read -r -d '' path; do
    if [[ -f "$M7_SOURCE_ROOT/$path" || -L "$M7_SOURCE_ROOT/$path" ]]; then
        printf '%s\0' "$path"
    fi
done < <(
    git -C "$M7_SOURCE_ROOT" ls-files --cached --others --exclude-standard -z
) > "$M7_FILE_LIST"

tar --null --create --file=- --directory="$M7_SOURCE_ROOT" \
    --files-from="$M7_FILE_LIST" | tar --extract --file=- --directory="$M7_ARCHIVE_ROOT"

cd "$M7_ARCHIVE_ROOT"
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY
export DOCREVIEW_MODE=canned
export UV_PROJECT_ENVIRONMENT="$M7_ARCHIVE_ROOT/.venv"

printf 'Clean archive: fresh locked dependency sync\n'
uv sync --locked --extra demo

printf 'Clean archive: focused release, demo, and API tests\n'
uv run pytest -o addopts="" tests/release tests/demo tests/api -q

printf 'Clean archive: lint, owned format, and documentation sync\n'
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
uv run python scripts/check_doc_parity.py inventory
uv run python scripts/check_doc_parity.py parity
uv run python scripts/check_doc_parity.py language
uv run pytest -o addopts="" tests/test_doc_sync.py tests/test_doc_parity.py -q

printf 'Clean archive: Compose configuration and application image build\n'
docker compose -p "$M7_PROJECT" config --quiet
docker compose -p "$M7_PROJECT" build app

printf 'Clean archive: Hugging Face image build and canned local smoke\n'
docker build --file deploy/huggingface/Dockerfile --tag "$M7_SPACE_IMAGE" .
docker run --detach --name "$M7_SPACE_CONTAINER" \
    --publish 127.0.0.1::7860 "$M7_SPACE_IMAGE" >/dev/null

M7_PORT=$(docker port "$M7_SPACE_CONTAINER" 7860/tcp | tail -n 1 | sed 's/.*://')
for attempt in $(seq 1 45); do
    if M7_PORT="$M7_PORT" python - <<'PY'
import json
import os
import urllib.error
import urllib.request

port = os.environ["M7_PORT"]
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
        health = json.load(response)
except (OSError, TimeoutError, urllib.error.URLError):
    raise SystemExit(1) from None
if health != {"status": "ok", "mode": "canned"}:
    raise SystemExit(f"unexpected health response: {health}")
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
        body = response.read().decode("utf-8")
except (OSError, TimeoutError, urllib.error.URLError):
    raise SystemExit(1) from None
if "Document Review Evidence Demo" not in body:
    raise SystemExit("Gradio landing page marker is missing")
PY
    then
        printf 'Clean archive: canned health and Gradio smoke passed on port %s\n' "$M7_PORT"
        exit 0
    fi
    if [[ "$attempt" == "45" ]]; then
        docker logs "$M7_SPACE_CONTAINER" >&2 || true
        printf 'Container smoke timed out\n' >&2
        exit 1
    fi
    sleep 1
done
```

**코드에서 꼭 볼 것**

- 첫 줄이 `set -euo pipefail`이다. **중간 명령이 실패해도 스크립트가 계속 진행하면, 마지막 명령의 성공이 전체 통과로 보고된다.**
- 자격증명을 `unset`한다. **이 검증의 목적이 비밀 없이 기동하는지 확인하는 것이므로, 실행한 셸의 키가 그대로 전달되면 검증 대상 자체가 달라진다.**
- 게이트를 비용이 낮은 순서로 실행한다. 의존성 설치, ruff, 테스트를 먼저 하고 이미지 빌드를 마지막에 둔다. Docker 빌드가 가장 오래 걸리므로, 앞 단계에서 실패하면 그 시간을 쓰지 않는다.
- `trap`은 **이 실행이 만든 대상만** 정리한다. 이름을 지정한 컨테이너와 이미지, 임시 아카이브가 대상이며 기존 컨테이너는 건드리지 않는다.
- 스모크 테스트는 루프백 주소로만 접속한다. 외부에 포트를 노출하지 않는다.

### 집중 테스트와 테스트가 지키는 계약

이 스크립트는 문서 검사가 아니라 실제 실행이다. Docker 컨테이너와 임시 파일 상태를 변경한다.

```bash
uv run pytest tests/release -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 커밋되지 않은 소스 파일 | 클론한 사람이 같은 것을 받는다. |
| 락 파일과 어긋난 의존성 | 의존성 해석이 재현된다. |
| 셸에 남아 있던 API 키 | 비밀 없이도 기동한다. |
| 이전 실행이 남긴 컨테이너 | 정리가 이 실행 범위로 제한된다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 스크립트의 해당 단계와 연결해 설명해 본다.

- **개발자 머신이 감추는 실패 다섯 가지는 무엇인가?**
  - **답:** 커밋되지 않은 파일, 락 파일과 다른 로컬 패키지, 무시된 `.env`의 비밀, 이미 실행 중인 데이터베이스, 캐시된 빌드 산출물이다. 새 환경은 이 다섯 가지 우연한 지원을 모두 제거한다.
- **`--others` 때문에 이 스크립트가 증명하지 못하는 것은 무엇인가?**
  - **답:** 무시 대상이 아닌 untracked 파일도 아카이브에 포함된다. 따라서 통과해도 HEAD 커밋만으로 완전하다는 사실은 증명되지 않으며, 별도의 깨끗한 작업 트리 검사가 필요하다.
- **자격증명을 `unset`하는 이유는 무엇인가?**
  - **답:** 셸에서 물려받은 상태가 검사를 오염시키는 일을 막고, 미리 준비된 모드의 기동이 비밀에 의존하지 않음을 증명한다. 해당 모드는 별도로 강제하므로 자격증명 제거가 모드를 선택하는 것은 아니다.
- **게이트를 싼 것부터 도는 이유는 무엇인가?**
  - **답:** 빠른 의존성·린트·테스트 실패가 오래 걸리는 이미지 빌드 전에 실행을 중단하게 하기 위해서다. 검증 결과는 같게 유지하면서 피드백을 앞당기고 낭비를 줄인다.
- **`trap`이 지우는 범위를 제한해야 하는 이유는 무엇인가?**
  - **답:** 정리는 성공·실패·중단 때 자동 실행되므로 범위가 넓으면 검사 전에 존재하던 컨테이너·이미지·디렉터리까지 지울 수 있다. 이 실행이 만든 명시적 이름의 자원과 검증된 임시 경로만 제거해야 한다.

---

[← 이전: 컨테이너](03-container.md) · [모듈 개요](../03-build.md)
