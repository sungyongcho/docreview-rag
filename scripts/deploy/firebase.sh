#!/usr/bin/env bash
# Build the static Next export for visitors and publish it to Firebase Hosting.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -f "${repo_root}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${repo_root}/.env"
  set +a
fi
: "${FIREBASE_PROJECT_ID:?Set FIREBASE_PROJECT_ID}"

cd "${repo_root}/web"
npm ci
# Pin the public build even when the calling shell contains DEV settings.
env -u NEXT_PUBLIC_OPERATOR_BASE_URL -u NEXT_PUBLIC_OPERATOR_TOKEN -u NEXT_PUBLIC_DB_ENDPOINT \
  NEXT_PUBLIC_ADMIN_MODE=canned \
  NEXT_PUBLIC_API_BASE_URL="https://sungyongcho.com/docreview-rag/api" \
  npm run build

source_dir="${repo_root}/web/out"
public_root="${repo_root}/deploy/firebase/public"
target_dir="${public_root}/docreview-rag"

if [[ ! -f "${source_dir}/index.html" ]]; then
  echo "web/out is missing; run npm run build in web/ first" >&2
  exit 1
fi

rm -rf -- "${target_dir}"
mkdir -p -- "${target_dir}"
cp -a -- "${source_dir}/." "${target_dir}/"
echo "staged ${target_dir}"
cd "${repo_root}/deploy/firebase"
npx firebase-tools deploy --only hosting --project "${FIREBASE_PROJECT_ID}"
