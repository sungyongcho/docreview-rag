#!/usr/bin/env bash
# DocReview helper protocol: 1
# Bump this version on every helper change.
_DOCREVIEW_PREVIOUS_HASH="${DOCREVIEW_HELPER_SHA256:-}"
_DOCREVIEW_PREVIOUS_VERSION="${DOCREVIEW_ALIAS_VERSION:-}"
DOCREVIEW_ALIAS_VERSION="2.0.0"
typeset -ga _DOCREVIEW_COMMAND_NAMES
typeset -gA _DOCREVIEW_OWNED_FUNCTIONS
_DOCREVIEW_INSTALL_STATE=install
# Retire only previously owned registrations absent from this version's public command set.
for _DOCREVIEW_OLD_NAME in "${_DOCREVIEW_COMMAND_NAMES[@]}"; do
    [ -n "${_DOCREVIEW_OLD_NAME}" ] || continue
    case " rag-alias rag-up rag-dev rag-prod rag-ollama-check rag-start-quick rag-start-fresh rag-reset rag-corpus rag-schema rag-help rag-alias-delete " in
        *" ${_DOCREVIEW_OLD_NAME} "*) ;;
        *)
            if [ "$(typeset -f "${_DOCREVIEW_OLD_NAME}")" = "${_DOCREVIEW_OWNED_FUNCTIONS[$_DOCREVIEW_OLD_NAME]-}" ]; then
                unset -f "${_DOCREVIEW_OLD_NAME}"
            fi ;;
    esac
done
if [ -n "${_DOCREVIEW_PREVIOUS_VERSION}" ] || typeset -f rag-help >/dev/null 2>&1; then
    _DOCREVIEW_INSTALL_STATE='already installed'
    [ "${_DOCREVIEW_PREVIOUS_VERSION}" = "${DOCREVIEW_ALIAS_VERSION}" ] || _DOCREVIEW_INSTALL_STATE='update required'
    for _DOCREVIEW_NAME in rag-alias rag-up rag-dev rag-prod rag-ollama-check rag-start-quick rag-start-fresh rag-reset rag-corpus rag-schema rag-help rag-alias-delete; do
        if ! typeset -f "${_DOCREVIEW_NAME}" >/dev/null 2>&1 || [ "$(typeset -f "${_DOCREVIEW_NAME}")" != "${_DOCREVIEW_OWNED_FUNCTIONS[$_DOCREVIEW_NAME]-}" ]; then
            _DOCREVIEW_INSTALL_STATE='update required'
        fi
        if alias "${_DOCREVIEW_NAME}" >/dev/null 2>&1; then
            _DOCREVIEW_INSTALL_STATE='update required'
            unalias "${_DOCREVIEW_NAME}"
        fi
    done
fi
# Source interactively to install and activate; execute for installation and optional login shell.
_DOCREVIEW_EXECUTED=0
_DOCREVIEW_FROM_STARTUP=0
_DOCREVIEW_INTERACTIVE=0
case $- in *i*) _DOCREVIEW_INTERACTIVE=1 ;; esac
if [ -n "${ZSH_VERSION:-}" ]; then
    case "${ZSH_EVAL_CONTEXT:-}" in
        *:file) ;;
        *) _DOCREVIEW_EXECUTED=1 ;;
    esac
    case "${ZSH_EVAL_CONTEXT:-}" in *:file:file*) _DOCREVIEW_FROM_STARTUP=1 ;; esac
    eval '_DOCREVIEW_ALIAS_FILE=${(%):-%x}'
elif [ -n "${BASH_VERSION:-}" ]; then
    if [ "${BASH_SOURCE[0]}" = "$0" ]; then
        _DOCREVIEW_EXECUTED=1
    fi
    _DOCREVIEW_ALIAS_FILE="${BASH_SOURCE[0]}"
    [ -z "${BASH_SOURCE[1]:-}" ] || _DOCREVIEW_FROM_STARTUP=1
else
    printf '%s\n' 'DocReview aliases require Bash or Zsh.' >&2
    return 1 2>/dev/null || exit 1
fi
# Decorate only a real terminal; redirected and NO_COLOR output stay plain.
_docreview_color() {
    [ -t 1 ] && [ -z "${NO_COLOR+x}" ] && [ "${TERM:-}" != dumb ]
}
_docreview_heading() {
    if _docreview_color; then printf '\033[36;1m%s\033[0m\n' "$*"; else printf '%s\n' "$*"; fi
}
_docreview_row() {
    if _docreview_color; then printf '  \033[1m%-52s\033[0m  %s\n' "$1" "$2"; else printf '  %-52s  %s\n' "$1" "$2"; fi
}
_docreview_reminder() {
    if _docreview_color; then printf '\033[1mremember to type rag-help\033[0m\n'; else printf '%s\n' 'remember to type rag-help'; fi
}
# Filter the same optional verbosity flag for every public helper command.
_docreview_options() {
    _DOCREVIEW_ARGS=()
    local _option
    for _option in "$@"; do
        case "${_option}" in
            --verbose|-vv) DOCREVIEW_VERBOSE=1 ;;
            *) _DOCREVIEW_ARGS+=("${_option}") ;;
        esac
    done
    export DOCREVIEW_VERBOSE
}
_docreview_runtime() {
    if _docreview_color; then
        env -u FORCE_COLOR PYTHON_COLORS=1 "$@"
    else
        env -u FORCE_COLOR NO_COLOR=1 PYTHON_COLORS=0 "$@"
    fi
}
# Keep helper output readable in every terminal.
_docreview_line() {
    if _docreview_color; then
        case "$*" in
            '    No backup.'*|'    Deletes ORM data/sources;'*|'    Preserves .env'*)
                printf '\033[33m%s\033[0m\n' "$*"; return ;;
            '    '*) printf '\033[2m%s\033[0m\n' "$*"; return ;;
        esac
    fi
    printf '%s\n' "$*"
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
    _docreview_line 'DocReview RAG v2'
    if [ "${_banner_columns}" -ge 51 ]; then
        _docreview_line 'SEC / DART · Evidence first. Answers with sources.'
    elif [ "${_banner_columns}" -ge 18 ]; then
        _docreview_line 'SEC / DART'
    fi
    printf '\n'
}

# Match only simple source statements naming this exact checkout's script.
_docreview_startup() {
    python3 -I - "$1" "${_DOCREVIEW_ROOT}/rag-alias.sh" "${_DOCREVIEW_RC}" "${2:-}" <<'PYCODE'
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

mode, target, filename, previous = sys.argv[1:]
legacy = str(Path(target).with_name(Path(target).name.replace('-', '_')))
previous_paths = {previous} if previous else set()
if previous:
    previous_paths.add(str(Path(previous).with_name(Path(previous).name.replace('-', '_'))))
p = Path(filename).expanduser().resolve()
exists = p.exists()
if not exists and mode != 'install':
    sys.exit(1 if mode in ('check', 'legacy-check') else 0)
try:
    original = p.read_bytes() if exists else b''
except OSError as error:
    print('[ERROR] Cannot read startup file: ' + str(error), file=sys.stderr)
    sys.exit(2)
lines = original.splitlines(keepends=True)
kept = []
registered = False
legacy_registered = False
previous_registered = False
owned_count = 0
replacement_index = None
for line in lines:
    try:
        lexer = shlex.shlex(line.decode(), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except (ValueError, UnicodeDecodeError):
        kept.append(line)
        continue
    simple = (len(tokens) >= 2 and tokens[0] in ('source', '.')
              and tokens[2:] in ([], ['>', '/dev/null']))
    matches = simple and tokens[1] == target
    old_match = simple and tokens[1] == legacy
    prior_match = simple and tokens[1] in previous_paths
    previous_registered = previous_registered or prior_match
    registered = registered or matches
    legacy_registered = legacy_registered or old_match
    removing = matches or (old_match and mode in ('migrate', 'remove', 'sync')) or (prior_match and mode in ('sync', 'remove'))
    if removing:
        owned_count += 1
        if replacement_index is None:
            replacement_index = len(kept)
    else:
        kept.append(line)
if mode == 'check':
    sys.exit(0 if registered else 1)
if mode == 'legacy-check':
    if legacy_registered:
        print('Old helper registration: ' + legacy)
    sys.exit(0 if legacy_registered else 1)
if mode == 'sync' and not (registered or legacy_registered or previous_registered):
    print('No owned startup registration found; commands are loaded in this shell only.')
    sys.exit(0)
if mode == 'sync' and registered and owned_count == 1:
    print('Startup registration is already current: ' + str(p))
    sys.exit(0)
if mode in ('install', 'migrate', 'sync'):
    if registered and mode == 'install':
        sys.exit(0)
    registration = ('source ' + shlex.quote(target) + ' >/dev/null\n').encode()
    if mode in ('migrate', 'sync') and replacement_index is not None:
        updated = b''.join(kept[:replacement_index]) + registration + b''.join(kept[replacement_index:])
    else:
        updated = original + (b'\n' if original and not original.endswith(b'\n') else b'') + registration
else:
    if not registered and not legacy_registered and not previous_registered:
        print('No registration for this checkout in: ' + str(p))
        sys.exit(0)
    updated = b''.join(kept)
if updated == original:
    print('Startup registration is already current: ' + str(p))
    sys.exit(0)
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
print(('Installed registration in: ' if mode in ('install', 'migrate', 'sync') else
       'Removed this checkout\'s source line from: ') + str(p))
PYCODE
}

# Confirm removal of exact startup entries; leave project files intact.
_docreview_uninstall() {
    local answer
    printf 'Target: %s\n' "${_DOCREVIEW_ROOT}/rag-alias.sh"
    printf 'Startup file: %s\n' "${_DOCREVIEW_RC}"
    _docreview_startup legacy-check || [ "$?" = 1 ] || return 1
    if [ -n "${_DOCREVIEW_PENDING_REGISTRATION_SOURCE:-}" ]; then
        printf 'Previous registration: %s\n' "${_DOCREVIEW_PENDING_REGISTRATION_SOURCE}"
    fi
    printf 'Remove this registration? [y/N] '
    IFS= read -r answer || return 0
    case "$answer" in
        y|Y|yes|YES) ;;
        *) printf '%s\n' 'Cancelled; nothing changed.'; return 0 ;;
    esac
    _docreview_startup remove "${_DOCREVIEW_PENDING_REGISTRATION_SOURCE:-}" || return 1
    if [ "${_DOCREVIEW_EXECUTED:-0}" = 1 ]; then
        printf '%s\n' 'Startup registration removed. Project files were kept.' \
            'In an already loaded shell, run rag-alias-delete to remove its commands.'
    else
        # Preserve any command the user replaced after registration.
        local name
        for name in rag-alias rag-up rag-dev rag-prod rag-ollama-check rag-reset rag-corpus rag-schema rag-start-quick rag-start-fresh rag-help rag-alias-delete; do
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
        bash) DOCREVIEW_VERIFY_ONLY=1 bash --noprofile --norc -c 'source "$1" >/dev/null' docreview "${_DOCREVIEW_ROOT}/rag-alias.sh" ;;
        zsh) DOCREVIEW_VERIFY_ONLY=1 zsh -f -c 'source "$1" >/dev/null' docreview "${_DOCREVIEW_ROOT}/rag-alias.sh" ;;
        *) return 1 ;;
    esac
}

# A sourced helper is already active; a child installer cannot modify its parent shell.
_docreview_activation() {
    printf 'Startup file: %s\n' "${_DOCREVIEW_RC}"
    if [ "${_DOCREVIEW_EXECUTED:-0}" = 1 ]; then
        printf '%s\n' 'Preferred one-step installation and activation in your current shell:'
        printf '  source %q\n' "${_DOCREVIEW_ROOT}/rag-alias.sh"
    else
        printf '%s\n' 'Helper commands are active in this shell. Run rag-help.'
    fi
}

# Open a login shell only after a successful executed install and explicit TTY consent.
_docreview_offer_login() {
    local _login_answer _login_shell
    printf '%s\n' 'An executed installer cannot change its calling shell.'
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        printf '%s\n' 'No interactive terminal; use the source command above. No shell was started.'
        return 0
    fi
    printf '\n%s\n' 'This replaces the installer process, not its parent; exit returns to the original shell.' \
        'Login files control startup. If Bash does not load .bashrc, use the source command above.'
    printf 'Start a new %s login shell in this terminal? [y/N] ' "${_DOCREVIEW_PARENT_SHELL}"
    IFS= read -r _login_answer || _login_answer=n
    case "${_login_answer}" in
        y|Y|yes|YES) ;;
        *) printf '%s\n' 'Login shell not started; current session preserved.'; return 0 ;;
    esac
    _login_shell="$(command -v "${_DOCREVIEW_PARENT_SHELL}")" || return 1
    _docreview_reminder
    exec "${_login_shell}" -l
}

# Share registration consent between sourced and executed entry points.
_docreview_install() {
    _DOCREVIEW_INSTALL_READY=0
    if [ "${_DOCREVIEW_RC}" = /dev/null ]; then
        printf '%s\n' '[ERROR] Start Bash or Zsh, then run ./rag-alias.sh again.' >&2
        return 2
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' '[ERROR] Python 3 is required to check and install startup registration.' >&2
        return 1
    fi
    if _docreview_startup legacy-check; then
        _docreview_line '[MIGRATION] This helper is now named rag-alias.sh; the old path is unavailable.'
        printf 'Startup file: %s\n' "${_DOCREVIEW_RC}"
        printf 'Replace this checkout registration with rag-alias.sh? [y/N] '
        IFS= read -r _DOCREVIEW_ANSWER || _DOCREVIEW_ANSWER=n
        case "${_DOCREVIEW_ANSWER}" in
            y|Y|yes|YES) ;;
            *) printf '%s\n' 'Cancelled; startup registration is unchanged.'; _docreview_activation; return 0 ;;
        esac
        _docreview_verify || return 1
        _docreview_startup migrate || return 1
        _docreview_startup check || return 1
        _DOCREVIEW_INSTALL_READY=1
        _docreview_line '[OK] Replaced the old registration; its backup was preserved.'
        _docreview_activation
        return 0
    else
        _DOCREVIEW_REGISTRATION_STATUS=$?
        [ "${_DOCREVIEW_REGISTRATION_STATUS}" = 1 ] || return "${_DOCREVIEW_REGISTRATION_STATUS}"
    fi
    if _docreview_startup check; then
        _docreview_verify || return 1
        _DOCREVIEW_INSTALL_READY=1
        _docreview_line '[INSTALLED] Startup registration and helper commands verified.'
        _docreview_line 'Run rag-help for help!'
        _docreview_activation
        return 0
    else
        _DOCREVIEW_REGISTRATION_STATUS=$?
        [ "${_DOCREVIEW_REGISTRATION_STATUS}" = 1 ] || return "${_DOCREVIEW_REGISTRATION_STATUS}"
    fi
    _docreview_line "[SETUP] Install DocReview helper for ${_DOCREVIEW_PARENT_SHELL}"
    printf 'Startup file: %s\n' "${_DOCREVIEW_RC}"
    printf '%s\n' 'Registers rag-help and the helper commands; run rag-start-quick separately for application setup.'
    printf 'Install this checkout registration? [y/N] '
    IFS= read -r _DOCREVIEW_ANSWER || _DOCREVIEW_ANSWER=n
    case "${_DOCREVIEW_ANSWER}" in
        y|Y|yes|YES) ;;
        *) printf '%s\n' 'Cancelled; nothing changed. Run ./rag-alias.sh when ready to install.'; return 0 ;;
    esac
    _docreview_verify || return 1
    _docreview_startup install || return 1
    _docreview_startup check || return 1
    _DOCREVIEW_INSTALL_READY=1
    _docreview_line '[OK] Startup registration installed and helper commands verified.'
    _docreview_activation
    return 0
}


# Hash the actual source file without printing its contents.
_docreview_hash() {
    python3 -I - "$1" <<'PYHASH'
import hashlib
import sys
from pathlib import Path
try:
    print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
except OSError as error:
    print('Cannot read helper file: ' + str(error), file=sys.stderr)
    raise SystemExit(2) from None
PYHASH
}

# Validate helper syntax and its declared loader contract without executing candidate code.
_docreview_validate_helper() {
    local _syntax_result=0
    case "${_DOCREVIEW_PARENT_SHELL}" in
        bash) env -u BASH_ENV -u ENV bash --noprofile --norc -n "$1" >/dev/null 2>&1 || _syntax_result=$? ;;
        zsh) env -u BASH_ENV -u ENV zsh -f -n "$1" >/dev/null 2>&1 || _syntax_result=$? ;;
        *) _syntax_result=2 ;;
    esac
    if [ "${_syntax_result}" != 0 ]; then
        printf '%s\n' 'Invalid helper syntax; the loaded commands were preserved.' >&2
        return 2
    fi
    python3 -I - "$1" <<'PYVALIDATE'
import re
import sys
from pathlib import Path
try:
    source = Path(sys.argv[1]).read_text()
except (OSError, UnicodeError):
    print('Cannot read helper source.', file=sys.stderr)
    raise SystemExit(2) from None
required = ('rag-alias', 'rag-help', '_docreview_install', '_docreview_startup', '_docreview_hash')
valid = '# DocReview helper protocol: 1' in source.splitlines() and all(
    re.search(r'(?m)^' + re.escape(name) + r'\(\)\s*\{', source) for name in required
)
valid = valid and 'export DOCREVIEW_HELPER_PATH=' in source and 'export DOCREVIEW_HELPER_SHA256' in source
if not valid:
    print('Not a supported DocReview helper; the loaded commands were preserved.', file=sys.stderr)
    raise SystemExit(2)
PYVALIDATE
}

# Refresh this loaded helper and rebind only its existing startup registration.
_docreview_update() {
    local _update_mode="$1" _update_target="${2:-${_DOCREVIEW_ROOT}/rag-alias.sh}"
    local _update_previous="${DOCREVIEW_HELPER_PATH:-${_DOCREVIEW_ROOT}/rag-alias.sh}"
    local _update_loaded="${DOCREVIEW_HELPER_SHA256:-unrecorded}" _update_hash _update_name
    local _update_registered_from
    local -a _update_names
    local -A _update_owned _update_custom
    if [ -d "${_update_target}" ]; then _update_target="${_update_target}/rag-alias.sh"; fi
    if [ "${_update_target##*/}" != rag-alias.sh ] || [ ! -r "${_update_target}" ] || [ ! -f "${_update_target}" ]; then
        printf '%s\n' 'Helper file unavailable. Use: rag-alias update /new/checkout/rag-alias.sh' >&2
        return 2
    fi
    _update_target="$(cd "$(dirname "${_update_target}")" && pwd)/rag-alias.sh" || return 2
    _docreview_validate_helper "${_update_target}" || return 2
    _update_hash="$(_docreview_hash "${_update_target}")" || return 2
    printf 'Installed: %s\nLoaded path: %s\nCheckout: %s\nCheckout path: %s\n' \
        "${_update_loaded}" "${_update_previous}" "${_update_hash}" "${_update_target}"
    if [ "${_update_hash}" = "${_update_loaded}" ] && [ "${_update_target}" = "${_update_previous}" ]; then
        printf '%s\n' 'Up to date.'
    else
        printf '%s\n' 'Update available.'
    fi
    [ "${_update_mode}" = update ] || return 0
    _update_registered_from="${_DOCREVIEW_PENDING_REGISTRATION_SOURCE:-${_update_previous}}"
    _DOCREVIEW_PENDING_REGISTRATION_SOURCE="${_update_registered_from}"
    if [ "${_update_hash}" != "${_update_loaded}" ] || [ "${_update_target}" != "${_update_previous}" ]; then
        _update_names=("${_DOCREVIEW_COMMAND_NAMES[@]}")
        for _update_name in "${_update_names[@]}"; do
            _update_owned[$_update_name]="${_DOCREVIEW_OWNED_FUNCTIONS[$_update_name]}"
            if typeset -f "${_update_name}" >/dev/null && [ "$(typeset -f "${_update_name}")" != "${_update_owned[$_update_name]}" ]; then
                _update_custom[$_update_name]="$(typeset -f "${_update_name}")"
            fi
        done
        local _DOCREVIEW_RELOADING=1
        source "${_update_target}" >/dev/null || return 1
        for _update_name in "${_update_names[@]}"; do
            if [ -n "${_update_custom[$_update_name]-}" ]; then
                eval "${_update_custom[$_update_name]}"
                printf 'Preserved customized command: %s\n' "${_update_name}"
            elif [ -z "${_DOCREVIEW_OWNED_FUNCTIONS[$_update_name]-}" ] && [ "$(typeset -f "${_update_name}")" = "${_update_owned[$_update_name]}" ]; then
                unset -f "${_update_name}"
            fi
        done
        if [ "${DOCREVIEW_HELPER_SHA256}" != "${_update_hash}" ]; then
            printf '%s\n' 'Helper changed while loading; inspect the file before retrying.' >&2
            return 1
        fi
        printf '%s\n' 'Updated helper commands in this shell.'
    fi
    _docreview_verify || return 1
    _docreview_startup sync "${_update_registered_from}" || return 1
    unset _DOCREVIEW_PENDING_REGISTRATION_SOURCE
}

rag-alias() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"

    case "${1:-}" in
        update|--check-updates)
            [ "$#" -le 2 ] || { printf '%s\n' 'Usage: rag-alias update [PATH]' >&2; return 2; }
            if [ "$1" = update ]; then _docreview_update update "${2:-}"; else _docreview_update check "${2:-}"; fi ;;
        ''|--help|-h)
            printf '%s\n' 'Usage: rag-alias update [CHECKOUT_OR_HELPER_PATH]' \
                'Compare installed and checkout hashes; reload helper-owned commands and repair the existing startup line.' \
                'Use --check-updates [PATH] for a read-only comparison. Customized commands and unrelated startup lines are preserved.' ;;
        *) printf '%s\n' 'Usage: rag-alias update [PATH] or rag-alias --check-updates [PATH]' >&2; return 2 ;;
    esac
}

# Remove only this checkout's registration and unchanged owned commands.
rag-alias-delete() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"

    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-alias-delete' 'Confirm removal of this checkout registration; keep project files.'
    else
        _docreview_uninstall
    fi
}

rag-up() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"

    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-up [COMPOSE_UP_ARGS...]' 'Build/start DEV and prepare an empty DB; existing data is never reset.' 'Requires Python setup from rag-start-quick or uv sync --locked.'
    else
        rag-dev up --build -d "$@"
    fi
}
# Run the selected module in the checkout that registered these commands.
_docreview_python() {
    if [ ! -x "${_DOCREVIEW_ROOT}/.venv/bin/python" ]; then
        printf '%s\n' '[FAIL] Project Python is missing. Run rag-start-quick or uv sync --locked first.' >&2
        return 2
    fi
    (cd "${_DOCREVIEW_ROOT}" && _docreview_runtime .venv/bin/python -m "$@")
}
rag-dev() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"

    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-dev [COMPOSE_ARGS...]' 'Manage the development stack; default: up -d.' 'Examples: rag-dev ps; rag-dev logs -f app; rag-dev down.'
    else
        _docreview_python scripts.stack dev "$@"
    fi
}
rag-prod() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"

    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-prod [COMPOSE_ARGS...]' 'Manage the local public preview; default: up -d.' 'Examples: rag-prod ps; rag-prod logs -f web; rag-prod down.'
    else
        _docreview_python scripts.stack prod "$@"
    fi
}
rag-ollama-check() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"
 _docreview_python scripts.diagnostics.ollama "$@"; }
rag-start-quick() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"
 _docreview_runtime bash "${_DOCREVIEW_ROOT}/scripts/stack/quickstart.sh" "$@"; }
rag-start-fresh() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"

    if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
        printf '%s\n' 'Usage: rag-start-fresh [--extreme] [--no-start] [--discard-tracked] [--status] [--verbose|-vv]' \
            'Preview and clean this checkout, preserving .env and local tool settings; then run quick setup.' \
            'Only uppercase Y confirms (Y/n); --extreme asks twice, removes .env and Ollama models, and stops.'
    else
        local _fresh_python
        _fresh_python="$(uv python find --no-python-downloads 3.14)" || {
            printf '%s\n' 'Python 3.14 is required. Run uv python install 3.14, then rag-start-fresh. Nothing changed.' >&2
            return 2
        }
        (cd "${_DOCREVIEW_ROOT}" && _docreview_runtime "${_fresh_python}" -m scripts.stack.fresh "$@")
    fi
}
rag-reset() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"
 _docreview_python scripts.stack.commands reset "$@"; }
rag-corpus() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"
 _docreview_python scripts.stack.commands corpus "$@"; }
rag-schema() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"
 _docreview_python scripts.schema "$@"; }
rag-help() {
    local -a _DOCREVIEW_ARGS
    local DOCREVIEW_VERBOSE="${DOCREVIEW_VERBOSE:-0}"
    _docreview_options "$@"; set -- "${_DOCREVIEW_ARGS[@]}"

    _docreview_banner
    _docreview_line 'Every command accepts --verbose (-vv). 모든 명령에 --verbose (-vv)를 붙일 수 있습니다'
    _docreview_heading '[QUICK START]'
    _docreview_row 'rag-start-quick' 'Prepare first run'
    _docreview_line '    Cloned and unsure what to do? Run rag-start-quick.'
    _docreview_row 'rag-start-fresh [--no-start|--extreme]' 'Clean checkout and start'
    _docreview_line '    Preserves .env and Ollama models; --extreme deletes both, then stops.'
    _docreview_line '    Then open the printed URL. Acquire, parse/chunk, embeddings, compute BM25.'
    _docreview_heading '[STACK]'
    _docreview_row 'rag-up [COMPOSE_UP_ARGS...]' 'Build DEV stack'
    _docreview_row 'rag-dev [COMPOSE_ARGS...]' 'Manage DEV stack'
    _docreview_row 'rag-prod [COMPOSE_ARGS...]' 'Manage public preview'
    _docreview_heading '[DATA AND DIAGNOSTICS]'
    _docreview_row 'rag-ollama-check [--setup|--details|--web-url URL]' 'Check model connection'
    _docreview_row 'rag-schema check|prepare|recover' 'Inspect/recover local schema'
    _docreview_row 'rag-corpus KIND [OPTIONS...]' 'Manage corpus jobs'
    _docreview_line '    Example: rag-corpus acquire_edgar --identifier NVDA --year 2024'
    _docreview_heading '[RESET]'
    _docreview_row 'rag-reset [--keep-sources|--sample|--status]' 'Reset data and rebuild'
    _docreview_line '    Deletes ORM data/sources; preserves .env, settings, exports and volumes.'
    _docreview_row 'rag-schema recreate [--keep-sources|--sample]' 'Reset data; stay stopped'
    _docreview_line '    No backup. Review preview; only uppercase Y confirms (Y/n).'
    _docreview_heading '[HELP]'
    _docreview_row 'rag-help' 'Show command summary'
    _docreview_row 'rag-alias update [PATH]' 'Refresh loaded helper'
    _docreview_row 'rag-alias-delete' 'Remove helper registration'
    _docreview_line 'Every command accepts --help for options and examples.'
    _docreview_line "Checkout: ${_DOCREVIEW_ROOT}"
}

typeset -ga _DOCREVIEW_COMMAND_NAMES
_DOCREVIEW_COMMAND_NAMES=(rag-alias rag-up rag-dev rag-prod rag-ollama-check rag-reset rag-corpus rag-schema rag-start-quick rag-start-fresh rag-help rag-alias-delete)
typeset -gA _DOCREVIEW_OWNED_FUNCTIONS
_DOCREVIEW_OWNED_FUNCTIONS=()
for _DOCREVIEW_COMMAND in "${_DOCREVIEW_COMMAND_NAMES[@]}"; do
    if ! typeset -f "${_DOCREVIEW_COMMAND}" >/dev/null; then
        printf '[ERROR] Command registration failed: %s\n' "${_DOCREVIEW_COMMAND}" >&2
        return 1 2>/dev/null || exit 1
    fi
    _DOCREVIEW_OWNED_FUNCTIONS[$_DOCREVIEW_COMMAND]="$(typeset -f "$_DOCREVIEW_COMMAND")"
done
unset _DOCREVIEW_COMMAND
export DOCREVIEW_HELPER_PATH="${_DOCREVIEW_ROOT}/${_DOCREVIEW_ALIAS_FILE##*/}"
DOCREVIEW_HELPER_SHA256="$(_docreview_hash "${DOCREVIEW_HELPER_PATH}")" || { return 1 2>/dev/null || exit 1; }
export DOCREVIEW_HELPER_SHA256

if [ "${_DOCREVIEW_INSTALL_STATE}" = 'already installed' ] && [ "${_DOCREVIEW_PREVIOUS_HASH:-${DOCREVIEW_HELPER_SHA256}}" != "${DOCREVIEW_HELPER_SHA256}" ]; then
    _DOCREVIEW_INSTALL_STATE='update required'
fi
if [ "${_DOCREVIEW_EXECUTED}" = 1 ]; then
    _docreview_banner
    case "${1:-}" in
        --delete|--uninstall) _docreview_uninstall; exit $? ;;
        --help|-h) _docreview_activation; exit 0 ;;
        '') ;;
        *) printf '%s\n' 'Usage: source ./rag-alias.sh or ./rag-alias.sh [--delete|--uninstall]' >&2; exit 2 ;;
    esac
    _docreview_install || exit $?
    if [ "${_DOCREVIEW_INSTALL_READY}" = 1 ]; then _docreview_offer_login; fi
    exit $?
fi
if [ "${_DOCREVIEW_RELOADING:-0}" != 1 ] && [ "${DOCREVIEW_VERIFY_ONLY:-0}" != 1 ] && [ "${_DOCREVIEW_FROM_STARTUP}" = 0 ]; then
    if [ "${_DOCREVIEW_INSTALL_STATE}" = install ]; then
        if [ "${_DOCREVIEW_INTERACTIVE}" = 1 ] && [ -t 0 ] && [ -t 1 ]; then
            _docreview_install || return $?
            if [ "${_DOCREVIEW_INSTALL_READY}" = 1 ]; then
                _docreview_reminder
                exec "$(command -v "${_DOCREVIEW_PARENT_SHELL}")" -l
            fi
        else
            _docreview_line '[install] DocReview commands registered in this shell.'
            _docreview_reminder
        fi
    else
        _docreview_line "[${_DOCREVIEW_INSTALL_STATE}]"
    fi
fi
unset _DOCREVIEW_EXECUTED _DOCREVIEW_ALIAS_FILE _DOCREVIEW_FROM_STARTUP _DOCREVIEW_INTERACTIVE
