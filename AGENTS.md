# AGENTS.md — Product Development Workflow

## Current branch and release policy

- `main` is the stable integration branch, the GitHub default, and the default local checkout.
- `v1` is a frozen legacy archive with one parentless commit. Never modify it or merge it into `main`.
- `v2.0.0` identifies product commit `61cb17b49b0b6bf0745b6fb7cfdd16b67d101731`.
- Use short-lived `<type>/<issue-number>-<description>` branches, such as `feat/<issue-number>-improve-navigation`, `fix/<issue-number>-refresh-readiness`, or `refactor/<issue-number>-simplify-settings`. Resolve the actual GitHub issue number first; never invent one.
- Do not prepend product versions such as `v2/` or `v3/` to ordinary work branches. Use release tags such as `v2.1.0` and `v3.0.0` for versions; creating or moving a tag remains a separately requested release action. Supporting multiple release lines requires an explicit maintenance policy.
- Keep only `main` and `v1` as canonical local branches at rest, tracking their remote counterparts.

## Repository-wide GitHub tracking

This policy applies to the entire repository, on every working branch. GitHub is the
shared work record so humans and agents can discover the purpose, current state,
implementation, verification and delivery of each change without reading a chat.

- Treat requests to implement a feature, fix a bug or address an issue as triggers to
  manage the scoped work through GitHub using `gh`, even without an explicit skill
  invocation. Requests such as "트래킹 업데이트", "이슈 관리", "PR 정리" or equivalent
  action requests also trigger tracking. Questions, explanations and read-only reviews
  authorize inspection only; a keyword in quoted material is not an action request.
- Triage incoming requests and user-provided screenshot observations first. Update the
  related issue when the outcome overlaps; create a new issue for a distinct outcome.
  Record observed behavior, desired behavior, affected surface and acceptance checks.
  An intake-only or status request does not start implementation. Follow the user's
  actual work instruction before dispatching implementation.
- The user authorizes scoped GitHub tracking and, when implementation/delivery is
  requested, the associated branch, commit, ordinary push, PR, verified squash merge,
  completed-branch retirement and actual local `main` synchronization. Render concrete
  scope/messages/evidence, but do not repeatedly request approval for that same flow.
  Dependabot authorization is defined separately below. Destructive user-data actions,
  credentials, deployment, repository protection changes and history rewriting remain
  separate boundaries.
- Use English Conventional Commit headers for commits and PR titles:
  `<type>(<scope>): <concise outcome>`. Prefer the same format for actionable issue
  titles when type/scope are clear. Do not rename unrelated historical items merely
  for consistency. Group related issues into one coherent PR when shared files or
  integration make that appropriate; link every actual issue and close only completed
  scope, leaving deferred work open.
- Parallelize only independently owned issue-sized work, with an explicit file map
  and at most two workers plus a coordinator. Shared contracts, Git operations and
  final integration belong to the coordinator. Reuse passing evidence; do not run
  duplicate full suites or mutate the same database concurrently.
- Fetch before work, before publishing and before merging: a user, another agent,
  Dependabot or the GitHub web UI can advance the remote at any time. Synchronize only
  after checking divergence, foreign changes and affected verification. Prefer
  fast-forward updates; never use automatic stash/reset/rebase to conceal conflicts.
- Before implementation, resolve the repository from its remote and check `gh` access.
  Search only related issues and PRs; reuse the matching work item instead of creating
  duplicates. If absent, create an English issue with the problem/outcome, scope and
  acceptance checks. Obtain its actual number before naming the implementation branch.
  Split into linked issues only when the work has independently verifiable outcomes.
- Before a commit, reconcile the issue scope and checklist with the actual diff and
  completed checks. Record concrete blockers and remaining work. Use the issue number
  in the branch name and `Refs` in the English commit message.
- After an authorized commit and push, link the actual commit and branch to the issue;
  create or update the authorized PR with scope, verification, remaining work and the
  correct base/head. Use `Closes` only for fully satisfied issue scope; otherwise use
  `Refs`. Never close an issue just because a branch was pushed or a PR was opened.
- After an authorized merge, verify the merge SHA, issue state and branch retirement.
  Verify the actual working checkout, not just a local `main` ref: report its branch,
  HEAD and remaining staged/unstaged/untracked paths. Preserve foreign work and ignored
  configuration/data; report any incomplete checkout transition explicitly.
- Use `gh issue list/view/create/edit`, `gh pr list/view/create/edit/checks` and, when
  authorized, `gh pr merge`. Resolve `--repo` explicitly and use `--body-file` for
  multiline prose. Reuse existing labels or project conventions rather than inventing
  workflow state. GitHub Projects boards, assignee/reviewer notifications and scheduled
  monitoring require their own applicable authorization.
- Update tracking at meaningful transitions: scope agreed, implementation ready,
  verification changed, blocker found, PR published and merge completed. Prefer editing
  the existing checklist/summary to repetitive comments or broad repository scans.
  Distinguish planned, implemented, verified and merged; retain failed/unrun checks.
- If GitHub access is unavailable, report tracking as blocked and continue safe local
  work within its existing authorization. Never fabricate issue numbers, URLs, checks
  or completion. Deployment, credential changes, paid operations, destructive data
  changes and history rewriting remain separate boundaries.

### Issue body format

Use the following English structure for new actionable issues and substantive scope
updates. Use concise bullets for scope and Markdown task checkboxes for independently
verifiable acceptance checks; nested bullets are appropriate for real subrequirements.

```markdown
## Problem / outcome

Describe the observed problem, concrete trigger and desired result.

## Scope

- Describe each affected behavior or implementation boundary.

## Acceptance checks

- [ ] State an observable result and its relevant verification command or evidence.
```

The three headings are a baseline, not a limit. For complex work, add focused
sections such as `Diagnosis`, `Behavior and state transitions`, `API contracts`,
`Recovery procedure`, `Dependencies` or `Verification evidence` when they clarify
implementation or review. Explain concrete causes, decisions and edge cases at the
depth the issue needs; avoid filler and do not hide actionable acceptance checks in prose.

Mark a checkbox complete only when its stated check has passed. Keep blocked or unrun
checks open with a concise reason. Extend an existing related issue instead of copying
its checklist into duplicate issues. Preserve useful prior evidence while updating scope.

## Dependabot management across this repository

The user authorizes agents to manage genuine Dependabot PRs through `gh` before and
after commit/delivery checkpoints in this repository. Follow commit-it's Dependabot
reconciliation procedure and preserve this repository's frozen `v1` archive and tags.
This authorization covers compatible, verified dependency PR merges, necessary
cherry-picks onto authorized active work branches, and reasoned closure of duplicate,
superseded or demonstrably incompatible updates. It does not authorize production
deployment, history rewriting, protection bypasses or advisory suppression.

- Inspect Dependabot author metadata, exact PR/base/head, dependency and lockfile diffs,
  compatibility/security impact and required checks. Run focused checks where CI is
  absent or insufficient; major releases require impact review, not blanket approval.
- Merge using the normal squash policy and the reviewed head only after applicable
  checks pass. Prefer updating from the merged base over unnecessary cherry-picks.
  For a necessary cherry-pick, verify the target, prevent duplicate patches, preserve
  the PR reference and validate the resulting lockfile and target behavior.
- Close only with a concrete reason and relevant replacement/follow-up link. Pending
  or transiently failing checks are blockers to investigate or defer, not automatic
  rejection. Keep unresolved security work tracked; never disable alerts or future
  updates merely to clear the queue.
- If a dependency merge advances `main` during feature work, reassess the affected
  integration before delivery. Stop on conflicts, missing permissions or failed gates.
  Report PR decisions, checks and actual resulting SHAs so agents and humans can follow
  the same GitHub record. Do not repeatedly poll or comment on unchanged PRs.

## GitHub Flow

1. Preserve unrelated staged, unstaged, untracked, and ignored work. Do not stash, reset, overwrite, or stage it without explicit authorization.
2. Start from a clean, updated `main`: `git switch main` followed by `git pull --ff-only origin main`. Stop on divergence or conflicting local work.
3. Resolve or create the scoped GitHub issue under the tracking policy, then create the branch with `git switch -c <type>/<issue-number>-<description>`.
4. Make the smallest coherent change and run focused behavioral checks plus the applicable static checks below. Review the complete diff and run `git diff --check`.
5. Prepare exact staging paths and complete English Conventional Commit messages. Use the `commit-it` preview and obtain any missing approval before staging, committing, and pushing; an explicitly approved sequence needs no repeated approval. Stage explicit paths with `git add -- <paths>`; never absorb unrelated work.
6. Open a focused pull request against `main`, recording the outcome and actual verification. Obtain explicit authorization for external writes and merges unless the exact action is already approved.
7. Squash-merge the reviewed pull request. Preserve the existing product history; do not force-push or rewrite it.
8. Verify the PR merge and final tree, switch off the completed work branch, and delete that branch locally and remotely when authorized. Refresh the actual local `main` with a fast-forward pull and confirm its HEAD and worktree state. A squash merge does not preserve the development commit as an ancestor; verify the merged result before removing its local ref.

Restore `core.hooksPath=.githooks` in each fresh clone. Tags identify releases; application deployment and GitHub Pages are separate operations requiring their own scope and authorization.

## Applicable engineering requirements

The coding, test placement, docstring, foreign-work protection, focused verification, English commit-message, and runtime guidance below remain applicable. Report checks as passed, failed, not run, or blocked; never claim mock checks establish live PostgreSQL behavior.

## Tutorial maintenance and screenshot evidence

For each requested feature, bug fix or changed user flow, consult this repository's
AGENTS.md before writing documentation and apply commit-it's tutorial checkpoint.
Update the relevant sources in `docs/TUTORIAL/en/` and `docs/TUTORIAL/ko/`, plus README
or CLI guidance only when affected. Preserve unrelated documentation and distinguish
implemented behavior from verification or remaining work. A change with no tutorial
impact needs only a brief explanation in its PR; do not create filler documentation.

By default, update tutorial text and preserve existing screenshots. Do not capture,
replace or regenerate screenshot assets unless the user requests it. When visual
evidence would help or an existing screenshot no longer illustrates the changed flow,
add a prominent `### SCREENSHOT NEEDED` callout and an adjacent HTML comment specifying
the feature, exact UI state, locale and expected evidence. Explain that the screenshot
is pending; never present an old or synthetic capture as proof of new behavior.

When screenshots are explicitly requested, capture actual application states in light
mode and both Korean and English unless the user narrows the scope. Reuse valid
existing evidence, exclude credentials and remove each pending marker only after the
matching screenshot is captured and verified. Consult commit-it for issue/PR delivery
and this section for repository-specific tutorial paths and screenshot policy; do not
recursively re-read either file when the relevant rules are already known.

## Historical assembly reference

The former `assemble`, `zero`, and `new` branch roles, import loop, checkpoint tables, module-completion review gates, and automatic checkpoint stamping describe the completed assembly process only. Sections 1, 2, 4, 4-1, and 9 below are historical, not the current branch workflow. The former user-only commit rule is superseded by the approved `commit-it` workflow above. Do not apply assembly-only requirements to ordinary product changes.

### Archived assembly operating agreement

이 파일은 `assemble` 브랜치에서 반복하는 **이식 루프**의 규칙만 담는다.
브랜치 역할·판단 우선순위·docstring 규격·테스트 배치 규격 같은 전체 계약은
별도의 재조립 하네스 문서에 있고, 세션마다 그것을 함께 제공한다.
둘이 충돌하면 하네스가 우선한다.

---

## 1. 루프 한 바퀴

```
범위 확정 → 이식(가져오기만) → 청소 → [사용자가 외부에서 코드 리뷰를 받아옴]
   → 수정 → 재청소 → 커밋 준비 → 커밋
```

| 단계 | 끝나는 조건 |
|---|---|
| 범위 확정 | 이 덩이가 어느 체크포인트인지, 어떤 파일이 오는지 목록으로 확정됨 |
| 이식 | 파일이 제자리에 놓임. 이 단계에서는 아무것도 고치지 않는다 |
| 청소 | 아래 §3 점검이 전부 0건, ruff·format·`git diff --check` 통과 |
| 리뷰 반영 | 사용자가 가져온 지적을 최소 범위로 수정 |
| 재청소 | §3 재실행. 리뷰 수정이 새 위반을 만들지 않았는지 확인 |
| 커밋 준비 | §5 점검표 + `git add` 명령 + 커밋 메시지 + 한글 요약 제출 |
| 커밋 | **사용자가 실행한다.** 에이전트는 절대 커밋하지 않는다 |

## 2. 요청 문구별 권한

| 문구 | 하는 일 |
|---|---|
| "계획", "확인해봐", "나눠봐" | 읽기 전용 조사. 파일 수정·생성 금지 |
| "가져와", "가져오기만 해" | 파일 복사만. 정리·수정·이름변경·심 제거 전부 금지 |
| "청소", "코드 정리" | 이번 덩이와 직접 관련 테스트만. 다른 모듈 탐색 금지 |
| "docstring 검수" | 바뀐 파일 전수 스캔 후 필요한 것만 수정 |
| "코드 리뷰" | 읽기 전용 finding만. 수정 금지 |
| "커밋 준비" | §5 점검표 + staging 명령 + 메시지 + 한글 요약 |

문구가 없으면 정리·수정까지 진행하는 것으로 본다.

## 3. 매 라운드 반복되는 점검

이식본마다 실제로 매번 나온 것들이다. 청소 단계에서 전수로 확인한다.

1. **학습용 심** — `tests/support.py`의 `need()`/`optional_module()`, conftest의 모듈
   픽스처(`E`/`W`/`G`/`OBS`/`XL`…), `*_MODULE` 환경변수 스위치. 전부 제거하고 직접 import.
2. **패키지 façade import** — `from app.llm import X` 형태. 이 저장소의 `__init__.py`는
   재수출하지 않는다(`app/retrieval`만 예외). 항상 정의 모듈 경로로.
3. **테스트 배치** — 구현 파일 기준이다. `app/X/y.py` → `tests/X/test_y.py`,
   여러 모듈 조립은 `tests/X/test_NN_<behavior>.py`(두 자리, 디렉터리별 01부터 연속).
4. **테스트 간 helper import** — `from tests.a.test_b import c` 금지. `support.py`로
   올리거나 파일 전용으로 자립시킨다.
5. **불필요한 `__init__.py` 추가 금지** — 없어도 되는 곳에 억지로 만들지 않는다.
   `app/db`처럼 없는 채로 도는 패키지는 그대로 둔다. 이식본이 들고 온 `__init__.py`가
   재수출만 하고 있으면 docstring만 남기거나 지운다.
6. **DB 모델 선행 조건** — persistence 모듈은 `app/db/models.py`에 테이블이 먼저 있어야
   한다(`EvalResult`, `Run`, `Trace` 전례). 스키마 계약 테스트는 `tests/db/test_models.py`.
7. **zero 분할 이전 레이아웃 참조** — 예전 모듈에서 심볼을 가져오거나(`retrieval_eval`),
   평면 필드에 접근(`GroupScore.case_count` → `.suite.case_count`)하는 코드.
8. **비공개·중첩 헬퍼 docstring** — ruff는 `_` 접두사를 잡지 않지만 이 저장소는 전부 단다.
   테스트 함수 docstring은 1~3줄, NumPyDoc 섹션 금지.
9. **덮어쓰기 사고** — zero 파일이 assemble 파일 위에 통째로 붙어 계약이 사라지는 경우.
   `git diff`로 이번 덩이와 무관한 삭제가 있는지 항상 확인한다.

## 4. 덩이 분할 판단

**파일 소유가 갈리면 나눈다. 한 파일을 여러 체크포인트가 건드리면 합친다.**

헝크 단위로 쪼개면 디스크에 존재한 적 없는 중간 상태가 커밋된다. 그 커밋에는 실행 결과를
붙일 수 없고, "모든 커밋은 그 상태로 검증됐다"는 이 저장소의 성질을 잃는다.

M10에서 3분할을 권했다가 뒤집은 사례가 근거다 — `registry.py`의 `Registry` 데이터클래스가
M10.1의 어댑터 등록과 M10.3의 `chunk_target`을 같은 정의에 담고 있었고, `parser.py`가
M10.2의 `CELL_TAGS`를 import했다.

분할할 때는 **커밋될 스냅샷 자체**를 격리 검증한다.

```bash
git archive "$(git write-tree)" | tar -x -C /tmp/staged
cd /tmp/staged && PYTHONPATH=/tmp/staged <repo>/.venv/bin/python -m pytest -q
```

코퍼스 원문(`data/corpus/**/*.html`)이 git에 없으므로 이 검증은 **import·수집 breakage만**
잡는다. 데이터 의존 테스트 결과는 최종 워킹 트리 기준으로 보고한다.

## 4-1. 리뷰 단위는 덩이가 아니라 모듈이다

**덩이는 커밋을 가르고, 모듈은 리뷰를 가른다.** 한 모듈의 덩이가 전부 들어오기 전에는
리뷰를 받지 않는다.

덩이 하나만 놓고 리뷰를 받으면 그 경계가 다른 경계를 어떻게 쓰는지가 아직 안 보인다.
같은 지적을 다음 덩이에서 다시 받게 되고, 리뷰 한 번의 값이 그만큼 깎인다. 예를 들어
M5는 `M5.1, M5.4` → `M5.3` → `M5.2` 세 덩이인데, 라우트만 있고 런타임 구성과 CLI가
없는 상태로는 주입이 실제로 교체 가능한지 볼 수 없다.

소속 모듈은 `README.md` 이식 범위표의 단계 라벨 앞자리로 정해진다(`M5.1` → `M5`).
모듈별로 리뷰에서 볼 것은 같은 파일의 리뷰 초점 표에 적는다. 대시보드가 둘을 읽어
모듈이 다 차면 알리고, 초점 문단을 클립보드로 넘긴다.

한 모듈이 다 차기 전에 리뷰가 필요해지면 — 계약이 흔들린다거나 같은 실수가 반복된다거나 —
그건 예외로 요청하고, 그 이유를 남긴다.

## 5. 커밋 전 점검표

- 이번 기능의 파일이 전부 포함됐는가 (staged / unstaged / untracked 모두 확인)
- 이식 덩이라면 `README.md` 표의 해당 행을 기준 커밋과 함께 같은 커밋에 담았는가
- 무관한 작업이 섞이지 않았는가 — 섞였으면 커밋을 나눈다
- 테스트 파일명이 §3-3 규칙을 따르는가
- 가까운 `conftest.py` / `support.py` / `golden.py`를 재사용했는가
- production 로직이 테스트에 복제되지 않았는가
- ruff / format / `git diff --check` 통과
- DB 검증 여부가 정확히 보고됐는가

## 6. 검증 보고 규칙

**통과함 / 실행하지 않음 / 환경 때문에 실행하지 못함 / 무관한 기존 실패**를 구분한다.

- 타입 검사: 이 환경에 `pyright`/`basedpyright` 바이너리가 없다. 매번 "미실행"으로 명시.
- live PostgreSQL: 내려가 있으면 skip으로 빠진다. 스키마·SQL을 건드린 덩이는 반드시
  `docker compose --project-directory . -f docker/docker-compose.yml up -d db` 후 `-m live_postgres --require-live-postgres`를 돌린다.
- SQL·pgvector 동작을 mock 테스트만으로 "검증 완료"라고 하지 않는다.

## 7. 커밋 산출 형식

한 줄 conventional commit이 전역 기본이지만 **이 저장소는 본문을 쓴다.**
`git add` 블록과 히어독을 항상 함께 낸다. `Co-Authored-By`·도구 귀속 푸터 금지. 커밋 메세지는 무조건 영어로 작성한다.
작성 페르소나 톤은 world TOP level swe/ai/ml engineer 스타일로. 양이 길필요 없음 웬만하면 축약.

```
type(scope): concise outcome

Summary
한두 문장.

Changes

- 완성된 기능 단위로. 작업 과정이 아니라 결과를
- 불릿 기호는 `-`

Verification

- 실행한 명령과 결과
- 실행하지 못한 것은 그렇게 명시
```

내부 단계 약자(`M1`, `M4.2` 등)와 breaking-change `!`는 커밋 메시지에 넣지 않는다.

## 8. 금지

- 명시적 요청 없는 커밋 실행
- 사용자 변경의 임의 revert / stash / format
- 현재 요청과 무관한 모듈 탐색이나 리팩터
- `new` / `zero` 브랜치 직접 수정
- zero 완성 파일의 무비판적 전체 복사

## 9. 진행 상황

이식 덩이별 zero 범위와 assemble 착지는 `README.md`의 이식 범위표에 기록한다.
`.dashboard/`의 대시보드가 그 표를 읽어 다음 단계와 코드리뷰 단위를 표시한다.

**표의 행은 `.githooks/pre-commit`이 자동으로 채운다.** 착지 경로에 파일이 새로 추가되는
커밋에서만, 아직 비어 있는 첫 행의 `기준`을 그 시점 HEAD로 찍는다. 스테이지된 README의
그 칸 하나만 인덱스에서 고쳐 쓰므로, 부분 스테이징이나 무관한 README 편집은 커밋에
휩쓸리지 않는다. 무관한 커밋에는 아무것도 하지 않으며, 찍을 때는 무엇을 찍었는지 출력한다.

훅이 왜 필요한지: `기준`은 덩이 자신의 해시가 아니라 올라가는 시점의 HEAD다. 자기
해시는 커밋 뒤에야 생겨 같은 커밋에 넣을 수 없고, 그러면 표가 구조적으로 한 커밋씩
뒤처진다. 실제로 세 덩이 연속 그렇게 어긋났고 아무도 눈치채지 못했다.

상태 칸은 두지 않는다. `기준`이 채워졌다는 것과 완료라는 것이 언제나 같은 말이었고,
손으로 맞출 칸이 하나 늘면 어긋날 자리도 하나 는다.

훅은 저장소 설정이 아니라 클론별 설정으로 돈다. 새로 클론했으면 한 번 켜 줘야 한다:

```bash
git config core.hooksPath .githooks
```

두 덩이가 같은 경로에 착지하면(예: M9의 두 덩이 모두 `app/agent/`) 파일이 추가됐다는
사실만으로는 어느 덩이인지 알 수 없다. 그때 훅은 찍지 않고 이유를 출력한다 — 실제로
그 덩이가 맞으면 `DASH_STAMP=1 git commit ...`으로 강제한다.
한 커밋만 건너뛰려면 `DASH_NO_STAMP=1 git commit ...`.

모듈별 리뷰 초점은 같은 파일의 리뷰 초점 표에 있다(§4-1).

## 10. 로컬 스택

`docker/docker-compose.yml`이 `db`·`app`·`web`과 소스 마운트·자동 reload를 갖춘 기본 개발 스택이다.
`docker/docker-compose.dev.yml`은 같은 base를 상속해 dev 권한을 명시하고,
`docker/docker-compose.prod.yml`은 기존 DB·앱 설정을 상속하면서 개발 웹·소스 마운트·reload·로컬
모델 연결을 제거해 방문자가 보게 될 화면을 재현한다. `.env`로 Compose 파일을 고르지 않는다.

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d db                      # DB만
docker compose --project-directory . -f docker/docker-compose.yml up --build -d app web         # 전체 (dev)
docker compose --project-directory . -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up --build -d app
```

prod 미리보기에 `--build`가 필요한 이유는 웹 번들 성격이 `NEXT_PUBLIC_ADMIN_MODE`
빌드 인자로 이미지에 구워지기 때문이다. 환경변수만 바꿔서는 바뀌지 않는다.

배포 산출물은 `deploy/gcp/docker-compose.deploy.yml`이고 배포 스크립트가 그것만
복사한다. 개발 overlay는 배포 경로에 닿지 않는다.

`MODE`는 OpenAI 키 슬롯을 고르고(dev는 `OPENAI_API_KEY_LOCAL`, prod는 `_PROD`),
`MODE=prod`는 로컬 모델 엔진을 값이 남아 있어도 거부한다. 화면을 가르는 것은
`DOCREVIEW_ADMIN_MODE`(백엔드 권한)와 `NEXT_PUBLIC_ADMIN_MODE`(번들 성격)이지 `MODE`가
아니다. 셋을 혼동하면 "설정을 바꿨는데 화면이 그대로"인 상태에 빠진다.

로컬 모델 절차와 `.env` 항목은 README의 "로컬 모델로 답변하기"에 있다. 엔드투엔드
게이트는 `scripts/verify_clean_checkout.sh`이며, §5의 ruff·format·`git diff --check`
삼종은 그보다 좁은 상시 점검이다. 둘은 다른 것이다.

## 11. 실패 읽는 법

리뷰 실행이 실패하면 응답의 `failure`가 세 모양 중 하나다. 셋을 구분하지 않으면
엉뚱한 설정을 만지게 된다.

| 모양 | 뜻 | 진단에 쓰는 필드 |
|---|---|---|
| `budget_exceeded` | 누적 한도에 걸림 | `resource`, `limit`, `observed`, `blocked_node` |
| `provider_failure` | 모델 호출 자체가 실패 | `status`, `attempts`, `details`, `node` |
| `node_error` | 모델 아닌 단계가 실패 | `error_type`, `message`, `node` |

`resource`는 `wall_clock_s`, `iterations`, `input_tokens`, `output_tokens` 중 하나다.
**wall clock 기본값은 120초이고 이건 토큰 예산이 아니다.** 예산은 한 호출이 아니라
run 전체(분류·라우팅·grade·check와 스키마 실패 재시도)에 누적된다. CPU에서 도는 로컬
모델은 이 120초를 거의 항상 넘긴다.

고치는 자리가 둘로 나뉘어 있다는 사실이 함정이다. wall clock·반복·토큰 한도는
**대화창 RAG settings › Run limits**, 근거 크기(`max_context_chars`, overfetch, 문서당 hit 수)는
**대화창 RAG settings › Evidence**다. 화면의 Run trace가 실패한 run의 필드를 그대로 펼치고 해당
설정을 여는 버튼을 함께 낸다.

job 상태는 여섯 개다. queued·running은 살아 있고, succeeded·failed·cancelled는 종료,
`interrupted`는 애플리케이션 재시작에 잘린 것이다. **중단된 일은 자동으로 이어받지
않는다.** 절반 끝난 ingest를 어디서부터 이어야 할지 알 수 없기 때문이다. failed와
interrupted만 retry를 제공한다.

서버에는 아직 UI가 없는 관측 자산이 있다. `GET /runs/{run_id}`와
`GET /runs/{run_id}/traces`이고, 후자의 `error`가 provider 실패의 원문 기록이다. Run
trace가 run id를 보여 주므로 손으로 조회할 수 있다. run 목록 route는 없다.
