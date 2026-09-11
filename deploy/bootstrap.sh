#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 DigitalOcean droplet for the grader.
#
#   ssh root@<droplet-ip> 'bash -s' < deploy/bootstrap.sh
#
# Run once as root. Safe to re-run: every step checks before it changes
# anything. What it does:
#
#   1. apt update/upgrade, base tools
#   2. Docker Engine + compose plugin from Docker's apt repository
#   3. user "deploy" (docker group) with root's authorized_keys
#   4. unattended security upgrades
#   5. ufw: OpenSSH, 80, 443 only
#   6. fail2ban for sshd
#   7. /srv/grader owned by deploy
#   8. allow unprivileged user namespaces (bubblewrap inside the worker)
#
# Afterwards, follow deploy/README.md: copy docker-compose.prod.yml and .env
# to /srv/grader, `docker login ghcr.io` as deploy, run deploy/deploy.sh.

set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="${APP_DIR:-/srv/grader}"
export DEBIAN_FRONTEND=noninteractive

if [[ "${EUID}" -ne 0 ]]; then
  echo "bootstrap.sh must run as root" >&2
  exit 1
fi

log() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------- 1. packages
log "Updating packages"
apt-get update -q
apt-get upgrade -yq
apt-get install -yq --no-install-recommends \
  ca-certificates curl gnupg ufw fail2ban unattended-upgrades apt-listchanges

# ------------------------------------------------------------------ 2. docker
log "Installing Docker Engine from download.docker.com"
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
arch="$(dpkg --print-architecture)"
docker_list="deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable"
if [[ ! -f /etc/apt/sources.list.d/docker.list ]] || ! grep -qF "${docker_list}" /etc/apt/sources.list.d/docker.list; then
  echo "${docker_list}" > /etc/apt/sources.list.d/docker.list
  apt-get update -q
fi
apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# Rotate container logs even if a compose file forgets to.
if [[ ! -f /etc/docker/daemon.json ]]; then
  cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" }
}
JSON
  systemctl restart docker
fi

# ------------------------------------------------------------- 3. deploy user
log "Creating user ${DEPLOY_USER}"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"

home="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
install -d -m 0700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${home}/.ssh"
ak="${home}/.ssh/authorized_keys"
touch "${ak}"
chmod 0600 "${ak}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${ak}"
# Copy root's keys (the ones DigitalOcean installed) without clobbering keys
# added later by hand.
if [[ -f /root/.ssh/authorized_keys ]]; then
  while IFS= read -r key; do
    [[ -z "${key}" || "${key}" == \#* ]] && continue
    grep -qxF -- "${key}" "${ak}" || echo "${key}" >> "${ak}"
  done < /root/.ssh/authorized_keys
fi

# ----------------------------------------------------- 4. unattended upgrades
log "Enabling unattended security upgrades"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
CONF
# Reboot automatically (at 04:00) when a kernel/libc update needs it.
cat > /etc/apt/apt.conf.d/52grader-unattended <<'CONF'
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
CONF
systemctl enable --now unattended-upgrades

# --------------------------------------------------------------------- 5. ufw
# Note: Docker publishes ports by inserting its own iptables rules ahead of
# ufw, so anything with "ports:" in a compose file is reachable regardless of
# ufw. The prod compose file only publishes 80/443, which are open here anyway.
log "Configuring ufw"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp     # HTTP/3
ufw --force enable

# ---------------------------------------------------------------- 6. fail2ban
log "Configuring fail2ban"
# Ubuntu 24.04 has no /var/log/auth.log by default; read the journal instead.
cat > /etc/fail2ban/jail.local <<'CONF'
[DEFAULT]
backend = systemd
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
CONF
systemctl enable --now fail2ban
systemctl restart fail2ban

# ----------------------------------------------------------------- 7. app dir
log "Creating ${APP_DIR}"
install -d -m 0750 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${APP_DIR}"

# ------------------------------------------------- 8. user namespaces (bwrap)
# The worker sandboxes student notebooks with bubblewrap, which needs
# unprivileged user namespaces. Ubuntu 24.04 restricts those via AppArmor by
# default; this restores the pre-24.04 kernel default for the whole host.
log "Allowing unprivileged user namespaces"
cat > /etc/sysctl.d/60-grader-userns.conf <<'CONF'
kernel.apparmor_restrict_unprivileged_userns = 0
CONF
sysctl --system >/dev/null

# ------------------------------------------------------------------- summary
cat <<MSG

Bootstrap complete.

Next, as ${DEPLOY_USER}:

  ssh ${DEPLOY_USER}@$(hostname -I | awk '{print $1}')

  # GHCR login with a classic PAT that has only read:packages
  # (GitHub -> Settings -> Developer settings -> Personal access tokens):
  echo '<PAT>' | docker login ghcr.io -u <github-username> --password-stdin

  # Then copy docker-compose.prod.yml, .env and deploy/deploy.sh into ${APP_DIR}
  # and run ./deploy.sh. Full steps: deploy/README.md

MSG
