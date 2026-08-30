#!/usr/bin/env bash
# Terminal dashboard for the assemble reassembly loop.
# Usage: watch -c -t -n 5 ./scripts/dashboard.sh
set -uo pipefail
cd "$(dirname "$0")/.."

B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'
GRN=$'\e[32m'; YEL=$'\e[33m'; RED=$'\e[31m'; CYN=$'\e[36m'; MAG=$'\e[35m'
CACHE=.dashboard-suite

rule() { printf '%s\n' "=================================================================="; }

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
head_short=$(git log -1 --format='%h %s' 2>/dev/null | cut -c1-58)
commits=$(git rev-list --count HEAD 2>/dev/null)
staged=$(git diff --cached --name-only | wc -l)
unstaged=$(git diff --name-only | wc -l)
untracked=$(git ls-files --others --exclude-standard | wc -l)
dirty=$((staged + unstaged + untracked))
collected=$(uv run pytest -q --collect-only 2>/dev/null | tail -1 | grep -oE '^[0-9]+' || echo '?')
[ -f "$CACHE" ] && suite=$(cat "$CACHE") || suite="미실행 — scripts/suite.sh 로 갱신"

if uv run ruff check app tests >/dev/null 2>&1; then lint="${GRN}통과${R}"; else lint="${RED}실패${R}"; fi

# Cheap standing checks: the ones this loop repeats every round.
scan=$(python3 - <<'PY' 2>/dev/null
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
)
read -r changed_py doc_gaps shim_files <<<"${scan:-0 0 0}"

printf '%s%s%s%*s%s\n' "$B$CYN" "DocReview Assemble" "$R" 46 "$(date '+%H:%M:%S')" ""
rule
printf ' 커밋 %s   수집 테스트 %s   변경 파일 %s   ruff %b\n' \
  "$commits" "$collected" "$dirty" "$lint"
printf ' %sHEAD%s %s\n' "$D" "$R" "$head_short"
printf ' %s브랜치%s %s   %sstaged%s %s  %sunstaged%s %s  %suntracked%s %s\n' \
  "$D" "$R" "$branch" "$D" "$R" "$staged" "$D" "$R" "$unstaged" "$D" "$R" "$untracked"
rule

# Module chain from README, presence-detected.
printf ' %s모듈 체인%s\n' "$B" "$R"
have() { [ -e "$1" ] && printf '%s✓%s' "$GRN" "$R" || printf '%s·%s' "$D" "$R"; }
printf '   %b M1 ingestion   %b M2 retrieval  %b M3 evals      %b M4 workflow\n' \
  "$(have app/ingestion/chunk.py)" "$(have app/retrieval/service.py)" \
  "$(have app/evals/scoring.py)" "$(have app/workflow/runner.py)"
printf '   %b M8 crossling.  %b M10 dart      %b M5 serving    %b M9 agent\n' \
  "$(have app/evals/crosslingual.py)" "$(have app/ingestion/dart.py)" \
  "$(have app/api)" "$(have app/agent)"
printf '   %b M6 demo        %b M7 deploy\n' "$(have app/demo)" "$(have deploy/Dockerfile)"
rule

# Loop phase, derived from the working tree.
printf ' %s루프 상태%s\n' "$B" "$R"
if [ "$dirty" -eq 0 ]; then
  printf '   %s✓ 청소 완료 — 워킹트리 깨끗%s\n' "$GRN" "$R"
  printf '   %s다음 단계 대기…  README 기준 다음: M5 Serving%s\n' "$CYN" "$R"
elif [ "$doc_gaps" -eq 0 ] && [ "$shim_files" -eq 0 ] && uv run ruff check app tests >/dev/null 2>&1; then
  printf '   %s✓ 청소 완료%s  변경 %s개 파일, docstring·심 위반 0\n' "$GRN" "$R" "$changed_py"
  printf '   %s커밋 준비됨 — 스테이징 대기%s\n' "$YEL" "$R"
else
  [ "$doc_gaps" -gt 0 ] && printf '   %s✗ docstring 누락·초과 %s건%s\n' "$RED" "$doc_gaps" "$R"
  [ "$shim_files" -gt 0 ] && printf '   %s✗ 학습용 심 잔존 %s개 파일%s\n' "$RED" "$shim_files" "$R"
  printf '   %s청소 필요%s\n' "$YEL" "$R"
fi
printf '   %s전체 스위트%s %s\n' "$D" "$R" "$suite"
rule

printf ' %s최근 커밋%s\n' "$B" "$R"
git log --oneline -6 2>/dev/null | sed 's/^/   /' | cut -c1-66
rule
printf ' %s반복 점검%s  심 / façade import / 테스트간 helper import / 번호 시퀀스\n' "$D" "$R"
printf ' %sDB%s %s\n' "$D" "$R" \
  "$(python3 -c "
import socket;s=socket.socket();s.settimeout(0.3)
try: s.connect(('127.0.0.1',5432)); print('PostgreSQL 연결됨')
except Exception: print('PostgreSQL 내려감 — docker compose up -d db')")"
