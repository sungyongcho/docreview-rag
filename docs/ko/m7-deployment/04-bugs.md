# M7 버그

다음 실패는 실행 가능한 검사로 확인할 수 있는 좁은 범위의 릴리스 회귀입니다.

## B01 — 환경 키가 유료 모드를 자동으로 활성화함

**증상:** `OPENAI_API_KEY`를 설정하면 미리 준비된 모드 실행이 공급자 기반 실행으로 바뀝니다.

**근본 원인:** 공급자 선택 로직이 자격 증명의 존재를 동의로 취급합니다.

**수정:** `DOCREVIEW_MODE=runtime`과 서버 측 키를 모두 요구합니다. 기본적으로 미리 준비된 모드가 우선합니다.

```bash
uv run pytest -o addopts="" tests/release/test_01_config.py -k "operator_key" -q
```

## B02 — 공개 브라우저가 비밀 값 입력 폼이 됨

**증상:** 비밀번호 텍스트 상자가 방문자의 키를 Gradio 상태를 통해 전송합니다.

**근본 원인:** "사용자 키 사용"을 운영자가 소유하는 서버 구성이 아니라 브라우저 기능으로 해석했습니다.

**수정:** 키 컴포넌트를 노출하지 마십시오. 명시적으로 승인받은 후에만 선택적 Space 비밀 값이나 일시적인 로컬 환경 값을 구성하십시오.

```bash
rg -n "api.?key|password|secret" app/demo.py app/release deploy/huggingface
```

## B03 — 인프로세스 제한기 하나를 분산 보호 수단으로 설명함

**증상:** 다중 워커 배포가 구성된 한도를 워커마다 한 번씩 허용합니다.

**근본 원인:** 프로세스 로컬 카운터에는 공유 상태가 없습니다.

**수정:** 워커 하나로 고정하고 LRU 제한기를 단일 인스턴스 보호 수단으로 설명하십시오. 복제본을 추가하기 전에 공유 외부 제한기를 추가하십시오.

```bash
rg -n -- "--workers|single_process|single-instance" deploy/huggingface app/release docs/en/m7-deployment docs/ko/m7-deployment
```

## B04 — 전달된 주소를 기본적으로 신뢰함

**증상:** 호출자가 `X-Forwarded-For` 값을 바꾸어 클라이언트별 제한을 회피합니다.

**근본 원인:** 신뢰할 수 있는 역방향 프록시 경계 없이 프록시 헤더를 받아들입니다.

**수정:** 기본적으로 직접 연결한 피어를 사용하고 명시적으로 신뢰하는 환경에서만 전달된 주소 파싱을 활성화하십시오.

```bash
uv run pytest -o addopts="" tests/release/test_03_guards.py -k "forwarded" -q
```

## B05 — 가드 응답이 보안 헤더를 우회함

**증상:** 성공한 API 응답에는 보안 헤더가 있지만 읽기 전용 403 또는 요청 제한 429 응답에는 없습니다.

**근본 원인:** 일찍 반환하는 가드 안쪽에 헤더 미들웨어를 등록했습니다.

**수정:** 헤더 계층을 마지막에 등록하여 가드를 감싸고 두 이른 반환 경로를 모두 단언하십시오.

```bash
uv run pytest -o addopts="" tests/release/test_03_guards.py -k "headers or ingestion" -q
```

## B06 — 서버 키가 로그 또는 영속화된 트레이스에 도달함

**증상:** 예외 텍스트, Uvicorn 출력 또는 실행 행에 자격 증명 값이 포함됩니다.

**근본 원인:** 마스킹 문맥 없이 키를 공급자 생성 이후까지 전달했습니다.

**수정:** 키를 `SecretStr`로 유지하고 그 값은 공급자와 persistence/log 마스킹에만 전달하며, 공급자의 원격 저장을 끄고 불리언 값만 공개적으로 노출하십시오.

```bash
uv run pytest -o addopts="" tests/release -k "secret or redacted or runtime_composition" -q
```

## B07 — 공개 수집이 릴리스 데이터베이스를 변경함

**증상:** 익명 트래픽이 `/ingest`를 호출할 수 있습니다.

**근본 원인:** 로컬 전체 시스템 API를 배포 정책 계층 없이 노출했습니다.

**수정:** 운영자가 통제된 환경에서 수집을 명시적으로 활성화하지 않는 한 서비스 실행 전에 타입이 지정된 읽기 전용 403 응답을 반환하십시오.

```bash
uv run pytest -o addopts="" tests/release -k "ingest" -q
```

## B08 — Space 메타데이터를 게시로 오인함

**증상:** 유효한 YAML 템플릿이 있다는 이유로 포트폴리오 문구가 "배포됨"이라고 말합니다.

**근본 원인:** 구성 준비 상태와 외부 계정 변경을 혼동했습니다.

**수정:** "배포 준비"라고 표현하고 Space, 푸시 또는 외부 리소스를 생성하지 않았다고 기록하십시오.

```bash
rg -n "deployment-ready|not published|external" README.md docs/en/m7-deployment docs/ko/m7-deployment deploy/huggingface
```

## B09 — 클린 아카이브가 로컬 코퍼스 또는 자격 증명을 몰래 복사함

**증상:** `.env`, `.venv` 또는 무시된 SEC HTML을 복사했기 때문에 클린 검증이 성공합니다.

**근본 원인:** Git에서 소스를 선택하지 않고 재귀 파일 시스템 복사를 사용했습니다.

**수정:** 추적되는 의도적인 미추적 소스에서 null로 구분된 목록을 만들고 무시 규칙을 준수하며, 클린 아카이브에서는 자체 완결적인 스위트만 실행하십시오.

```bash
scripts/verify_clean_checkout.sh
```

## B10 — 비루트 Space 사용자가 가상 환경을 만들 수 없음

**증상:** 이미지가 잠금 동기화 중 `Permission denied`로 실패하며 대상은 `/home/user/app/.venv`입니다.

**근본 원인:** 빌드가 UID 1000 상태로 전환될 때 `WORKDIR`는 존재하지만 계속 root 소유입니다.

**수정:** `USER user` 전에 정확한 애플리케이션 디렉터리를 만들고 소유권을 변경한 다음 해당 사용자로 잠금 동기화를 수행하십시오.

```bash
docker build --file deploy/huggingface/Dockerfile --tag docreview-m7-space:local .
```
