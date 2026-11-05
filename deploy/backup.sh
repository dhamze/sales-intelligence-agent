#!/usr/bin/env bash
# Encrypted database backup. Run nightly from the deploy user's crontab:
#
#   15 3 * * * /opt/sia/deploy/backup.sh >> /opt/sia/backups/backup.log 2>&1
#
# - Dumps the whole database (all organisations) as the schema owner, in PostgreSQL's custom
#   format (compressed; restorable table by table).
# - Encrypts it to a GPG PUBLIC key: the server can write backups but cannot read them. The
#   private key stays offline with the operator (see docs/operations.md, section 6).
# - Keeps 7 daily and 4 weekly backups locally; optionally copies each backup off the server
#   (rclone) and pings a heartbeat URL on success, so a backup that silently stops running
#   raises an alert.
#
# Settings: deploy/backup.env (see deploy/backup.env.example).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
[[ -f "${here}/backup.env" ]] && . "${here}/backup.env"

: "${BACKUP_GPG_RECIPIENT:?set BACKUP_GPG_RECIPIENT in deploy/backup.env}"
backup_dir="${BACKUP_DIR:-${here}/../backups}"
keep_daily="${BACKUP_KEEP_DAILY:-7}"
keep_weekly="${BACKUP_KEEP_WEEKLY:-4}"
compose_project="${COMPOSE_PROJECT:-sia-prod}"

mkdir -p "${backup_dir}/daily" "${backup_dir}/weekly"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${backup_dir}/daily/sia-${stamp}.dump.gpg"
partial="${target}.partial"
trap 'rm -f "${partial}"' EXIT

echo "$(date -u +%FT%TZ) backup starting"
db_container="$(docker ps --quiet --filter "label=com.docker.compose.project=${compose_project}" \
  --filter "label=com.docker.compose.service=db")"
[[ -n "${db_container}" ]] || { echo "database container is not running" >&2; exit 1; }

# pipefail: a failing pg_dump fails the whole pipeline (no half-written "backup").
docker exec "${db_container}" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  | gpg --batch --yes --trust-model always --encrypt --recipient "${BACKUP_GPG_RECIPIENT}" \
      --output "${partial}"
[[ -s "${partial}" ]] || { echo "empty backup" >&2; exit 1; }
mv "${partial}" "${target}"
sha256sum "${target}" > "${target}.sha256"
echo "$(date -u +%FT%TZ) wrote ${target} ($(du -h "${target}" | cut -f1))"

# Sundays: also keep a weekly copy.
if [[ "$(date -u +%u)" == "7" ]]; then
  cp "${target}" "${target}.sha256" "${backup_dir}/weekly/"
fi

prune() {  # keep the newest $2 backups in directory $1
  find "$1" -maxdepth 1 -name 'sia-*.dump.gpg' -printf '%T@ %p\n' | sort -rn \
    | tail -n "+$(($2 + 1))" | cut -d' ' -f2- | while read -r old; do
      rm -f "${old}" "${old}.sha256"
    done
}
prune "${backup_dir}/daily" "${keep_daily}"
prune "${backup_dir}/weekly" "${keep_weekly}"

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  rclone copy "${target}" "${BACKUP_REMOTE}" && echo "copied off-server to ${BACKUP_REMOTE}"
fi
if [[ -n "${BACKUP_PING_URL:-}" ]]; then
  curl -fsS --max-time 10 --retry 3 "${BACKUP_PING_URL}" > /dev/null
fi
echo "$(date -u +%FT%TZ) backup done"
