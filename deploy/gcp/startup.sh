#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run this startup script as root" >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl docker.io docker-compose-v2
systemctl enable --now docker

install -d -m 0750 /opt/docreview /var/lib/docreview/{postgres,corpus,eval-runs,caddy-data,caddy-config,secrets}

if [[ ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "DocReview VM prerequisites installed. Copy deployment files into /opt/docreview."
