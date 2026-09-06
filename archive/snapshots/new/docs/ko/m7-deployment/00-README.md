# M7 개요 — 배포 준비 릴리스

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

M7은 외부 서비스가 게시되었다고 주장하지 않으면서 검증된 로컬 포트폴리오를 범위가 제한된 배포 산출물로 전환합니다. 문서에 표시되는 경로는 **M7.1 릴리스 가드 -> M7.2 Hugging Face/container 자산 -> M7.3 클린 아카이브 릴리스 증명**입니다.

## 현재 마일스톤 상태

| 단계 | 결과 | 상태 |
|---|---|---|
| M7.1 | 미리 준비된 모드를 기본으로 하는 정책, 범위가 제한된 요청 제한, 서버 전용 선택적 공급자 키, 비용 상한, 보안 헤더 | 구현 완료. 집중 release/demo/API 스위트에서 67 개 통과 측정 |
| M7.2 | Docker Space 메타데이터, 비루트 이미지, 상태 확인, 강화된 Compose 애플리케이션 | 구현 완료. 로컬 컨테이너 증거는 M7.3 단계에서 기록 |
| M7.3 | 전체 오프라인 회귀 테스트와 임시 클린 아카이브 sync/build/smoke | 완료. 718 개 통과, 1 개 건너뜀 및 클린 아카이브 증명 통과 |

이 튜토리얼의 어떤 명령도 Hugging Face Space를 만들거나 저장소 또는 이미지를 푸시하거나 공급자 요청을 수행하지 않습니다.

## 릴리스 계약

`canned by default -> explicit runtime opt-in -> bounded server work -> non-secret evidence`

- `DOCREVIEW_MODE=canned`은 환경에 `OPENAI_API_KEY`가 있더라도 기본값입니다.
- 공개 UI에는 키 필드가 없습니다. 선택적 OpenAI 액세스는 운영자가 제공하는 서버 비밀 값을 사용하며 `DOCREVIEW_MODE=runtime`일 때만 활성화됩니다.
- 공급자 작업은 입력 토큰 12,000 개, 출력 토큰 600 개, 워크플로당 예상 비용 `$0.01`로 제한됩니다. 이러한 상한은 비용 지출을 허가하지 않습니다.
- POST에 준하는 작업은 범위가 제한된 각 인프로세스 클라이언트 키에 대해 이동식 1분당 요청 10 건, 이동식 1일당 요청 100 건으로 제한됩니다. 이는 워커 하나에는 적합하지만 복제본에는 적합하지 않습니다.
- 공개 수집은 비활성화되어 있습니다. 응답에는 이른 403 및 429 응답을 포함해 no-store, no-sniff, 리퍼러, 권한, 교차 출처 헤더가 포함됩니다.
- 기본 미리 준비된 픽스처는 데이터베이스나 공급자를 전혀 호출하지 않습니다.

## 문서 여섯 개의 진행 경로

1. [개요](00-README.md)는 배포 경계와 상태를 설명합니다. 2. [측정 결과](01-findings.md)는 측정된 동작과 남은 한계를 기록합니다. 3. [명세](02-spec.md)는 릴리스 보안 및 정직성 요구 사항을 확정합니다. 4. [빌드 가이드](03-build.md)는 M7.1 단계부터 M7.3 단계까지 명시적인 순서로 진행합니다. 5. [버그](04-bugs.md)는 구체적인 배포 함정과 회귀를 설명합니다. 6. [검증](05-verify.md)은 정확한 로컬 및 클린 아카이브 게이트를 기록합니다.

## 로컬 미리 준비된 모드 실행

```bash
uv sync --locked --extra demo
DOCREVIEW_MODE=canned uv run --extra demo uvicorn app.release.space:app --host 127.0.0.1 --port 7860 --workers 1 --log-level warning
```

다른 터미널에서 다음을 실행합니다.

```bash
curl --fail --silent --show-error http://127.0.0.1:7860/health
curl --fail --silent --show-error http://127.0.0.1:7860/release
```

예상 표기는 `mode=canned`과 `openai_enabled=false`입니다. 브라우저 랜딩 페이지는 실제 SEC 검색이나 모델 기반 리뷰가 아닌 **미리 준비된 픽스처**입니다.

## 의도적으로 실행하지 않은 외부 작업

`deploy/huggingface/` 아래의 메타데이터 템플릿은 공식 [Docker Spaces 메타데이터 및 포트 규칙](https://huggingface.co/docs/hub/en/spaces-sdks-docker)을 따릅니다. Space 생성, 설정 페이지에서 비밀 값 추가, 준비된 파일 푸시는 모두 명시적으로 승인된 사용자 계정을 요구하며 이 릴리스 증명의 범위를 벗어납니다.
