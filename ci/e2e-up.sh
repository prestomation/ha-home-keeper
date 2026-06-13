#!/usr/bin/env bash
# One-shot local / session runner for the e2e tests:
#   prepare env -> build panel -> start HA -> wait -> run Playwright -> tear down.
#
# Usage: bash ci/e2e-up.sh [extra playwright args...]
#   KEEP_UP=1 bash ci/e2e-up.sh   # leave the HA container running afterwards
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  if [ "${KEEP_UP:-0}" != "1" ]; then
    echo "[e2e-up] tearing down Home Assistant container..."
    (cd tests/integration && docker compose down -v) || true
  fi
}
trap cleanup EXIT

echo "[e2e-up] preparing browser environment..."
bash ci/setup-browser-env.sh

echo "[e2e-up] building panel JS..."
bash ci/build-panel.sh

echo "[e2e-up] starting Home Assistant..."
(cd tests/integration && docker compose up -d)

echo "[e2e-up] waiting for Home Assistant..."
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8123/api/ 2>/dev/null || true)
  if [ "$code" = "200" ] || [ "$code" = "401" ]; then
    echo "[e2e-up] Home Assistant is responding (HTTP $code)."
    break
  fi
  sleep 2
done

echo "[e2e-up] running Playwright tests..."
bash ci/test-e2e.sh "$@"
