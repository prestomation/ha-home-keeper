#!/usr/bin/env bash
# Prepare the environment for Playwright browser e2e tests.
#
# Idempotent: safe to run repeatedly (e.g. from a Claude Code SessionStart hook).
# Starts the Docker daemon (needed for the Home Assistant container) and installs
# the Chromium browser Playwright drives. Non-fatal if Docker can't start so it
# never blocks unrelated sessions — e2e scripts surface a clear error instead.
set -uo pipefail

log() { echo "[setup-browser-env] $*"; }

# ── Docker daemon ───────────────────────────────────────────────────────────
if docker info >/dev/null 2>&1; then
  log "Docker daemon already running."
else
  log "Starting Docker daemon..."
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo -n dockerd >/tmp/dockerd.log 2>&1 &
  else
    dockerd >/tmp/dockerd.log 2>&1 &
  fi
  for _ in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
  done
  if docker info >/dev/null 2>&1; then
    log "Docker daemon is up."
  else
    log "WARNING: Docker daemon did not start; e2e tests requiring HA will not run here."
    log "See /tmp/dockerd.log for details."
  fi
fi

# ── Playwright browser ──────────────────────────────────────────────────────
# Install into tests/e2e so it uses that project's pinned @playwright/test.
E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/tests/e2e"
if [ -d "$E2E_DIR" ]; then
  if [ ! -d "$E2E_DIR/node_modules" ]; then
    log "Installing tests/e2e npm deps..."
    (cd "$E2E_DIR" && npm install --no-audit --no-fund) || log "WARNING: npm install failed"
  fi
  log "Installing Playwright Chromium (with OS deps)..."
  (cd "$E2E_DIR" && npx playwright install --with-deps chromium) \
    || npx playwright install chromium \
    || log "WARNING: Playwright browser install failed"
else
  log "tests/e2e not present yet; skipping browser install."
fi

log "Done."
