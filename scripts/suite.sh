#!/usr/bin/env bash
# Refresh the slow lines the dashboard caches: the suite result and the test count.
set -uo pipefail
cd "$(dirname "$0")/.."
uv run pytest -q --collect-only 2>/dev/null | tail -1 | grep -oE '^[0-9]+' > .dashboard-collect
uv run pytest -q 2>&1 | tail -1 | tee .dashboard-suite
