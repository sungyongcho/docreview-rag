#!/usr/bin/env bash
# Refresh the full-suite line the dashboard shows.
set -uo pipefail
cd "$(dirname "$0")/.."
uv run pytest -q 2>&1 | tail -1 | tee .dashboard-suite
