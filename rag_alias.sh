#!/usr/bin/env bash
# Execute for setup instructions; source from Bash or Zsh to register commands.
_DOCREVIEW_EXECUTED=0
if [ -n "${ZSH_VERSION:-}" ]; then
    case "${ZSH_EVAL_CONTEXT:-}" in
        *:file) ;;
        *) _DOCREVIEW_EXECUTED=1 ;;
    esac
    eval '_DOCREVIEW_ALIAS_FILE=${(%):-%N}'
elif [ -n "${BASH_VERSION:-}" ]; then
    if [ "${BASH_SOURCE[0]}" = "$0" ]; then
        _DOCREVIEW_EXECUTED=1
    fi
    _DOCREVIEW_ALIAS_FILE="${BASH_SOURCE[0]}"
else
    printf '%s\n' 'DocReview aliases require Bash or Zsh.' >&2
    return 1 2>/dev/null || exit 1
fi
# Print a semantic accent only on color-capable terminals.
_docreview_line() {
    local color="$1"
    shift
    if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ -z "${NO_COLOR+x}" ]; then
        printf '\033[%sm%s\033[0m\n' "$color" "$*"
    else
        printf '%s\n' "$*"
    fi
}

# Read the shared Small assets with standard shell tools at a readable width.
_docreview_banner() {
    local _banner_columns="${COLUMNS:-80}" _banner_asset=''
    case "${_banner_columns}" in
        ''|*[!0-9]*) _banner_columns=80 ;;
    esac
    if [ "${_banner_columns}" -ge 78 ]; then
        _banner_asset="${_DOCREVIEW_ROOT}/web/branding/wordmark.txt"
    elif [ "${_banner_columns}" -ge 18 ]; then
        _banner_asset="${_DOCREVIEW_ROOT}/web/branding/monogram.txt"
    fi
    printf '\n'
    if [ -n "${_banner_asset}" ] && [ -r "${_banner_asset}" ]; then
        cat -- "${_banner_asset}"
        printf '\n'
    fi
    _docreview_line '1' 'DocReview RAG v2'
    if [ "${_banner_columns}" -ge 51 ]; then
        _docreview_line '2' 'SEC / DART · Evidence first. Answers with sources.'
    elif [ "${_banner_columns}" -ge 18 ]; then
        _docreview_line '2' 'SEC / DART'
    fi
    printf '\n'
}

# Match only simple source statements naming this exact checkout's script.
_docreview_startup() {
    python3 - "$1" "${_DOCREVIEW_ROOT}/rag_alias.sh" "${_DOCREVIEW_RC}" <<'PYCODE'
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

mode, target, filename = sys.argv[1:]
p = Path(filename)
if not p.exists():
    sys.exit(1 if mode == 'check' else 0)
original = p.read_bytes()
lines = original.splitlines(keepends=True)
kept = []
for line in lines:
    try:
        lexer = shlex.shlex(line.decode(), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except (ValueError, UnicodeDecodeError):
        kept.append(line)
        continue
    matches = (len(tokens) >= 2 and tokens[0] in ('source', '.')
               and tokens[1] == target
               and tokens[2:] in ([], ['>', '/dev/null']))
    if not matches:
        kept.append(line)
if len(kept) == len(lines):
    sys.exit(1 if mode == 'check' else 0)
if mode == 'check':
    print(str(p))
    sys.exit(0)
fd, backup = tempfile.mkstemp(prefix=p.name + '.docreview-backup-', dir=p.parent)
os.close(fd)
shutil.copy2(p, backup)
if p.read_bytes() != original:
    raise SystemExit('Startup file changed; uninstall aborted.')
p.write_bytes(b''.join(kept))
print('Removed this checkout\'s source line from: ' + str(p))
print('Backup: ' + backup)
PYCODE
}

# Confirm removal of exact startup entries; leave project files intact.
_docreview_uninstall() {
    local answer
    printf 'Target: %s\n' "${_DOCREVIEW_ROOT}/rag_alias.sh"
    printf 'Startup file: %s\n' "${_DOCREVIEW_RC}"
    printf 'Remove this registration? [y/N] '
    IFS= read -r answer || return 0
    case "$answer" in
        y|Y|yes|YES) ;;
        *) printf '%s\n' 'Cancelled; nothing changed.'; return 0 ;;
    esac
    _docreview_startup remove || return 1
    if [ "${_DOCREVIEW_EXECUTED:-0}" = 1 ]; then
        printf '%s\n' 'Startup registration removed. Project files were kept.' \
            'In an already loaded shell, run rag-alias-delete to remove its commands.'
    else
        # Preserve any command the user replaced after registration.
        local name
        for name in rag-dev rag-prod rag-diagnose rag-ollama-check rag-fresh-start rag-corpus rag-quickstart rag-help rag-alias-delete; do
            if [ "$(typeset -f "$name")" = "${_DOCREVIEW_OWNED_FUNCTIONS[$name]}" ]; then
                unset -f "$name"
            fi
        done
        for name in rag-dev-up rag-dev-down rag-prod-up rag-prod-down; do
            if [ "$(alias "$name" 2>/dev/null)" = "${_DOCREVIEW_OWNED_ALIASES[$name]}" ]; then
                unalias "$name"
            fi
        done
        printf '%s\n' 'Removed this script\'"'"'s unchanged commands; project files were kept.'
        unset _DOCREVIEW_OWNED_FUNCTIONS _DOCREVIEW_OWNED_ALIASES
    fi
}

_DOCREVIEW_ROOT="$(cd "$(dirname "${_DOCREVIEW_ALIAS_FILE}")" && pwd)"
if [ "${_DOCREVIEW_EXECUTED}" = 1 ]; then
    _DOCREVIEW_PARENT_SHELL="$(ps -p "$PPID" -o comm=)"
    _DOCREVIEW_PARENT_SHELL="${_DOCREVIEW_PARENT_SHELL##*/}"
    _DOCREVIEW_PARENT_SHELL="${_DOCREVIEW_PARENT_SHELL#-}"
else
    if [ -n "${ZSH_VERSION:-}" ]; then
        _DOCREVIEW_PARENT_SHELL=zsh
    else
        _DOCREVIEW_PARENT_SHELL=bash
    fi
fi
case "${_DOCREVIEW_PARENT_SHELL}" in
    zsh) _DOCREVIEW_RC="${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash) _DOCREVIEW_RC="$HOME/.bashrc" ;;
    *) _DOCREVIEW_RC=/dev/null ;;
esac
if [ "${_DOCREVIEW_EXECUTED}" = 1 ]; then
    _docreview_banner
    case "${1:-}" in
        --uninstall)
            _docreview_uninstall
            exit $?
            ;;
        '') ;;
        *) printf '%s\n' 'Usage: ./rag_alias.sh [--uninstall]' >&2; exit 2 ;;
    esac
    if _docreview_startup check >/dev/null; then
        _docreview_line '1;32' '[INSTALLED] Startup registration already exists; no setup needed.'
        _docreview_line '1;36' 'Run rag-help for help!'
        _docreview_line '2' 'If this terminal predates registration, open a new terminal first.'
    else
        _docreview_line '1;33' "[SETUP] Shell: ${_DOCREVIEW_PARENT_SHELL}"
        printf '%s\n' 'Run this in your terminal to register and verify DocReview commands:'
        case "${_DOCREVIEW_PARENT_SHELL}" in
            bash|zsh) ;;
            *) printf '%s\n' '  bash' '# Then run in Bash:' ;;
        esac
        printf '  source %q\n' "${_DOCREVIEW_ROOT}/rag_alias.sh"
        _docreview_line '1;32' 'After running source, run rag-help for help!'
    fi
    printf '\nUninstall: rag-alias-delete (loaded shell), or:\n'
    printf '  %q --uninstall\n' "${_DOCREVIEW_ROOT}/rag_alias.sh"
    if [ -t 0 ] && [ "${_DOCREVIEW_RC}" != /dev/null ]; then
        _docreview_uninstall
    fi
    exit 0
fi
unset _DOCREVIEW_EXECUTED _DOCREVIEW_ALIAS_FILE

# Remove only this checkout's registration and unchanged owned commands.
rag-alias-delete() { _docreview_uninstall; }

rag-dev() { bash "${_DOCREVIEW_ROOT}/scripts/run_local.sh" dev "$@"; }
rag-prod() { bash "${_DOCREVIEW_ROOT}/scripts/run_local.sh" prod "$@"; }
rag-diagnose() { bash "${_DOCREVIEW_ROOT}/scripts/diagnose_ollama.sh" "$@"; }
rag-ollama-check() { rag-diagnose "$@"; }
rag-quickstart() { bash "${_DOCREVIEW_ROOT}/scripts/quickstart.sh" "$@"; }
rag-fresh-start() { (cd "${_DOCREVIEW_ROOT}" && .venv/bin/python -m scripts.runtime_commands fresh-start "$@"); }
rag-corpus() { (cd "${_DOCREVIEW_ROOT}" && .venv/bin/python -m scripts.runtime_commands corpus "$@"); }
rag-help() {
    _docreview_banner
    _docreview_line '1;36' '[STACK] Local development / production preview'
    printf '%s\n' \
        '  rag-dev [COMPOSE_ARGS...]     Development stack (default: up -d)' \
        '  rag-prod [COMPOSE_ARGS...]    Local public preview (default: up -d)' \
        '  rag-dev-up / rag-prod-up     Start in the background' \
        '  rag-dev-down / rag-prod-down Stop; preserve data volumes' \
        ''
    _docreview_line '1;36' '[OBSERVE] Status and logs'
    printf '%s\n' \
        '  rag-dev ps                   Show service status' \
        '  rag-dev logs -f app           Follow API logs' \
        '  rag-prod logs -f web          Follow preview web logs' \
        ''
    _docreview_line '1;36' '[DIAGNOSE] Application and model connection'
    printf '%s\n' \
        '  rag-ollama-check              Diagnose the active/default server; no URL needed' \
        '  rag-ollama-check --setup      Show Ollama installation and model setup steps' \
        '  rag-ollama-check --details    Explain host/container and listener checks' \
        '  rag-ollama-check --web-url http://localhost:9000' \
        '                               Target a different DocReview address' \
        '  rag-ollama-check --help       Show diagnostic options' \
        '  rag-diagnose [OPTIONS...]     Same diagnostic command' \
        ''
    _docreview_line '1;33' '[QUICK START] Build and run'
    printf '%s\n' \
        '  rag-quickstart               Prepare a new checkout and open the tutorial' \
        '  rag-quickstart --help        Show first-run requirements' \
        '  rag-dev up --build -d         Rebuild and start development services' \
        '  rag-fresh-start              Reset project data, rebuild, and restart from scratch' \
        '  rag-fresh-start --help       Show reset requirements and warnings' \
        '  rag-help                     Show this help' \
        ''
    _docreview_line '1;31' 'WARNING: rag-fresh-start permanently deletes the project database,'
    printf '%s\n' \
        '  downloaded SEC/DART filings, evaluation results, and saved local model settings.' \
        '  Download SEC/DART data again and repeat all setup and processing steps' \
        '  to restore full functionality. No backup is created.' \
        '  Use the commands below or the development web UI started by Quick Start.' \
        '  Code, .env, keys, and host Ollama are preserved. Start rag-dev first.' \
        ''
    _docreview_line '1;36' '[REBUILD DATA] Same jobs as the development web Build / Jobs panels'
    printf '%s\n' \
        '  rag-corpus acquire_edgar --identifier NVDA --year 2024' \
        '  rag-corpus acquire_dart --identifier 005930 --year 2024' \
        '  rag-corpus ingest_manifest --manifest <manifest> --selection <selection-id>' \
        '  rag-corpus backfill_embeddings' \
        '  rag-corpus rebuild_bm25' \
        '  rag-corpus inspect           Show manifests, documents, and index readiness' \
        '  rag-corpus readiness         Show runtime and model configuration' \
        '  rag-corpus status            Check completion before starting the next step' \
        '  rag-corpus --help            Show operation options' \
        '  Downloads require SEC/DART configuration; embeddings may incur provider charges.' \
        '  Configure the answer model and run evaluation in the development web UI.' \
        '  After a terminal reset: Settings > Data & help > Reset runtime data >' \
        '  View reset status > Clear browser data and start again, then follow Build.' \
        '  Public read-only deployments cannot perform these admin operations.' \
        ''
    _docreview_line '1;33' '[UNINSTALL] Remove this checkout'"'"'s aliases'
    printf '%s\n' '  rag-alias-delete             Confirm removal; keep project files' ''
    _docreview_line '2' "Checkout: ${_DOCREVIEW_ROOT}"
    _docreview_line '2' 'Diagnostics read metadata; they do not start or install Ollama.'
    _docreview_line '2' '--web-url points to DocReview, not to the Ollama server.'
}
alias rag-dev-up='rag-dev up -d'
alias rag-dev-down='rag-dev down'
alias rag-prod-up='rag-prod up -d'
alias rag-prod-down='rag-prod down'

typeset -A _DOCREVIEW_OWNED_FUNCTIONS _DOCREVIEW_OWNED_ALIASES
for _DOCREVIEW_COMMAND in rag-dev rag-prod rag-diagnose rag-ollama-check rag-fresh-start rag-corpus rag-quickstart rag-help rag-alias-delete; do
    if ! typeset -f "${_DOCREVIEW_COMMAND}" >/dev/null; then
        printf '[ERROR] Command registration failed: %s\n' "${_DOCREVIEW_COMMAND}" >&2
        unset _DOCREVIEW_COMMAND
        return 1
    fi
    _DOCREVIEW_OWNED_FUNCTIONS[$_DOCREVIEW_COMMAND]="$(typeset -f "$_DOCREVIEW_COMMAND")"
done
for _DOCREVIEW_COMMAND in rag-dev-up rag-dev-down rag-prod-up rag-prod-down; do
    if ! alias "${_DOCREVIEW_COMMAND}" >/dev/null; then
        printf '[ERROR] Alias registration failed: %s\n' "${_DOCREVIEW_COMMAND}" >&2
        unset _DOCREVIEW_COMMAND
        return 1
    fi
    _DOCREVIEW_OWNED_ALIASES[$_DOCREVIEW_COMMAND]="$(alias "$_DOCREVIEW_COMMAND")"
done
unset _DOCREVIEW_COMMAND

_docreview_banner
_docreview_line '1;32' '[OK] DocReview commands registered and verified in this shell.'
_docreview_line '2' "Checkout: ${_DOCREVIEW_ROOT}"
printf '%s\n' \
    '  rag-dev, rag-prod, rag-diagnose, rag-ollama-check, rag-help' \
    '  rag-quickstart, rag-fresh-start, rag-corpus' \
    '  rag-dev-up, rag-dev-down, rag-prod-up, rag-prod-down' \
    ''
_docreview_line '1;36' 'Run rag-help for help!'
