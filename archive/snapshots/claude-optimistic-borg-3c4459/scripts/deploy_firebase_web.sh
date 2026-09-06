#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${FIREBASE_PROJECT_ID:?Set FIREBASE_PROJECT_ID}"

cd "${repo_root}/web"
npm ci
NEXT_PUBLIC_API_BASE_URL="https://sungyongcho.com/docreview-rag-agent/api" \
NEXT_PUBLIC_ADMIN_MODE="canned" \
npm run build

"${repo_root}/scripts/stage_firebase_web.sh"
cd "${repo_root}/deploy/firebase"
npx firebase-tools deploy --only hosting --project "${FIREBASE_PROJECT_ID}"
