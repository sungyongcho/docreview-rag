# Zero Branch Learning Baseline / zero 브랜치 학습 기준선

`zero` is the hands-on reconstruction branch. `new` remains the completed reference branch.

`zero`는 직접 재구현하는 학습 브랜치이고, `new`는 완성된 참조 브랜치다.

## Current progress / 현재 진행 상태

| Item | State |
|---|---|
| Completed implementation | `M1.1` |
| Next implementation | `M1.2` |
| First file to create | `app/ingestion/tables.py` |
| Learner filename suffix | None; always use the canonical path |

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

## Start M1.2 / M1.2 시작

Read the Korean or English build tutorial, implement the canonical file at the documented path, then run the focused tests after each checkpoint. Compare against the reference baseline once a checkpoint is done.

```bash
uv sync --locked --group dev
uv run pytest
uv run pytest tests/ingestion/test_09_tables.py -v
```

- [한국어 M1.2 튜토리얼](../ko/m1-2-tables/00-README.md)
- [English M1.2 tutorial](../en/m1-2-tables/00-README.md)

## What is intentionally retained / 의도적으로 남긴 것

- all bilingual tutorials and their complete code blocks;
- future test harnesses, golden fixtures, corpus inputs, and measured reference artifacts;
- uv, Docker, deployment, documentation, and repository settings;
- only the M1.1 runtime implementation under `app/`.

Future tests and deployment assets are learning inputs. Their presence does not mark a milestone as complete.

`make docs` checks generated complete-file sections and source-linked code blocks against the pinned completed reference. It does not require `zero`'s independently rebuilt implementation to be byte-for-byte identical; focused tests enforce behavior. The check never implements a future milestone on `zero`.

`make docs`는 생성된 완성 파일 구간과 소스 연결 코드 블록을 고정된 완성 참조와 대조한다. 독립적으로 재구현한 `zero` 코드가 바이트 단위로 같을 필요는 없으며, 동작은 집중 테스트가 검증한다. 이 검사는 `zero`에 미래 마일스톤을 구현하지 않는다.
