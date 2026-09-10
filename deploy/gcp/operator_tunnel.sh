#!/usr/bin/env bash
# Production exposes no administrative bypass port.
set -euo pipefail

echo "Production administrator tunneling is disabled; use the local DEV environment for administration." >&2
exit 1
