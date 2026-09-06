# 구현 문서 지도

이 문서는 `zero` 학습 브랜치의 완전한 한국어 튜토리얼 시작점이다. 마일스톤 번호는 책임, 코드 경계, 테스트, 6종 튜토리얼과 일대일로 대응한다. 문서는 완성된 참조 코드를 구현 목표로 보존하며, 현재 진행 상태를 주장하지 않는다. 같은 경로를 영어로 읽으려면 [영어판](../en/00-README.md)을 사용한다.

| 단계 | 책임 | 코드 | 테스트 | 문서 |
|---|---|---|---|---|
| M1.1 | 10-K HTML → Item 섹션 | `parser.py`, `xref.py` | `tests/ingestion/test_01_*`~`test_08_*` | [파서](m1-1-parser/00-README.md) |
| M1.2 | HTML 표 → 마크다운 | `tables.py` | `tests/ingestion/test_09_tables.py` | [표](m1-2-tables/00-README.md) |
| M1.3 | 섹션 → 출처 안정 청크 | `chunk.py` | `tests/chunk/` | [청킹](m1-3-chunk/00-README.md) |
| M1.4 | 청크 → 멱등 DB 업서트 | `seed.py`, DB 모델 | `tests/db/` | [데이터베이스 시드](m1-4-seed/00-README.md) |
| M2 | 정확 벡터 + PostgreSQL 전문 검색 → RRF | `app/retrieval/` | `tests/retrieval/` | [검색](m2-retrieval/00-README.md) |
| M3 | 구간 골든셋 → 지표, 회귀, 어블레이션 | `app/evals/` | `tests/evals/` | [평가](m3-evals/00-README.md) |
| M4 | 검색 → 평가 → 검사 → 보고 | `app/workflow/` | `tests/workflow/` | [워크플로](m4-workflow/00-README.md) |
| M5 | 타입 기반 CLI, API, 런타임, 컨테이너 | `app/api/`, `app/cli.py` | `tests/api/` | [서빙](m5-serving/00-README.md) |
| M6 | 증거 우선 포트폴리오 데모 | `app/demo.py` | `tests/demo/` | [데모](m6-demo/00-README.md) |
| M7 | 보호된 릴리스 패키지와 클린 아카이브 증명 | `app/release/`, `deploy/` | `tests/release/` | [배포](m7-deployment/00-README.md) |
| M8.1 | 같은 불변 스팬 위의 한국어 쌍둥이 스위트 | `bilingual.py`, `retrieval_ko.json` | `tests/crosslingual/test_01_*` | [교차 언어](m8-crosslingual/00-README.md) |
| M8.2 | 수정 이전의 언어별 측정 | `crosslingual.py` | `tests/crosslingual/test_02_*` | [교차 언어](m8-crosslingual/03-build.md) |
| M8.3 | 실험군으로 들어가는 감지, 라우팅, 번역 | `language.py`, `translate.py` | `tests/crosslingual/test_03_*`~`test_04_*` | [교차 언어](m8-crosslingual/03-build.md) |
| M8.4 | ko/en 동등성 비율과 그 바닥, 그리고 게이트 | `parity.py` | `tests/crosslingual/test_05_*` | [검증](m8-crosslingual/05-verify.md) |
| M9 | 근거 게이트 인용을 가진 툴 호출 에이전트 | `app/agent/` | `tests/agent/` | [에이전트](m9-agent/00-README.md) |

문서가 존재한다는 사실은 구현 완료를 뜻하지 않는다. 현재 상태는 [`docs/project/learning.toml`](../project/learning.toml), 세부 순서는 [`module-plan.md`](../project/module-plan.md)를 따른다.

[통합 문서 허브](../00-README.md)에서 현재 튜토리얼, 정렬된 구현 순서, 역사적 계획 근거, 포트폴리오 마감 작업 중 필요한 경로를 선택한다. [`docs/project/module-plan.md`](../project/module-plan.md)는 세부 의존성 순서만 담당한다.

포트폴리오 공개 문서는 [아키텍처](architecture.md), [평가](eval-report.md), [실패 분석](failure-analysis.md)이다.

## 현재 시작점

보존된 참조 문서판은 `docs/en/**`와 `docs/ko/**` 아래에 하나의 공통 상대 경로 인벤터리를 고정한다. 영어판은 구조 기준본이고 한국어판은 같은 실행 리터럴, 증거, 문서 목적지를 유지한 자연스러운 번역본이다. `docs/project/**`는 공통 경로와 계획 기록을 보관하고, `docs/00-README.md`는 제3의 현지화 복사본을 만들지 않고 문서판을 선택한다.

두 문서판을 완료로 판단하기 전에 다음 게이트를 실행한다.

```bash
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
uv run python scripts/check_doc_parity.py inventory
uv run python scripts/check_doc_parity.py parity
uv run python scripts/check_doc_parity.py language
```

마지막으로 기록된 전체 스위트 기준선은 2026-08-13의 `718 passed, 1 skipped`다. 건너뛴 하나는 명시적으로 선택 실행하는 실제 OpenAI 워크플로 테스트이며, 일반 검증은 유료 공급자를 호출하지 않는다. 이 수치는 채워진 저장소 전체를 다시 실행한 뒤에만 갱신한다.

## 문서 계약

- 모든 구현 마일스톤은 책임별 `00`부터 `05`까지의 튜토리얼 세트를 유지한다.
- 각 `03-build.md`는 의존성 순서에 따라 선행 조건, 정식 파일, 명령, 기대 결과, 중단 조건, 디버깅 검사를 설명한다.
- 코드 펜스, 명령, 경로, 인라인 코드, 소스 마커, 체크포인트 ID, 실측값, 표 구조는 번역 가능한 산문이 아니라 보호된 기술 리터럴이다. 기존 M1.1 소스는 로컬 파일과 비교하고, 미래 소스는 고정된 `reference_revision`과 비교하되 `zero/app/` 아래에는 생성하지 않는다.
- 로컬 링크는 번역된 제목 조각을 사용할 수 있지만 두 문서판에서 같은 논리 문서로 연결돼야 한다.
- [`localization-manifest.json`](../localization-manifest.json)은 인벤터리를 고정하고, [`localization.toml`](../localization.toml)은 기준 언어와 보호 필드를 정의한다.
- `scripts/`는 제품의 일부다. 테스트 스위트가 생성된 완성 파일 절을 검증하고 문서 게이트를 직접 호출한다.

## 이중 언어 검증

인벤터리 게이트는 누락되거나 추가된 파일을 거부한다. 동등성 게이트는 영어 기준본과 번역에 영향받지 않는 마크다운 구조를 비교하고, 번역된 제목 조각의 문자열 일치를 요구하는 대신 링크가 가리키는 문서의 정체성을 확인한다. 언어 게이트는 보호되지 않은 영어 산문의 한글, 한국어판에 남은 의심스러운 영어 문단, 일관되지 않은 한국어 용어를 거부한다. 링크·소스 코드 게이트는 모든 로컬 대상, 앵커, 소스 연동 코드가 실제로 존재하며 최신인지 별도로 증명한다.

```bash
make docs
```
