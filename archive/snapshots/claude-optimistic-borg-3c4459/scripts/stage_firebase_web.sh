#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${repo_root}/web/out"
public_root="${repo_root}/deploy/firebase/public"
target_dir="${public_root}/docreview-rag-agent"

if [[ ! -f "${source_dir}/index.html" ]]; then
  echo "web/out is missing; run npm run build in web/ first" >&2
  exit 1
fi

rm -rf -- "${target_dir}"
mkdir -p -- "${target_dir}"
cp -a -- "${source_dir}/." "${target_dir}/"
echo "staged ${target_dir}"
