#!/usr/bin/env bash
# Print the two origin values the Cloudflare Worker (gomoku repo) needs.
# Paste the output into the gomoku .env, then run its 03_deploy_cloudflare.sh.
# Re-run after every VM stop/start: the external IP is ephemeral.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh" >/dev/null

external_ip="$(gcloud compute instances describe "${VM_NAME}" \
  --project "${PROJECT_ID}" \
  --zone "${ZONE}" \
  --format 'value(networkInterfaces[0].accessConfigs[0].natIP)')"
if [[ -z "${external_ip}" ]]; then
  echo "VM ${VM_NAME} has no external IP. Is it running?" >&2
  exit 1
fi

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

echo "DEPLOY_DOCREVIEW_IP=${external_ip}"
echo "DEPLOY_DOCREVIEW_ORIGIN=http://${external_ip}:${ORIGIN_PORT}"
echo "DEPLOY_DOCREVIEW_SITE_ORIGIN=https://${firebase_site}.web.app"
