#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Panel for the assemble reassembly loop. Loaded by .dashboard/dashboard.sh.
#
# Sources of truth this file only reads:
#   README.md port-map table   what has been ported and what is next
#   AGENTS.md §3               the checks that repeat every round
#   pyproject.toml [tool.ruff] the lint contract
# ---------------------------------------------------------------------------

PROJECT_NAME="DocReview RAG · assemble"
CACHE_DIR=".dashboard-cache"

SECTIONS=(vcs quality progress checks commits)
SECTION_TITLES=(
    [vcs]="버전 관리"
    [quality]="품질"
    [progress]="이식 진행"
    [checks]="반복 점검"
    [commits]="최근 커밋"
)

# Never on a tick: the suite takes minutes and collection takes seconds.
# .venv/bin/pytest, not `uv run pytest` — uv locks the environment and would
# serialise this against whatever runs in the user's other window.
SLOW_JOBS=(
    "suite|.venv/bin/pytest -q 2>&1 | tail -1"
    "collect|.venv/bin/pytest -q --collect-only 2>/dev/null | tail -1 | grep -oE '^[0-9]+'"
)

RUFF=.venv/bin/ruff
PYTEST=.venv/bin/pytest

BRANCH=""; HEAD_LINE=""; COMMITS=0
STAGED=0; UNSTAGED=0; UNTRACKED=0; DIRTY=0
LINT_OK=-1; FMT_OK=-1
CHANGED_PY=0; DOC_GAPS=0; SHIM_FILES=0
STAGE=""; ZERO_RANGE=""; LANDING=""; PORT_DONE=0; PORT_TOTAL=0
DB_STATE="?"; DB_TICK=0

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

# The README table moves independently of the working tree, so its mtime joins
# the fingerprint that decides whether the medium tier reruns.
panel_fingerprint() { stat -c %Y README.md 2>/dev/null; }

panel_medium() {
    "$RUFF" check app tests >/dev/null 2>&1 && LINT_OK=1 || LINT_OK=0
    "$RUFF" format --check app tests >/dev/null 2>&1 && FMT_OK=1 || FMT_OK=0

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

    # The port-map table is the only record of what has landed. The first row
    # that is not 완료 is the next chunk.
    IFS='|' read -r STAGE ZERO_RANGE LANDING PORT_DONE PORT_TOTAL <<<"$(awk -F'|' '
        /port-map:start/ { inside = 1; next }
        /port-map:end/   { inside = 0 }
        inside && /^\|/ {
            for (i = 2; i <= 6; i++) gsub(/^[ \t]+|[ \t]+$/, "", $i)
            if ($2 == "단계" || $2 ~ /^-+$/) next
            total++
            if ($6 == "완료") { done++; next }
            if (!found) { found = 1; stage = $2; zero = $3; land = $4 }
        }
        END { printf "%s|%s|%s|%d|%d\n", stage, zero, land, done, total }
    ' README.md 2>/dev/null)"
}

ok_badge() {
    case $1 in
        1) badge ok "$2" ;;
        0) badge bad "$2" ;;
        *) badge idle "$2" ;;
    esac
}

section_vcs() {
    kv "브랜치" "${B}${BRANCH}${R}   ${D}커밋${R} ${COMMITS}"
    kv "HEAD  " "$HEAD_LINE"
    if [ "$DIRTY" -eq 0 ]; then
        kv "워킹트리" "$(badge ok "깨끗함")"
    else
        kv "워킹트리" "${D}staged${R} ${STAGED}  ${D}unstaged${R} ${UNSTAGED}  ${D}untracked${R} ${UNTRACKED}"
    fi
}

section_quality() {
    local types
    if [ -x .venv/bin/pyright ] || command -v pyright >/dev/null 2>&1; then
        types="$(badge idle "pyright 미실행")"
    else
        # pyproject configures [tool.pyright] but nothing installs it here.
        types="$(badge idle "pyright 미설치")"
    fi
    grid "$(ok_badge "$LINT_OK" "ruff check")" "$(ok_badge "$FMT_OK" "ruff format")" "$types"
    cache_age suite
    local suite; suite=$(cache suite "${D}미실행 — .dashboard/dashboard-refresh.sh${R}")
    kv "전체 스위트" "${suite}   ${D}${AGE_TEXT}${R}"
    kv "수집 테스트" "$(cache collect '?')"
}

section_progress() {
    local pct=0
    [ "$PORT_TOTAL" -gt 0 ] && pct=$((PORT_DONE * 100 / PORT_TOTAL))
    local bar_w=$((TCOLS / 3)); ((bar_w > 30)) && bar_w=30
    local filled=$((bar_w * PORT_DONE / (PORT_TOTAL > 0 ? PORT_TOTAL : 1)))
    local bar=""; local i
    for ((i = 0; i < bar_w; i++)); do
        ((i < filled)) && bar+="█" || bar+="·"
    done
    kv "이식 덩이" "${GRN}${bar:0:filled}${R}${D}${bar:filled}${R}  ${PORT_DONE}/${PORT_TOTAL}  ${pct}%"
    if [ -n "$STAGE" ]; then
        kv "다음 단계" "${CYN}${B}${STAGE}${R}"
        [ "$LAYOUT" != narrow ] && kv "  zero  " "$ZERO_RANGE"
        kv "  착지  " "$LANDING"
    else
        kv "다음 단계" "$(badge ok "표의 모든 행이 완료")"
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
        kv "PostgreSQL" "$(badge warn "5432 내려감 — DB 테스트는 skip")"
    fi
    [ "$LAYOUT" = wide ] && kv "수동 확인" "${D}façade 재수출 · 테스트간 helper import · 무관한 삭제${R}"
}

section_commits() {
    local line
    while IFS= read -r line; do row "  ${D}${line:0:7}${R}${line:7}"; done < <(git log --oneline -5 2>/dev/null)
}

detail_commits() {
    git log --format='%h %ad %s' --date=short -n "$(( ${1:-0} + 1 ))" 2>/dev/null | tail -1
    git show --stat --oneline "$(git log --format=%h -n "$(( ${1:-0} + 1 ))" | tail -1)" 2>/dev/null | tail -20
}

panel_verdict() {
    if [ "$DIRTY" -eq 0 ]; then
        badge ok "커밋할 것 없음 — 다음 덩이 ${STAGE:-?} 착수 가능"
    elif [ "$DOC_GAPS" -eq 0 ] && [ "$SHIM_FILES" -eq 0 ] && [ "$LINT_OK" = 1 ] && [ "$FMT_OK" = 1 ]; then
        badge warn "변경 ${DIRTY}건, 자동 점검 통과 — 남은 것은 수동 확인 3종과 스테이징"
    else
        badge bad "변경 ${DIRTY}건, 청소 필요"
    fi
}
