# 운영 핸드북 — 이 저장소를 다루는 방법

이 문서는 저장소의 운영 규칙 전부를 한 곳에 모은 참조다. 학습 중 지켜야 할 계약(코드 품질, 튜토리얼 작성)은 [learning-baseline.md](learning-baseline.md)에 있고, 진행 경로와 상태는 [module-plan.md](module-plan.md)에 있다. 이 문서는 "무엇이 어디에 속하고, 무엇을 바꿀 때 어떤 절차를 밟는가"만 다룬다.

## 1. 브랜치와 반입 모델

- `new`는 M1–M9 전부가 구현된 **완성 참조 브랜치**다. 캐주얼하게 수정하지 않는다. 수정이 허용되는 경우는 §3의 레시피를 따르는 의도적 변경뿐이다.
- `zero`는 학습 브랜치다. `new`에서 **문서·테스트·핀만** 반입하고, `app/` 코드는 절대 반입하지 않는다 — 구현은 튜토리얼을 따라 직접 작성한다.
- **테스트는 반입된 동결 계약이다. 구현이 테스트를 만족시키며, 그 역방향은 없다.** 테스트를 구현에 맞춰 고치는 것은 채점지를 고쳐 점수를 내는 것과 같다. 테스트 계약 자체가 틀렸다고 판단되면 §3-(c)대로 `new` 원본에서 고친 뒤 반입한다.
- **skip은 통과가 아니다.** 하니스는 미구현 심볼을 `not implemented yet`으로 skip 처리하고, import가 실패한 모듈도 조용히 전부 skip으로 바꾼다. 전부 skip인 상태는 "아직 채점이 시작되지 않음"이다. 튜토리얼의 집중 테스트가 해당 문서 범위만으로 통과할 수 없을 때는 문서가 정확한 통과 시점을 명시한다 — 그 시점 전의 skip은 정상이다.
- `make test`는 `pyproject.toml`의 `testpaths`(M1.1 범위 + 문서 게이트)만 돈다. 이후 모듈은 각 튜토리얼의 집중 테스트 명령 또는 `make next`로 실행한다.

## 2. 소유권 지도

| 대상 | 소유 | 규칙 |
|---|---|---|
| `docs/en/**`, `docs/ko/**` | `new` | 원본은 `new`. 상태-무관 수정은 `zero`에 선반영할 수 있으나 이후 `new`에 체리픽해 수렴시킨다. 코드 블록은 어느 브랜치에서도 수기 수정 금지 (§3-(b)) |
| `tests/**` | `new` | 동결 계약. 변경은 §3-(c) 파이프라인으로만 |
| `docs/project/learning.toml` `[learning]` | `zero` | 진행 상태의 기계값. 체크포인트마다 갱신 |
| `docs/project/learning.toml`·`tutorial-code.toml`의 핀 | 파이프라인 | `reference_revision`과 `[reference] revision`은 **항상 두 파일이 함께** §3-(b) 절차로만 이동 |
| `docs/project/module-plan.md` Status 칼럼 | `zero` | 사람용 진행 뷰의 단일 원본. `new`에서 반입할 때 행 추가만 병합하고 Status 셀은 `zero` 값을 보존 |
| `docs/project/tutorial-code.toml` 모듈·그룹 목록 | `new` | 새 모듈은 `new`에서 등록 후 반입 |
| `README.md`, `docs/00-README.md`, `docs/project/*.md`, `docs/optimize/**` | `zero` | 브랜치별 자유 (루트 README는 브랜치마다 다른 파일이다) |
| `app/**` (zero) | 학습자 | 튜토리얼 구현물. 문서와 바이트 대조되지 않으며 집중 테스트가 동작을 검증 |

## 3. 변경 레시피

### (a) 상태-무관 문서 수정 (오타, 설명 보강, 모순 해소)

- `zero`에서 수정한다 — 단, 코드 펜스 내용과 `<!-- src: -->`/`<!-- file: -->` 마커는 건드리지 않는다.
- `docs/en`·`docs/ko` 파일이면 두 로케일을 같은 구조(제목 단계, 표 모양, 인라인 코드 순서, 링크 대상)로 함께 고친다.
- `make docs` 통과 확인 후 한 줄 컨벤셔널 커밋. 이후 `new`에 같은 커밋을 체리픽해 두 브랜치를 수렴시킨다.

### (b) 정식 코드 또는 문서에 보일 코드 주석 변경

문서의 코드 블록은 핀 리비전과 바이트 단위로 대조되므로 **절대 문서 쪽에서 고치지 않는다.** 튜토리얼에 보이길 원하는 주석·수정은 소스에 넣는다.

- `new`에서 소스(`app/**`, `tests/**`)를 수정하고 게이트 통과 후 커밋한다.
- `learning.toml`의 `reference_revision`과 `tutorial-code.toml`의 `revision`을 **둘 다** 새 커밋으로 범프한다.
- `uv run python scripts/sync_tutorial_code.py`로 각 `03-build.md`의 완성 파일 구간을 재생성하고, `src:` 마커 발췌가 바뀌었으면 해당 블록을 핀 상태로 재주입한다.
- `new`에서 `make docs` 통과 후 문서·핀 커밋.
- `zero`에서 해당 파일들만 checkout으로 반입한다 (문서, 테스트, 두 TOML; `app/` 제외) → `make docs` → 커밋.

### (c) 테스트 계약 수정

레시피 (b)와 동일하다 — 계약의 원본은 `new`의 `tests/**`이므로 거기서 고치고, 핀 범프와 함께 `zero`로 반입한다. `zero`의 테스트 파일을 직접 고치지 않는다.

## 4. 문서 기계장치

2026-08-27 결정으로 패리티·코드 대조·동기화 장치(`check_doc_parity.py`, `check_doc_code.py`, `sync_tutorial_code.py`와 그 테스트, `localization.toml`/`localization-manifest.json`)는 zero에서 제거했다. `new`는 레거시 참조 브랜치로 동결한다. 남은 것:

| 도구 | 역할 |
|---|---|
| `scripts/format_docs.py` | 문단 리플로우 규칙. `make docs`와 `make test`의 `tests/test_doc_format.py`가 검사 |
| `scripts/next_milestone.py` | `learning.toml`의 `next_milestone`을 읽어 `tutorial-code.toml`의 해당 그룹 명령을 실행 (`make next`) |

문서 안의 `<!-- src: … -->` 마커는 제거된 대조 장치의 흔적으로, 이제 검증되지 않는 참고 표기일 뿐이다. 문서에 새 개념 파일이 등장하면 첫 사용 전에 출처(어느 모듈이 만들었고 왜 존재하는지)를 소개한다.

## 5. 체크포인트 완료 체크리스트

집중 테스트가 초록이 된 순간 다음을 순서대로 수행한다.

- [learning.toml](learning.toml)의 `completed_through`·`next_milestone`을 갱신한다.
- [module-plan.md](module-plan.md)에서 해당 Status 셀 1칸을 갱신한다 (모듈 완료 시 상위 표까지).
- 모듈이 끝났으면 `pyproject.toml` `[tool.pyright]` `exclude`에서 해당 테스트 디렉터리를 제거한다 (예: `tests/evals`는 M3.4 완료 시). 제거 후 basedpyright 0 에러를 확인한다.
- 모듈 단위 최적화·리팩터링 검수를 돌리고 [../optimize/instruction.md](../optimize/instruction.md) 형식으로 기록한다. docstring은 [../optimize/docstring.md](../optimize/docstring.md) 기준.
- 게이트: `make lint && make docs && make test && make typecheck` + 해당 모듈 집중 스위트.

## 6. 알려진 이연 항목

- `docs/en|ko/m2-retrieval/tutorial/08,09`는 Protocol 패턴 기준으로 서술돼 있으나 실제 코드는 R1-1의 클로저 어댑터다. 차이는 [../optimize/refactor.md](../optimize/refactor.md) R1-1에 기록돼 있고, 문서 정합은 별도 결정으로 보류 중이다.
- `# pyright: ignore[reportCallIssue]` 3건(`tests/retrieval/test_02_embeddings.py`, `test_07_service.py`)은 pydantic-settings 합성 시그니처의 확인된 오탐으로 자리별 억제를 유지한다.
- DART(한국 공시) 코퍼스는 R2 확장으로 이연. M8이 만든 질의 경로·쌍둥이 골든셋·동등성 게이트는 코퍼스에 독립적이며, 확장 여지는 [../en/m8-crosslingual/01-findings.md](../en/m8-crosslingual/01-findings.md)와 [planning/03-scope-and-narrative.md](planning/03-scope-and-narrative.md) §8에 기록돼 있다.

## 7. 세션 시작 — 사람과 LLM 공용 진입점

- [README.md](../../README.md) → [docs/00-README.md](../00-README.md) → 이 핸드북 → [learning-baseline.md](learning-baseline.md) 순서로 읽는다. 코드를 쓰기 전에 learning-baseline의 **코드 품질 계약**을 반드시 적용한다.
- 현재 위치는 [learning.toml](learning.toml)이 기계값, [module-plan.md](module-plan.md) Status 칼럼이 사람용 뷰다. 그 밖의 어떤 문서도 진행 상태를 주장하지 않는다.
- 다음 할 일은 `make next` — `learning.toml`의 `next_milestone`에 등록된 집중 테스트를 실행한다.
- 절대 규칙 넷: 테스트가 아니라 구현을 고친다 · `new`의 코드는 §3 파이프라인으로만 바꾼다 · 문서 코드 블록은 수기 수정하지 않는다 · 타입 에러 0이 완료 조건이다.
