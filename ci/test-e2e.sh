#!/usr/bin/env bash
# Run the Playwright e2e tests.
# Assumes: Home Assistant Docker container is already running on $HA_URL
# (default http://localhost:8123), the panel JS has been built (ci/build-panel.sh),
# and a Chromium browser is installed (ci/setup-browser-env.sh).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../tests/e2e"

if [ ! -d node_modules ]; then
  npm ci 2>/dev/null || npm install --no-audit --no-fund
fi

exec npx playwright test "$@"
