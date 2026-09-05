# Source this file from Bash or Zsh; every command targets this checkout.
if [ -n "${ZSH_VERSION:-}" ]; then
    eval '_DOCREVIEW_ALIAS_FILE=${(%):-%N}'
elif [ -n "${BASH_VERSION:-}" ]; then
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
alias rag-dev-up='rag-dev up -d'
alias rag-dev-down='rag-dev down'
alias rag-prod-up='rag-prod up -d'
alias rag-prod-down='rag-prod down'
