#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Panel for the assemble reassembly loop. Loaded by .dashboard/dashboard.sh.
#
# Sources of truth this file only reads:
#   README.md port-map table   what has been ported and what is next
#   AGENTS.md §3, §6           the checks that repeat, and what counts as proof
#   pyproject.toml             the lint contract and the live-database marker
#
# The engine owns the session channel. This file never touches session.env or
# events.jsonl; it only reads $DASH_NOTE when a row should react to one.
# ---------------------------------------------------------------------------

PROJECT_NAME="DocReview RAG · assemble"
CACHE_DIR=".dashboard-cache"

SECTIONS=(vcs quality progress checks commands commits)
SECTION_TITLES=(
    [vcs]="버전 관리"
    [quality]="품질"
    [progress]="이식 진행"
    [checks]="반복 점검"
    [commands]="명령"
    [commits]="최근 커밋"
)

VIEW_TITLES=(
    [chunk]="이식 덩이"
    [commit]="커밋"
    [cfile]="파일"
    [command]="명령"
)

# AGENTS.md §6 separates "통과함" from "미실행". A cached suite line is only
# proof while it is recent enough to still describe this tree, and how recent
# that has to be is a judgement — so it is a mode, not a constant. The mode
# scales the ceiling; the measurement underneath is the same cache age.
MODES=(strict normal relaxed)
MODE_DEFAULT=normal
MODE_TITLES=(
    [strict]="엄격 15분"
    [normal]="보통 1시간"
    [relaxed]="느슨 8시간"
)

# Commands the repository actually uses. These are written with `uv run`
# because the user pastes them into a shell; the dashboard itself calls
# .venv/bin/* so it never contends for uv's lock.
COMMANDS=(
    "스위트|uv run pytest -m \"not live_postgres\"|DB 없이 도는 기본 스위트. 대부분의 라운드는 이것으로 끝난다"
    "DB 기동|docker compose up -d db|live 테스트 전 PostgreSQL을 올린다. 스키마·SQL을 건드린 덩이는 필수"
    "live 검증|uv run pytest -m live_postgres --require-live-postgres|SQL·pgvector 실검증. 플래그가 있어야 DB 부재가 skip이 아닌 실패가 된다"
    "DB 정지|docker compose stop db|검증이 끝나면 내린다"
    "린트|uv run ruff check app tests|pyproject [tool.ruff.lint] 계약. E501도 여기서 잡힌다"
    "포맷|uv run ruff format app tests|커밋 전 마지막 관문"
    "캐시 갱신|.dashboard/dashboard-refresh.sh|이 대시보드의 스위트·수집 수를 새로 잰다"
    # No literal pipe in the command: this array is split on "|".
    "스냅샷 검증|git archive -o /tmp/staged.tar \"\$(git write-tree)\"|AGENTS.md §4. 분할 커밋될 스테이지 상태를 떠서 별도 디렉터리에서 실행한다"
)

# Minutes each. Never on a tick.
SLOW_JOBS=(
    "suite|.venv/bin/pytest -q 2>&1 | tail -1"
    "collect|.venv/bin/pytest -q --collect-only 2>/dev/null | tail -1 | grep -oE '^[0-9]+'"
)

RUFF=.venv/bin/ruff

BRANCH=""; HEAD_LINE=""; COMMITS=0
STAGED=0; UNSTAGED=0; UNTRACKED=0; DIRTY=0
LINT_OK=-1; FMT_OK=-1; LINT_COUNT=0
CHANGED_PY=0; DOC_GAPS=0; SHIM_FILES=0
STAGE=""; ZERO_RANGE=""; LANDING=""; PORT_DONE=0; PORT_TOTAL=0
PORT_ROWS=()
DB_STATE="?"; DB_TICK=0
SUITE_FRESH=-1

mode_window() {
    case "${MODE:-normal}" in
        strict) printf '900' ;;
        relaxed) printf '28800' ;;
        *) printf '3600' ;;
    esac
}

panel_fast() {
    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    HEAD_LINE=$(git log -1 --format='%h %s' 2>/dev/null)
    COMMITS=$(git rev-list --count HEAD 2>/dev/null)
    STAGED=$(git diff --cached --name-only | wc -l)
    UNSTAGED=$(git diff --name-only | wc -l)
    UNTRACKED=$(git ls-files --others --exclude-standard | wc -l)
    DIRTY=$((STAGED + UNSTAGED + UNTRACKED))

    # /dev/tcp is a bash builtin, so this costs no fork. A local port that is
    # down refuses immediately; it never hangs the frame.
    if ((DB_TICK % 5 == 0)); then
        if (exec 3<>/dev/tcp/127.0.0.1/5432) 2>/dev/null; then
            exec 3>&- 3<&-; DB_STATE="연결됨"
        else
            DB_STATE="내려감"
        fi
    fi
    DB_TICK=$((DB_TICK + 1))
}

# The README table and the suite cache both move independently of the working
# tree, so their mtimes join the fingerprint that decides a medium rerun.
panel_fingerprint() {
    stat -c %Y README.md "$CACHE_DIR/suite" 2>/dev/null
}

panel_medium() {
    "$RUFF" check app tests >/dev/null 2>&1 && LINT_OK=1 || LINT_OK=0
    [ "$LINT_OK" = 0 ] && LINT_COUNT=$("$RUFF" check app tests 2>/dev/null | grep -cE '^[^ ]+:[0-9]+:[0-9]+:') || LINT_COUNT=0
    "$RUFF" format --check app tests >/dev/null 2>&1 && FMT_OK=1 || FMT_OK=0

    # A cached suite line stops being proof the moment a source file is newer
    # than it, whatever the clock says. That is the hard test; the mode window
    # is only the soft one on top.
    SUITE_FRESH=-1
    if [ -f "$CACHE_DIR/suite" ]; then
        SUITE_FRESH=1
        local newer
        newer=$(find app tests -name '*.py' -newer "$CACHE_DIR/suite" -print -quit 2>/dev/null)
        [ -n "$newer" ] && SUITE_FRESH=0
    fi

    # AGENTS.md §3: docstring proportion and leftover learning shims. Only the
    # files this round touched are parsed, so the cost tracks the diff.
    read -r CHANGED_PY DOC_GAPS SHIM_FILES <<<"$(python3 - <<'PY' 2>/dev/null || echo "0 0 0"
import ast, pathlib, re, subprocess
out = subprocess.run(["git", "status", "--porcelain", "-uall"], capture_output=True, text=True).stdout
changed = []
for line in out.splitlines():
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ")[1]
    if path.endswith(".py") and pathlib.Path(path).exists():
        changed.append(path)
docs = shim = 0
for name in changed:
    tree = ast.parse(pathlib.Path(name).read_text())
    if ast.get_docstring(tree) is None:
        docs += 1
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        d = ast.get_docstring(n)
        if d is None and not n.name.startswith("__") and not name.startswith("tests/"):
            docs += 1
        elif d and name.startswith("tests/") and n.name.startswith("test_") and len(d.strip().splitlines()) > 3:
            docs += 1
for p in pathlib.Path("tests").rglob("*.py"):
    t = p.read_text()
    if "tests.support" in t or "optional_module(" in t or re.search(r"\bneed\(", t):
        shim += 1
print(f"{len(changed)} {docs} {shim}")
PY
)"

    # The port-map table is the only record of what has landed. Keep every row
    # so the detail screen does not parse README a second time.
    PORT_ROWS=()
    local line
    while IFS= read -r line; do PORT_ROWS+=("$line"); done < <(awk -F'|' '
        /port-map:start/ { inside = 1; next }
        /port-map:end/   { inside = 0 }
        inside && /^\|/ {
            for (i = 2; i <= 6; i++) gsub(/^[ \t]+|[ \t]+$/, "", $i)
            if ($2 == "단계" || $2 ~ /^-+$/) next
            printf "%s\t%s\t%s\t%s\t%s\n", $2, $3, $4, $5, $6
        }
    ' README.md 2>/dev/null)

    STAGE=""; ZERO_RANGE=""; LANDING=""; PORT_DONE=0; PORT_TOTAL=${#PORT_ROWS[@]}
    local f
    for line in "${PORT_ROWS[@]}"; do
        IFS=$'\t' read -r -a f <<<"$line"
        if [ "${f[4]}" = "완료" ]; then
            PORT_DONE=$((PORT_DONE + 1))
        elif [ -z "$STAGE" ]; then
            STAGE=${f[0]}; ZERO_RANGE=${f[1]}; LANDING=${f[2]}
        fi
    done
}

ok_badge() {
    case $1 in
        1) badge ok "$2" ;;
        0) badge bad "$2" ;;
        *) badge idle "$2" ;;
    esac
}

# --- sections ---------------------------------------------------------------

section_vcs() {
    kv "브랜치" "${B}${BRANCH}${R}   ${D}커밋${R} ${COMMITS}"
    kv "HEAD  " "$HEAD_LINE"
    if [ "$DIRTY" -eq 0 ]; then
        kv "워킹트리" "$(badge ok "깨끗함")"
    else
        kv "워킹트리" "${D}staged${R} ${STAGED}  ${D}unstaged${R} ${UNSTAGED}  ${D}untracked${R} ${UNTRACKED}"
        link vcs changed "  ${D}바뀐 파일 ${DIRTY}건 보기${R}"
    fi
}

detail_vcs() {
    if [ "${1:-}" = changed ] || [ -z "${1:-}" ] || [[ $1 =~ ^[0-9]+$ ]]; then
        row " ${B}바뀐 파일${R}"
        local st path
        while IFS= read -r st; do
            path=${st:3}
            [[ $path == *" -> "* ]] && path=${path##* -> }
            link cfile "$path" "  ${D}${st:0:2}${R}  ${path}"
        done < <(git status --porcelain -uall 2>/dev/null)
        blank
    fi
    row " ${B}원격${R}"
    if [ -n "$(git remote 2>/dev/null)" ]; then
        rows_from < <(git remote -v 2>/dev/null)
    else
        row "  ${D}없음 — 이 저장소는 로컬에서만 재조립된다${R}"
    fi
    blank
    kv "작성자" "$(git config user.name 2>/dev/null) <$(git config user.email 2>/dev/null)>"
    kv "추적  " "$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || printf '없음 (로컬 전용)')"
}

detail_cfile() {
    local path=$1
    row " ${B}${path}${R}"; blank
    if [ ! -e "$path" ]; then
        row "  ${D}삭제됨${R}"; blank
        rows_from < <(git log --oneline -3 -- "$path" 2>/dev/null)
        return
    fi
    kv "크기" "$(wc -l <"$path" 2>/dev/null | tr -d ' ')줄"
    blank
    if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
        rows_from < <(git diff -- "$path" 2>/dev/null | head -60)
    else
        row "  ${D}추적되지 않음 — 앞 40줄${R}"
        rows_from < <(head -40 "$path" 2>/dev/null)
    fi
}

section_quality() {
    mode_strip
    local types
    if [ -x .venv/bin/pyright ] || command -v pyright >/dev/null 2>&1; then
        types="$(badge idle "pyright 미실행")"
    else
        # pyproject configures [tool.pyright] but nothing installs it here.
        types="$(badge idle "pyright 미설치")"
    fi
    local lint="ruff check"
    [ "$LINT_OK" = 0 ] && lint="ruff check ${LINT_COUNT}건"
    grid "$(ok_badge "$LINT_OK" "$lint")" "$(ok_badge "$FMT_OK" "ruff format")" "$types"

    cache_age suite
    local suite; suite=$(cache suite "${D}미실행${R}")
    kv "전체 스위트" "$suite"
    if [ "$AGE" -lt 0 ]; then
        kv "증거 나이" "$(badge idle "캐시 없음 — .dashboard/dashboard-refresh.sh")"
    elif [ "$SUITE_FRESH" = 0 ]; then
        kv "증거 나이" "$(badge bad "코드가 더 최신 — 이 결과는 이 트리를 설명하지 않음")"
    else
        gauge "$AGE" "$(mode_window)"
        kv "증거 나이" "${GAUGE}  ${AGE_TEXT} / ${MODE_TITLES[${MODE:-normal}]}"
    fi
    kv "수집 테스트" "$(cache collect '?')"
    link quality all "  ${D}린트 출력과 캐시 원문 보기${R}"
}

detail_quality() {
    row " ${B}ruff check${R}"
    if [ "$LINT_OK" = 1 ]; then
        row "  $(badge ok "위반 없음")"
    else
        rows_from < <("$RUFF" check app tests 2>&1 | head -40)
    fi
    blank
    row " ${B}ruff format --check${R}"
    if [ "$FMT_OK" = 1 ]; then
        row "  $(badge ok "재포맷 대상 없음")"
    else
        rows_from < <("$RUFF" format --check app tests 2>&1 | head -20)
    fi
    blank
    row " ${B}캐시된 증거${R}"
    cache_age suite
    kv "스위트" "$(cache suite "${D}미실행${R}")"
    kv "잰 때" "${AGE_TEXT}   ${D}창 ${MODE_TITLES[${MODE:-normal}]}${R}"
    kv "수집  " "$(cache collect '?')"
    if [ "$SUITE_FRESH" = 0 ]; then
        blank
        row "  $(badge bad "캐시 이후 수정된 소스")"
        rows_from < <(find app tests -name '*.py' -newer "$CACHE_DIR/suite" 2>/dev/null | head -10)
    fi
    blank
    row " ${B}타입 검사${R}"
    row "  ${D}pyproject에 [tool.pyright] basic이 설정돼 있으나 바이너리가 없다.${R}"
    row "  ${D}AGENTS.md §6에 따라 통과가 아니라 '미실행'으로 보고한다.${R}"
}

section_progress() {
    local pct=0
    [ "$PORT_TOTAL" -gt 0 ] && pct=$((PORT_DONE * 100 / PORT_TOTAL))
    local bar_w=$((TCOLS / 3)); ((bar_w > 30)) && bar_w=30
    local filled=0
    [ "$PORT_TOTAL" -gt 0 ] && filled=$((bar_w * PORT_DONE / PORT_TOTAL))
    local bar="" i
    for ((i = 0; i < bar_w; i++)); do ((i < filled)) && bar+="█" || bar+="·"; done
    kv "이식 덩이" "${GRN}${bar:0:filled}${R}${D}${bar:filled}${R}  ${PORT_DONE}/${PORT_TOTAL}  ${pct}%"
    if [ -n "$STAGE" ]; then
        kv "다음 단계" "${CYN}${B}${STAGE}${R}"
        [ "$LAYOUT" != narrow ] && kv "  zero  " "$ZERO_RANGE"
        kv "  착지  " "$LANDING"
        [ "$DIRTY" -eq 0 ] && kv "  착수  " "${YEL}\"가져와\"${R} ${D}· 이식만 시키는 문구 (AGENTS.md §2)${R}"
    else
        kv "다음 단계" "$(badge ok "표의 모든 행이 완료")"
    fi
    link progress all "  ${D}이식 범위표 전체 보기${R}"
}

detail_progress() {
    row " ${B}README.md 이식 범위표${R}   ${D}${PORT_DONE}/${PORT_TOTAL} 완료${R}"
    blank
    local i=0 line f mark
    for line in "${PORT_ROWS[@]}"; do
        IFS=$'\t' read -r -a f <<<"$line"
        if [ "${f[4]}" = "완료" ]; then mark="${GRN}✓${R}"; else mark="${YEL}·${R}"; fi
        dw_pad "${f[0]}" 14
        link chunk "$i" "  ${mark} ${PAD} ${D}${f[3]}${R}  ${f[2]}"
        i=$((i + 1))
    done
}

detail_chunk() {
    local line=${PORT_ROWS[$1]:-} f
    [ -z "$line" ] && { row "  ${D}그런 행이 없다${R}"; return; }
    IFS=$'\t' read -r -a f <<<"$line"
    row " ${B}${f[0]}${R}   ${f[4]}"
    blank
    kv "zero 범위" "${f[1]}"
    kv "착지     " "${f[2]}"
    kv "커밋     " "${f[3]}"
    blank
    if [ "${f[3]}" != "—" ] && git cat-file -e "${f[3]}^{commit}" 2>/dev/null; then
        rows_from < <(git show -s --format='%h  %ad  %s' --date=short "${f[3]}" 2>/dev/null)
        hr
        rows_from < <(git show --stat --format='' "${f[3]}" 2>/dev/null | sed '/^$/d' | head -24)
    else
        row "  ${D}아직 커밋되지 않은 덩이다. 위 zero 범위가 가져올 대상이다.${R}"
        blank
        row "  ${D}이식만 시키려면: ${R}${YEL}\"가져와\"${R}${D} 또는 ${R}${YEL}\"가져오기만 해\"${R}"
    fi
}

section_checks() {
    local doc shim
    if [ "$DOC_GAPS" -gt 0 ]; then doc=$(badge bad "docstring ${DOC_GAPS}건"); else doc=$(badge ok "docstring"); fi
    if [ "$SHIM_FILES" -gt 0 ]; then shim=$(badge bad "학습용 심 ${SHIM_FILES}파일"); else shim=$(badge ok "심 없음"); fi
    grid "$doc" "$shim" "$(badge idle "변경 .py ${CHANGED_PY}")"
    if [ "$DB_STATE" = "연결됨" ]; then
        kv "PostgreSQL" "$(badge ok "5432 연결됨")"
    else
        kv "PostgreSQL" "$(badge warn "5432 내려감 — live 표식 테스트는 skip")"
    fi
    link checks all "  ${D}AGENTS.md §3 아홉 항목 보기${R}"
}

detail_checks() {
    row " ${B}자동으로 재는 것${R}"
    row "  $(ok_badge $((DOC_GAPS == 0)) "docstring 비례 — 모듈·비공개 헬퍼 누락, 테스트 3줄 초과")"
    row "  $(ok_badge $((SHIM_FILES == 0)) "학습용 심 — tests.support · optional_module · need(")"
    row "  $(ok_badge "$LINT_OK" "ruff check (E·W·F·B·I·UP·N·D·ANN)")"
    row "  $(ok_badge "$FMT_OK" "ruff format")"
    blank
    row " ${B}눈으로 봐야 하는 것${R}"
    row "  ${D}패키지 façade import — app/retrieval 외에는 __init__이 재수출하지 않는다${R}"
    row "  ${D}테스트 간 helper import — from tests.a.test_b import c 금지${R}"
    row "  ${D}무관한 삭제 — zero 파일이 assemble 계약을 덮어썼는지${R}"
    row "  ${D}테스트 배치 — 구현 파일 기준, 번호는 디렉터리별 01부터 연속${R}"
    row "  ${D}누락 __init__.py — app/ 하위 패키지마다 docstring 파일${R}"
    blank
    if [ "$CHANGED_PY" -gt 0 ]; then
        row " ${B}이번 라운드가 건드린 .py ${CHANGED_PY}개${R}"
        rows_from < <(git status --porcelain -uall 2>/dev/null | awk '$NF ~ /\.py$/ {print "  " $0}' | head -30)
    else
        row "  ${D}이번 라운드가 건드린 .py 없음${R}"
    fi
}

section_commands() {
    local i=0 spec label cmd
    for spec in "${COMMANDS[@]}"; do
        label=${spec%%|*}; cmd=${spec#*|}; cmd=${cmd%%|*}
        dw_pad "$label" 12
        link command "$i" "  ${PAD}${D}${cmd}${R}"
        i=$((i + 1))
    done
}

detail_command() {
    local spec=${COMMANDS[$1]:-}
    [ -z "$spec" ] && { row "  ${D}그런 항목이 없다${R}"; return; }
    local label=${spec%%|*} rest=${spec#*|}
    row " ${B}${label}${R}"; blank
    row "  ${GRN}${rest%%|*}${R}"; blank
    row "  ${D}${rest#*|}${R}"; blank
    if clip_copy "${rest%%|*}"; then
        row "  $(badge ok "클립보드에 복사됨")"
    else
        row "  ${D}클립보드 도구가 없다 — 위 줄을 직접 복사한다${R}"
    fi
}

section_commits() {
    local line
    while IFS= read -r line; do row "  ${D}${line:0:7}${R}${line:7}"; done < <(git log --oneline -5 2>/dev/null)
    link commits log "  ${D}더 보기${R}"
}

detail_commits() {
    if [ "${1:-}" = log ]; then
        local i=0 line
        while IFS= read -r line; do
            link commit "$i" "  ${D}${line:0:7}${R}${line:7}"
            i=$((i + 1))
        done < <(git log --oneline -30 2>/dev/null)
        return
    fi
    detail_commit "${1:-0}"
}

detail_commit() {
    local sha; sha=$(git log --format='%H' -1 --skip="$1" 2>/dev/null)
    [ -z "$sha" ] && { row "  ${D}찾지 못했다${R}"; return; }
    rows_from < <(git show -s --format='%h  %an  %ad' --date=iso "$sha" 2>/dev/null)
    blank
    rows_from < <(git show -s --format='%B' "$sha" 2>/dev/null | sed '/^$/d' | head -24)
    hr
    local path
    while IFS= read -r path; do
        [ -z "$path" ] && continue
        link cfile "$path" "  ${path}"
    done < <(git show --name-only --format='' "$sha" 2>/dev/null | head -24)
}

panel_verdict() {
    if [ "$DIRTY" -eq 0 ]; then
        badge ok "커밋할 것 없음 — 다음 덩이 ${STAGE:-?} 착수 가능"
    elif [ "$DOC_GAPS" -eq 0 ] && [ "$SHIM_FILES" -eq 0 ] && [ "$LINT_OK" = 1 ] && [ "$FMT_OK" = 1 ]; then
        badge warn "변경 ${DIRTY}건, 자동 점검 통과 — 남은 것은 눈으로 볼 5종과 스테이징"
    else
        badge bad "변경 ${DIRTY}건, 청소 필요"
    fi
}
