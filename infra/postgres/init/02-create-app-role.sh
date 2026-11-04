#!/usr/bin/env bash
# Creates (or updates) `sia_app`, the restricted login role the API uses at runtime.
#
# - Runs automatically when the database volume is first created.
# - Safe to re-run at any time (e.g. after changing SIA_APP_DB_PASSWORD):
#     docker compose exec db bash /docker-entrypoint-initdb.d/02-create-app-role.sh
# - CI runs it against the service container (connection via standard PG* env vars).
#
# Table-level permissions are granted by migrations, not here.
set -euo pipefail

: "${SIA_APP_DB_PASSWORD:?SIA_APP_DB_PASSWORD must be set}"

# The password is read inside psql with \getenv, so it never appears in the process list.
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB:-postgres}" <<'EOSQL'
\getenv app_password SIA_APP_DB_PASSWORD
SELECT 'CREATE ROLE sia_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sia_app') \gexec
ALTER ROLE sia_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'app_password';
EOSQL

echo "sia_app role is ready."
