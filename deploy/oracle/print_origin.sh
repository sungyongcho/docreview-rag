#!/usr/bin/env bash
# Print the origin values for the site's Cloudflare Worker routing (gomoku .env).
# Apply them there, then deploy through that site's routing workflow
# (gomoku/deploy/03_deploy_cloudflare.sh). Re-run after any instance stop/start:
# the Oracle public IP is ephemeral unless a reserved IP was attached.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SUMMARY=0
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh" >/dev/null

# Firebase site id: FIREBASE_SITE wins, otherwise the default project in .firebaserc
# (Firebase Hosting's default site id equals the project id).
firebase_site="${FIREBASE_SITE:-}"
if [[ -z "${firebase_site}" ]]; then
  firebaserc="${REPO_ROOT}/deploy/firebase/.firebaserc"
  if [[ -f "${firebaserc}" ]]; then
    firebase_site="$(sed -n 's/.*"default"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${firebaserc}" | head -n 1)"
  fi
fi
if [[ -z "${firebase_site}" ]]; then
  echo "Set FIREBASE_SITE or create deploy/firebase/.firebaserc (see .firebaserc.example)." >&2
  exit 1
fi

echo "DEPLOY_DOCREVIEW_IP=${ORACLE_HOST}"
echo "DEPLOY_DOCREVIEW_ORIGIN=http://${ORACLE_HOST}:${ORIGIN_PORT}"
echo "DEPLOY_DOCREVIEW_SITE_ORIGIN=https://${firebase_site}.web.app"
