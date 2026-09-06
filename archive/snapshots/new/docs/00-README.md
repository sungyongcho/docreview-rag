# Project Documentation Hub / 프로젝트 문서 허브

이 파일이 프로젝트 문서의 **유일한 시작점**이다. 구현을 다시 따라가거나, 설계 근거를 찾거나, 포트폴리오를 마감할 때 아래 경로만 선택하면 된다.

> `zero` branch progress: M1.1 is complete and M1.2 is next. Complete code blocks in later tutorials are retained implementation targets, not claims that those modules already exist.

- [Zero branch learning baseline / zero 브랜치 학습 기준선](project/learning-baseline.md)

## 1. Current documentation / 현재 문서

- [English documentation](en/00-README.md)
- [한국어 문서](ko/00-README.md)
- [Detailed module route / 상세 모듈 순서](project/module-plan.md)
- Portfolio evidence: [architecture](en/architecture.md), [evaluation](en/eval-report.md), [failure analysis](en/failure-analysis.md)

`docs/en/**`와 `docs/ko/**`는 전체 튜토리얼을 보존한다. M1.1 소스 블록은 현재 코드와, 미래 소스 블록은 고정된 `reference_revision` 참조와 엄격히 대조한다. 문서 검증은 미래 파일을 `zero/app/`에 생성하지 않는다. [`docs/project/module-plan.md`](project/module-plan.md)는 세부 의존성 순서만 담당한다.

## 2. Planning evidence / 계획 근거

[`docs/project/planning/`](project/planning/README.md)은 구현 전에 정리한 요구사항, 42 과제 분석, 설계 결정, 포트폴리오 서사, 초기 빌드 계획의 **역사적 기록**이다. 현재 구현 상태나 실행 명령의 기준으로 사용하지 않는다.

정보가 충돌하면 다음 우선순위를 적용한다.

1. 코드와 테스트 2. `docs/en/**` 또는 `docs/ko/**` 3. `docs/project/module-plan.md` 4. `docs/project/planning/**`

## 3. Portfolio closeout / 포트폴리오 마감

1. [골든셋 검수](ko/m3-evals/01-findings.md) 2. [실제 로컬 데모와 스크린샷](ko/m6-demo/05-verify.md) 3. [릴리스 검증](ko/m7-deployment/05-verify.md) 4. [Hugging Face Space 메타데이터](../deploy/huggingface/README.md) 5. [실제 OpenAI 스모크 테스트 — 선택](ko/m4-workflow/05-verify.md#6-선택적-실제-공급자-게이트)

`deploy/huggingface/README.md`는 배포 자산과 함께 있어야 하므로 이동하지 않는다. 이 허브에서 진입점만 제공한다.

## 4. Shared verification / 공통 검증

현지화 인벤터리는 [`localization-manifest.json`](localization-manifest.json), 보호 규칙은 [`localization.toml`](localization.toml)이 담당한다. 전체 문서 검증은 저장소 루트에서 `make docs`로 실행한다.
