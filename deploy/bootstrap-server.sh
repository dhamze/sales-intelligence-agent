#!/usr/bin/env bash
# One-time setup of a FRESH Ubuntu 24.04 LTS server for Sales Intelligence.
#
#   scp deploy/bootstrap-server.sh root@<server-ip>:/root/
#   ssh root@<server-ip> bash /root/bootstrap-server.sh
#
# Safe to re-run. What it does:
#   - installs security updates, Docker (official repository, signed), fail2ban, ufw;
#   - creates the `deploy` user (SSH key copied from root) that deployments log in as;
#   - SSH: keys only, no root login (only after confirming the deploy user has a key);
#   - firewall: only SSH, HTTP and HTTPS (HTTP/3) are reachable;
#   - automatic security updates (reboots at 04:30 when a kernel update needs it);
#   - Docker log rotation (logs can't fill the disk) and a 2 GB swap file;
#   - /opt/sia for the app's files.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="/opt/sia"

if [[ $(id -u) -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID}" != "ubuntu" || "${VERSION_ID}" != "24.04" ]]; then
  echo "This script is written for Ubuntu 24.04 (found ${PRETTY_NAME})." >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive

echo "==> Updates and base packages"
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl gnupg ufw fail2ban unattended-upgrades

echo "==> Docker (official repository, signature-checked)"
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
  docker-compose-plugin
mkdir -p /etc/docker
daemon_config='{
  "log-driver": "local",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "live-restore": true
}'
systemctl enable --now docker
# Restart Docker only when its settings change: a restart is unnecessary on re-runs, and it
# would cut off this script if it is being run from inside a container.
if [[ "$(cat /etc/docker/daemon.json 2> /dev/null)" != "${daemon_config}" ]]; then
  printf '%s\n' "${daemon_config}" > /etc/docker/daemon.json
  systemctl restart docker
fi

echo "==> Deploy user '${DEPLOY_USER}'"
if ! id "${DEPLOY_USER}" &> /dev/null; then
  useradd --create-home --shell /bin/bash "${DEPLOY_USER}"
fi
# Docker group = can control containers. Acceptable on a single-purpose server; the user has
# no password and logs in with an SSH key only.
usermod -aG docker "${DEPLOY_USER}"
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
if [[ -s /root/.ssh/authorized_keys ]]; then
  install -m 600 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /root/.ssh/authorized_keys \
    "/home/${DEPLOY_USER}/.ssh/authorized_keys"
fi
install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${APP_DIR}" "${APP_DIR}/deploy" \
  "${APP_DIR}/infra/postgres/init" "${APP_DIR}/backups"

echo "==> SSH: keys only, no root login"
if [[ -s "/home/${DEPLOY_USER}/.ssh/authorized_keys" ]]; then
  cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'SSHD'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
SSHD
  # Ubuntu 24.04 starts sshd on demand (ssh.socket), so its runtime directory may not exist
  # yet; `sshd -t` needs it.
  install -d -m 0755 /run/sshd
  sshd -t  # refuse to apply a broken configuration
  # Reload if sshd runs as a service; with socket activation every new connection reads the
  # configuration anyway, and an inactive service must not fail the script.
  systemctl try-reload-or-restart ssh
else
  echo "!! No SSH key found for ${DEPLOY_USER}: root login and passwords LEFT ENABLED." >&2
  echo "!! Add your key to /root/.ssh/authorized_keys and run this script again." >&2
fi

echo "==> Firewall (SSH, HTTP, HTTPS only)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
# Note: Docker-published ports bypass ufw. Only Caddy publishes ports (80/443), which are
# allowed anyway; the database and API are never published.

echo "==> fail2ban (bans IPs that keep failing SSH logins)"
systemctl enable --now fail2ban

echo "==> Automatic security updates"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT
cat > /etc/apt/apt.conf.d/52sia-reboot <<'APT'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
APT

echo "==> Swap (2 GB)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo
echo "Done. Next: log in as '${DEPLOY_USER}' (ssh ${DEPLOY_USER}@<server-ip>) and create"
echo "${APP_DIR}/deploy/.env.production from deploy/env.production.example (see docs/operations.md)."
