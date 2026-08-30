#!/usr/bin/env bash
# Live panel for the assemble reassembly loop.
#   ./scripts/dashboard.sh          refresh in place once a second
#   ./scripts/dashboard.sh --once   print one frame and exit
set -uo pipefail
cd "$(dirname "$0")/.."
export TERM="${TERM:-xterm-256color}"
export LC_ALL="${LC_ALL:-${LANG:-C.UTF-8}}"
wipe() { clear 2>/dev/null || printf '\033[H\033[2J'; }

B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'
GRN=$'\e[32m'; YEL=$'\e[33m'; RED=$'\e[31m'; CYN=$'\e[36m'
SUITE_CACHE=.dashboard-suite
COLLECT_CACHE=.dashboard-collect
RUFF=.venv/bin/ruff

# Lint and the docstring scan are the only costly work, so they run again only
# when the tree fingerprint moves. An idle tick then costs a few git calls.
fingerprint=""; lint_ok=0; changed_py=0; doc_gaps=0; shim_files=0

refresh_checks() {
    "$RUFF" check app tests >/dev/null 2>&1 && lint_ok=1 || lint_ok=0
    read -r changed_py doc_gaps shim_files <<<"$(python3 - <<'PY' 2>/dev/null || echo "0 0 0"
import ast, pathlib, re, subprocess
out = subprocess.run(["git","status","--porcelain","-uall"],capture_output=True,text=True).stdout
changed=[]
for line in out.splitlines():
    path=line[3:].strip()
    if " -> " in path: path=path.split(" -> ")[1]
    if path.endswith(".py") and pathlib.Path(path).exists(): changed.append(path)
docs=shim=0
for name in changed:
    tree=ast.parse(pathlib.Path(name).read_text())
    if ast.get_docstring(tree) is None: docs+=1
    for n in ast.walk(tree):
        if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): continue
        d=ast.get_docstring(n)
        if d is None and not n.name.startswith("__") and not name.startswith("tests/"): docs+=1
        elif d and name.startswith("tests/") and n.name.startswith("test_") and len(d.strip().splitlines())>3: docs+=1
for p in pathlib.Path("tests").rglob("*.py"):
    t=p.read_text()
    if "tests.support" in t or "optional_module(" in t or re.search(r"\bneed\(",t): shim+=1
print(f"{len(changed)} {docs} {shim}")
PY
)"
}

have() { [ -e "$1" ] && printf '%s✓%s' "$GRN" "$R" || printf '%s·%s' "$D" "$R"; }
rule() { printf '%s\n' "=================================================================="; }

# The port map in README.md is the single record of what each chunk brings over.
# The first row that is not 완료 is what comes next.
port_map() {
    awk -F'|' '
        /port-map:start/ { inside = 1; next }
        /port-map:end/   { inside = 0 }
        inside && /^\|/ {
            for (i = 2; i <= 6; i++) { gsub(/^[ \t]+|[ \t]+$/, "", $i) }
            if ($2 == "단계" || $2 ~ /^-+$/) next
            total++
            if ($6 == "완료") { done++; next }
            if (!found) { found = 1; stage = $2; zero = $3; land = $4 }
        }
        END { printf "%s|%s|%s|%d|%d\n", stage, zero, land, done, total }
    ' README.md 2>/dev/null
}

render() {
    local branch head_short commits staged unstaged untracked dirty collected suite lint fp
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    head_short=$(git log -1 --format='%h %s' 2>/dev/null | cut -c1-58)
    commits=$(git rev-list --count HEAD 2>/dev/null)
    staged=$(git diff --cached --name-only | wc -l)
    unstaged=$(git diff --name-only | wc -l)
    untracked=$(git ls-files --others --exclude-standard | wc -l)
    dirty=$((staged + unstaged + untracked))

    fp=$(git status --porcelain -uall | cksum)
    [ "$fp" != "$fingerprint" ] && { refresh_checks; fingerprint="$fp"; }
    [ "$lint_ok" -eq 1 ] && lint="${GRN}통과${R}" || lint="${RED}실패${R}"

    [ -f "$COLLECT_CACHE" ] && collected=$(cat "$COLLECT_CACHE") || collected='?'
    [ -f "$SUITE_CACHE" ] && suite=$(cat "$SUITE_CACHE") || suite="미실행 — ./scripts/suite.sh"

    printf '%sDocReview Assemble%s   %s%s%s\n' "$B$CYN" "$R" "$D" "$(date '+%H:%M:%S')" "$R"
    rule
    printf ' 커밋 %s   수집 테스트 %s   변경 파일 %s   ruff %b\n' "$commits" "$collected" "$dirty" "$lint"
    printf ' %sHEAD%s %s\n' "$D" "$R" "$head_short"
    printf ' %s브랜치%s %s   %sstaged%s %s  %sunstaged%s %s  %suntracked%s %s\n' \
        "$D" "$R" "$branch" "$D" "$R" "$staged" "$D" "$R" "$unstaged" "$D" "$R" "$untracked"
    rule
    printf ' %s모듈 체인%s\n' "$B" "$R"
    printf '   %b M1 ingestion   %b M2 retrieval  %b M3 evals      %b M4 workflow\n' \
        "$(have app/ingestion/chunk.py)" "$(have app/retrieval/service.py)" \
        "$(have app/evals/scoring.py)" "$(have app/workflow/runner.py)"
    printf '   %b M8 crossling.  %b M10 dart      %b M5 serving    %b M9 agent\n' \
        "$(have app/evals/crosslingual.py)" "$(have app/ingestion/dart.py)" \
        "$(have app/api)" "$(have app/agent)"
    printf '   %b M6 demo        %b M7 deploy\n' "$(have app/demo)" "$(have deploy/Dockerfile)"
    rule
    printf ' %s루프 상태%s\n' "$B" "$R"
    if [ "$dirty" -eq 0 ]; then
        printf '   %s✓ 청소 완료 — 워킹트리 깨끗%s\n' "$GRN" "$R"
    elif [ "$doc_gaps" -eq 0 ] && [ "$shim_files" -eq 0 ] && [ "$lint_ok" -eq 1 ]; then
        printf '   %s✓ 청소 완료%s  변경 %s개 파일, docstring·심 위반 0\n' "$GRN" "$R" "$changed_py"
        printf '   %s커밋 준비됨 — 스테이징 대기%s\n' "$YEL" "$R"
    else
        [ "$doc_gaps" -gt 0 ] && printf '   %s✗ docstring 누락·초과 %s건%s\n' "$RED" "$doc_gaps" "$R"
        [ "$shim_files" -gt 0 ] && printf '   %s✗ 학습용 심 잔존 %s개 파일%s\n' "$RED" "$shim_files" "$R"
        printf '   %s청소 필요%s\n' "$YEL" "$R"
    fi
    printf '   %s전체 스위트%s %s\n' "$D" "$R" "$suite"
    rule

    IFS='|' read -r stage zrange land done total <<<"$(port_map)"
    if [ -n "$stage" ]; then
        printf ' %s다음 단계%s  %s%s%s     %s이식 덩이 %s/%s 완료%s\n' \
            "$B" "$R" "$CYN" "$stage" "$R" "$D" "$done" "$total" "$R"
        printf '   %szero%s  %s\n' "$D" "$R" "${zrange:0:56}"
        [ "${#zrange}" -gt 56 ] && printf '         %s\n' "${zrange:56:56}"
        printf '   %s착지%s  %s\n' "$D" "$R" "${land:0:56}"
        if [ "$dirty" -eq 0 ]; then
            printf '   %s이식만 시키려면:%s "가져와" · "가져오기만 해"\n' "$YEL" "$R"
        else
            printf '   %s현재 변경분을 먼저 커밋한 뒤 착수합니다.%s\n' "$D" "$R"
        fi
    fi
    rule
    printf ' %s최근 커밋%s\n' "$B" "$R"
    git log --oneline -5 2>/dev/null | sed 's/^/   /' | cut -c1-66
    rule
    printf ' %s반복 점검%s  심 · façade · 테스트간 helper · 번호 시퀀스\n' "$D" "$R"
    printf ' %sDB%s %s\n' "$D" "$R" \
        "$(python3 -c "
import socket;s=socket.socket();s.settimeout(0.3)
try: s.connect(('127.0.0.1',5432)); print('연결됨')
except Exception: print('내려감')")"
}

if [ "${1:-}" = "--once" ]; then render; exit 0; fi
trap 'wipe; exit 0' INT TERM
while :; do
    frame=$(render)
    wipe
    printf '%s\n' "$frame"
    sleep 1
done
