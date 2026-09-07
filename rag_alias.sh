#!/usr/bin/env bash
# Execute to install or verify startup registration; source to load commands now.
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
p = Path(filename).expanduser().resolve()
exists = p.exists()
if not exists and mode != 'install':
    sys.exit(1 if mode == 'check' else 0)
try:
    original = p.read_bytes() if exists else b''
except OSError as error:
    print('[ERROR] Cannot read startup file: ' + str(error), file=sys.stderr)
    sys.exit(2)
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
registered = len(kept) != len(lines)
if mode == 'check':
    sys.exit(0 if registered else 1)
if mode == 'install':
    if registered:
        sys.exit(0)
    updated = original + (b'\n' if original and not original.endswith(b'\n') else b'')
    updated += ('source ' + shlex.quote(target) + ' >/dev/null\n').encode()
else:
    if not registered:
        print('No registration for this checkout in: ' + str(p))
        sys.exit(0)
    updated = b''.join(kept)
p.parent.mkdir(parents=True, exist_ok=True)
if exists:
    fd, backup = tempfile.mkstemp(prefix=p.name + '.docreview-backup-', dir=p.parent)
    os.close(fd)
    shutil.copy2(p, backup)
    print('Backup: ' + backup)
fd, temporary = tempfile.mkstemp(prefix=p.name + '.docreview-', dir=p.parent)
try:
    with os.fdopen(fd, 'wb') as output:
        output.write(updated)
        output.flush()
        os.fsync(output.fileno())
    if exists:
        shutil.copymode(p, temporary)
    if p.exists() != exists or (exists and p.read_bytes() != original):
        raise SystemExit('Startup file changed; registration update aborted.')
    os.replace(temporary, p)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print(('Installed registration in: ' if mode == 'install' else
       'Removed this checkout\'s source line from: ') + str(p))
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
        for name in rag-up rag-dev rag-prod rag-ollama-check rag-fresh-start rag-corpus rag-schema rag-quickstart rag-help rag-alias-delete; do
            if [ "$(typeset -f "$name")" = "${_DOCREVIEW_OWNED_FUNCTIONS[$name]}" ]; then
                unset -f "$name"
            fi
        done
        printf '%s\n' 'Removed this script\'"'"'s unchanged commands; project files were kept.'
        unset _DOCREVIEW_OWNED_FUNCTIONS
    fi
}

_DOCREVIEW_ROOT="$(cd "$(dirname "${_DOCREVIEW_ALIAS_FILE}")" && pwd)"
if [ "${_DOCREVIEW_EXECUTED}" = 1 ]; then
    _DOCREVIEW_PARENT_SHELL="$(ps -p "$PPID" -o comm=)"
    _DOCREVIEW_PARENT_SHELL="${_DOCREVIEW_PARENT_SHELL##*/}"
    _DOCREVIEW_PARENT_SHELL="${_DOCREVIEW_PARENT_SHELL#-}"
    case "${_DOCREVIEW_PARENT_SHELL}" in
        bash|zsh) ;;
        *) _DOCREVIEW_PARENT_SHELL="${SHELL##*/}" ;;
    esac
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
# Validate command registration and wrapper targets without running application operations.
_docreview_verify() {
    local target
    for target in scripts/stack/__main__.py scripts/diagnostics/ollama.py scripts/stack/quickstart.sh scripts/stack/commands.py scripts/schema/__main__.py; do
        if [ ! -r "${_DOCREVIEW_ROOT}/$target" ]; then
            printf '[ERROR] Missing helper target: %s\n' "${_DOCREVIEW_ROOT}/$target" >&2
            return 1
        fi
    done
    case "${_DOCREVIEW_PARENT_SHELL}" in
        bash) bash --noprofile --norc -c 'source "$1" >/dev/null' docreview "${_DOCREVIEW_ROOT}/rag_alias.sh" ;;
        zsh) zsh -f -c 'source "$1" >/dev/null' docreview "${_DOCREVIEW_ROOT}/rag_alias.sh" ;;
        *) return 1 ;;
    esac
}

# A child script cannot change its parent shell; print the exact activation command.
_docreview_activation() {
    printf 'Startup file: %s\n' "${_DOCREVIEW_RC}"
    printf '%s\n' 'Paste these commands into this terminal; no shell restart is needed:'
    printf '  source %q\n' "${_DOCREVIEW_ROOT}/rag_alias.sh"
    printf '  rag-help\n'
    printf '\nRemove this checkout registration: rag-alias-delete, or:\n'
    printf '  %q --delete\n' "${_DOCREVIEW_ROOT}/rag_alias.sh"
}

if [ "${_DOCREVIEW_EXECUTED}" = 1 ]; then
    _docreview_banner
    case "${1:-}" in
        --delete|--uninstall) _docreview_uninstall; exit $? ;;
        '') ;;
        *) printf '%s\n' 'Usage: ./rag_alias.sh [--delete|--uninstall]' >&2; exit 2 ;;
    esac
    if [ "${_DOCREVIEW_RC}" = /dev/null ]; then
        printf '%s\n' '[ERROR] Start Bash or Zsh, then run ./rag_alias.sh again.' >&2
        exit 2
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' '[ERROR] Python 3 is required to check and install startup registration.' >&2
        exit 1
    fi
    if _docreview_startup check; then
        _docreview_verify || exit 1
        _docreview_line '1;32' '[INSTALLED] Startup registration and helper commands verified.'
        _docreview_line '1;36' 'Run rag-help for help!'
        _docreview_activation
        exit 0
    else
        _DOCREVIEW_REGISTRATION_STATUS=$?
        [ "${_DOCREVIEW_REGISTRATION_STATUS}" = 1 ] || exit "${_DOCREVIEW_REGISTRATION_STATUS}"
    fi
    _docreview_line '1;33' "[SETUP] Install DocReview helper for ${_DOCREVIEW_PARENT_SHELL}"
    printf 'Startup file: %s\n' "${_DOCREVIEW_RC}"
    printf '%s\n' 'Registers rag-help and the helper commands; run rag-quickstart separately for application setup.'
    printf 'Install this checkout registration? [y/N] '
    IFS= read -r _DOCREVIEW_ANSWER || _DOCREVIEW_ANSWER=n
    case "${_DOCREVIEW_ANSWER}" in
        y|Y|yes|YES) ;;
        *) printf '%s\n' 'Cancelled; nothing changed. Run ./rag_alias.sh when ready to install.'; exit 0 ;;
    esac
    _docreview_verify || exit 1
    _docreview_startup install || exit 1
    _docreview_startup check || exit 1
    _docreview_line '1;32' '[OK] Startup registration installed and helper commands verified.'
    _docreview_activation
    exit 0
fi
unset _DOCREVIEW_EXECUTED _DOCREVIEW_ALIAS_FILE

# Remove only this checkout's registration and unchanged owned commands.
rag-alias-delete() {
    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-alias-delete' 'Confirm removal of this checkout registration; keep project files.'
    else
        _docreview_uninstall
    fi
}

rag-up() {
    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-up [COMPOSE_UP_ARGS...]' 'Build/start DEV and prepare an empty DB; existing data is never reset.' 'Requires Python setup from rag-quickstart or uv sync --locked.'
    else
        rag-dev up --build -d "$@"
    fi
}
# Run the selected module in the checkout that registered these commands.
_docreview_python() {
    if [ ! -x "${_DOCREVIEW_ROOT}/.venv/bin/python" ]; then
        printf '%s\n' '[FAIL] Project Python is missing. Run rag-quickstart or uv sync --locked first.' >&2
        return 2
    fi
    (cd "${_DOCREVIEW_ROOT}" && .venv/bin/python -m "$@")
}
rag-dev() {
    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-dev [COMPOSE_ARGS...]' 'Manage the development stack; default: up -d.' 'Examples: rag-dev ps; rag-dev logs -f app; rag-dev down.'
    else
        _docreview_python scripts.stack dev "$@"
    fi
}
rag-prod() {
    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-prod [COMPOSE_ARGS...]' 'Manage the local public preview; default: up -d.' 'Examples: rag-prod ps; rag-prod logs -f web; rag-prod down.'
    else
        _docreview_python scripts.stack prod "$@"
    fi
}
rag-ollama-check() { _docreview_python scripts.diagnostics.ollama "$@"; }
rag-quickstart() { bash "${_DOCREVIEW_ROOT}/scripts/stack/quickstart.sh" "$@"; }
rag-fresh-start() { _docreview_python scripts.stack.commands fresh-start "$@"; }
rag-corpus() { _docreview_python scripts.stack.commands corpus "$@"; }
rag-schema() { _docreview_python scripts.schema "$@"; }
rag-help() {
    _docreview_banner
    _docreview_line '1;36' '[STACK]'
    printf '  %-62s  %s\n' \
        'rag-quickstart' 'Prepare first run' \
        'rag-up [COMPOSE_UP_ARGS...]' 'Build DEV stack' \
        'rag-dev [COMPOSE_ARGS...]' 'Manage DEV stack' \
        'rag-prod [COMPOSE_ARGS...]' 'Manage public preview'
    _docreview_line '1;36' '[DATA AND DIAGNOSTICS]'
    printf '  %-62s  %s\n' \
        'rag-ollama-check [--setup|--details|--web-url URL]' 'Check model connection' \
        'rag-schema check|prepare|recover|recreate' 'Manage local schema' \
        'rag-fresh-start [--status|--extreme]' 'Reset project runtime' \
        'rag-corpus status|inspect|readiness|acquire_edgar|acquire_dart|ingest_manifest|backfill_embeddings|rebuild_bm25' 'Manage corpus jobs'
    printf '%s\n' '  Example: rag-corpus acquire_edgar --identifier NVDA --year 2024' ''
    _docreview_line '1;33' 'WARNING ordinary reset: deletes DB, downloads, results and saved model settings; preserves code, .env and host Ollama.'
    _docreview_line '1;31' 'WARNING extreme reset: also deletes previewed config, caches and acknowledged browser data; two confirmations, no restart.'
    _docreview_line '1;33' 'WARNING schema recreate: deletes ORM data and sources; --keep-sources preserves sources, --sample presets the sample selection.'
    printf '\n'
    _docreview_line '1;36' '[HELP]'
    printf '  %-62s  %s\n' \
        'rag-help' 'Show command summary' \
        'rag-alias-delete' 'Remove helper registration'
    printf '\n'
    _docreview_line '2' 'Every command accepts --help for options and examples.'
    _docreview_line '2' "Checkout: ${_DOCREVIEW_ROOT}"
}

typeset -A _DOCREVIEW_OWNED_FUNCTIONS
for _DOCREVIEW_COMMAND in rag-up rag-dev rag-prod rag-ollama-check rag-fresh-start rag-corpus rag-schema rag-quickstart rag-help rag-alias-delete; do
    if ! typeset -f "${_DOCREVIEW_COMMAND}" >/dev/null; then
        printf '[ERROR] Command registration failed: %s\n' "${_DOCREVIEW_COMMAND}" >&2
        unset _DOCREVIEW_COMMAND
        return 1
    fi
    _DOCREVIEW_OWNED_FUNCTIONS[$_DOCREVIEW_COMMAND]="$(typeset -f "$_DOCREVIEW_COMMAND")"
done
unset _DOCREVIEW_COMMAND

_docreview_banner
_docreview_line '1;32' '[OK] DocReview commands registered and verified in this shell.'
_docreview_line '2' "Checkout: ${_DOCREVIEW_ROOT}"
printf '%s\n' \
    '  rag-up, rag-dev, rag-prod, rag-ollama-check, rag-help' \
    '  rag-quickstart, rag-fresh-start, rag-corpus, rag-schema, rag-alias-delete' \
    ''
_docreview_line '1;36' 'Run rag-help for help!'
