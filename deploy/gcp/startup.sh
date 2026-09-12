#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run this startup script as root" >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl python3 docker.io docker-compose-v2
systemctl enable --now docker

# Artifact Registry pull auth for the VM service account (metadata-server token).
DCG_VERSION=2.1.30
curl -fsSL "https://github.com/GoogleCloudPlatform/docker-credential-gcr/releases/download/v${DCG_VERSION}/docker-credential-gcr_linux_amd64-${DCG_VERSION}.tar.gz" \
  | tar -xz -C /usr/local/bin docker-credential-gcr
docker-credential-gcr configure-docker --registries us-central1-docker.pkg.dev

install -d -m 0750 /opt/docreview /var/lib/docreview

if [[ ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "DocReview VM prerequisites installed. Copy deployment files into /opt/docreview."
