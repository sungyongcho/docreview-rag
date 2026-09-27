#!/usr/bin/env bash
# Print non-secret origin overrides for DocReview's dedicated Cloudflare Worker.
# Keep overrides in this repository's .env, then deploy from deploy/cloudflare.
# Verify the existing API DNS record if the Oracle instance address changes;
# this command does not modify DNS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SUMMARY=0
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh" >/dev/null

# An explicit static origin wins. Otherwise resolve the Firebase site from its
# configured ID or the default project (whose default Hosting site has that ID).
site_origin="${DEPLOY_DOCREVIEW_SITE_ORIGIN:-}"
if [[ -z "${site_origin}" ]]; then
  firebase_site="${FIREBASE_SITE:-}"
  if [[ -z "${firebase_site}" ]]; then
    firebaserc="${REPO_ROOT}/deploy/firebase/.firebaserc"
    if [[ -f "${firebaserc}" ]]; then
      firebase_site="$(sed -n 's/.*"default"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${firebaserc}" | head -n 1)"
    fi
  fi
  if [[ -z "${firebase_site}" ]]; then
    echo "Set DEPLOY_DOCREVIEW_SITE_ORIGIN, FIREBASE_SITE, or deploy/firebase/.firebaserc." >&2
    exit 1
  fi
  site_origin="https://${firebase_site}.web.app"
fi

printf 'DEPLOY_DOCREVIEW_ORIGIN=%s\n' "${DEPLOY_DOCREVIEW_ORIGIN:-http://docreview-api.sungyongcho.com:${ORIGIN_PORT}}"
printf 'DEPLOY_DOCREVIEW_SITE_ORIGIN=%s\n' "${site_origin}"
printf 'Verify the existing API origin DNS record points to Oracle host %s; DNS is not modified.\n' "${ORACLE_HOST}" >&2
