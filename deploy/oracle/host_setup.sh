#!/usr/bin/env bash
# Runs ON the Oracle A1 instance as root (prepare_host.sh copies and invokes it).
# Idempotent: prepares Docker, swap, the host firewall and DocReview's directories.
# Ubuntu 24.04 aarch64 (Oracle image).
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run this host setup script as root" >&2
  exit 1
fi

SSH_USER="${1:-ubuntu}"
ORIGIN_PORT="${2:-8880}"

log() { echo "[$(date +'%F %T')] $*"; }

log "Installing Docker, compose, rsync and Python..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl rsync python3 docker.io docker-compose-v2 iptables-persistent
systemctl enable --now docker
if id "${SSH_USER}" >/dev/null 2>&1; then
  usermod -aG docker "${SSH_USER}"
fi

# A swap file protects image builds from OOM kills.
if [[ ! -f /swapfile ]]; then
  log "Creating 2 GB swap file..."
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
  log "Swap file exists."
fi

# Oracle's Ubuntu image ends INPUT with a REJECT. Source restriction to Cloudflare
# IPv4 ranges is enforced by the VCN security list.
if iptables -C INPUT -p tcp -m state --state NEW --dport "${ORIGIN_PORT}" -j ACCEPT 2>/dev/null; then
  log "Firewall: port ${ORIGIN_PORT} already open."
else
  # Position 6 mirrors Oracle's default layout, before the trailing REJECT.
  if ! iptables -I INPUT 6 -p tcp -m state --state NEW --dport "${ORIGIN_PORT}" -j ACCEPT 2>/dev/null; then
    iptables -I INPUT -p tcp -m state --state NEW --dport "${ORIGIN_PORT}" -j ACCEPT
  fi
  log "Firewall: opened tcp/${ORIGIN_PORT}."
fi
netfilter-persistent save >/dev/null

install -d -m 0750 /opt/docreview /var/lib/docreview
install -d -m 0755 -o "${SSH_USER}" -g "${SSH_USER}" "/home/${SSH_USER}/build"

log "Host ready: $(uname -m), $(nproc) cores, docker $(docker --version | awk '{print $3}' | tr -d ,)"
