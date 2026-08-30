#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Terminal project dashboard — generic engine.
#
# The engine owns what is identical in every repository: a layout that follows
# the window, display-width arithmetic that survives CJK and emoji, a refresh
# budget that keeps idle ticks cheap, measured terminal capabilities, and input
# handling. It knows nothing about any particular project.
#
# Everything project-specific lives in a panel file that declares SECTIONS and
# one section_<name> function per section. See references/panel-api.md.
#
#   dashboard.sh             live, redrawing on an interval
#   dashboard.sh --once      print one frame and exit (pipes, watch, CI)
#   dashboard.sh --probe     print measured terminal capabilities and exit
# ---------------------------------------------------------------------------
set -uo pipefail
shopt -s extglob

ENGINE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PANEL=""
INTERVAL=1
ONCE=0
PROBE_ONLY=0
WANT_ALT=1
WANT_MOUSE=auto

usage() {
    cat <<'USAGE'
usage: dashboard.sh [--once] [--probe] [--interval N] [--panel FILE]
                    [--no-mouse] [--no-alt] [--help]

  --once        print a single frame to stdout and exit
  --probe       measure terminal capabilities, print the report, exit
  --interval N  seconds between redraws (default 1)
  --panel FILE  panel file to load (default: search the repo)
  --no-mouse    skip mouse tracking even where it is supported
  --no-alt      stay on the main screen instead of the alternate screen

keys: space/r refresh now   1-9 toggle section   q quit
USAGE
}

while [ $# -gt 0 ]; do
    case $1 in
        --once) ONCE=1 ;;
        --probe) PROBE_ONLY=1 ;;
        --interval) INTERVAL=${2:?--interval needs a value}; shift ;;
        --panel) PANEL=${2:?--panel needs a path}; shift ;;
        --no-mouse) WANT_MOUSE=no ;;
        --no-alt) WANT_ALT=0 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'dashboard: unknown argument %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# --------------------------------------------------------------------------
# Repository root and panel discovery
# --------------------------------------------------------------------------
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || ROOT=$(cd "$ENGINE_DIR/.." && pwd)
cd "$ROOT" || exit 1

if [ -z "$PANEL" ]; then
    for candidate in \
        "$ROOT/scripts/dashboard.panel.sh" \
        "$ROOT/.dashboard/panel.sh" \
        "$ENGINE_DIR/panel.sh" \
        "$ENGINE_DIR/dashboard.panel.sh"
    do
        [ -f "$candidate" ] && { PANEL=$candidate; break; }
    done
fi
if [ -z "$PANEL" ] || [ ! -f "$PANEL" ]; then
    printf 'dashboard: no panel file found (looked for scripts/dashboard.panel.sh and .dashboard/panel.sh)\n' >&2
    exit 1
fi

# --------------------------------------------------------------------------
# The two-way channel.
#
# An agent session working on the repository writes dash-send.sh's file into
# the cache directory; the dashboard applies it on the next tick. Going back
# the other way, what the reader does here is appended to events.jsonl, which
# the session tails. Two files, no daemon and no port, and neither is tracked,
# so a signal never turns into a commit.
#
# This lives in the engine rather than in each panel because none of it is
# project-specific. A panel that reimplements it is duplicating the engine.
# --------------------------------------------------------------------------
DASH_NOTE=""; DASH_QUESTION=""; DASH_OPTIONS=""
_SIGNAL_MTIME=""
declare -a DASH_OPTION_LIST=()

# JSON string escaping without jq: the events file has to be machine-readable
# by whatever is tailing it, and a note or an option is arbitrary text that
# will contain a quote or a backslash sooner or later.
dash_json_str() {
    local s=${1-} out=""
    s=${s//\\/\\\\}
    s=${s//\"/\\\"}
    s=${s//$'\n'/\\n}
    s=${s//$'\t'/\\t}
    s=${s//$'\r'/}
    printf '"%s"' "$s"
}

# One JSON object per line, appended. The session reads each line as an event.
dash_emit() {
    local kind=$1 body="" k v stamp
    shift
    printf -v stamp '%(%FT%T%z)T' -1
    while [ $# -ge 2 ]; do
        k=$1; v=$2; shift 2
        body+=",$(dash_json_str "$k"):$(dash_json_str "$v")"
    done
    printf '{"t":%s,"kind":%s%s}\n' \
        "$(dash_json_str "$stamp")" "$(dash_json_str "$kind")" "$body" \
        >> "$CACHE_DIR/events.jsonl" 2>/dev/null
}

# Applied once per send, keyed on the file's mtime rather than its contents.
# Reapplying a fold on every tick would snap that section shut under the
# reader's fingers the moment they opened it by hand.
dash_read_signal() {
    local f="$CACHE_DIR/session.env" mtime="" name
    [ -f "$f" ] && mtime=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
    [ "$mtime" = "$_SIGNAL_MTIME" ] && return 0
    _SIGNAL_MTIME=$mtime
    DASH_NOTE=""; DASH_QUESTION=""; DASH_OPTIONS=""
    local NOTE="" QUESTION="" OPTIONS="" FOLD="" OPEN=""
    if [ -n "$mtime" ]; then
        # shellcheck disable=SC1090
        . "$f" 2>/dev/null
    fi
    DASH_NOTE=$NOTE; DASH_QUESTION=$QUESTION; DASH_OPTIONS=$OPTIONS
    DASH_OPTION_LIST=()
    if [ -n "$DASH_OPTIONS" ]; then
        local saved=$IFS; IFS='|'; read -ra DASH_OPTION_LIST <<<"$DASH_OPTIONS"; IFS=$saved
    fi
    for name in $FOLD; do COLLAPSED[$name]=1; done
    for name in $OPEN; do unset "COLLAPSED[$name]"; done
    return 0
}

# --------------------------------------------------------------------------
# Style. Colours are dropped when the frame is not going to a terminal, so
# --once stays clean in a pipe.
# --------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'
    GRN=$'\e[32m'; YEL=$'\e[33m'; RED=$'\e[31m'; CYN=$'\e[36m'; MAG=$'\e[35m'
else
    B=""; D=""; R=""; GRN=""; YEL=""; RED=""; CYN=""; MAG=""
fi
RULE_CHAR=${DASH_RULE_CHAR:-─}

# --------------------------------------------------------------------------
# Display width. A terminal cell is not a character: Hangul, Han, kana and
# most emoji occupy two columns, combining marks and joiners occupy none.
# Padding by ${#s} is what makes a table shear the moment Korean appears.
#
# dw sets DW instead of echoing, so callers never fork a subshell, and results
# are memoised because labels repeat on every frame.
# --------------------------------------------------------------------------
declare -A _DW_MEMO=()
DW=0
dw() {
    local s=$1
    if [ -n "${_DW_MEMO[$s]+set}" ]; then DW=${_DW_MEMO[$s]}; return; fi
    local t=${s//$'\e['*([0-9;])[a-zA-Z]/}
    local -i w=0 i n=${#t} cp
    for ((i = 0; i < n; i++)); do
        printf -v cp '%d' "'${t:i:1}"
        if ((cp < 0x0300)); then
            ((w += 1))
        elif ((  (cp >= 0x0300 && cp <= 0x036F) || cp == 0x200B || cp == 0x200C \
              || cp == 0x200D || cp == 0xFEFF || (cp >= 0xFE00 && cp <= 0xFE0F) \
              || (cp >= 0x1F3FB && cp <= 0x1F3FF) )); then
            :
        elif ((  (cp >= 0x1100 && cp <= 0x115F) || (cp >= 0x2E80 && cp <= 0x303E) \
              || (cp >= 0x3041 && cp <= 0x33FF) || (cp >= 0x3400 && cp <= 0x4DBF) \
              || (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0xA000 && cp <= 0xA4CF) \
              || (cp >= 0xAC00 && cp <= 0xD7A3) || (cp >= 0xF900 && cp <= 0xFAFF) \
              || (cp >= 0xFE10 && cp <= 0xFE19) || (cp >= 0xFE30 && cp <= 0xFE6F) \
              || (cp >= 0xFF00 && cp <= 0xFF60) || (cp >= 0xFFE0 && cp <= 0xFFE6) \
              || (cp >= 0x1F300 && cp <= 0x1F64F) || (cp >= 0x1F680 && cp <= 0x1F6FF) \
              || (cp >= 0x1F900 && cp <= 0x1F9FF) || (cp >= 0x1FA70 && cp <= 0x1FAFF) \
              || (cp >= 0x20000 && cp <= 0x3FFFD) )); then
            ((w += 2))
        else
            ((w += 1))
        fi
    done
    _DW_MEMO[$s]=$w
    DW=$w
}

# Truncate to at most $2 columns, keeping escape sequences intact and never
# splitting a two-column character across the edge.
dw_cut() {
    local s=$1 limit=$2
    dw "$s"; [ "$DW" -le "$limit" ] && { CUT=$s; return; }
    local out="" seq="" ch cw
    local -i i n=${#s} w=0 cp
    for ((i = 0; i < n; i++)); do
        ch=${s:i:1}
        if [ "$ch" = $'\e' ]; then
            seq=$ch
            while ((i + 1 < n)); do
                ((i++)); seq+=${s:i:1}
                [[ ${s:i:1} == [a-zA-Z] ]] && break
            done
            out+=$seq
            continue
        fi
        printf -v cp '%d' "'$ch"
        dw "$ch"; cw=$DW
        ((w + cw > limit - 1)) && break
        out+=$ch; ((w += cw))
    done
    CUT="${out}${D}…${R}"
}

# Pad to exactly $2 columns; $3 is l (default) or r.
dw_pad() {
    local s=$1 width=$2 side=${3:-l} fill=""
    dw "$s"
    local -i gap=$((width - DW))
    ((gap <= 0)) && { PAD=$s; return; }
    printf -v fill '%*s' "$gap" ''
    if [ "$side" = r ]; then PAD="${fill}${s}"; else PAD="${s}${fill}"; fi
}

# --------------------------------------------------------------------------
# Frame buffer. Panels call row/hr/kv; nothing prints until the frame is done.
# --------------------------------------------------------------------------
FRAME=()
declare -A HIT=()
TCOLS=80; TROWS=24; LAYOUT=medium

row() {
    dw_cut "$1" "$TCOLS"
    FRAME+=("$CUT")
}
hr() {
    local line=""
    printf -v line '%*s' "$TCOLS" ''
    FRAME+=("${D}${line// /$RULE_CHAR}${R}")
}
blank() { FRAME+=(""); }

# kv "label" "value" — a dim label and its value.
kv() { row "  ${D}$1${R} $2"; }

# badge ok|warn|bad|idle "text"
badge() {
    case $1 in
        ok)   printf '%s' "${GRN}✓ $2${R}" ;;
        warn) printf '%s' "${YEL}▲ $2${R}" ;;
        bad)  printf '%s' "${RED}✗ $2${R}" ;;
        *)    printf '%s' "${D}· $2${R}" ;;
    esac
}

# grid item... — flow items into as many columns as the current width allows.
grid() {
    local -a items=("$@")
    local -i maxw=0 i
    for i in "${!items[@]}"; do dw "${items[i]}"; ((DW > maxw)) && maxw=$DW; done
    local -i cell=$((maxw + 3))
    local -i ncols=$(((TCOLS - 3) / cell))
    ((ncols < 1)) && ncols=1
    local line="" ; local -i col=0
    for i in "${!items[@]}"; do
        dw_pad "${items[i]}" "$maxw"
        line+="$PAD   "
        ((col++))
        if ((col == ncols)); then row "   ${line}"; line=""; col=0; fi
    done
    [ -n "$line" ] && row "   ${line}"
}

# --------------------------------------------------------------------------
# Cache access for values too slow to compute on a tick.
# --------------------------------------------------------------------------
cache() { [ -f "$CACHE_DIR/$1" ] && cat "$CACHE_DIR/$1" || printf '%s' "${2-}"; }

# 상세 화면으로 들어가는 줄. 클릭하면 그 화면이 네비게이션 스택에 쌓인다.
link() { # link <view> <arg> <text>
    row "  ${CYN}›${R} $3"
    HIT[$((${#FRAME[@]} - 1))]="nav:$1:$2"
}

# 여러 줄 텍스트를 그대로 행으로 흘려보낸다. 명령 출력을 상세에 붙일 때 쓴다.
# Given a command, runs it and emits a row per line. Given nothing, reads
# stdin -- but only ever as `rows_from < <(cmd)`, never as `cmd | rows_from`:
# the right-hand side of a pipe is a subshell, so every row it appends to FRAME
# dies with it and the section renders empty with no error anywhere. Passing
# the command as arguments is the form that cannot be got wrong.
rows_from() {
    local line
    if [ $# -gt 0 ]; then
        while IFS= read -r line; do row "  $line"; done < <("$@")
        return 0
    fi
    while IFS= read -r line; do row "  $line"; done
}

# 자동차 속도계처럼 생긴 눈금. 예산 대비 실측을 한눈에 본다.
# gauge <값> <최대> [칸수] → $GAUGE
gauge() {
    local v=$1 max=$2 w=${3:-24}
    local -i filled pos
    local pct
    pct=$(LC_ALL=C awk -v v="$v" -v m="$max" 'BEGIN{ if(m<=0){print 0}else{printf "%d", (v/m)*100} }' 2>/dev/null)
    [ -z "$pct" ] && pct=0
    filled=$(( pct * w / 100 )); ((filled > w)) && filled=$w; ((filled < 0)) && filled=0
    pos=$filled; ((pos >= w)) && pos=$((w - 1))
    local col=$GRN
    ((pct >= 70)) && col=$YEL
    ((pct >= 100)) && col=$RED
    local bar="" i
    for ((i = 0; i < w; i++)); do
        if ((i == pos)); then bar+="${col}▮${R}"
        elif ((i < filled)); then bar+="${col}━${R}"
        else bar+="${D}·${R}"
        fi
    done
    GAUGE="${D}⟨${R}${bar}${D}⟩${R} ${col}${pct}%${R}"
}

# 모드 선택 띠. 클릭한 칸을 알아내려고 각 이름의 열 범위를 기억해 둔다.
MODE_HIT_ROW=-1
MODE_RANGES=()
mode_strip() {
    [ ${#MODES[@]} -eq 0 ] && return 0
    MODE_RANGES=()
    local text="  " m label
    local -i col=3
    for m in "${MODES[@]}"; do
        label=${MODE_TITLES[$m]:-$m}
        dw "$label"; local -i lw=$DW
        MODE_RANGES+=("$col:$((col + lw + 1)):$m")
        if [ "$m" = "$MODE" ]; then text+="${B}${GRN}[${label}]${R} "
        else text+="${D} ${label} ${R}"; fi
        col=$((col + lw + 3))
    done
    row "$text"
    MODE_HIT_ROW=$((${#FRAME[@]} - 1))
    HIT[$MODE_HIT_ROW]="mode"
}

# 클립보드에 넣는다. 대시보드는 프로젝트 명령을 실행하지 않는다 — 넘겨줄 뿐이다.
clip_copy() {
    if command -v wl-copy >/dev/null 2>&1; then printf '%s' "$1" | wl-copy 2>/dev/null && return 0; fi
    if command -v xclip  >/dev/null 2>&1; then printf '%s' "$1" | xclip -selection clipboard 2>/dev/null && return 0; fi
    return 1
}

# --------------------------------------------------------------------------
# Alerts. A panel calls alert() when something worth interrupting the user
# happened -- a gate flipping from pass to fail, a budget crossed, a long job
# finishing. Deduped per key so a state that holds across many ticks fires
# once, not every second; the bell badge and the alert log persist across a
# restart because both live under CACHE_DIR, not in memory only.
# --------------------------------------------------------------------------
declare -A ALERT_LAST=()
_ALERT_STATE_LOADED=0
_alert_load_state() {
    _ALERT_STATE_LOADED=1
    [ -f "$CACHE_DIR/.alert-state" ] || return 0
    local k v
    while IFS='=' read -r k v; do [ -n "$k" ] && ALERT_LAST[$k]=$v; done < "$CACHE_DIR/.alert-state"
}

# alert <level: info|warn|bad> <key> <message> [report_path]
# report_path, if given, becomes a link into the built-in pager (detail_report).
alert() {
    local level=$1 key=$2 message=$3 report=${4:-}
    [ "$_ALERT_STATE_LOADED" = 1 ] || _alert_load_state
    [ "${ALERT_LAST[$key]:-}" = "$message" ] && return 0
    ALERT_LAST[$key]=$message
    : > "$CACHE_DIR/.alert-state"
    local k
    for k in "${!ALERT_LAST[@]}"; do printf '%s=%s\n' "$k" "${ALERT_LAST[$k]}" >> "$CACHE_DIR/.alert-state"; done
    local ts; printf -v ts '%(%s)T' -1
    printf '%s\t%s\t%s\t%s\t%s\n' "$ts" "$level" "$key" "$report" "${message//$'\n'/ }" >> "$CACHE_DIR/alerts.tsv"
    if [ "$(wc -l < "$CACHE_DIR/alerts.tsv" 2>/dev/null || echo 0)" -gt 200 ]; then
        tail -n 200 "$CACHE_DIR/alerts.tsv" > "$CACHE_DIR/.alerts.tmp" && mv "$CACHE_DIR/.alerts.tmp" "$CACHE_DIR/alerts.tsv"
    fi
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -a dashboard "${PROJECT_NAME}" "$message" 2>/dev/null
    else
        printf '\a' > /dev/tty 2>/dev/null
    fi
}

alert_unseen() {
    [ -f "$CACHE_DIR/alerts.tsv" ] || { printf 0; return; }
    local seen=0
    [ -f "$CACHE_DIR/.alerts-seen" ] && seen=$(cat "$CACHE_DIR/.alerts-seen" 2>/dev/null)
    awk -F'\t' -v s="${seen:-0}" '$1+0>s+0' "$CACHE_DIR/alerts.tsv" 2>/dev/null | wc -l
}
alerts_mark_seen() { local now; printf -v now '%(%s)T' -1; printf '%s' "$now" > "$CACHE_DIR/.alerts-seen" 2>/dev/null; }

# --------------------------------------------------------------------------
# Trend metrics. record_metric appends a timestamped reading; sparkline turns
# recent readings into a one-line unicode bar chart in $SPARK. Call
# record_metric wherever a fresh number is actually measured -- typically
# panel_medium or right after a SLOW_JOBS command -- never every tick.
# --------------------------------------------------------------------------
record_metric() { # record_metric <name> <value> [max_points=200]
    local name=$1 value=$2 max=${3:-200}
    local dir="$CACHE_DIR/metrics" f
    mkdir -p "$dir" 2>/dev/null
    f="$dir/$name.tsv"
    local ts; printf -v ts '%(%s)T' -1
    printf '%s\t%s\n' "$ts" "$value" >> "$f"
    if [ "$(wc -l < "$f" 2>/dev/null || echo 0)" -gt "$max" ]; then
        tail -n "$max" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    fi
}

SPARK=""
sparkline() { # sparkline <name> [width=20] -> $SPARK
    local name=$1 width=${2:-20}
    local f="$CACHE_DIR/metrics/$name.tsv"
    SPARK="${D}(no data)${R}"
    [ -f "$f" ] || return 0
    local -a vals; mapfile -t vals < <(tail -n "$width" "$f" 2>/dev/null | cut -f2)
    ((${#vals[@]})) || return 0
    local min=${vals[0]} max=${vals[0]} v
    for v in "${vals[@]}"; do
        LC_ALL=C awk -v v="$v" -v m="$min" 'BEGIN{exit !(v+0<m+0)}' 2>/dev/null && min=$v
        LC_ALL=C awk -v v="$v" -v m="$max" 'BEGIN{exit !(v+0>m+0)}' 2>/dev/null && max=$v
    done
    local range; range=$(LC_ALL=C awk -v a="$max" -v b="$min" 'BEGIN{d=a-b; print (d==0?1:d)}')
    local blocks=(▁ ▂ ▃ ▄ ▅ ▆ ▇ █)
    local out="" idx
    for v in "${vals[@]}"; do
        idx=$(LC_ALL=C awk -v v="$v" -v b="$min" -v r="$range" 'BEGIN{i=int((v-b)/r*7+0.5); if(i<0)i=0; if(i>7)i=7; print i}')
        out+="${blocks[idx]}"
    done
    SPARK="$out"
}
cache_age() {
    local f=$CACHE_DIR/$1
    [ -f "$f" ] || { AGE=-1; AGE_TEXT="never"; return; }
    local -i mt now
    mt=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0)
    printf -v now '%(%s)T' -1
    AGE=$((now - mt))
    if   ((AGE < 90));   then AGE_TEXT="${AGE}s ago"
    elif ((AGE < 5400)); then AGE_TEXT="$((AGE / 60))m ago"
    else                      AGE_TEXT="$((AGE / 3600))h ago"; fi
}

# --------------------------------------------------------------------------
# Terminal capabilities, measured rather than assumed.
#
# DECRQM (CSI ? Ps $ p) asks the terminal whether it knows a private mode. The
# reply is CSI ? Ps ; Pm $ y, where Pm 0 means "never heard of it" and 1-4 mean
# set / reset / permanently set / permanently reset. Terminals that ignore
# DECRQM stay silent, so the read times out and we fall back to terminfo.
# --------------------------------------------------------------------------
CAP_TTY=no; CAP_ALT=no; CAP_MOUSE=no; CAP_ALT_WHY=""; CAP_MOUSE_WHY=""
CAP_DECRQM_1000=""; CAP_DECRQM_1049=""

decrqm() {
    DECRQM="silent"
    [ -t 0 ] && [ -t 1 ] || { DECRQM="no-tty"; return; }
    local saved reply=""
    saved=$(stty -g 2>/dev/null) || { DECRQM="no-stty"; return; }
    stty raw -echo min 0 time 0 2>/dev/null
    printf '\e[?%s$p' "$1" >/dev/tty
    IFS= read -r -s -t 0.35 -d 'y' reply </dev/tty
    stty "$saved" 2>/dev/null
    case $reply in
        *';0$'*) DECRQM="unsupported" ;;
        *';1$'*|*';2$'*|*';3$'*|*';4$'*) DECRQM="supported" ;;
        "") DECRQM="silent" ;;
        *) DECRQM="silent" ;;
    esac
}

probe_caps() {
    [ -t 1 ] && CAP_TTY=yes
    : "${TERM:=}"
    if [ -z "$TERM" ] || [ "$TERM" = dumb ]; then
        export TERM=xterm-256color
        CAP_ALT_WHY="TERM was empty; assumed xterm-256color"
    fi

    if [ "$CAP_TTY" = no ]; then
        CAP_ALT_WHY="stdout is not a terminal"; CAP_MOUSE_WHY="stdout is not a terminal"
        return
    fi

    if tput smcup >/dev/null 2>&1 && [ -n "$(tput smcup 2>/dev/null)" ]; then
        CAP_ALT=yes; CAP_ALT_WHY="terminfo smcup present"
    else
        decrqm 1049; CAP_DECRQM_1049=$DECRQM
        if [ "$DECRQM" = supported ]; then
            CAP_ALT=yes; CAP_ALT_WHY="DECRQM 1049 supported (no terminfo smcup)"
        else
            CAP_ALT=no; CAP_ALT_WHY="no terminfo smcup, DECRQM 1049 $DECRQM"
        fi
    fi

    [ "$WANT_MOUSE" = no ] && { CAP_MOUSE_WHY="disabled with --no-mouse"; return; }
    decrqm 1000; CAP_DECRQM_1000=$DECRQM
    case $DECRQM in
        supported) CAP_MOUSE=yes; CAP_MOUSE_WHY="DECRQM 1000 answered" ;;
        unsupported) CAP_MOUSE=no; CAP_MOUSE_WHY="DECRQM 1000 answered: mode unknown to terminal" ;;
        *)
            if [ -n "$(tput kmous 2>/dev/null)" ]; then
                CAP_MOUSE=yes; CAP_MOUSE_WHY="DECRQM $DECRQM, terminfo kmous present"
            else
                CAP_MOUSE=no; CAP_MOUSE_WHY="DECRQM $DECRQM, no terminfo kmous"
            fi ;;
    esac
}

print_probe() {
    probe_caps
    printf 'terminal capability probe\n'
    printf '  TERM              %s\n' "${TERM:-(empty)}"
    printf '  stdout is a tty   %s\n' "$CAP_TTY"
    printf '  DECRQM ?1000      %s\n' "${CAP_DECRQM_1000:-not queried}"
    printf '  DECRQM ?1049      %s\n' "${CAP_DECRQM_1049:-not queried (terminfo answered first)}"
    printf '  terminfo smcup    %s\n' "$([ -n "$(tput smcup 2>/dev/null)" ] && echo present || echo absent)"
    printf '  terminfo kmous    %s\n' "$([ -n "$(tput kmous 2>/dev/null)" ] && echo present || echo absent)"
    printf '\n'
    printf '  alternate screen  %s  (%s)\n' "$CAP_ALT" "$CAP_ALT_WHY"
    printf '  mouse tracking    %s  (%s)\n' "$CAP_MOUSE" "$CAP_MOUSE_WHY"
    if [ "$CAP_MOUSE" = yes ]; then
        printf '\n  click a section header to fold it, a body line for detail, the header bar to refresh.\n'
    else
        printf '\n  falling back to keys: space/r refresh, 1-9 toggle a section, q quit.\n'
    fi
}

# --------------------------------------------------------------------------
# Screen control
# --------------------------------------------------------------------------
term_size() {
    local c l
    c=$(tput cols 2>/dev/null) || c=""
    l=$(tput lines 2>/dev/null) || l=""
    if [ -z "$c" ] || [ -z "$l" ] || [ "$c" -lt 20 ] 2>/dev/null; then
        if read -r l c < <(stty size 2>/dev/null </dev/tty); then :; else
            c=${DASH_COLS:-96}; l=${DASH_ROWS:-40}
        fi
    fi
    TCOLS=${c:-96}; TROWS=${l:-40}
    if   ((TCOLS < 72));  then LAYOUT=narrow
    elif ((TCOLS < 104)); then LAYOUT=medium
    else                       LAYOUT=wide; fi
}

ENTERED_ALT=0
enter_screen() {
    [ "$CAP_TTY" = yes ] || return 0
    if [ "$WANT_ALT" = 1 ] && [ "$CAP_ALT" = yes ]; then
        tput smcup 2>/dev/null || printf '\e[?1049h'
        ENTERED_ALT=1
    else
        # No alternate screen: clear once, then repaint in place. Frames are
        # written from the home position and never scroll, so nothing piles up
        # in the scrollback either way.
        clear 2>/dev/null || printf '\e[H\e[2J'
    fi
    tput civis 2>/dev/null || printf '\e[?25l'
    # Echo off for the whole run, not just inside `read -s`. Anything arriving
    # while a frame is being painted is echoed by the terminal driver
    # otherwise, and with mouse tracking on a single click is a burst of bytes
    # -- which is what "clicking types escape sequences at me" actually is.
    STTY_SAVED=$(stty -g 2>/dev/null) && stty -echo 2>/dev/null
    [ "$CAP_MOUSE" = yes ] && printf '\e[?1000h\e[?1002h\e[?1006h'
    return 0
}
LEFT_SCREEN=0
STTY_SAVED=""
leave_screen() {
    [ "$CAP_TTY" = yes ] || return 0
    [ "$LEFT_SCREEN" = 1 ] && return 0
    LEFT_SCREEN=1
    [ "$CAP_MOUSE" = yes ] && printf '\e[?1006l\e[?1002l\e[?1000l'
    [ -n "${STTY_SAVED:-}" ] && stty "$STTY_SAVED" 2>/dev/null
    tput cnorm 2>/dev/null || printf '\e[?25h'
    if [ "$ENTERED_ALT" = 1 ]; then
        tput rmcup 2>/dev/null || printf '\e[?1049l'
    else
        printf '\n'
    fi
    return 0
}

# Paint from the home position, erasing each line as it is rewritten and the
# rest of the screen at the end. No full clear, so no flicker; no newline after
# the last visible row, so the frame never scrolls into the scrollback.
paint() {
    local -i total=${#FRAME[@]}
    local -i chrome=$FRAME_CHROME; ((chrome > total)) && chrome=$total
    local -i visible=$((TROWS - chrome)); ((visible < 1)) && visible=1
    local -i max_scroll=$((total - chrome - visible)); ((max_scroll < 0)) && max_scroll=0
    ((VIEW_SCROLL > max_scroll)) && VIEW_SCROLL=$max_scroll
    ((VIEW_SCROLL < 0)) && VIEW_SCROLL=0
    local -i start=$((chrome + VIEW_SCROLL))
    local -i last=$((start + visible - 1)); ((last > total - 1)) && last=$((total - 1))
    local out="" i first=1
    for ((i = 0; i < chrome; i++)); do
        [ "$first" = 1 ] || out+=$'\n'; first=0
        out+="${FRAME[i]}"$'\e[K'
    done
    for ((i = start; i <= last; i++)); do
        [ "$first" = 1 ] || out+=$'\n'; first=0
        out+="${FRAME[i]}"$'\e[K'
    done
    printf '\e[H%s\e[J' "$out"
}

# --------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------
declare -A SECTION_TITLES=()
declare -A COLLAPSED=()
declare -A MODE_TITLES=()
declare -A VIEW_TITLES=()
declare -A EDIT_TARGETS=()
declare -A CTX_TITLES=()
MODES=()
MODE_DEFAULT=""
MODE=""
COMMANDS=()
SECTIONS=()
SLOW_JOBS=()
CTXS=()
CTX_DEFAULT=""
PROJECT_NAME=$(basename "$ROOT")
CACHE_DIR=".dashboard-cache"

# shellcheck disable=SC1090
. "$PANEL"

case $CACHE_DIR in /*) ;; *) CACHE_DIR="$ROOT/$CACHE_DIR" ;; esac
mkdir -p "$CACHE_DIR" 2>/dev/null
CACHE_HOME=$CACHE_DIR


declare -F panel_fast        >/dev/null || panel_fast() { :; }
declare -F panel_medium      >/dev/null || panel_medium() { :; }
declare -F panel_fingerprint >/dev/null || panel_fingerprint() { :; }
declare -F panel_verdict     >/dev/null || panel_verdict() { :; }

# 고른 모드는 캐시에 남겨 다음 실행에도 이어진다.
if [ ${#MODES[@]} -gt 0 ]; then
    MODE=$(cat "$CACHE_DIR/mode" 2>/dev/null)
    case " ${MODES[*]} " in
        *" $MODE "*) ;;
        *) MODE=${MODE_DEFAULT:-${MODES[0]}} ;;
    esac
fi
mode_set() {
    MODE=$1
    printf '%s' "$MODE" > "$CACHE_DIR/mode" 2>/dev/null
    FINGERPRINT=""
    VIEW_SCROLL=0
}
mode_cycle() {
    local -i i
    for i in "${!MODES[@]}"; do
        if [ "${MODES[i]}" = "$MODE" ]; then
            mode_set "${MODES[$(((i + 1) % ${#MODES[@]}))]}"; return 0
        fi
    done
    mode_set "${MODES[0]}"
}
ctx_cycle() {
    local -i i
    for i in "${!CTXS[@]}"; do
        if [ "${CTXS[i]}" = "$CTX" ]; then
            ctx_set "${CTXS[$(((i + 1) % ${#CTXS[@]}))]}"; return 0
        fi
    done
    ((${#CTXS[@]})) && ctx_set "${CTXS[0]}"
}

# --------------------------------------------------------------------------
# Direct edit. A panel opts a screen into this by setting
# EDIT_TARGETS[view]=path -- everything else stays read-only. Pressing e (or
# clicking the hint the breadcrumb shows) suspends the alt-screen, hands the
# terminal to $VISUAL/$EDITOR, and forces a refresh on return.
# --------------------------------------------------------------------------
edit_current() {
    local -i n=${#NAV_VIEW[@]}
    ((n)) || return 0
    local target=${EDIT_TARGETS[${NAV_VIEW[$((n - 1))]}]:-}
    [ -n "$target" ] || return 0
    leave_screen
    "${VISUAL:-${EDITOR:-vi}}" "$target" </dev/tty >/dev/tty 2>&1
    LEFT_SCREEN=0
    enter_screen
    FINGERPRINT=""
}

# --------------------------------------------------------------------------
# Worktree/context switch. Auto-populated from `git worktree list` when a
# panel does not declare CTXS -- a repo with only one worktree never shows the
# strip, since there is nothing to choose. Switching actually `cd`s, so every
# git call after it reads the chosen worktree; each context keeps its own
# slow-job cache so one worktree's test run never overwrites another's.
# --------------------------------------------------------------------------
CTX=""
_ctx_slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9' '_'; }
ctx_cache_dir() { printf '%s/ctx-%s' "$CACHE_HOME" "$(_ctx_slug "$1")"; }
ctx_set() {
    CTX=$1
    cd "$CTX" 2>/dev/null || return 0
    CACHE_DIR=$(ctx_cache_dir "$CTX")
    mkdir -p "$CACHE_DIR" 2>/dev/null
    printf '%s' "$CTX" > "$CACHE_HOME/.ctx" 2>/dev/null
    FINGERPRINT=""
    VIEW_SCROLL=0
}
CTX_RANGES=()
ctx_strip() {
    ((${#CTXS[@]} > 1)) || return 0
    CTX_RANGES=()
    local text="  " c label
    local -i col=3
    for c in "${CTXS[@]}"; do
        label=${CTX_TITLES[$c]:-$(basename "$c")}
        dw "$label"; local -i lw=$DW
        CTX_RANGES+=("$col:$((col + lw + 1)):$c")
        if [ "$c" = "$CTX" ]; then text+="${B}${GRN}[${label}]${R} "
        else text+="${D} ${label} ${R}"; fi
        col=$((col + lw + 3))
    done
    row "$text"
    HIT[$((${#FRAME[@]} - 1))]="ctx"
}
# 워크트리가 하나뿐이면 선택할 게 없다 - 그때는 목록도 비운다.
if [ ${#CTXS[@]} -eq 0 ]; then
    while IFS= read -r _wt_line; do
        [[ $_wt_line == worktree\ * ]] && CTXS+=("${_wt_line#worktree }")
    done < <(git -C "$ROOT" worktree list --porcelain 2>/dev/null)
    ((${#CTXS[@]} <= 1)) && CTXS=()
fi
if ((${#CTXS[@]} > 1)); then
    CTX=$(cat "$CACHE_HOME/.ctx" 2>/dev/null)
    case " ${CTXS[*]} " in *" $CTX "*) ;; *) CTX=${CTX_DEFAULT:-$ROOT} ;; esac
    ctx_set "$CTX"
fi


# --------------------------------------------------------------------------
# Refresh budget. Fast work runs on every tick. Medium work runs only when the
# working tree fingerprint moves, so an idle tick costs a couple of git calls
# and nothing else. Slow work never runs here at all; it is read from the cache
# that dashboard-refresh.sh writes.
# --------------------------------------------------------------------------
FINGERPRINT=""
run_checks() {
    local fp
    fp=$(git status --porcelain -uall 2>/dev/null | cksum)$(panel_fingerprint)
    if [ "$fp" != "$FINGERPRINT" ]; then
        panel_medium
        FINGERPRINT=$fp
    fi
    dash_read_signal
    panel_fast
}

build_frame() {
    FRAME=(); HIT=(); CUR_VIEW=""
    local stamp; printf -v stamp '%(%H:%M:%S)T' -1

    local -i n_unseen; n_unseen=$(alert_unseen)
    local bell=""; BELL_RANGE=""
    if ((n_unseen > 0)); then bell=" ${RED}🔔${n_unseen}${R}"; fi

    local left="${B}${CYN}${PROJECT_NAME}${R}${bell}"
    local right="${D}${stamp}${R}"
    dw "$left"; local -i lw=$DW
    dw "$right"; local -i rw=$DW
    if ((n_unseen > 0)); then
        # 종 배지는 프로젝트 이름 바로 뒤에 있다. 그 열 범위만 따로 기억해서
        # 헤더 줄 클릭이 갱신인지 종 클릭인지 가른다.
        dw "${B}${CYN}${PROJECT_NAME}${R}"; local -i namecol=$((DW + 1))
        dw "$bell"; local -i bellw=$DW
        BELL_RANGE="${namecol}:$((namecol + bellw - 1))"
    fi
    if ((lw + rw + 2 <= TCOLS)); then
        dw_pad "$left" $((TCOLS - rw))
        FRAME+=("${PAD}${right}")
    else
        FRAME+=("$left")
    fi
    HIT[0]="refresh"
    hr
    ctx_strip
    FRAME_CHROME=${#FRAME[@]}

    # The signal block sits above the sections because it is the one thing on
    # the frame that is not derived from the repository: it is the session
    # talking, and it is answered here rather than in another window.
    if [ -n "$DASH_NOTE" ] || [ -n "$DASH_QUESTION" ]; then
        [ -n "$DASH_NOTE" ] && row " ${CYN}◆${R} ${DASH_NOTE}"
        if [ -n "$DASH_QUESTION" ]; then
            row " ${B}? ${DASH_QUESTION}${R}"
            local -i oi=0
            for opt in "${DASH_OPTION_LIST[@]}"; do
                [ -n "$opt" ] || continue
                row "   ${CYN}▸${R} ${opt}"
                HIT[$((${#FRAME[@]} - 1))]="signal:$oi"
                oi=$((oi + 1))
            done
        fi
        hr
    fi

    local -i n=0 idx
    for idx in "${!SECTIONS[@]}"; do
        local name=${SECTIONS[idx]}
        n=$((idx + 1))
        local title=${SECTION_TITLES[$name]:-$name}
        local mark="▾"
        [ -n "${COLLAPSED[$name]:-}" ] && mark="▸"
        row " ${D}${n}${R} ${mark} ${B}${title}${R}"
        HIT[$((${#FRAME[@]} - 1))]="section:$name"
        if [ -z "${COLLAPSED[$name]:-}" ]; then
            local before=${#FRAME[@]}
            "section_$name"
            local after=${#FRAME[@]} j
            # 이미 주인이 있는 줄(link, mode)은 건드리지 않는다. 덮어쓰면
            # 그 줄의 클릭이 통째로 구획 본문 클릭으로 바뀐다.
            for ((j = before; j < after; j++)); do
                [ -z "${HIT[$j]:-}" ] && HIT[$j]="body:$name:$((j - before))"
            done
        fi
        ((idx < ${#SECTIONS[@]} - 1)) && hr
    done

    local verdict; verdict=$(panel_verdict)
    if [ -n "$verdict" ]; then hr; row " $verdict"; fi

    if [ "$ONCE" = 0 ] && [ "$CAP_TTY" = yes ]; then
        local hint extra=""
        ((${#MODES[@]}))    && extra+=" · m mode"
        ((${#CTXS[@]} > 1)) && extra+=" · w worktree"
        if [ "$CAP_MOUSE" = yes ]; then
            hint="click: fold section · body line for detail · header to refresh${extra}   q quit"
        else
            hint="space refresh · 1-9 fold section${extra} · q quit   ${D}(mouse: $CAP_MOUSE_WHY)${R}"
        fi
        while ((${#FRAME[@]} < TROWS - 1)); do blank; done
        row "${D}${hint}${R}"
    fi
}

declare -F detail_alerts >/dev/null || detail_alerts() {
    alerts_mark_seen
    if [ ! -s "$CACHE_DIR/alerts.tsv" ]; then
        row "  ${D}알림 없음 — 아직 alert()가 불린 적이 없다${R}"
        return
    fi
    local ts level key report message icon when whentxt
    while IFS=$'\t' read -r ts level key report message; do
        case $level in
            bad)  icon="${RED}✕${R}" ;;
            warn) icon="${YEL}!${R}" ;;
            *)    icon="${CYN}i${R}" ;;
        esac
        when=$(( $(date +%s) - ts )); ((when < 0)) && when=0
        if   ((when < 60));   then whentxt="${when}s"
        elif ((when < 3600)); then whentxt="$((when/60))m"
        else                       whentxt="$((when/3600))h"; fi
        if [ -n "$report" ] && [ -f "$report" ]; then
            link report "$report" "${icon} ${D}${whentxt} 전${R}  ${message}"
        else
            row "  ${icon} ${D}${whentxt} 전${R}  ${message}"
        fi
    done < <(tac "$CACHE_DIR/alerts.tsv" 2>/dev/null || tail -r "$CACHE_DIR/alerts.tsv" 2>/dev/null)
}

# --------------------------------------------------------------------------
# Built-in pager. Any link/alert that points at a text file opens here,
# staying inside the alt-screen rather than shelling out to less/vim -- the
# whole reading experience stays inside this one process and this one screen.
# --------------------------------------------------------------------------
PAGER_FILE=""; PAGER_LINES=(); PAGER_TOP=0; PAGER_QUERY=""

# Any screen taller than the terminal scrolls its body by wheel, the header
# and breadcrumb stay put. FRAME_CHROME is how many leading FRAME rows the
# current build_frame/build_view call pinned before its body began.
FRAME_CHROME=0
VIEW_SCROLL=0
declare -a PAGER_MATCHES=(); PAGER_MIDX=-1

_pager_load() {
    [ "$PAGER_FILE" = "$1" ] && return 0
    PAGER_FILE=$1; PAGER_TOP=0; PAGER_QUERY=""; PAGER_MATCHES=(); PAGER_MIDX=-1
    if [ -r "$1" ]; then
        mapfile -t PAGER_LINES < "$1"
    else
        PAGER_LINES=("${D}읽을 수 없다: $1${R}")
    fi
}
_pager_search() {
    PAGER_MATCHES=(); PAGER_MIDX=-1
    [ -n "$PAGER_QUERY" ] || return 0
    local i
    for i in "${!PAGER_LINES[@]}"; do
        [[ ${PAGER_LINES[i]} == *"$PAGER_QUERY"* ]] && PAGER_MATCHES+=("$i")
    done
}
_pager_next_match() {
    ((${#PAGER_MATCHES[@]})) || return 0
    PAGER_MIDX=$(( (PAGER_MIDX + 1) % ${#PAGER_MATCHES[@]} ))
    PAGER_TOP=${PAGER_MATCHES[$PAGER_MIDX]}
}
_pager_prev_match() {
    ((${#PAGER_MATCHES[@]})) || return 0
    PAGER_MIDX=$(( (PAGER_MIDX - 1 + ${#PAGER_MATCHES[@]}) % ${#PAGER_MATCHES[@]} ))
    PAGER_TOP=${PAGER_MATCHES[$PAGER_MIDX]}
}
_pager_prompt_search() {
    printf '\e[%d;1H\e[2K/' "$TROWS"
    [ -n "$STTY_SAVED" ] && stty "$STTY_SAVED" 2>/dev/null </dev/tty
    tput cnorm 2>/dev/null
    local q=""; IFS= read -r q </dev/tty
    stty -echo -icanon min 0 time 0 2>/dev/null </dev/tty
    tput civis 2>/dev/null
    PAGER_QUERY=$q; _pager_search; _pager_next_match
}

declare -F detail_report >/dev/null || detail_report() {
    _pager_load "$1"
    local -i avail=$((TROWS - 6)); ((avail < 3)) && avail=3
    local -i total=${#PAGER_LINES[@]}
    ((PAGER_TOP > total - avail)) && PAGER_TOP=$((total - avail))
    ((PAGER_TOP < 0)) && PAGER_TOP=0
    local -i i last=0
    for ((i = PAGER_TOP; i < PAGER_TOP + avail && i < total; i++)); do
        if [ -n "$PAGER_QUERY" ] && [[ ${PAGER_LINES[i]} == *"$PAGER_QUERY"* ]]; then
            row "  ${YEL}${PAGER_LINES[i]}${R}"
        else
            row "  ${PAGER_LINES[i]}"
        fi
        last=$((i + 1))
    done
    local m=""
    ((${#PAGER_MATCHES[@]})) && m="  ${D}검색 '${PAGER_QUERY}' ${GRN}$((PAGER_MIDX + 1))/${#PAGER_MATCHES[@]}${R}"
    row "${D}$((PAGER_TOP + 1))-${last}/${total}  j/k 스크롤 · gg/G 처음·끝 · / 검색 · n/N 다음·이전${R}${m}"
}

# 상세 화면은 쌓인다. 뒤로 가면 한 장씩 벗겨진다.
NAV_VIEW=(); NAV_ARG=(); NAV_TITLE=()

# 화면 이름은 VIEW_TITLES, 없으면 구획 제목, 그것도 없으면 내부 이름을 쓴다.
view_title() { printf '%s' "${VIEW_TITLES[$1]:-${SECTION_TITLES[$1]:-$1}}"; }
nav_push() { NAV_VIEW+=("$1"); NAV_ARG+=("$2"); NAV_TITLE+=("$(view_title "$1")"); VIEW_SCROLL=0; }
nav_pop() {
    local -i n=${#NAV_VIEW[@]}
    ((n)) || return 0
    NAV_VIEW=("${NAV_VIEW[@]:0:$((n - 1))}")
    NAV_ARG=("${NAV_ARG[@]:0:$((n - 1))}")
    NAV_TITLE=("${NAV_TITLE[@]:0:$((n - 1))}")
    VIEW_SCROLL=0
}
nav_depth() { printf '%d' "${#NAV_VIEW[@]}"; }

CUR_VIEW=""
build_view() {
    FRAME=(); HIT=()
    local -i n=${#NAV_VIEW[@]} i
    local view=${NAV_VIEW[$((n - 1))]} arg=${NAV_ARG[$((n - 1))]}
    CUR_VIEW=$view

    local crumb="${D}${PROJECT_NAME}${R}"
    for ((i = 0; i < n; i++)); do crumb+="${D} › ${R}${B}${NAV_TITLE[i]}${R}"; done
    row " $crumb"
    HIT[0]="refresh"
    row " ${CYN}←${R} ${D}뒤로  (esc · backspace · 우클릭)${R}"
    HIT[1]="back"
    hr
    FRAME_CHROME=${#FRAME[@]}

    if declare -F "detail_$view" >/dev/null; then
        "detail_$view" "$arg"
    else
        row "  ${D}이 화면에는 상세가 없다: ${view}${R}"
    fi

    if [ "$CAP_TTY" = yes ]; then
        local editable=""
        [ -n "${EDIT_TARGETS[$view]:-}" ] && editable=" · e 편집"
        while ((${#FRAME[@]} < TROWS - 1)); do blank; done
        row "${D}esc 뒤로${editable} · q 종료${R}"
    fi
}

# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------
MOUSE_SEEN=0
handle_mouse() {
    # SGR 1006: ESC [ < btn ; col ; row (M press | m release)
    MOUSE_SEEN=0
    local seq="" ch
    while read -rsn1 -t 0.05 ch; do
        seq+=$ch
        [[ $ch == [Mm] ]] && break
        ((${#seq} > 24)) && break
    done
    # ESC 다음의 '[' 는 아직 여기 남아 있다. 벗겨내지 않으면 아래 검사가
    # 항상 실패해서 클릭이 통째로 무시된다.
    seq=${seq#\[}
    [[ $seq == \<*[Mm] ]] || return 0
    MOUSE_SEEN=1
    [[ $seq == *M ]] || return 0
    local body=${seq:1:$((${#seq} - 2))}
    local btn=${body%%;*}; local rest=${body#*;}
    local y=${rest#*;}
    if ((btn == 2)); then nav_pop; return 0; fi
    if ((btn == 64)); then
        if [ "$CUR_VIEW" = report ]; then
            ((PAGER_TOP -= 3)); ((PAGER_TOP < 0)) && PAGER_TOP=0
        else
            ((VIEW_SCROLL -= 3)); ((VIEW_SCROLL < 0)) && VIEW_SCROLL=0
        fi
        return 0
    fi
    if ((btn == 65)); then
        if [ "$CUR_VIEW" = report ]; then
            PAGER_TOP=$((PAGER_TOP + 3))
        else
            VIEW_SCROLL=$((VIEW_SCROLL + 3))
        fi
        return 0
    fi
    ((btn == 0)) || return 0
    local x=${body#*;}; x=${x%%;*}
    # paint() shows the chrome rows, then the body from VIEW_SCROLL onward, so a
    # screen row below the chrome names a FRAME row that far further down. Look
    # up the row the user actually clicked, not the one that used to be there.
    local -i _row=$((y - 1))
    ((_row >= FRAME_CHROME)) && _row=$((_row + VIEW_SCROLL))
    local target=${HIT[$_row]:-}
    case $target in
        refresh)
            if [ -n "${BELL_RANGE:-}" ]; then
                local bs=${BELL_RANGE%%:*} be=${BELL_RANGE#*:}
                if ((x >= bs && x <= be)); then
                    nav_push alerts ""; alerts_mark_seen; dash_emit alerts opened; return 0
                fi
            fi
            FINGERPRINT="" ;;
        back) nav_pop ;;
        mode)
            local r start stop mname
            for r in "${MODE_RANGES[@]}"; do
                start=${r%%:*}; stop=${r#*:}; mname=${stop#*:}; stop=${stop%%:*}
                if ((x >= start && x <= stop)); then
                    mode_set "$mname"; dash_emit mode name "$mname"; return 0
                fi
            done
            mode_cycle; dash_emit mode name "$MODE" ;;
        ctx)
            local rc startc stopc cname
            for rc in "${CTX_RANGES[@]}"; do
                startc=${rc%%:*}; stopc=${rc#*:}; cname=${stopc#*:}; stopc=${stopc%%:*}
                if ((x >= startc && x <= stopc)); then
                    ctx_set "$cname"; dash_emit ctx path "$cname"; return 0
                fi
            done ;;
        nav:*)
            local spec=${target#nav:}
            local view=${spec%%:*} narg=${spec#*:}
            if declare -F "detail_$view" >/dev/null; then
                nav_push "$view" "$narg"
                dash_emit detail view "$view" arg "$narg"
            fi ;;
        section:*)
            local name=${target#section:}
            if [ -n "${COLLAPSED[$name]:-}" ]; then unset "COLLAPSED[$name]"; else COLLAPSED[$name]=1; fi
            VIEW_SCROLL=0
            dash_emit "$(fold_state "$name")" section "$name" ;;
        signal:*)
            local choice=${DASH_OPTION_LIST[${target#signal:}]:-}
            if [ -n "$choice" ]; then
                dash_emit answer question "$DASH_QUESTION" choice "$choice"
                DASH_QUESTION=""; DASH_OPTIONS=""; DASH_OPTION_LIST=()
                DASH_NOTE="답을 보냈다 / answer sent: $choice"
            fi ;;
        body:*)
            local rest2=${target#body:}
            local name=${rest2%%:*}
            if declare -F "detail_$name" >/dev/null; then
                nav_push "$name" "${rest2##*:}"
                dash_emit detail section "$name" row "${rest2##*:}"
            fi ;;
    esac
}

fold_state() { [ -n "${COLLAPSED[$1]:-}" ] && printf folded || printf open; }

toggle_index() {
    local -i i=$1
    ((i >= 1 && i <= ${#SECTIONS[@]})) || return 0
    local name=${SECTIONS[$((i - 1))]}
    if [ -n "${COLLAPSED[$name]:-}" ]; then unset "COLLAPSED[$name]"; else COLLAPSED[$name]=1; fi
    VIEW_SCROLL=0
    # Folding is the only navigation available with keys alone, which makes it
    # the only signal a terminal without mouse support can send back.
    dash_emit "$(fold_state "$name")" section "$name"
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
if [ "$PROBE_ONLY" = 1 ]; then print_probe; exit 0; fi

if [ "$ONCE" = 1 ]; then
    CAP_TTY=$([ -t 1 ] && echo yes || echo no)
    term_size
    run_checks
    build_frame
    printf '%s\n' "${FRAME[@]}"
    exit 0
fi

probe_caps
RESIZED=1
trap 'RESIZED=1' WINCH
trap 'leave_screen; exit 0' INT TERM
trap 'leave_screen' EXIT
enter_screen

while :; do
    term_size
    if [ "$(nav_depth)" != 0 ]; then
        build_view
    else
        run_checks
        build_frame
    fi
    paint
    RESIZED=0

    key=""
    if read -rsn1 -t "$INTERVAL" key; then
        if [ "$(nav_depth)" != 0 ] && [ "$CUR_VIEW" = report ]; then
            case $key in
                q|Q) break ;;
                $'\e') handle_mouse; [ "$MOUSE_SEEN" = 1 ] || nav_pop ;;
                $'\177'|$'\b') nav_pop ;;
                j) ((PAGER_TOP++)) ;;
                k) ((PAGER_TOP > 0)) && ((PAGER_TOP--)) ;;
                d) ((PAGER_TOP += 10)) ;;
                u|b) ((PAGER_TOP -= 10)); ((PAGER_TOP < 0)) && PAGER_TOP=0 ;;
                g)
                    local k2=""; read -rsn1 -t 0.3 k2 </dev/tty
                    [ "$k2" = g ] && PAGER_TOP=0 ;;
                G) PAGER_TOP=999999999 ;;
                /) _pager_prompt_search ;;
                n) _pager_next_match ;;
                N) _pager_prev_match ;;
                ' '|r|R) FINGERPRINT="" ;;
            esac
            continue
        fi
        if [ "$(nav_depth)" != 0 ]; then
            case $key in
                q|Q) break ;;
                $'\e') handle_mouse; [ "$MOUSE_SEEN" = 1 ] || nav_pop ;;
                $'\177'|$'\b'|b|B) nav_pop ;;
                e) edit_current ;;
                ' '|r|R) FINGERPRINT="" ;;
            esac
            continue
        fi
        case $key in
            q|Q) break ;;
            ' '|r|R) FINGERPRINT="" ;;
            m|M) [ ${#MODES[@]} -gt 0 ] && mode_cycle && dash_emit mode name "$MODE" ;;
            w|W) [ ${#CTXS[@]} -gt 1 ] && ctx_cycle && dash_emit ctx path "$CTX" ;;
            [1-9]) toggle_index "$key" ;;
            $'\e') handle_mouse ;;
        esac
    fi
done
leave_screen
