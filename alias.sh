# Source this file from Bash or Zsh; every command targets this checkout.
if [ -n "${ZSH_VERSION:-}" ]; then
    case "${ZSH_EVAL_CONTEXT:-}" in
        *:file) ;;
        *) printf '%s\n' 'Use source ./alias.sh to register commands in your current shell.' >&2; exit 1 ;;
    esac
    eval '_DOCREVIEW_ALIAS_FILE=${(%):-%N}'
elif [ -n "${BASH_VERSION:-}" ]; then
    if [ "${BASH_SOURCE[0]}" = "$0" ]; then
        printf '%s\n' 'Use source ./alias.sh to register commands in your current shell.' >&2
        exit 1
    fi
    _DOCREVIEW_ALIAS_FILE="${BASH_SOURCE[0]}"
else
    printf '%s\n' 'DocReview aliases require Bash or Zsh.' >&2
    return 1
fi
_DOCREVIEW_ROOT="$(cd "$(dirname "${_DOCREVIEW_ALIAS_FILE}")" && pwd)"
unset _DOCREVIEW_ALIAS_FILE

rag-dev() { bash "${_DOCREVIEW_ROOT}/scripts/run_local.sh" dev "$@"; }
rag-prod() { bash "${_DOCREVIEW_ROOT}/scripts/run_local.sh" prod "$@"; }
rag-diagnose() { bash "${_DOCREVIEW_ROOT}/scripts/diagnose_ollama.sh" "$@"; }
rag-ollama-check() { rag-diagnose "$@"; }
rag-help() {
    printf '%s\n' \
        'DocReview commands (target: this checkout)' \
        '' \
        '  rag-dev [COMPOSE_ARGS...]    Development stack (default: up -d)' \
        '  rag-prod [COMPOSE_ARGS...]   Local public preview (default: up -d)' \
        '  rag-dev-up / rag-prod-up    Start the selected stack in the background' \
        '  rag-dev-down / rag-prod-down Stop the stack and preserve data volumes' \
        '' \
        '  rag-dev up --build -d       Rebuild and start development services' \
        '  rag-dev ps                  Show service status' \
        '  rag-dev logs -f app          Follow API logs' \
        '  rag-prod logs -f web         Follow preview web logs' \
        '' \
        '  rag-ollama-check             Diagnose the app and its model connection' \
        '  rag-ollama-check --web-url http://localhost:9000' \
        '                               Diagnose a different DocReview web address' \
        '  rag-ollama-check --help      Show diagnostic options' \
        '  rag-diagnose [OPTIONS...]    Same diagnostic command' \
        '  rag-help                    Show this help' \
        '' \
        'Diagnostics read server/model metadata; they do not start or install Ollama.' \
        'The --web-url option points to DocReview, not to the Ollama server.'
}
alias rag-dev-up='rag-dev up -d'
alias rag-dev-down='rag-dev down'
alias rag-prod-up='rag-prod up -d'
alias rag-prod-down='rag-prod down'

printf '%s\n' \
    '' \
    '  +--------------------------------------+' \
    '  |  [D]  DOCREVIEW COMMANDS              |' \
    '  |       Evidence first.                 |' \
    '  +--------------------------------------+' \
    ''
printf '[OK] DocReview commands registered in this shell: %s\n' "${_DOCREVIEW_ROOT}"
printf '%s\n' \
    '  rag-dev, rag-prod, rag-diagnose, rag-ollama-check, rag-help' \
    '  rag-dev-up, rag-dev-down, rag-prod-up, rag-prod-down' \
    'Run rag-help for usage and options.'
