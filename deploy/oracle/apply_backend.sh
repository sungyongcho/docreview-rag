#!/usr/bin/env bash
# Run on the Oracle instance as root. Mirrors deploy/gcp/apply_backend.sh with one
# difference: the application image is built locally on the instance, so it is
# verified with `docker image inspect` instead of pulled from a registry.
# A failed first restore remains blocked for manual inspection.
set -euo pipefail
umask 077

[[ "$(id -u)" == 0 ]] || { echo "Run the remote installer as root." >&2; exit 1; }
mode="${1:?Expected first-install, update or rollback}"
stage="${2:?Expected the private staging directory}"
image="${3:-}"
install_dir=/opt/docreview
data_dir=/var/lib/docreview

fail() { echo "$*" >&2; exit 1; }
case "${mode}" in
  first-install|update) [[ -n "${image}" ]] || fail "An application image is required." ;;
  rollback) ;;
  *) fail "Expected first-install, update or rollback." ;;
esac
[[ -d "${stage}" && ! -L "${stage}" ]] || fail "Private staging directory is missing."
[[ ! -L "${install_dir}" && ! -L "${data_dir}" ]] || fail "Deployment roots must not be symlinks."
mkdir -p -m 0750 "${install_dir}" "${data_dir}"
exec 9>"${install_dir}/.deployment.lock"
flock -n 9 || fail "Another deployment is running."
[[ ! -e "${data_dir}/.restore-in-progress" ]] || fail "Interrupted restore found; preserve and inspect the existing data."

compose() {
  docker compose --project-directory "${install_dir}" \
    --env-file "${install_dir}/.env" --env-file "${install_dir}/image.env" \
    -f "${install_dir}/docker-compose.yml" "$@"
}

if [[ "${mode}" != rollback ]]; then
  docker image inspect "${image}" >/dev/null 2>&1 || fail "Application image not found on this host: ${image} (build it first)."
fi

if [[ "${mode}" == first-install ]]; then
  [[ ! -e "${install_dir}/.env" && ! -e "${install_dir}/docker-compose.yml" ]] \
    || fail "Deployment configuration already exists; first-install will not overwrite it."
  [[ -z "$(find "${data_dir}" -mindepth 1 ! -type d -print -quit)" ]] \
    || fail "First-install requires empty persistent storage; existing data was preserved."
  python3 "${stage}/verify_artifacts.py" "${stage}/artifacts"
  (set -o noclobber; printf 'First restore started: %s\n' "$(date -u +%FT%TZ)" > "${data_dir}/.restore-in-progress")
  install -d -m 0750 "${install_dir}/deploy" "${data_dir}/postgres" \
    "${data_dir}/corpus" "${data_dir}/eval-runs" "${data_dir}/runtime" \
    "${data_dir}/caddy-data" "${data_dir}/caddy-config"
  install -d -m 0700 "${data_dir}/secrets"
  install -m 0644 "${stage}/docker-compose.deploy.yml" "${install_dir}/docker-compose.yml"
  install -m 0644 "${stage}/Caddyfile" "${install_dir}/deploy/Caddyfile"
  install -m 0600 "${stage}/backend.env" "${install_dir}/.env"
  # shellcheck disable=SC1091
  source "${install_dir}/.env"
  printf '%s' "${POSTGRES_PASSWORD:?Missing PostgreSQL password}" > "${data_dir}/secrets/postgres_password"
  printf 'DOCREVIEW_IMAGE=%s\n' "${image}" > "${install_dir}/image.env"
  export DOCREVIEW_IMAGE="${image}"
  compose config --quiet
  # Only the registry images are pulled; the app image was built on this host.
  compose pull db caddy
  python3 "${stage}/verify_artifacts.py" "${stage}/artifacts" --extract-to "${data_dir}"
  chown -R root:10001 "${data_dir}/corpus" "${data_dir}/eval-runs"
  chown 10001:10001 "${data_dir}/runtime"
  chmod 0700 "${data_dir}/runtime"
  compose up -d --wait --wait-timeout 120 db
  compose exec -T db pg_restore --exit-on-error --single-transaction --no-owner --no-privileges \
    -U filing -d filing < "${stage}/artifacts/database.public.dump"
  compose exec -T db psql -X -v ON_ERROR_STOP=1 -At -U filing -d filing \
    < "${stage}/verify_restore.sql" > "${stage}/database-report.json"
  python3 "${stage}/verify_artifacts.py" "${stage}/artifacts" \
    --database-report "${stage}/database-report.json"
  # The image entrypoint additionally checks its exact database schema before startup.
  compose run --rm --no-deps app /app/.venv/bin/python -c 'print("Runtime schema verified.")'
  compose up -d --wait --wait-timeout 180 app caddy
  mv "${data_dir}/.restore-in-progress" "${data_dir}/.restore-complete"
else
  [[ -f "${data_dir}/.restore-complete" && -f "${data_dir}/postgres/PG_VERSION" \
    && -f "${install_dir}/image.env" ]] || fail "A completed first-install is required; no data was restored or reset."
  if [[ "${mode}" == rollback ]]; then
    [[ -f "${install_dir}/rollback-image" ]] || fail "No rollback image is recorded."
    image="$(cat "${install_dir}/rollback-image")"
    docker image inspect "${image}" >/dev/null
  else
    [[ ! -e "${install_dir}/.update-in-progress" ]] \
      || fail "An interrupted update exists; use rollback before attempting another update."
    previous_id="$(compose images -q app)"
    [[ -n "${previous_id}" ]] || fail "Cannot preserve a rollback image for the existing app."
    rollback_image="docreview-rollback:$(date -u +%Y%m%dT%H%M%S)-$$"
    docker image tag "${previous_id}" "${rollback_image}"
    printf '%s\n' "${rollback_image}" > "${install_dir}/rollback-image"
    (set -o noclobber; printf '%s\n' "${image}" > "${install_dir}/.update-in-progress")
  fi
  export DOCREVIEW_IMAGE="${image}"
  # Update only the app; database, sources, evaluations and SQLite usage remain intact.
  compose up -d --no-deps --wait --wait-timeout 180 app
  printf 'DOCREVIEW_IMAGE=%s\n' "${image}" > "${install_dir}/image.env"
  if [[ -f "${install_dir}/.update-in-progress" ]]; then
    mv "${install_dir}/.update-in-progress" "${install_dir}/.last-update"
  fi
fi
compose ps
