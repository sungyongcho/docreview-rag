#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

environment_dump="$(mktemp)"
cleanup_environment_dump() {
  rm -f "${environment_dump}"
}
trap cleanup_environment_dump EXIT
if ! .venv/bin/python scripts/local_env.py > "${environment_dump}"; then
  exit 2
fi
while IFS= read -r -d '' key && IFS= read -r -d '' value; do
  printf -v "${key}" '%s' "${value}"
  export "${key}"
done < "${environment_dump}"
cleanup_environment_dump
trap - EXIT

export HOST_GID="${HOST_GID:-$(id -g)}"
export DOCREVIEW_ADMIN_CORS_ORIGIN="http://${DOCREVIEW_LOCAL_HOST}:${DOCREVIEW_OPERATOR_WEB_PORT}"

if [[ "${MODE}" == "dev" ]]; then
  export NEXT_PUBLIC_ADMIN_MODE=live
  export DOCREVIEW_ADMIN_MODE=live
  docker compose up --build -d app
  printf 'UI http://%s:%s/docreview-rag-agent/\nAPI http://%s:%s\nDB %s:%s\nOperations http://%s:%s\n' "${DOCREVIEW_LOCAL_HOST}" "${DOCREVIEW_OPERATOR_WEB_PORT}" "${DOCREVIEW_LOCAL_HOST}" "${APP_PORT}" "${DOCREVIEW_LOCAL_HOST}" "${DB_PORT}" "${DOCREVIEW_LOCAL_HOST}" "${DOCREVIEW_OPERATOR_PORT}"
  exec scripts/run_local_operator_web.sh
fi

export NEXT_PUBLIC_ADMIN_MODE=canned
export DOCREVIEW_ADMIN_MODE=readonly
docker compose up --build -d app
printf 'UI http://%s:%s/docreview-rag-agent/\nAPI http://%s:%s\nDB %s:%s\n' "${DOCREVIEW_LOCAL_HOST}" "${APP_PORT}" "${DOCREVIEW_LOCAL_HOST}" "${APP_PORT}" "${DOCREVIEW_LOCAL_HOST}" "${DB_PORT}"
