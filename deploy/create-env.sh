#!/usr/bin/env bash
# Create /opt/sia/deploy/.env.production ON THE SERVER, with fresh random passwords.
#
#   create-env.sh <hostname>        e.g. create-env.sh sia-demo.duckdns.org
#
# Passwords are generated here, on the server, so they never travel through chats, clipboards
# or other machines. Refuses to overwrite an existing file (that would lock the app out of
# its own database). Optional values (AI key, Sentry) are left empty: add them later with
# `nano /opt/sia/deploy/.env.production`.
set -euo pipefail

host="${1:?usage: create-env.sh <hostname, e.g. sia-demo.duckdns.org>}"
if [[ ! "${host}" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then
  echo "Not a valid hostname: ${host}" >&2
  exit 2
fi
target="${ENV_FILE:-/opt/sia/deploy/.env.production}"
if [[ -e "${target}" ]]; then
  echo "${target} already exists; not overwriting it." >&2
  exit 1
fi

secret() { head -c 32 /dev/urandom | base64 | tr -d '/+=\n' | head -c 40; }

umask 077  # readable by the deploy user only
cat > "${target}" <<ENV
# Production settings (created $(date -u +%F) by deploy/create-env.sh). Keep private.
SITE_ADDRESS=${host}
SIA_ALLOWED_ORIGINS=["https://${host}"]

POSTGRES_DB=sia
POSTGRES_USER=sia_owner
POSTGRES_PASSWORD=$(secret)
SIA_APP_DB_PASSWORD=$(secret)

SIA_LOG_FORMAT=json
SIA_LOG_LEVEL=INFO

# Cost protection: AI pauses for everyone at this estimated monthly spend; public signups
# get no AI (an operator enables it per organisation).
SIA_AI_MONTHLY_BUDGET_USD=10
SIA_AI_ENABLED_FOR_NEW_ORGS=false

# Optional, add later: a production-only Anthropic key (with a spend limit set in the
# Anthropic console) and the backend Sentry DSN.
ANTHROPIC_API_KEY=
SENTRY_DSN=
ENV
echo "Created ${target} for https://${host} (passwords generated on this server)."
