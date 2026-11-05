#!/usr/bin/env bash
# Deploy (or roll back to) one release on the server. Called by the GitHub Actions deploy
# workflow over SSH; can also be run by hand:
#
#   deploy/deploy.sh <release>        e.g. deploy/deploy.sh 84b09f2...  (a git commit SHA)
#
# Expects the layout created by the workflow under DEPLOY_DIR (default: this repo layout):
#   deploy/compose.prod.yaml, deploy/.env.production, infra/postgres/init/02-create-app-role.sh
# and IMAGE_PREFIX, e.g. ghcr.io/owner (images: $IMAGE_PREFIX/sia-backend:<release>, sia-web).
set -euo pipefail

release="${1:?usage: deploy.sh <release>}"
: "${IMAGE_PREFIX:?set IMAGE_PREFIX, e.g. ghcr.io/owner}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose_file="${here}/compose.prod.yaml"

export SIA_RELEASE="${release}"
export SIA_BACKEND_IMAGE="${IMAGE_PREFIX}/sia-backend:${release}"
export SIA_WEB_IMAGE="${IMAGE_PREFIX}/sia-web:${release}"

compose() { docker compose -f "${compose_file}" "$@"; }

echo "==> Pulling ${release}"
compose pull --quiet migrate api worker web

# Restart in stages so the public entry point (Caddy) is never down for long: Caddy holds API
# requests while the API restarts (see Caddyfile), and is itself restarted last, on its own.
# `--wait` returns once services are running/healthy, or fails if one doesn't get there.
echo "==> Database"
compose up --detach --no-build --wait --wait-timeout 120 db

echo "==> Migrations"
compose run --rm --no-deps migrate

echo "==> API and worker"
compose up --detach --no-build --no-deps --wait --wait-timeout 180 api worker

echo "==> Web (Caddy)"
compose up --detach --no-build --no-deps --wait --wait-timeout 60 web

echo "==> Recording the release"
# Compose reads deploy/.env automatically, so later commands on the server (e.g. running an
# admin script) use the images of the running release. No secrets in here.
cat > "${here}/.env" <<ENV
SIA_RELEASE=${SIA_RELEASE}
SIA_BACKEND_IMAGE=${SIA_BACKEND_IMAGE}
SIA_WEB_IMAGE=${SIA_WEB_IMAGE}
ENV

echo "==> Removing images no longer used (keeps the running ones)"
docker image prune --force --filter "until=168h" > /dev/null

echo "==> Deployed ${release}"
compose ps --format "table {{.Service}}\t{{.Status}}"
