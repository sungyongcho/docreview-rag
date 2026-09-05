# DocReview RAG v2 — 독립 실행 가능한 구현·검증·인계 계획

> 최종 실행 갱신: Light 한영60장·문서 참조·정적 빌드·일반/HF 로컬 이미지 검증을 완료했습니다. 현재 결과는 [검증 보고서](2026-09-05-v2-verification.md)의 최종 실행 절을 따르며, 아래 이전 단계 상태는 이력입니다. 추가 기능 관측은 이 문서 끝의 H01–H06 큐에 기록했습니다.

작성일: 2026-09-05. 이 문서는 이전 대화를 읽지 않고 같은 저장소에서 작업을 이어가기 위한 작업 계약이다.
이전 v2로 불렀던 구현은 개념적으로 v1.4 beta이고, 현재 완료한 애플리케이션의 제품 버전은 v2다.
제품명 `DocReview RAG`, URL, 저장소 이름은 유지한다. 새로운 제품 이름이나 전면 브랜드 교체를 뜻하지 않는다.

## 1. 현재 상태와 읽는 법

- 저장소: `/home/wwaya/Documents/docreview-rag-agent`; 작업 브랜치: `assemble`.
- 최초 작업 시작 HEAD: `110c78b`; 인계 기준은 `1dd72a7`이다. 완료된 코드 체크포인트는 `be3d837` → `c5bb137` → `a4d3d1b` → `3c83469`이다.
- 사용자는 범위를 고정했다. 승인된 UI·문서·로컬 연결·공개 미리보기 코드는 `3c83469`까지 커밋되었으며 추가 기능 구현이나 미관 탐색을 다시 시작하지 않는다.
- `3c83469`와 같은 소스의 staged 스냅샷에서 Web 374개, release 17개 및 정적 Web 빌드가 통과했다. 실제 촬영은 EN 30장·KO 7장 완료했으며 문서 자산 통합을 검증 중이다. 최종 일반/HF 이미지 빌드·실제 응답 검증은 남아 있다.
- 아래 `구현됨`은 소스와 관련 기능 검증이 있다는 뜻이며, 전체 수용 기준 통과나 최종 화면 승인과 같지 않다.
- `진행 중`은 동시 작업 결과를 최신 diff로 확인해야 한다. `대기`는 완료 증거가 아직 없다.
- `차단`은 권한 또는 실행 환경의 명시적 차단이다. 시간이 지났다고 해소된 것으로 보지 않는다.
- 아래 R01~R27은 완료한 구현의 계약·추적 기록이다. 이를 새 구현 목록으로 사용하지 않는다. 남은 실행 범위는 문서·캡처 통합 검증, 최종 일반/HF 이미지 확인, 결과 기록·커밋뿐이다.

| 단계 | 작성 시점 상태 | 완료 기록 갱신 칸 |
|---|---|---|
| 코퍼스·공개 문서·회사명·평가 데이터셋 | 커밋 완료; 격리 스냅샷 69 tests passed | `70d20ff` |
| 실행 관측·라우팅·초기화 안전 점검 | 커밋 완료; 격리 스냅샷 138 passed, destructive live test 1 deselected | `9d0acfa` |
| UI·번역·탐색·성능·도움말·공개 미리보기 | 구현·커밋 완료 | 최종 코드 `3c83469`; 같은 소스 staged Web 374 / release 17 / static build 통과 |
| 실제 장면·튜토리얼 이미지 | EN 30장·KO 7장 촬영 완료; 문서 통합 검증 중 | 실제 자산 37개(36 JPEG·1 PNG), locale 슬롯 60개 = 실제 촬영 37 + EN 재사용 23; 상세는 captures.json·QA |
| 최신 소스 일반/HF Docker 재빌드 | 최종 캡처 자산 포함 빌드·실제 응답 검증 대기 | 완료 뒤 §8의 단일 최종 이미지 기록 갱신 |
| 웹·host operator 코드 반영 | 별도 직접 승인 후 재시작·반영 완료 | 8000/18001·기존 인증/origin·소스 마운트·DB 보존; 실제 reset은 권한 문제로 차단 유지 |

검증 수나 커밋 해시를 기억으로 채우지 않는다. 위 칸은 실제 실행·커밋 후 담당자가 갱신한다.

## 2. 권한과 보호 경계

1. 현재 `AGENTS.md`와 `/home/wwaya/.codex/plugins/cache/personal/docreview-rag-agent/0.1.0/skills/docreview-workflow/SKILL.md`를 읽는다.
2. 사용자는 완료된 일관된 단계의 자동 staging·commit을 명시적으로 승인했고, 자동 승인 검토의 기존 금지 적용 이후 현재 대화에서 이번 작업의 예외를 직접 허용했다. 완료 코드의 커밋 기록은 §1에 있다. 남은 문서·검증 산출물도 승인된 범위에서만 `commit-it`으로 저장한다.
3. 따라서 원래 붙여넣기 문서와 로컬 규칙의 사용자 직접 커밋 제한은 이 작업에 한해 최신 명시 승인으로 대체된다. push·외부 배포는 승인되지 않았다.
4. 커밋 전 실제 diff와 검증 결과를 바탕으로 범위·메시지를 준비하고, 이미 승인된 범위 안에서만 실행한다. 존재하지 않은 중간 헝크 상태를 만들지 않는다.
5. 사용자 DB·원문·설정 삭제, 자동 chmod/chown/ACL 변경, credential 변경, 유료 provider 호출은 승인되지 않았다.
6. 8000번 개발 서비스, 소스 마운트와 Documentation 라이브 편집을 보존한다. 필요한 웹·운영자 재시작은 별도 직접 승인으로 이미 완료했다. 새 재시작을 자동으로 반복하지 않는다.
7. host operator 18001의 과거 재시작 승인 차단은 별도 직접 승인·실행으로 해소됐다. 커밋 승인과 재시작 승인은 별개였으며, 초기화 가능 여부는 현재 파일 권한 때문에 계속 차단된다.
8. 보호 대상: `AGENTS.md`, `README.md` 개발 이력·작성 주체 편집, `web/next-env.d.ts`, `docs/2026-09-04-local-development-ui-report.md`의 기존 변경.
9. `NOTES.md` 기존 내용과 다른 외부 작업을 보존한다. 자동으로 stage하지 않는다. 이 계획을 이유로 과거 NOTES를 조사하지 않는다.
10. `git add .`, 전체 stash/reset/revert/format, 사용자 변경 흡수, `new`/`zero` 직접 수정은 금지한다.
11. `.env`, operator token, DB dump, 인증 헤더를 채팅·로그·문서·커밋에 출력하지 않는다.
12. 필요한 독립 작업만 파일 소유가 겹치지 않게 위임한다. 공통 상태·스타일·최종 시각 판단은 통합 담당자가 맡는다.

## 3. 다시 시작할 때의 최소 확인

```bash
pwd
git branch --show-current
git rev-parse HEAD
git status --short
git diff --cached --stat
git diff --stat
```

- 현재 인덱스가 비어 있다고 가정하지 않는다. 시작 당시에는 비어 있었지만 이어받는 시점에는 커밋 준비가 진행됐을 수 있다.
- 아래 파일 지도에서 남은 기능의 정확한 파일만 읽는다. 저장소 전수 조사나 이전 구현 재작성을 시작하지 않는다.
- 수정 대상의 unstaged와 staged diff를 먼저 확인한다. 같은 파일에 초기 구현과 후속 수정이 함께 있으면 완성된 파일 단위로 검증·커밋한다.
- `/tmp/docreview-v2-production-verification.md`가 남아 있으면 읽는다. 임시 보고서는 보조 증거이며 최신 소스 통과를 보장하지 않는다.
- 서비스·컨테이너의 현재 포트와 응답을 읽기 전용으로 확인한다. 아래 기록을 현재 환경 사실로 단정하지 않는다.

## 4. 요구사항 추적표

### R01 — 공유 Small ASCII 브랜드 · P1 · 구현·커밋·실제 장면 촬영 완료

- 원본: `web/branding/wordmark.txt`, `monogram.txt`; Web 표현은 `ascii.ts`와 byte parity test로 일치시킨다.
- 셸은 표준 도구로 정적 자산을 읽는다. 전체 Small 워드마크 78열, DR 모노그램 13열이며 작은 영역은 모노그램과 읽을 수 있는 제품명·v2를 사용한다.
- `rag_alias.sh` 직접 실행·source·rag-help·Bash/Zsh·NO_COLOR·dumb·narrow·보호된 uninstall을 격리 환경에서 검증했다.
- `be3d837`에서 이전 사선 글자와 작게 축소하던 CSS를 제거했다. 최종 화면 행렬은 별도 QA 문서에 기록한다.

### R02 — 초기화 진입 버튼 · P1 · 구현·관련 검증·실제 장면 촬영 완료

- 파일: `build-workspace.tsx`, `build-pipeline.tsx`, `wipe-runtime.tsx`, 관련 CSS와 테스트. 아래 컴포넌트 약식 경로는 모두 `web/components/` 기준이다.
- Reset runtime을 Pipeline 도구 모음의 왼쪽 상단에 둔다. 붉은 테두리·배경으로 파괴적 동작임을 구별한다.
- 펼침 상태에 따라 chevron과 접근성 상태가 바뀌어야 한다. 펼침만으로 초기화가 실행되지 않는다.
- 의존: R08 권한 진단. 수용: 키보드와 터치로 열고 닫기, 비허용 상태 이유 표시, 중복 초기화 버튼 제거.

### R03 — 실제 상태 표시와 움직임 · P1 · 구현·관련 검증 완료, 관찰 범위는 §7

- 파일: `review-progress.tsx`, `system-status.tsx`, `service-health-modal.tsx`, `build-pipeline.tsx`, 공통 CSS.
- 완료·확인된 준비 상태는 녹색 점에 약한 breathing, 실제 실행 중은 더 강한 pulse를 사용한다.
- 실패는 빨강, 준비 부족·주의는 amber, 아직 확인하지 못한 상태는 중립색이다.
- 서버 시작 이벤트 전에는 전체 대기만 표시한다. 실제 단계를 가짜 타이머로 진행시키지 않는다.
- 재검색이면 뒤 단계는 대기로 돌아간다. 완료·실패·중단·미실행을 서로 구분한다.
- 수용: reduced-motion에서는 반복 움직임이 멈추고 텍스트·아이콘은 남는다; DB/BM25 미확인은 녹색이 아니다.

### R04 — 기업 코드와 실제 이름 · P0 · 구현 및 관련 테스트 있음

- 파일: `app/ingestion/company_names.py`, `edgar_api.py`, `app/api/document_catalog.py`, `web/lib/company-labels.ts`, `document-inventory.tsx`, `acquisition-fields.tsx`.
- Documents 기업 필터·목록·상세와 수집·파싱 입력에서 코드와 기업명을 함께 보여 준다.
- manifest의 실제 `issuer_name`과 SEC submissions에 이미 있는 이름을 보존·사용한다. 표시용 하드코딩이나 추가 SEC API 요청을 만들지 않는다.
- 이름이 없으면 정직하게 코드만 표시한다. 가짜 기업명, 첫 회사 이름 재사용, SEC/DART 식별자 혼합을 금지한다.
- 공개 화면의 기업 이름·facet은 게시된 문서만 근거로 만든다. 미게시 기업 존재를 누출하지 않는다.
- 수용: SEC·DART 실제 메타데이터, 이름 누락, 같은 코드의 표시 일관성, 공개/비공개 분리 테스트.

### R05 — Documents·Jobs 가변 분할 · P1 · 구현 및 관련 테스트 있음

- 파일: `master-detail-divider.tsx`, `use-master-detail.ts`, `master-detail.module.css`, `document-inventory.tsx`, `job-center.tsx`.
- 미선택은 전체 너비 목록이다. 임의의 첫 행과 빈 상세 카드를 자동으로 만들지 않는다.
- 실제 콘텐츠 영역이 1100px 이상일 때만 좌우 분할한다. 브라우저 너비가 아니라 사이드바를 제외한 영역 기준이다.
- 목록 기본 360px, 최소 320px, 최대 600px, 상세 최소 560px를 함께 만족시킨다. 원래 계획의 320~420px보다 최신 요구가 우선한다.
- 포인터 드래그, 방향키, Shift 조합, Home/End, 더블클릭 기본값 복귀를 지원한다.
- Documents와 Jobs 너비를 별도로 저장한다. 좁은 화면 왕복 시 기존 큰 화면 너비를 보존한다.
- 수용: divider 접근성 이름/값, 경계 clamp, 키보드 동작, 작은 화면 목록 복귀 시 검색·필터·스크롤·선택 유지.

### R06 — 수집·파싱 TokenSelect · P1 · 구현 및 관련 테스트 있음

- 파일: `token-select.tsx`, `token-select.css`, `acquisition-fields.tsx`, `pipeline-reference.tsx`, `build-workspace.tsx`.
- 원시 ticker/year 문자열 입력을 검색·선택·붙여넣기·제거 가능한 칩 UI로 바꾼다.
- 소유 코퍼스의 기업 코드/이름을 검색하고 여러 기업을 일괄 붙여넣을 수 있다. 유효 SEC ticker와 DART 6자리 코드를 구분한다.
- 연도와 범위를 처리하되 펼친 연도 수는 50 이하로 제한한다. 범위 초과와 잘못된 토큰을 명시한다.
- 잘못된 입력 초안을 잃지 않는다. blur 직후 실행 클릭도 최신 입력을 검증하며 이전 props를 실행하지 않는다.
- 연결된 CLI 미리보기는 동일한 유효 props에서 파생한다. UI와 CLI용 입력을 이중 관리하지 않는다.
- 수용: 복수 paste, 중복 제거, 칩 개별 제거, Enter/blur, invalid draft 유지, 실행 차단과 오류 수정 후 해제.

### R07 — 대화 필터의 전체 코퍼스 facet · P0 · 구현·통합 회귀 완료

- 파일: `conversation-settings.tsx`, `service-shell.tsx`, `web/lib/api.ts`, `app/api/document_catalog.py`, `app/api/routes/admin.py`, `public_documents.py`.
- `/admin/documents/facets` 또는 `/public/documents/facets`에 현재 `registry=sec|dart`를 반영한다. 최초 50개 목록에서 선택지를 추출하지 않는다.
- 기업·언어·보고서 유형·연도를 dropdown/search/chip으로 제공한다. 데이터가 없는 상태도 명확히 설명한다.
- 범위와 호환되지 않는 기존 선택값은 보이게 유지하여 사용자가 명시적으로 제거할 수 있게 한다.
- 범위 변경·언어 변경·빠른 재요청에서 abort/latest-response guard를 적용한다. 오류는 재시도할 수 있다.
- 필터 invalid draft를 `onValidityChange`로 상위에 전달하여 Send를 막는다. 눈에 보이는 invalid와 실제 전송 상태가 일치해야 한다.
- 한국어 UI의 Filters/Retrieval/Evidence/Run limits 및 동적 안내·접근성 이름을 모두 번역한다.
- 수용: 50개를 넘는 코퍼스 facet, SEC↔DART 빠른 변경, 오래된 응답 무시, 미게시 정보 차단, 오류 재시도, invalid Send 차단.

### R08 — 초기화 가능 여부·최종 확인 · P0 · 코드 반영·진단 완료, 실제 삭제는 권한 때문에 차단

- 파일: `app/operator/wipe.py`, `service.py`, `app/api/runtime_gate.py`, `admin_runtime.py`, `web/lib/operator-api.ts`, `wipe-runtime.tsx`.
- 초기화 capability는 실제 필요한 파일 읽기/삭제와 부모 디렉터리 권한, DB 및 진행 중 jobs까지 확인한다.
- 기존 일부 사전 검사가 빠져 `가능`으로 잘못 표시했던 경로를 재현하고 false를 반환하는지 검증한다.
- typed diagnosis에 code/path/owner/mode/operator UID·GID, 검사 시각, 성공·실패를 제공한다.
- 관리자에게 수동 ACL 해결 명령을 안내하되 자동 chmod/chown/reset을 수행하지 않는다.
- 마지막 삭제 질문은 portal modal에서 경고·Cancel·화면에 표시된 정확한 `WIPE <project-name>` 문구를 요구한다. focus 진입/가두기/복귀를 검증했으며 사용자 데이터 삭제는 실행하지 않았다.
- 기록된 읽기 전용 진단은 `data/local-settings/local-llm.json` owner/group 65534:65534, 파일 0600, 부모 0755, operator UID 1000이었다. 운영자 코드 반영 뒤에도 실제 초기화는 파일 권한 문제로 차단되며 권한을 바꾸지 않았다.
- 기존 파일의 권한이나 내용은 변경하지 않았다. 이 결과를 초기화 성공으로 보고하지 않는다.
- 웹과 18001 host operator는 별도 직접 승인 후 반영을 완료했다. 8000/18001, 기존 operator token/origin, 소스 마운트와 DB를 보존했다.
- 과거 재시작 승인 차단은 해소됐고, 파일 권한에 따른 실제 reset 차단은 별개다. 초기화나 권한 변경을 성공했다고 표현하지 않는다.
- 수용: 폐기용 파일·DB의 권한 실패/성공, jobs 차단, 실제 모달, 승인 후에만 새 18001 capability 재확인. 사용자 DB 삭제는 하지 않는다.

### R09 — 문서 범위와 서버 결정값 · P0 · 구현 및 관련 테스트 있음

- 파일: `composer-toolbar.tsx`, `request-preview.tsx`, `review-progress.tsx`, `execution-performance.tsx`, `app/observability/stages.py`, `app/workflow/runner.py`.
- Auto/SEC/DART를 선택 상태로 항상 볼 수 있게 한다. (?) 도움말은 hover·focus·touch·Escape에 대응한다.
- 사용자 선택 범위와 서버가 해석한 registry/issuer/year/reason은 서로 다른 값으로 보존한다.
- 서버 결정값은 실제 단계·실행 성능에서 표시한다. 이벤트 전에는 대기/미확인으로 표시하며 질문만 보고 추측하지 않는다.
- 설정 변경은 진행 중 요청의 스냅샷을 바꾸지 않는다. 완료 후 재방문에서도 원래 선택과 실제 결정값이 유지돼야 한다.
- 수용: Auto 미결정→결정 이벤트, 명시 SEC/DART, 과거 run, 재실행, 호출 중 설정 변경.

### R10 — 프리셋 의미와 Custom 진입 · P1 · 구현 및 관련 테스트 있음

- 파일: `composer-toolbar.tsx`, `request-preview.tsx`, `profile-fields.tsx`, `web/lib/types.ts`, 실제 RetrievalProfile 정의.
- Balanced/Korean/Accuracy/Custom의 목적과 달라지는 값을 실제 정의·resolved RetrievalProfile에서 설명한다.
- (?) 안내와 요청 미리보기에 검색 방식, k, reranker, 언어 라우팅, 필터, prompt 구성을 구분한다.
- Custom 선택 즉시 편집기를 연다. 기존 raw profile 값을 임의로 덮어쓰지 않는다.
- 실행 전 근거 미결정과 실행 후 적용값을 구별한다. 프리셋 설명을 별도 하드코딩 목록으로 관리하지 않는다.
- 수용: 정의 변경 시 설명 일치, Custom 즉시 열림, 질문·답변 보존, in-flight 요청 불변.

### R11 — 요청 상세 drawer/modal · P1 · 구현 및 관련 테스트 있음

- 파일: `request-preview.tsx`, `composer-toolbar.tsx`, `review-controls.css`.
- 좋은 설정 비교 내용은 보존하고 데스크톱 우측 넓은 drawer, 모바일 전체 화면 modal로 보여 준다.
- 자체 스크롤·닫기·Escape·focus 복귀·배경 inert를 지원한다. 열 때 composer 높이가 늘어나지 않는다.
- 수용: 긴 실제 설정, 모바일 키보드, Tab 순환, 열기 버튼 focus 복귀, 배경 입력 불가, 과거 실행값 확인.

### R12 — 대화 정렬·코퍼스 준비 상태 · P1 · 통합 설정·공개 경계 검증 완료

- 파일: `composer-toolbar.tsx`, `service-shell.tsx`, `system-status.tsx`, `review-controls.css`.
- 문서 범위 → 답변 엔진/로컬 모델 → 검색 프리셋 → 필터/고급 설정 순서를 유지한다.
- 떠 있는 레이블과 기준선 불일치를 없애고 desktop 40px/mobile 44px 터치 영역을 맞춘다.
- 모바일에서도 선택한 범위·엔진을 숨기지 않는다. 넓은 화면 일반 작업 최대 너비는 1680px다.
- 준비 상태 수치는 private DEV 전체 코퍼스와 방문자 공개 목록을 구분한다. 공개 `/ready`는 내부 개수와 writable을 null로 반환하며, 공개 목록의 실제 개수는 공개 catalog에서 읽는다. 배포 UI 미리보기는 DEV 대화·상태와 분리된 읽기 전용 문서에서 공개 GET만 사용하고 복귀 시 DEV 작업을 보존한다.
- 대화 조작은 하나의 Review settings drawer로 통합했다. 회사·회계연도를 눈에 띄게 표시하고 요청 상세는 별도 간결한 inspector에서 확인한다.
- DB 연결됨과 검색 준비됨은 다른 상태다. 미확인 DB/BM25를 녹색으로 표시하지 않는다.
- 수용: 모든 너비·사이드바 조합에서 정렬, 정확한 합계 설명, readonly에서 미게시 개수 노출 없음.

### R13 — 준비 상태에서 대화로 돌아오기 · P1 · 구현·회귀·실제 복귀 검증 완료

- 파일: `service-shell.tsx`, `retained-panel.tsx`, `build-workspace.tsx`, `measure-workspace.tsx`, 관련 탐색 테스트.
- 대화의 readiness에서 Pipeline으로 이동하면 위쪽에 Back to conversation을 표시한다.
- 대화 질문·필터·선택·스크롤 및 이미 방문한 작업 공간의 상태를 복원한다. 숨겨 유지하는 panel과 탐색 이력을 확인한다.
- Documents/Jobs 복귀에서 첫 행을 임의 선택하지 않는다. Golden 미저장 초안 이탈 보호를 우회하지 않는다.
- 수용: 대화→readiness→Pipeline→복귀, 여러 workspace 왕복, 좁은 화면 상세 복귀, 취소한 이탈은 원래 초안 유지.

### R14 — 문맥형 한영 Help · P1 · 두 화면 구조로 통합·회귀·실제 장면 촬영 완료

- 파일: `help-overlay.tsx`, `help-overlay.css`, `web/lib/help-primer.ts`, `help-content.ts`, `help-search.ts`, `messages-ko.ts`.
- Help는 홈 → 주제 상세 두 화면이다. 홈의 네 작업 그룹은 필터이며 중간 메뉴로 이동하지 않는다. 하위 분류는 제목만 표시하고 추천 최대 네 개·검색·목록에서 주제를 직접 연다. Back 한 번으로 검색어·필터·스크롤·포커스를 복원한다.
- 상시 숫자 배지와 삼각형은 제거했다. 선택한 주제의 실제 보이는 대상 하나만 클릭을 가로채지 않는 테두리와 작은 라벨로 표시한다. 상세는 요약·세 단계·보조 Reference·전체 문서 링크다.
- 제목 가중치가 본문보다 높은 로컬 결정적 keyword 검색을 사용한다. UI locale과 관계없이 한영 텍스트를 검색한다. LLM 호출은 없다.
- 화면 밖 기능은 소유 화면으로 Go to 이동을 제공한다. 관련 설명은 See also로 연결한다.
- 조건부 기능은 해당 화면과 필요한 컨트롤을 열어 주되 작업을 자동 실행하지 않는다.
- 모달 키보드 이벤트가 배경 단축키·입력과 충돌하지 않게 한다. 현재 섹션 선택은 실제 열린 화면과 일치해야 한다.
- 수용: 한영 교차 검색, 제목 우선 순위, 없음 상태, Go to 후 기능 표시, ESC/focus, 자동 실행 없음.

### R15 — Evidence Pin/Exclude 설명 · P1 · 구현·회귀 검증 완료

- 파일: `service-shell.tsx`, `markdown-message.tsx`, `web/lib/types.ts`, `messages-ko.ts`, 실제 `app/api/evidence.py`와 요청 소비 경로.
- 적용 시점·재검토·저장 결과 제한은 인계 구현에 있다. `be3d837`에서 고정이 인용을 보장하지 않는다는 설명과 회귀 검증을 추가했다.
- 먼저 실제 backend의 `pinnedChunkIds`/`excludedChunkIds` 적용 경로를 확인한다. 이름만 보고 강제 인용·검색 제외 범위를 추정하지 않는다.
- 두 동작의 의미, 이번 결과/다음 요청 중 적용 시점, toggle 상태·선택 수, 재실행 CTA를 한영으로 설명한다.
- 현재 답변이 즉시 다시 계산된다고 오해하게 만들지 않는다. pin/exclude 충돌 처리는 실제 계약과 맞춘다.
- 수용: 실제 payload 일치, toggle/해제·카운트, 적용 시점 설명, 유효 재실행 CTA, 유료 호출 없는 회귀 테스트.

### R16 — 실측 ASCII 실행 성능 · P1 · 구현·회귀·기존 실제 기록 촬영 완료

- 파일: `execution-performance.tsx`, `review-progress.tsx`, `web/lib/messages-ko.ts`, `app/observability/stages.py`, `trace.py`, `persistence.py`, `app/llm/local.py`.
- 최신 사용자는 측정값 기반 ASCII bar/call flow와 정확한 표를 명시적으로 요구했다. 단순 표만으로 완료하지 않는다.
- 전체 요청 시간, 단계 시간, 직렬 모델 호출, 재시도, 가능하면 load/prompt-eval/generation 및 토큰 속도를 구별한다.
- 막대 길이는 실제 측정값의 비율로 계산한다. 미수집 값은 `미수집`/`Not collected`이며 0으로 채우지 않는다.
- completed와 단계 이름은 번역하고 raw node ID·모델명·원문 로그는 보존한다.
- 실제 순서와 동시성에 맞는 call flow를 만들고 단계 시간 합계를 전체 wall time으로 오인하지 않게 한다.
- CPU/GPU, 모델 크기를 실측 없이 지연 원인으로 단정하지 않는다. 이번 작업에서 유료 호출이나 Gemma profiling을 했다고 주장하지 않는다.
- 수용: 정상/재시도/실패/기존 telemetry 없음, 값 누락, 0이 실제 수집된 경우, 긴 모델명, 작은 화면 가로 넘침과 스크린리더 대체 표.

### R17 — Pipeline 통합 공간 · P1 · 구현·관련 검증·실제 장면 촬영 완료

- 파일: `build-pipeline.tsx`, `build-workspace.tsx`, `pipeline-reference.tsx`, `web/lib/pipeline.ts`.
- 그래프·권장 다음 단계·선택 단계 실행을 한 workspace로 합치고 큰 추천 배너·반복 제목을 제거한다.
- 선택 단계의 목적·선행 조건·입력·주 동작을 먼저, 실제 작업 기록·CLI 참고를 보조로 배치한다.
- 기존 stage ID와 동작을 유지하며 embedding/BM25 병렬 관계를 표현한다.
- 평가 의존성은 검색 인덱스와 평가 데이터셋에서 연결한다. 답변 생성 완료가 평가의 필수 조건인 것처럼 그리지 않는다.
- 수용: 노드 클릭은 선택만 수행, 실행 조건 이유, 좁은 화면 순서, 넓은 화면 노드 폭 제한, 실제 그래프와 CLI 일치.

### R18 — Documents/Jobs 데이터 경쟁과 상세 · P0 · 구현 및 관련 테스트 있음

- 파일: `document-inventory.tsx`, `job-center.tsx`, `web/lib/api.ts`.
- Documents 기본 toolbar는 검색·기업·회계연도·필터, 추가 필터는 출처·언어·유형·파싱·embedding·snapshot이다.
- 적용 필터는 제거 칩, 목록 정보는 문서·회사/연도·준비·chunk 수, 상세는 원문·검색 준비·관련 작업·다음 행동이다.
- 문서명 버튼과 행 선택이 같은 상세를 연다. 검색·상세·추가 페이지 모두 취소 또는 최신 요청 식별을 갖춘다.
- A→B 선택에서 늦은 A 응답이 덮지 않으며 실패한 새 요청에 이전 상세가 남아 새 결과로 보이지 않는다.
- Jobs 목록은 이름·대상·상태·진행·시각, 상세는 옵션·진행·오류·결과·가능한 후속 동작이다.
- 수용: loading/error/empty/필터로 선택 제외, 늦은 응답, cancelled/interrupted 표시, retry는 지원 상태에서만 제공.

### R19 — 평가 workspace 전 흐름 · P1 · 구현·회귀·사용 가능한 실제 상태 촬영 완료

- 파일: `playground.tsx`, `measure-workspace.tsx`, `experiment-defaults.tsx`, `evaluation-workspace.css`, `app/evals/admin.py`.
- 검색 테스트는 실행 전 질문·설정이 전체 너비를 사용하고 고급 옵션은 접는다. 실행 후에만 결과 영역을 연다.
- Golden은 원본 readonly와 draft edit를 구별하고 dataset/version/작성 상태, 문항 목록→상세, 하나의 draft 동작 영역을 제공한다.
- 기존 4종과 `_v2_astra` 3종을 같은 데이터셋 목록에서 제공한다. 파일 존재와 목록 계약을 함께 확인한다.
- Runs는 목록→새 평가 설정 modal/panel→선택 dataset/version/index/profile 확인→job→result로 이어진다.
- snapshot 저장은 선택한 결과의 후속 동작이다. 비교 기준/후보 metadata와 호환 불가 이유를 먼저 보여 준다.
- 결과가 있을 때만 지표 변화·문항 차이를 표시한다. 설정 화면 이동은 `평가 준비`로 표현한다.
- 수용: 미저장 보호, 빈 상태, 불가 이유, job/result 연결, 비교 불일치, readonly 권한. 사용자 데이터 게시를 검증용으로 실행하지 않는다.

### R20 — System·클릭·스크롤 일관성 · P1 · 구현·연결 검증·실제 장면 촬영 완료

- 파일: `system-workspace.tsx`, `local-connection-settings.tsx`, `local-engine-settings.tsx`, `operations.tsx`, 공통 CSS.
- 로컬 모델 영역은 전체 너비, 내부는 역할·설치 모델로 나눈다. 주소·환경은 간결한 정보 목록이다.
- 제목은 화면마다 한 번, 중복 카드와 동작 버튼은 통합한다. 읽는 본문은 가독성 있는 줄 길이를 유지한다.
- 동작은 button, 이동은 a; hover/focus 강조, 행 선택 상태, 정적 badge와 클릭 동작의 시각 차이를 명확히 한다.
- 원본 JSON 보기는 명시적 읽기 동작이며 disabled 저장/검증/게시/취소/재시도에는 실제 이유가 있다.
- 페이지·목록·상세 스크롤 책임을 분리하고 스크롤바 공간·하단 여백을 확보한다.
- 수용: 연결 실패 때 기존 정상 설정 보존, 상태 헤더 확장에 API/DB/schema/권한, 중복 스크롤·빈 열 제거.

### R21 — 관측·스트림 하위 호환 · P0 · 구현 및 관련 테스트 있음

- 파일: `app/api/routes/stream.py`, `app/workflow/runner.py`, `app/observability/{stages,types,trace,persistence}.py`, `app/llm/{provider,local,schemas}.py`.
- stages telemetry는 `X-DocReview-Telemetry: stages` opt-in으로 기존 클라이언트 스트림 계약을 유지한다.
- run/trace와 응답에 단계 시작·완료·경과 및 선택적 모델 timing을 추가하되 기존 기록을 계속 읽을 수 있게 한다.
- 진행 중 현재 작업·경과·마지막 상태 수신, 완료 후 실행 성능을 보여 준다.
- 모델·context·token 한도를 자동 조정하지 않는다. wall clock budget과 token budget은 별개로 설명한다.
- 수용: legacy stream, opt-in stream, 실패·중단·재검색, persistence roundtrip, Ollama metric 누락, 원문 provider 오류 보존.

### R22 — 방문자 공개 문서 경계 · P0 · 코드 및 폐기용 DB 검증 있음

- 파일: `app/api/document_catalog.py`, `app/api/routes/public_documents.py`, `app/release/app.py`, `app/api/admin_schemas.py`, 관련 API 테스트.
- 방문자도 게시 snapshot에 속한 문서만 목록·검색·상세·facet으로 탐색한다. 기존 데이터 형식은 재사용한다.
- 미게시 데이터·로컬 경로·관리자 API·기업 identity를 공개하지 않는다. readonly에서 편집·Jobs 조작·로컬 설정·초기화 권한을 늘리지 않는다.
- 현재 원본에는 문서 30개, chunk 22,367개, published snapshot 0개였다. 따라서 공개 목록이 빈 것은 올바르다.
- 양성 공개 membership은 폐기용 DB fixture 테스트로 검증했다. 촬영을 위해 원본에 게시 결과를 만들지 않는다.
- 수용: public list/facet/detail의 일관된 membership, 없는 문서 404, admin 403, readonly UI에서 허용 행동만 표시.

### R23 — 15개 한영 문서·12단계 실습과 실제 이미지 · P2 · 문서·기능·촬영 완료, 자산 통합 검증 중

- 정식 목록과 순서의 원본은 `web/lib/documentation-registry.json`이다. `docs/TUTORIAL/{en,ko}/`의 15개 주제씩 총 30개 Markdown 문서와 12개 실습 단계를 검증했다. 기존 walkthrough·CLI·루트 링크는 호환 매핑으로 보존한다.
- 허브 `docs/TUTORIAL.md` 및 기존 walkthrough/cli 호환 파일의 관계는 현재 renderer를 확인하고 보존한다.
- renderer: `web/components/documentation-page.tsx`, `tutorial-markdown.tsx`, `documentation-navigation.tsx`, `web/app/docs/`의 언어별 route.
- 최종 캡처는 `docs/TUTORIAL/captures.json`을 기준으로 EN 30장·KO 7장, 실제 자산 37개(36 JPEG·1 PNG)다. 언어별 슬롯 60개는 실제 촬영 37개와 EN 재사용 23개로 구성되며 KO 30장을 따로 촬영한 것으로 세지 않는다.
- 최종 실제 UI를 촬영하여 변경된 장면만 교체한다. 프리셋 설명·실행 성능은 필요한 문맥에 추가한다.
- 원문·답변·실행 결과를 촬영용 가짜 값으로 조작하지 않는다. 실행하지 않은 기능을 실행 완료 장면처럼 만들지 않는다.
- 메뉴명·버튼·완료 조건·캡션을 한영 모두 맞춘다. 이미지 원본 크기 보기·코드 복사·목차·모바일·라이브 편집을 검증한다.
- 문서의 복사·언어 전환·이미지 확대·모바일 탐색·라이브 편집을 실제로 확인했다. 최종 이미지 링크와 캡션 통합은 문서 담당자가 검증 중이다. 모든 route와 내부 heading은 공유 registry 검증을 사용한다.

### R24 — 실제 정적 프로덕션 검증 · P0 · 이전 이미지 통과, 최신 재빌드 대기

- 파일: `docker/Dockerfile`, `deploy/huggingface/Dockerfile`, `.dockerignore`, `scripts/check_web_build.py`, 필요한 compose 설정.
- Next 개발 서버 성공만으로 통과하지 않는다. 격리 Web export, 일반 Docker, HF Docker의 최종 소스를 검증한다.
- 이전 일반/HF 컨테이너는 각각 `http://127.0.0.1:18080/docreview-rag-agent/`, `http://127.0.0.1:17860/docreview-rag-agent/`였다.
- 폐기용 clone DB 컨테이너 `docreview-v2-catalog-test`, host port 32769를 사용했다. 원본 DB는 읽기 전용 복사만 했다.
- 기존 빌드에서 `/docreview-rag-agent/api/...` API base와 FastAPI root route가 불일치하여 browser API는 HTML 404였다.
- root가 Docker ARG/ENV의 API base를 빈 값으로 수정했다. 최신 소스 재빌드와 실제 browser 요청 확인 전에는 해결 완료로 쓰지 않는다.
- 산출물에 dev watcher/reload/source mount/.env/local-settings/operator 비밀값이 없어야 한다.
- 수용: 실제 정적 페이지에서 한영 docs·자산·공개 문서 API·권한 경계 정상, 개발 8000 유지, 최종 이미지 ID와 명령·주소 기록.

### R25 — Documentation 헤더 폭·복귀 동작 · P1 · 구현·관련 기능·폭 검증 완료

- 파일: `web/components/documentation-page.tsx`, `documentation-navigation.tsx`, 관련 docs CSS.
- 3440px에서 로고는 왼쪽 끝, 서비스 복귀는 오른쪽 끝으로 갈라지는 헤더를 본문과 같은 제한 너비로 정렬한다.
- `Return to service` 동작의 위치와 시각적 우선순위를 명확히 하고 모바일에서도 항상 찾을 수 있게 한다.
- 제목·언어·문서 탐색·브랜드·복귀가 경쟁하지 않게 하며 본문의 읽기 폭과 정렬 기준을 공유한다.
- 수용: 390/768/1440/3440px, 한영·light/dark에서 복귀가 보이고 키보드 focus 및 실제 이동 정상, 가로로 긴 공백 감소.

### R26 — 제작자 공통 서명과 출처 · P1 · 공통 컴포넌트 구현·관련 검증 완료

- 공통 `web/components/creator-signature.tsx`의 `CreatorSignature`가 compact/footer/about 표시에 사용된다.
- 출처 관계는 `DocReview RAG → Sungyong Cho → https://sungyongcho.com`이다. 기본 문구는 `Built by Sungyong Cho`, Settings/About은 `Designed & built by Sungyong Cho`를 우선한다.
- 초기 제안 `Created by Sungyong Cho`보다 이 최신 문구와 공통 컴포넌트 방향이 우선한다.
- 메인 app은 sidebar 하단의 차분하고 지속적인 서명, 모바일은 footer 등 적절한 위치를 사용한다.
- Documentation header/footer는 제품·제작자 정체성과 복귀 동작의 위계를 강화한다. 작은 제작자 카드가 자연스러운 경우 사용할 수 있다.
- Settings/About에는 version/environment와 제작자를 인접 배치한다. 빈 welcome의 추가 표시는 공간이 충분할 때만 하며 반복 장식은 피한다.
- 작업을 가리는 floating 광고 overlay를 만들지 않는다. 기존 monochrome/terminal 디자인 token을 재사용한다.
- 로컬 포트폴리오는 읽기 전용 디자인 참고다. 직접 관찰하지 않은 live 홈페이지 CSS를 실측했다고 주장하지 않는다.
- 수용: 한영·모바일·넓은 화면에서 링크 가시성, hover/focus/키보드 활성화, 새 탭이면 `noopener`, 작업 방해 없음, 제품 URL 및 README 작성 이력 불변.

### R27 — 자동 실제 촬영·시각 수정 반복 · P1 · 실제 촬영·기록 완료, 최종 자산 통합 검증 중

- 모든 새 기능을 먼저 완성한 뒤 실제 UI를 자동 캡처하고 별도의 UI polish ledger에 결함을 기록한다.
- screenshot 결함과 수정·재촬영 근거는 `docs/2026-09-05-v2-ui-polish-qa.md`에 기록했다. 최종 장면의 revision·locale·viewport·재사용 관계는 캡처 manifest가 담당한다.
- 각 항목은 ID, 화면/소스 경로, viewport, locale, theme, 원본 screenshot 참조, 실제 문제, 수정 경로, 검증, 재촬영 상태를 포함한다.
- 필수 순서: `자동 실제 UI 캡처 → screenshot 근거로 polish 기록 → 필요한 수정 → 영향 장면만 재촬영 → tutorial 이미지·caption 갱신 → 수용 기준까지 반복`.
- 이전 인터페이스 이미지는 최종 상태의 증거로 재사용하지 않는다. 새 캡처는 실제 데이터·기존 실행 기록·정직한 빈 상태를 사용하며, 출처가 확인되지 않은 옛 이미지를 임의로 mock이라고 분류하지 않는다.
- 촬영을 위해 원문·답변·결과를 조작하지 않는다. 빈 상태·차단 상태는 그대로 정직하게 촬영한다.
- Pin/Exclude 설명(R15)은 사용자가 요청한 최종 polish 목록 끝에 명시적으로 남기고 실제 구현·촬영 시 완료 표시한다.
- 수용: 각 발견에 screenshot 근거와 수정 후 확인이 연결됨; 영향 없는 장면의 불필요한 반복 촬영 없음; 최종 tutorial과 QA capture 일치.

## 우선 적용한 Ollama 핫픽스

- 사용자가 주소를 몰라도 Default로 기존 환경 기본 서버를 선택한다. 다른 서버는 Add a server로 등록한다.
- 연결 실패·저장 실패 시 기존 연결을 유지한다. Web·CLI는 같은 읽기 전용 진단 결과를 사용한다.
- macOS/Linux Ollama 준비 문서를 추가하고 Local LLM 화면에서 새 탭으로 연다.
- 앱·CLI 수정 뒤 관련 한영 문서를 반영했다. 최종 캡처에는 Default, 서버 추가, 연결 진단 장면을 포함한다.

## 현재 실행의 추가 문서 계약

- `web/lib/documentation-registry.json`이 15개 문서·한영 제목·그룹·순서·관련 문서·12개 단계·이전 링크 매핑의 원본이다.
- `docs/TUTORIAL/{ko,en}`의 주제별 문서는 `{#step-N}` 식별자를 공유한다. 개요의 단계 목록은 registry에서 생성한다.
- 코드 완료 → 문서·링크·라이브 편집 검증 → `docs/TUTORIAL/captures.json`의 실제 촬영 → 관찰한 화면만 수정·재촬영 → 최종 일반/HF 이미지 검증 순서를 따른다.
- 이번 실행의 검증·청소·화면 결함 기록은 같은 날짜의 `v2-verification.md`, `v2-cleanup-ledger.md`, `v2-ui-polish-qa.md`에 남긴다.
- 첫 앱 커밋은 첨부 승인만으로는 자동 검토가 거절했다. 사용자가 현재 대화에서 이번 작업의 예외를 직접 승인한 뒤 `be3d837`이 생성됐다. 운영자 18001 재시작은 이 승인에 포함되지 않는다.

## 5. 동결된 범위의 남은 마무리

1. 문서 담당자가 실제 캡처 37개와 60개 언어별 슬롯의 링크·캡션·EN 재사용을 최종 검증한다.
2. 완성된 문서·자산이 들어간 일반/HF 정적 이미지를 빌드하고 실제 browser/API/공개 경계를 확인한다. 개발 8000과 사용자 DB를 보존한다.
3. 최종 산출물의 이미지 ID·주소·실제 검증 범위·커밋을 보고서에 기록한다. 사용자 승인 범위의 문서·검증 산출물만 명시적 경로로 커밋한다.
4. 보호 대상 보존을 확인하고 종료한다. 코퍼스 확대, 수집 API·연도 범위 확장, 추가 UI 탐색, 새 provider 호출은 재개하지 않는다.

## 6. 검증 명령과 증거 수집

아래 명령은 검증 계약을 재현하기 위한 참고이며 새 실행 목록이 아니다. 코드 `3c83469`의 같은 소스 staged Web 374개·release 17개·정적 Web 빌드는 이미 통과했다. 변경이나 확인된 실패 없이 완료된 전체 검증을 반복하지 않으며 사용자 DB에 테스트를 연결하지 않는다.

```bash
# Web: web 디렉터리에서, 변경된 기능 테스트부터 실행
npm test -- components/token-select.test.tsx components/acquisition-fields.test.tsx components/conversation-settings.test.tsx
npm test -- components/master-detail-divider.test.tsx components/document-inventory.test.tsx components/job-center.test.tsx
npm test -- components/composer-toolbar.test.tsx components/request-preview.test.tsx components/review-progress.test.tsx
npm test -- components/help-overlay.test.tsx components/help-coverage.test.tsx lib/help-search.test.ts
npm test -- components/service-shell.test.tsx components/build-workspace.test.tsx components/wipe-runtime.test.tsx
npm run typecheck

# 저장소 루트: Python 경계별 회귀
.venv/bin/python -m pytest -q tests/api/test_document_catalog.py tests/ingestion/test_company_names.py tests/ingestion/test_edgar_api.py
.venv/bin/python -m pytest -q tests/operator/test_wipe.py tests/operator/test_service.py tests/api/test_runtime_gate.py
.venv/bin/python -m pytest -q tests/observability/test_stages.py tests/observability/test_persistence.py tests/api/test_04_review_stream.py tests/workflow/test_02_run_lifecycle.py tests/llm/test_local.py

# 최종 웹 격리 빌드: 실행 중 .next를 덮어쓰지 않는 스크립트
.venv/bin/python scripts/check_web_build.py

# 기존 limited builder 사용. 최신 소스/튜토리얼 이미지가 준비된 뒤 실행
 docker buildx build --builder limited --load -f docker/Dockerfile -t docreview:v2-preview .
 docker buildx build --builder limited --load -f deploy/huggingface/Dockerfile -t docreview:v2-hf-preview .

git diff --check
```

- 새 기능이나 추가 일반 정리를 시작하지 않는다. 최종 문서·이미지 변경에 필요한 자산/정적 빌드 확인만 수행하고 실제 명령과 결과를 기록한다.
- Python ruff check/format --check는 변경된 Python 경로를 명시해서 실행한다. 광범위 자동 format을 하지 않는다.
- Python 타입 검사기는 존재 여부를 먼저 확인한다. 없으면 `실행하지 않음: 바이너리 없음`으로 기록한다. Web typecheck와 혼동하지 않는다.
- SQL·공개 membership 검증은 이미 있는 폐기용 PostgreSQL 접속 설정을 비밀값 출력 없이 사용하여 `-m live_postgres --require-live-postgres`를 실행한다.
- connection 변수명은 실제 `tests/conftest.py`의 계약을 확인한다. 추측한 DSN으로 사용자 DB에 테스트를 실행하지 않는다.
- staging을 분리했다면 그 인덱스 스냅샷을 새 임시 디렉터리에 export하여 필요한 import/수집/빌드를 검증한다. untracked corpus가 빠지는 한계를 보고한다.
- 격리 Web 검증에서는 기존 node_modules를 재사용할 수 있지만 실행 중 개발 `.next`를 공유하거나 삭제하지 않는다.
- 모든 결과는 명령·대상 snapshot/HEAD·성공/실패·실행 시점을 기록한다. 과거 233개 또는 다른 중간 테스트 수를 최신 결과로 복사하지 않는다.

## 7. 실제 확인한 시각·상호작용 범위

| 확인 범위 | 실제 기록 |
|---|---|
| 너비 측정 | Review EN/KO와 Documentation EN을 390, 768, 1280, 1440, 1920, 2560, 3440 CSS px에서 측정했으며 root 가로 넘침이 없었다. |
| 좁은 화면 관찰 | 390px light·reduced-motion·sidebar와 390×844 전체 화면 Review settings를 시각적으로 확인했다. |
| 설정·탐색 | 단일 drawer, 열기 전후 composer 높이 62px 유지, Escape·focus·배경 복원 및 배포 UI 미리보기 왕복의 정확한 draft/scroll 보존을 확인했다. |
| 문서 기능 | 정확한 코드 복사, 언어 변경 후 문서/anchor 유지, 모바일 탐색·표 내부 스크롤, 실제 이미지 확대, 라이브 편집 후 원본 byte 복원을 확인했다. |
| 캡처 | 실제 EN 30장·KO 7장. 60개 locale 슬롯 중 23개는 EN 이미지 재사용이며 실제 KO 촬영으로 집계하지 않는다. |
| 상태·권한 | 실제 기존 기록·빈 공개 목록·권한 차단 상태를 촬영했다. 실행하지 않은 상태의 검증은 명시된 컴포넌트/백엔드 테스트와 구분한다. |

이는 모든 언어×테마×sidebar×상태의 전체 곱을 통과했다는 뜻이 아니다. 실제 scene별 viewport·locale·theme는 captures.json과 QA 기록을 따른다. 측정하지 않은 확대 조합·동적 상태를 촬영 수로 대신 증명하지 않는다.

## 8. 남은 차단·한계와 금지된 우회

- **해소된 재시작 차단:** 웹·18001 host operator의 별도 직접 승인과 반영은 완료했다. 이 기록을 새 재시작의 자동 승인으로 확대하지 않는다.
- **권한 불일치:** local-llm.json 소유권/0600은 실제 사용자 환경의 문제다. 설명·진단까지만 수행하며 자동 권한 변경/삭제는 금지한다.
- **공개 데이터 없음:** 원본 published snapshot 0개이므로 양성 공개 UI를 실제 원본으로 촬영할 수 없다. 폐기용 계약 테스트와 실제 빈 상태를 분리해 보고한다.
- **성능 원인 미확정:** 사용자가 실제 실행한 기록은 있을 수 있으나 agent가 Gemma CPU/GPU profiling이나 유료 model benchmark를 완료한 것은 아니다.
- **최종 정적 이미지:** 일반/HF 이미지는 최종 문서·캡처를 포함하여 재빌드·실제 browser/API 검증할 차례다. 과거 성공 이미지나 현재 미리보기 주소를 최종 통과로 표현하지 않는다.
- **최종 이미지 기록 — `PENDING_ROOT_PRODUCTION_METADATA`:** 일반/HF 각각의 source revision, 실행한 build 명령, image ID, 실제 확인 주소, browser/API/docs/public-boundary 결과를 root가 실행 후 채운다.
- **임시 파일:** `/tmp` 로그·script·DB dump는 사라질 수 있다. dump를 문서에 포함하거나 공개 artifact로 전달하지 않는다.

## 9. 완료 기준과 최종 보고 양식

- [ ] R01~R27의 수용 기준과 상태가 최종 소스에 맞게 갱신됨.
- [x] R13 탐색 복원, R15 근거 동작 설명, R16 실측 ASCII 성능이 구현·검증됨.
- [x] 기존 기능과 공개/관리자 권한 경계가 유지됨; 임의 model/context/token 변경 없음.
- [ ] 실제 기록된 시각 범위와 30개 한영 문서·37개 실제 이미지·23개 EN 재사용 슬롯의 최종 통합이 일치함.
- [x] Documentation 제한 너비 헤더·복귀와 공통 제작자 서명(R25/R26)의 구현·관련 검증이 완료됨.
- [ ] R27의 별도 screenshot 기반 polish ledger와 영향 장면 재촬영 반복이 완료됨.
- [ ] 최신 일반/HF 이미지에서 browser API base 문제 해결을 확인하고 주소·이미지 ID를 기록함.
- [ ] 관련 테스트·typecheck·ruff/format·diff check 결과가 통과/실패/미실행/차단으로 구분됨.
- [ ] 승인된 단계별 커밋 해시와 정확한 포함 범위를 기록하고 보호 대상 변경을 보존함.
- [x] 웹·host operator 별도 승인 및 실제 반영을 기록함. 실제 reset 권한 차단과 구별함.
- [x] 8000 개발 서비스와 Documentation 라이브 편집 유지; 원본 DB 삭제·유료 호출·push·외부 배포 없음.

최종 보고는 변경 결과, 검증 명령/결과, 커밋, 확인 가능한 로컬 주소, 남은 차단만 간결하게 작성한다.
모든 항목을 충족하지 못했으면 `전체 완료`라고 하지 않는다. 검증을 더 할 명분으로 무관한 정리 작업을 만들지 않는다.

## 10. 동결 범위 인계문

```text
DocReview RAG v2의 코드 구현은 assemble@3c83469까지 완료·커밋되었다.
완료한 기능을 재구현하거나 이 문서의 R01~R27을 새 작업 목록으로 재개하지 않는다.
같은 소스 staged 검증은 Web 374개·release 17개·정적 Web 빌드를 통과했다.
실제 캡처는 EN 30장·KO 7장, 총 37개이며 locale 60개 슬롯의 나머지 23개는 EN 재사용이다.
남은 일은 문서/캡처 통합 검증, 최종 일반/HF 정적 이미지의 실제 browser/API/docs/공개 경계 확인,
실행한 결과의 보고서 기록과 승인된 범위의 커밋뿐이다. 그 뒤 종료한다.
웹 8000·operator 18001은 별도 직접 승인으로 코드 반영이 완료됐다. 실제 reset은 권한 때문에
계속 차단되며 데이터 삭제·권한 변경을 실행하지 않는다. 개발 서비스·DB·소스 마운트와
AGENTS.md/README.md/web/next-env.d.ts/NOTES.md/기존 로컬 UI 보고서의 외부 변경을 보존한다.
로컬 DEV의 파싱·회사·연도 확대 및 DB 성장 기능은 사용자가 취소했다. 유료 호출·외부 push/deploy도 없다.
실제 캡처·측정 범위만 보고하고 전체 시각 행렬이나 미실행 Docker 검증을 완료로 확대하지 않는다.
```

## 이번 실행의 범위 확정

사용자가 현재 진행한 UI 개선과 배포 UI 미리보기까지로 범위를 고정했다. 로컬 DEV의 파싱·기업·연도 확대와 DB 성장 기능은 추가하지 않는다. 이후에는 필요한 문서·캡처·정적 이미지 검증과 커밋만 완료한다. 대상 사용자는 프랑스·영어권 EU·북미·한국의 채용 담당자·개발자·일반 사용자·IT/PM이며 기존 디자인 언어와 EN/KO 구성을 유지한다.


## 사용자 추가 핫스팟 큐

### H01 — 영어 NVIDIA 질문의 한국어 번역 라우팅 실패 · 조사 대기

- 등록: 2026-09-05, 사용자 첨부 실행 화면. 이번 요청은 큐 등록이며 수정 실행 승인은 아니다.
- 질문: `What drove NVIDIA data center revenue growth?`
- 증상: `Query routing failed for ko (QueryTranslationError).`로 답변 미생성.
- 화면에 기록된 범위: 자동 → SEC, 기업 NVDA, 회계연도 제한 없음; 기업 이름 일치로 범위를 결정한 뒤 실패.
- 기록된 실행: 요청 4.32초; `route` 완료 <1ms 다음 `route` 실패 4.26초. 후보/관련 근거 0, 모델 단계 0; 서버 실행 시간·모델 호출·CPU/GPU 적재 상태 미수집.
- 원인: 미확인. UI 한국어와 질문/검색 번역 대상 `ko`가 어떤 설정에서 결정됐는지, 번역 공급자 오류와 단계 이벤트를 실제 저장 설정·추적 기록으로 대조해야 한다. UI 언어가 원인이라고 단정하지 않는다.
- 검증 상태: 사용자 제공 화면만 기록. 재실행·유료 호출·설정 변경·백엔드 수정 없음. 기존 캡처 장면 20의 과거 31ms 실패와 별개의 사례다.

### H02 — 일부 권한에서 열 수 없는 평가 작업을 Help가 안내 · 수정·검증 완료

- 발견: 최종 핫픽스의 직접 정의·호출부 대조. `can_build_snapshot=true`, `can_run_evaluation=false`에서 스냅샷 저장 도움말과 작업 이동 안내가 노출되지만 평가 작업 화면은 열리지 않는다.
- 수정: `web/lib/help-content.ts`에서 평가 작업 권한도 요구하고, 작업 권한이 없는 스냅샷 목록 설명을 공개 읽기 안내로 제한.
- 검증: 수정 전 회귀 실패 재현 → 관련 43개 테스트 통과 → 통합 Web 406개와 TypeScript 통과.

### H03 — 개발 기록을 에디터에서 교체 저장하면 DEV가 이전 파일을 읽음 · 수정·검증 완료

- 발견: 개발 기록의 단일 파일 bind mount에서 원문에 공백 한 줄만 더해 atomic rename 저장한 뒤 컨테이너가 원래 바이트를 계속 읽는 현상을 재현했다.
- 수정: 기존 웹·TUTORIAL 마운트를 유지하면서 문서 부모 디렉터리를 읽기 전용으로 추가. 새 pathname을 감시기가 읽도록 했다.
- 검증: 같은 atomic 저장의 변경 바이트가 컨테이너에 보임을 확인하고 원문은 원래 바이트로 복원. Compose 계약 11개 통과. 웹 환경변수 값·포트·기존 마운트 유지; 작업/초기화 유휴 확인 후 웹만 재생성.

촬영 중 기능 점검은 버튼·권한·언어·로딩·오류·스크롤·포커스의 실제 상태를 함께 확인한다. 추가 기능 결함은 이 큐에 기록하며, 원인을 모르면 미확인으로 남긴다. 프레이밍·캡처 도구 배율 문제는 UI QA 보고서의 재촬영 기록으로 구분한다.

### H04 — 실행 데이터 초기화가 로컬 설정 파일 권한으로 차단됨 · 최소 ACL로 해결

- 발견: 2026-09-05 Light 재촬영 중 실제 초기화 패널을 열어 차단 상태를 재확인했다. 이전 인계에도 기록된 제한이다.
- 증상: 삭제 버튼 비활성화, `runtime_file_permission`, `Runtime file cannot be removed by this operator: data/local-settings/local-llm.json`.
- 원인: 로컬 작업 서비스가 해당 런타임 파일을 처리할 권한이 없다는 실제 진단. 해결에는 사용자가 별도로 승인하는 권한 변경이 필요하다.
- 처리: 사용자가 안전한 파일 접근과 관리자 인증 창을 승인했다. 소유자 UID 10001을 유지하면서 UID 1000에 설정 파일 읽기 ACL과 부모 폴더 접근·쓰기 ACL만 추가했다. 관리자 인증 후 `/wipe/capability`가 `available: true`, 오류 없음으로 확인됐다. 브라우저에서 읽기 전용 재점검 후 초기화 가능 안내와 버튼 활성화도 확인했다. 초기화·데이터 삭제·소유권·인증 정보 변경 없음.
- 장면 17의 EN/KO 원본 크롭은 권한 조정 전의 실제 차단 사례이며, 캡션에서 시점을 명시한다.

### H05 — 초기 개발 기록 연결 중 hydration 불일치 로그 · 최신 DEV 재현 없음

- 관측: 2026-09-05 20:45:34.992 UTC의 브라우저 로그 1건. `GuidesNavigation`의 서버 영어 문구와 클라이언트 한국어 문구가 불일치했다. 초기 연결 파일과 번역 키를 함께 추가하던 시점이다.
- 원인: 당시 서버 산출물이 남아 있지 않아 확정할 수 없다. 현재 Provider는 서버와 최초 클라이언트 렌더 모두 한국어로 시작하고 저장 언어를 effect에서 적용한다. 중간 HMR 컴파일 상태 차이는 가능성이지 확정 원인이 아니다.
- 검증: 21:31:36 UTC 이후 최신 DEV를 영어·한국어로 각각 새로고침한 결과 신규 hydration 오류 0건. 경고 억제나 추정 수정은 하지 않았다. 최종 일반/HF 정적 이미지 브라우저에서도 hydration 오류 0건을 확인했다. 상세 결과는 검증 보고서에 기록한다.

### H06 — 문서 탐색 스크롤바의 상시 노출 완화 · UX 핫픽스 대기

- 등록: 사용자가 최종 PROD 개발 기록 화면의 좌측 메뉴 스크롤바 스크린샷을 제공하며 핫픽스 추가를 요청했다.
- 증상: 문서 메뉴의 길고 진한 스크롤바가 상시 보여 본문과 탐색 메뉴의 시각적 집중을 방해한다.
- 요청 방향: 문서 탐색의 스크롤바는 평소에는 숨기고 hover·키보드 포커스 등 조작 시 필요에 따라 절제되게 표시한다. 표시 전환으로 레이아웃이 튀지 않도록 한다.
- 유지할 동작: 휠·터치·키보드 스크롤, 메뉴 끝 항목 접근, 독립 스크롤, 명확한 포커스. 이미지 확대 뷰어의 이동 수단까지 일괄 제거하지 않는다.
- 검증 예정: EN/KO, Light/Dark/System, 데스크톱·좁은 화면에서 스크롤과 포커스 및 메뉴 하단 접근 확인. 문서 메뉴 장면29는 실제 변경 뒤 다시 촬영한다.
- 상태: 큐에 등록했으며 현재 CSS와 고정된 제품 스냅샷은 변경하지 않았다.

## 최종 커밋 실행 기록

- 제품 커밋: `737b70b8fdba711f3c56543cd9c1eb659e9c4e36` — `feat(web): complete bilingual guides, themes, and image viewing`.
- 제품157파일의 커밋 트리 `7d2f5f9c0fd3b49b210f4fe6ee8a419c04590bb1`은 검증한 고정 소스와 일치한다. 보고서5파일은 별도 증거 기록 커밋으로 분리한다.
- 최초 커밋은 자동 승인 검토에서 거절됐다. 이후 사용자가 이 작업의 모든 커밋 예외와 commit-it 방식 staging을 명시적으로 승인했고, 그 승인 뒤에만 다시 실행했다. 우회·푸시·외부 배포 없음.
- H01 번역 라우팅 오류는 조사 큐, H06 스크롤바 UX는 후속 핫픽스 큐에 남는다. H06의 CSS 수정·장면29 재촬영·이미지 재빌드는 아직 구현하지 않았다.
