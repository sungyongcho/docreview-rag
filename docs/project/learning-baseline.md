# Zero Branch Learning Baseline / zero 브랜치 학습 기준선

`zero` is the hands-on reconstruction branch. `new` remains the completed reference branch. The branch and import model, change recipes, and documentation machinery are in the [operations handbook](handbook.md); this file holds the contracts.

`zero`는 직접 재구현하는 학습 브랜치이고, `new`는 완성된 참조 브랜치다. 브랜치·반입 모델과 변경 절차, 문서 기계장치는 [운영 핸드북](handbook.md)에 있으며, 이 문서는 계약만 담는다.

## Current progress / 현재 진행 상태

진행 상태는 [learning.toml](learning.toml)(기계값)과 [module-plan.md](module-plan.md)의 Status 칼럼(사람용 뷰)만이 원본이다. 이 문서를 포함해 다른 어떤 문서도 진행 상태를 주장하지 않는다. 학습자 접미사 파일은 없다 — 항상 정식 경로를 사용한다.

The complete tutorial code remains under `docs/en/**` and `docs/ko/**`. Each `03-build.md` carries a reference baseline of the complete canonical files, verified against the pinned `reference_revision` implementation. That verification does not create future files under `zero/app/`.

전체 튜토리얼 코드는 `docs/en/**`와 `docs/ko/**`에 남아 있다. 각 `03-build.md`에는 고정된 `reference_revision` 구현과 대조한 완성 기준본이 정식 파일 전체로 들어 있다. 이 검증은 `zero/app/` 아래에 미래 모듈 파일을 생성하지 않는다.

## Safe branch switching / 안전한 브랜치 전환

Commit or stash work before switching branches.

```bash
git status --short
git switch new
git switch zero
```

일반 학습에서는 `new`로 전환할 필요가 없다. `zero`의 빌드 문서를 읽고 정식 경로를 직접 작성한다. 브랜치 전환은 완성 프로젝트를 별도로 조사할 때만 사용한다.

## Start the next milestone / 다음 마일스톤 시작

Read the build tutorial for the next checkpoint in [module-plan.md](module-plan.md), implement the canonical file at the documented path, then run the focused tests after each checkpoint. Compare against the reference baseline once a checkpoint is done.

```bash
uv sync --locked --group dev
uv run pytest
make next
```

`make next`는 [learning.toml](learning.toml)의 `next_milestone`에 등록된 집중 테스트를 실행한다. 체크포인트가 끝나면 핸드북의 [완료 체크리스트](handbook.md#5-체크포인트-완료-체크리스트)를 수행한다.

## What is intentionally retained / 의도적으로 남긴 것

- all bilingual tutorials and their complete code blocks;
- future test harnesses, golden fixtures, corpus inputs, and measured reference artifacts;
- uv, Docker, deployment, documentation, and repository settings;
- only the M1.1 runtime implementation under `app/`.

Future tests and deployment assets are learning inputs. Their presence does not mark a milestone as complete.

`make docs` checks generated complete-file sections and source-linked code blocks against the pinned completed reference. It does not require `zero`'s independently rebuilt implementation to be byte-for-byte identical; focused tests enforce behavior. The check never implements a future milestone on `zero`.

`make docs`는 생성된 완성 파일 구간과 소스 연결 코드 블록을 고정된 완성 참조와 대조한다. 독립적으로 재구현한 `zero` 코드가 바이트 단위로 같을 필요는 없으며, 동작은 집중 테스트가 검증한다. 이 검사는 `zero`에 미래 마일스톤을 구현하지 않는다.

## Code quality contract / 코드 품질 계약

모든 코드 생성·수정·리팩터링에 적용한다. 기준은 두 파일이 전부다: lint와 포맷은 루트 `pyproject.toml`의 `[tool.ruff]`, 타입 검사는 같은 파일의 `[tool.pyright]`(`typeCheckingMode = "basic"`, Pylance와 CLI가 공유하는 단일 소스)다. 코드를 쓰기 전에 두 섹션을 기준으로 삼고, 작업을 끝내기 전에 아래 검증이 전부 통과해야 한다 — **타입 에러 0이 완료 조건이다.**

```bash
make lint
make docs
make test
uv run pytest tests/retrieval tests/chunk tests/db -q
uv run --with basedpyright basedpyright app tests scripts
```

`make test`는 `testpaths`(M1.1 범위 + 문서 게이트)만 돌므로 이후 모듈 스위트는 네 번째 명령으로 별도 실행한다. `zero`가 학습 브랜치, `new`는 프로즌 참조 브랜치이며 `new`는 절대 수정하지 않는다.

**행동강령: lint/타입 검사를 통과시키기 위한 `_ClassName`식 끼워 맞추기는 절대 금지.** 어노테이션이 요구된다는 이유로 private Protocol, 래퍼 클래스, 더미 타입을 만들어 붙이지 않는다. 대신 이 순서로 해결한다.

- 먼저 라이브러리가 어노테이션용으로 제공하는 **공개 타입**을 찾는다 (예: SQLAlchemy `SQLColumnExpression`).
- lazy import 경계는 Protocol + `cast` 대신 **typed 클로저**로 감싼다 (예: `app/retrieval/sbert.py`의 `_load`).
- 런타임 검증이 있는 이질 값 딕셔너리는 `dict[str, Any]`로 정직하게 적는다.
- 테스트가 의도적으로 계약을 위반하는 자리만 `cast`로 의도를 표시한다.
- 마지막 수단으로, 서드파티 스텁의 **확인된 오탐**만 자리별 `# pyright: ignore[rule]`로 억제한다. 광역 억제는 금지.

기록 규칙: 크로스모듈 리팩터링은 [refactor.md](../optimize/refactor.md), 체크포인트 최적화는 [instruction.md](../optimize/instruction.md), docstring은 [docstring.md](../optimize/docstring.md)를 따른다. 코드가 바뀌면 해당 최적화 문서의 `[수정코드]` 블록을 실제 소스와 다시 맞춘다.

## Tutorial authoring contract / 튜토리얼 작성 계약

새 체크포인트 튜토리얼은 기존 M2.1~M2.8의 학습 흐름을 기준으로 삼는다. 목표는 완성 코드를 한 번에 보여 주는 것이 아니라, 독자가 실패 원인과 설계 결정을 이해하면서 정식 파일을 단계별로 완성하게 하는 것이다.

- 제목 바로 아래에서 이전 체크포인트가 남긴 문제와 관찰 가능한 실패 증상을 설명한다.
- `**선행 조건:**`에 직전 집중 테스트 명령을 적는다. 이 명령이 통과하지 않으면 다음 단계로 진행하지 않는다.
- `무엇을 작성하고 어디를 직접 구현할까` 표에 정식 경로, 학습 행동, 각 구간에서 얻어야 할 이해를 적는다.
- 각 구현 구간은 **설계 압력 → 학습 행동 → 정식 코드 블록 → 코드에서 볼 것 → 집중 테스트와 결과 해석** 순서로 진행한다. 한 구간의 테스트가 실패하면 다음 구간으로 넘어가지 않는다.
- `학습 행동`은 `구조 작성`, `직접 구현`, `설계 결정 확인`, `경계 변환 검토`, `기존 정의 교체`처럼 독자가 실제로 할 일을 구분한다. 완성 코드를 생각 없이 복사하라는 표현은 쓰지 않는다.
- 제공된 테스트·fixture와 `파일 수정 없음` 블록은 읽기 또는 검산 대상으로 표시한다. 애플리케이션 파일에 입력할 코드와 개념 예제를 혼동하게 만들지 않는다.
- 마지막 `집중 테스트와 테스트가 지키는 계약`에는 실행 명령, 실패시킨 값과 보호되는 계약, 완료 조건, 중단 조건, 첫 디버깅 순서를 기록한다.
- `여기까지 왔을 때 설명할 수 있어야 하는 것`의 모든 답은 앞선 본문에서 굵은 핵심 문장으로 먼저 설명한다. 문서 끝에는 다음 체크포인트 또는 모듈 개요 링크를 둔다.
- 집중 테스트가 해당 문서 범위만으로 통과할 수 없으면 정확한 통과 시점을 본문에 명시한다. `__init__.py`/`__all__` 재수출 단계는 고정된 참조 구현이 요구하는 지점 이상으로 가르치지 않는다.
- 다른 모듈이 만든 산출물(테이블, 데이터 파일, 타입)이 처음 등장하면 사용 전에 출처 — 어느 모듈이 왜 만들었는지 — 를 소개한다.
- 튜토리얼에 보일 코드 주석·수정은 `new`의 소스에 넣고 핀 범프로 재주입한다. 문서의 코드 블록은 수기로 수정하지 않는다 ([핸드북 §3](handbook.md#3-변경-레시피)).
- 테스트 계약의 변경도 `new` 원본에서 수행한 뒤 반입한다. `zero`의 테스트 파일은 직접 고치지 않는다.

산문은 한국어 개발 서적의 독서 흐름을 따른다. 먼저 터미널이나 실행 결과에서 관찰할 수 있는 실패를 보여 주고, 그 원인을 한 문단에 한 주장씩 설명한 뒤 코드로 해결한다. 주어·원인·결과를 생략하지 않으며, 번역투 명사 나열이나 “이것/그것” 같은 모호한 지시어를 피한다. 비유는 실제 코드 관계를 더 빨리 이해하게 할 때만 쓰고, 수식과 전문 용어는 직관을 먼저 설명한 다음 도입한다. 문단을 길게 늘여 권위 있어 보이게 만들지 말고, 독자가 다음 코드 줄을 왜 작성하는지 알 수 있을 만큼만 설명한다.

코드 펜스, 명령, 경로, 식별자, `<!-- src: ... -->` 마커와 제목 단계·표 구조는 문서 게이트가 읽는 계약이다. 한 로케일의 구조를 바꾸면 다른 로케일도 같은 구조로 맞추고, 코드 블록은 영어 주석과 정식 심볼을 유지한다. 완성 파일 부록은 체크포인트를 다 만든 뒤 비교하는 기준본이지, 튜토리얼 시작 시 통째로 작성하는 선행 조건이 아니다.
