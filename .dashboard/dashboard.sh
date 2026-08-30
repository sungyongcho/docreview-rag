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
    [ "$CAP_MOUSE" = yes ] && printf '\e[?1000h\e[?1002h\e[?1006h'
    return 0
}
LEFT_SCREEN=0
leave_screen() {
    [ "$CAP_TTY" = yes ] || return 0
    [ "$LEFT_SCREEN" = 1 ] && return 0
    LEFT_SCREEN=1
    [ "$CAP_MOUSE" = yes ] && printf '\e[?1006l\e[?1002l\e[?1000l'
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
    local out="" i last=$((${#FRAME[@]} - 1))
    ((last > TROWS - 1)) && last=$((TROWS - 1))
    for ((i = 0; i <= last; i++)); do
        out+="${FRAME[i]}"$'\e[K'
        ((i < last)) && out+=$'\n'
    done
    printf '\e[H%s\e[J' "$out"
}

# --------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------
declare -A SECTION_TITLES=()
declare -A COLLAPSED=()
SECTIONS=()
SLOW_JOBS=()
PROJECT_NAME=$(basename "$ROOT")
CACHE_DIR=".dashboard-cache"

# shellcheck disable=SC1090
. "$PANEL"

case $CACHE_DIR in /*) ;; *) CACHE_DIR="$ROOT/$CACHE_DIR" ;; esac
mkdir -p "$CACHE_DIR" 2>/dev/null

declare -F panel_fast        >/dev/null || panel_fast() { :; }
declare -F panel_medium      >/dev/null || panel_medium() { :; }
declare -F panel_fingerprint >/dev/null || panel_fingerprint() { :; }
declare -F panel_verdict     >/dev/null || panel_verdict() { :; }

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
    panel_fast
}

build_frame() {
    FRAME=(); HIT=()
    local stamp; printf -v stamp '%(%H:%M:%S)T' -1

    local left="${B}${CYN}${PROJECT_NAME}${R}"
    local right="${D}${stamp}${R}"
    dw "$left"; local -i lw=$DW
    dw "$right"; local -i rw=$DW
    if ((lw + rw + 2 <= TCOLS)); then
        dw_pad "$left" $((TCOLS - rw))
        FRAME+=("${PAD}${right}")
    else
        FRAME+=("$left")
    fi
    HIT[0]="refresh"
    hr

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
            for ((j = before; j < after; j++)); do HIT[$j]="body:$name:$((j - before))"; done
        fi
        ((idx < ${#SECTIONS[@]} - 1)) && hr
    done

    local verdict; verdict=$(panel_verdict)
    if [ -n "$verdict" ]; then hr; row " $verdict"; fi

    if [ "$ONCE" = 0 ] && [ "$CAP_TTY" = yes ]; then
        local hint
        if [ "$CAP_MOUSE" = yes ]; then
            hint="click: fold section · body line for detail · header to refresh   q quit"
        else
            hint="space refresh · 1-9 fold section · q quit   ${D}(mouse: $CAP_MOUSE_WHY)${R}"
        fi
        while ((${#FRAME[@]} < TROWS - 1)); do blank; done
        row "${D}${hint}${R}"
    fi
}

DETAIL=""
build_detail() {
    FRAME=(); HIT=()
    row " ${B}${CYN}${DETAIL_TITLE}${R}"
    hr
    local line
    while IFS= read -r line; do row "  $line"; done <<<"$DETAIL"
    hr
    row " ${D}any key returns${R}"
}

# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------
handle_mouse() {
    # SGR 1006: ESC [ < btn ; col ; row (M press | m release)
    local seq="" ch
    while read -rsn1 -t 0.05 ch; do
        seq+=$ch
        [[ $ch == [Mm] ]] && break
        ((${#seq} > 24)) && break
    done
    [[ $seq == \<*[Mm] ]] || return 0
    [[ $seq == *M ]] || return 0
    local body=${seq:1:$((${#seq} - 2))}
    local btn=${body%%;*}; local rest=${body#*;}
    local y=${rest#*;}
    ((btn == 0)) || return 0
    local target=${HIT[$((y - 1))]:-}
    case $target in
        refresh) FINGERPRINT="" ;;
        section:*)
            local name=${target#section:}
            if [ -n "${COLLAPSED[$name]:-}" ]; then unset "COLLAPSED[$name]"; else COLLAPSED[$name]=1; fi ;;
        body:*)
            local rest2=${target#body:}
            local name=${rest2%%:*}
            if declare -F "detail_$name" >/dev/null; then
                DETAIL=$("detail_$name" "${rest2##*:}")
                DETAIL_TITLE=${SECTION_TITLES[$name]:-$name}
            fi ;;
    esac
}

toggle_index() {
    local -i i=$1
    ((i >= 1 && i <= ${#SECTIONS[@]})) || return 0
    local name=${SECTIONS[$((i - 1))]}
    if [ -n "${COLLAPSED[$name]:-}" ]; then unset "COLLAPSED[$name]"; else COLLAPSED[$name]=1; fi
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
    if [ -n "$DETAIL" ]; then
        build_detail
    else
        run_checks
        build_frame
    fi
    paint
    RESIZED=0

    key=""
    if read -rsn1 -t "$INTERVAL" key; then
        if [ -n "$DETAIL" ]; then
            [ "$key" = $'\e' ] && handle_mouse
            DETAIL=""
            continue
        fi
        case $key in
            q|Q) break ;;
            ' '|r|R) FINGERPRINT="" ;;
            [1-9]) toggle_index "$key" ;;
            $'\e') handle_mouse ;;
        esac
    fi
done
leave_screen
