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
    [review]="코드리뷰 단위"
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
REVIEW_MOD=""; REVIEW_DONE=0; REVIEW_TOTAL=0; REVIEW_FOCUS=""; REVIEW_BASE=""
MAP_LAG=0; MAP_LAST=""
REVIEW_DONE_AT=""
REVIEW_READY=()
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
    # One ruff run serves both the verdict and the count; running it twice
    # would double the cost of every failing rerun for the same answer.
    local lint_out
    if lint_out=$("$RUFF" check app tests --output-format=concise 2>/dev/null); then
        LINT_OK=1; LINT_COUNT=0
    else
        LINT_OK=0
        LINT_COUNT=$(printf '%s\n' "$lint_out" | grep -cE '^[^ ]+:[0-9]+:[0-9]+: ')
    fi
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
        if d is None and not n.name.startswith("__"):
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
    # AGENTS.md §4-1: a chunk is a commit, a module is a review. The module is
    # the stage label's leading M<n>, so membership has no second copy anywhere.
    REVIEW_MOD=""; REVIEW_DONE=0; REVIEW_TOTAL=0; REVIEW_READY=(); REVIEW_BASE=""
    local f mod
    declare -A _mod_total=() _mod_done=()
    local -a _mod_order=()
    for line in "${PORT_ROWS[@]}"; do
        IFS=$'\t' read -r -a f <<<"$line"
        mod="init"; [[ ${f[0]} =~ ^(M[0-9]+) ]] && mod=${BASH_REMATCH[1]}
        [ -n "${_mod_total[$mod]:-}" ] || _mod_order+=("$mod")
        _mod_total[$mod]=$(( ${_mod_total[$mod]:-0} + 1 ))
        if [ "${f[4]}" = "완료" ]; then
            PORT_DONE=$((PORT_DONE + 1))
            _mod_done[$mod]=$(( ${_mod_done[$mod]:-0} + 1 ))
        elif [ -z "$STAGE" ]; then
            STAGE=${f[0]}; ZERO_RANGE=${f[1]}; LANDING=${f[2]}
        fi
    done
    # The review follows the newest landed chunk, not the next pending one. Keyed
    # on the next chunk instead, a module that just filled up would be replaced by
    # the following one at the very moment it became reviewable.
    for line in "${PORT_ROWS[@]}"; do
        IFS=$'\t' read -r -a f <<<"$line"
        if [ "${f[4]}" = "완료" ]; then
            REVIEW_MOD="init"; [[ ${f[0]} =~ ^(M[0-9]+) ]] && REVIEW_MOD=${BASH_REMATCH[1]}
        fi
    done
    [ -n "$REVIEW_MOD" ] || REVIEW_MOD=${_mod_order[0]:-}
    REVIEW_TOTAL=${_mod_total[$REVIEW_MOD]:-0}
    REVIEW_DONE=${_mod_done[$REVIEW_MOD]:-0}
    for mod in "${_mod_order[@]}"; do
        [ "${_mod_done[$mod]:-0}" = "${_mod_total[$mod]}" ] && REVIEW_READY+=("$mod")
    done
    # The table records the base each chunk landed on, so a module's review range
    # is its first chunk's base -- read, not derived from a hash that row cannot
    # have carried at the time it was written.
    for line in "${PORT_ROWS[@]}"; do
        IFS=$'\t' read -r -a f <<<"$line"
        mod="init"; [[ ${f[0]} =~ ^(M[0-9]+) ]] && mod=${BASH_REMATCH[1]}
        if [ "$mod" = "$REVIEW_MOD" ] && [ "${f[4]}" = "완료" ] && [ "${f[3]}" != "—" ]; then
            git cat-file -e "${f[3]}^{commit}" 2>/dev/null && REVIEW_BASE=${f[3]}
            break
        fi
    done

    # The table is updated by hand after each commit, so it silently falls behind
    # and every count on this screen goes stale with it. Nothing else notices, so
    # measure it here: commits after the newest recorded chunk that touched the
    # ported tree are port work the table has not been told about. Commits that
    # only touch docs or this dashboard are correctly absent from it.
    MAP_LAG=0; MAP_LAST=""
    local last=""
    for line in "${PORT_ROWS[@]}"; do
        IFS=$'\t' read -r -a f <<<"$line"
        [ "${f[4]}" = "완료" ] && [ "${f[3]}" != "—" ] && last=${f[3]}
    done
    if [ -n "$last" ] && git cat-file -e "${last}^{commit}" 2>/dev/null; then
        MAP_LAST=$last
        local seen; seen=$(git rev-list --count "${last}..HEAD" -- app tests 2>/dev/null || printf 0)
        MAP_LAG=$((seen - 1))
        ((MAP_LAG < 0)) && MAP_LAG=0
    fi

    IFS='|' read -r REVIEW_DONE_AT REVIEW_FOCUS <<<"$(awk -F'|' -v want="$REVIEW_MOD" '
        /review-focus:start/ { inside = 1; next }
        /review-focus:end/   { inside = 0 }
        inside && /^\|/ {
            for (i = 2; i <= 4; i++) gsub(/^[ \t]+|[ \t]+$/, "", $i)
            if ($2 == want) { printf "%s|%s\n", $3, $4; exit }
        }
    ' README.md 2>/dev/null)"
    [ "$REVIEW_DONE_AT" = "—" ] && REVIEW_DONE_AT=""
}

ok_badge() {
    case $1 in
        1) badge ok "$2" ;;
        0) badge bad "$2" ;;
        *) badge idle "$2" ;;
    esac
}

# The 1s loop re-renders an open detail screen on every tick; copying on each
# render would clobber the reader's clipboard every second. Copy only when the
# hand-off text changes -- once per screen, not once per tick.
_LAST_CLIP=""
clip_once() {
    [ "$1" = "$_LAST_CLIP" ] && return 0
    clip_copy "$1" || return 1
    _LAST_CLIP=$1
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
    if [ "$SUITE_FRESH" = 0 ]; then
        kv "수집 테스트" "$(cache collect '?')  $(badge warn "같은 캐시 — 함께 낡음")"
    else
        kv "수집 테스트" "$(cache collect '?')"
    fi
    link quality all "  ${D}린트 출력과 캐시 원문 보기${R}"
}

detail_quality() {
    row " ${B}ruff check${R}"
    if [ "$LINT_OK" = 1 ]; then
        row "  $(badge ok "위반 없음")"
    else
        rows_from < <("$RUFF" check app tests --output-format=concise 2>&1 | head -40)
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
    if [ -n "$REVIEW_MOD" ] && [ "$REVIEW_TOTAL" -gt 0 ]; then
        local rv
        if [ -n "$REVIEW_DONE_AT" ] && [ "$REVIEW_DONE" -ge "$REVIEW_TOTAL" ]; then
            rv="$(badge ok "${REVIEW_MOD} 리뷰 완료") ${D}반영 기준 ${REVIEW_DONE_AT}${R}"
        elif [ "$REVIEW_DONE" -ge "$REVIEW_TOTAL" ]; then
            rv="$(badge ok "${REVIEW_MOD} 다 참 — 코드 리뷰 시점")"
        else
            rv="${CYN}${REVIEW_MOD}${R} ${REVIEW_DONE}/${REVIEW_TOTAL} 덩이  ${D}$((REVIEW_TOTAL - REVIEW_DONE))개 더 들어와야 리뷰${R}"
        fi
        kv "코드리뷰 단위" "$rv"
        if [ -n "$REVIEW_BASE" ] && [ -n "$REVIEW_DONE_AT" ]; then
            kv "  범위  " "${D}${REVIEW_BASE}..${REVIEW_DONE_AT} 리뷰함${R}"
        elif [ -n "$REVIEW_BASE" ]; then
            kv "  범위  " "${YEL}${REVIEW_BASE}${R} ${D}이후부터 리뷰가 진행되어야 함${R}"
        else
            kv "  범위  " "${D}${REVIEW_MOD}의 첫 덩이가 아직 들어오지 않았다${R}"
        fi
    fi
    if [ "${MAP_LAG:-0}" -gt 0 ]; then
        kv "  표    " "$(badge bad "기록되지 않은 이식 커밋 ${MAP_LAG}개 — 위 숫자는 낡았다")"
    fi
    link progress all "  ${D}이식 범위표 전체 보기${R}"
    link review "$REVIEW_MOD" "  ${D}리뷰에서 볼 것 · 복붙용 문단${R}"
}

# Fold a paragraph onto as many rows as it needs. `row` truncates at the frame
# edge, which is right for a status line and wrong for text meant to be read and
# copied -- and the fallback "copy it yourself" is useless against an ellipsis.
wrap_rows() {
    local text=$1 width=$2 line="" word
    # Split on whitespace with pathname expansion off: a token like app/api/*
    # or a lone ? must stay literal instead of matching files in the CWD.
    set -f
    for word in $text; do
        if [ -z "$line" ]; then line=$word; continue; fi
        dw "$line $word"
        if ((DW > width)); then row "  $line"; line=$word; else line="$line $word"; fi
    done
    set +f
    [ -n "$line" ] && row "  $line"
}

# AGENTS.md §4-1. The focus text lives in README so this screen has no second
# copy of it; the clipboard hand-off is the point, so it goes out verbatim.
detail_review() {
    local mod=${1:-$REVIEW_MOD}
    row " ${B}코드리뷰 단위 ${mod}${R}   ${REVIEW_DONE}/${REVIEW_TOTAL} 덩이"
    blank
    if [ -n "$REVIEW_BASE" ] && [ -n "$REVIEW_DONE_AT" ]; then
        row "  ${REVIEW_BASE}..${REVIEW_DONE_AT} 구간을 리뷰했고 반영이 끝났다."
        blank
        row "  ${D}다시 보려면${R}  ${GRN}git diff ${REVIEW_BASE}..${REVIEW_DONE_AT}${R}"
    elif [ -n "$REVIEW_BASE" ]; then
        row "  ${YEL}${REVIEW_BASE}${R} 이후부터 리뷰가 진행되어야 한다."
        row "  ${D}$(git log -1 --format='%h %s' "$REVIEW_BASE" 2>/dev/null)${R}"
        blank
        row "  ${GRN}git diff ${REVIEW_BASE}..HEAD${R}"
    else
        row "  ${D}${mod}의 첫 덩이가 아직 들어오지 않아 리뷰 기준점이 없다${R}"
    fi
    blank
    if [ -n "$REVIEW_DONE_AT" ]; then
        row "  $(badge ok "리뷰를 받아 반영했다")   ${D}반영이 올라간 기준 ${REVIEW_DONE_AT}${R}"
    elif [ "$REVIEW_DONE" -ge "$REVIEW_TOTAL" ] && [ "$REVIEW_TOTAL" -gt 0 ]; then
        row "  $(badge ok "모듈이 다 찼다 — 지금이 리뷰 시점")"
    else
        row "  $(badge warn "아직 $((REVIEW_TOTAL - REVIEW_DONE))개 덩이가 남았다")"
        row "  ${D}덩이 하나만 놓고 받는 리뷰는 다음 덩이에서 같은 지적을 되풀이한다.${R}"
    fi
    blank
    row " ${B}${mod} 에서 집중할 것${R}"
    if [ -n "$REVIEW_FOCUS" ]; then
        wrap_rows "$REVIEW_FOCUS" $((TCOLS - 6))
        blank
        local handoff="$REVIEW_FOCUS"
        [ -n "$REVIEW_BASE" ] && handoff="${REVIEW_BASE} 이후부터 리뷰. ${REVIEW_FOCUS}"
        if clip_once "$handoff"; then
            row "  $(badge ok "기준 커밋과 함께 클립보드에 복사됨 — 리뷰 요청에 그대로 붙인다")"
        else
            row "  ${D}클립보드 도구가 없다 — 위 줄을 직접 복사한다${R}"
        fi
    else
        row "  ${D}README 리뷰 초점 표에 ${mod} 행이 없다${R}"
    fi
    blank
    row " ${B}이 모듈에 속한 덩이${R}"
    local i=0 line f m mark
    for line in "${PORT_ROWS[@]}"; do
        IFS=$'\t' read -r -a f <<<"$line"
        m="init"; [[ ${f[0]} =~ ^(M[0-9]+) ]] && m=${BASH_REMATCH[1]}
        if [ "$m" = "$mod" ]; then
            if [ "${f[4]}" = "완료" ]; then mark="${GRN}✓${R}"; else mark="${YEL}·${R}"; fi
            dw_pad "${f[0]}" 14
            link chunk "$i" "  ${mark} ${PAD} ${D}${f[3]}${R}  ${f[2]}"
        fi
        i=$((i + 1))
    done
    blank
    row " ${B}리뷰를 이미 받을 수 있는 모듈${R}"
    row "  ${D}${REVIEW_READY[*]:-없음}${R}"
}

detail_progress() {
    row " ${B}README.md 이식 범위표${R}   ${D}${PORT_DONE}/${PORT_TOTAL} 완료${R}"
    blank
    if [ "${MAP_LAG:-0}" -gt 0 ]; then
        row "  $(badge bad "표가 ${MAP_LAG}개 커밋 뒤처졌다 — ${MAP_LAST} 이후로 기록되지 않았다")"
        rows_from < <(git log --oneline "${MAP_LAST}..HEAD" -- app tests 2>/dev/null | sed 's/^/    /')
        row "  ${D}덩이를 끝냈으면 README 표의 해당 행을 커밋 해시와 함께 완료로 바꾼다.${R}"
        blank
    fi
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
    kv "기준     " "${f[3]}"
    blank
    if [ "${f[3]}" != "—" ] && git cat-file -e "${f[3]}^{commit}" 2>/dev/null; then
        # The row records where the chunk landed, so its own commit is the first
        # child of that base on this branch.
        local own
        own=$(git rev-list --ancestry-path --reverse "${f[3]}..HEAD" 2>/dev/null | head -1)
        if [ -n "$own" ]; then
            rows_from < <(git show -s --format='%h  %ad  %s' --date=short "$own" 2>/dev/null)
            hr
            rows_from < <(git show --stat --format='' "$own" 2>/dev/null | sed '/^$/d' | head -24)
        else
            row "  ${D}기준 이후의 커밋을 찾지 못했다${R}"
        fi
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
    row "  ${D}억지 __init__.py — 없어도 되는 패키지에 새로 만들지 않는다${R}"
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
    if clip_once "${rest%%|*}"; then
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
