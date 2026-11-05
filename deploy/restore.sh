#!/usr/bin/env bash
# Restore an encrypted backup made by backup.sh. Needs the backup PRIVATE key in the GPG
# keyring of whoever runs it (import it only for the restore; see docs/operations.md).
#
#   restore.sh verify  <file.dump.gpg>   restore into a scratch database, check it, delete it
#   restore.sh replace <file.dump.gpg>   REPLACE the production database (asks to confirm)
#
# `verify` is the regular restore drill: a backup only counts once it has been restored.
set -euo pipefail

mode="${1:-}"
file="${2:-}"
if [[ "${mode}" != "verify" && "${mode}" != "replace" ]] || [[ ! -f "${file}" ]]; then
  echo "usage: restore.sh verify|replace <file.dump.gpg>" >&2
  exit 2
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose_project="${COMPOSE_PROJECT:-sia-prod}"
compose() { docker compose -f "${here}/compose.prod.yaml" "$@"; }

if [[ -f "${file}.sha256" ]]; then
  (cd "$(dirname "${file}")" && sha256sum --check --quiet "$(basename "${file}").sha256")
  echo "checksum ok"
fi

db="$(docker ps --quiet --filter "label=com.docker.compose.project=${compose_project}" \
  --filter "label=com.docker.compose.service=db")"
[[ -n "${db}" ]] || { echo "database container is not running" >&2; exit 1; }

psql_admin() {  # run SQL as the owner on the maintenance database
  docker exec -i "${db}" sh -c 'psql -v ON_ERROR_STOP=1 -qAt -U "$POSTGRES_USER" -d postgres'
}
restore_into() {  # decrypt and restore into database $1
  gpg --batch --quiet --decrypt "${file}" \
    | docker exec -i "${db}" sh -c "pg_restore -U \"\$POSTGRES_USER\" -d '$1' --exit-on-error"
}
query() {  # run SQL as the owner on database $1, print the result
  docker exec -i "${db}" sh -c "psql -v ON_ERROR_STOP=1 -qAt -U \"\$POSTGRES_USER\" -d '$1'"
}
check() {  # sanity checks on database $1
  local version tables forced
  version="$(echo "SELECT version_num FROM alembic_version" | query "$1")"
  tables="$(echo "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'" | query "$1")"
  forced="$(echo "SELECT count(*) FROM pg_class WHERE relforcerowsecurity" | query "$1")"
  [[ -n "${version}" && "${tables}" -gt 10 && "${forced}" -gt 5 ]] || {
    echo "restored database failed the checks (version=${version} tables=${tables} rls=${forced})" >&2
    return 1
  }
  echo "schema version ${version}, ${tables} tables, row-level security on ${forced} tables"
  echo "SELECT 'organizations', count(*) FROM organizations UNION ALL
        SELECT 'users', count(*) FROM users UNION ALL
        SELECT 'companies', count(*) FROM companies UNION ALL
        SELECT 'contacts', count(*) FROM contacts UNION ALL
        SELECT 'account_briefs', count(*) FROM account_briefs" | query "$1" | tr '|' ' '
}

if [[ "${mode}" == "verify" ]]; then
  scratch="sia_restore_check"
  trap 'echo "DROP DATABASE IF EXISTS ${scratch}" | psql_admin' EXIT
  echo "DROP DATABASE IF EXISTS ${scratch}; CREATE DATABASE ${scratch}" | psql_admin
  restore_into "${scratch}"
  check "${scratch}"
  echo "VERIFIED: ${file} restores cleanly"
  exit 0
fi

# --- replace -------------------------------------------------------------------------------
live="$(docker exec "${db}" sh -c 'echo "$POSTGRES_DB"')"
echo "This REPLACES the production database '${live}' with ${file}."
echo "All changes since that backup are lost. Type: replace production"
answer="${CONFIRM:-}"
[[ -n "${answer}" ]] || read -r answer
[[ "${answer}" == "replace production" ]] || { echo "aborted" >&2; exit 1; }

# Restore into a new database first: if anything fails, production is untouched.
incoming="${live}_incoming"
echo "DROP DATABASE IF EXISTS ${incoming}; CREATE DATABASE ${incoming}" | psql_admin
restore_into "${incoming}"
check "${incoming}"

echo "Stopping the app"
compose stop web api worker
echo "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE datname = '${live}' AND pid <> pg_backend_pid();
      DROP DATABASE ${live};
      ALTER DATABASE ${incoming} RENAME TO ${live};" | psql_admin > /dev/null
echo "Starting the app"
compose up --detach --no-build --no-deps --wait --wait-timeout 180 api worker web
echo "RESTORED: production now runs on ${file}"
