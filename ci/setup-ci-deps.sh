#!/usr/bin/env bash
# Install every dependency the CI workflows need, so a session can run the same
# commands locally (lint, unit tests, frontend tests, mutation, e2e, docs).
#
# Idempotent: each step checks first and skips what is already there. Safe to run
# repeatedly (it is wired to a Claude Code SessionStart hook). No step is fatal —
# the script always finishes and prints a summary, so one blocked download does
# not stop a session.
#
# Usage:
#   bash ci/setup-ci-deps.sh                  # install what is missing
#   FORCE=1 bash ci/setup-ci-deps.sh          # install everything again
#   SKIP_BROWSER=1 bash ci/setup-ci-deps.sh   # do not touch Docker or Playwright
#
# The Python packages go in .venv (git ignores it). Activate it before you run the
# Python lanes: source .venv/bin/activate
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

FORCE="${FORCE:-0}"
SKIP_BROWSER="${SKIP_BROWSER:-0}"
VALE_VERSION="${VALE_VERSION:-3.9.1}"
MUTMUT_VERSION="${MUTMUT_VERSION:-3.7.0}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
VENV="${VENV:-$ROOT/.venv}"
PY_FLOOR="${PY_FLOOR:-3.14}"
# Newest first. CI runs the floor; this machine often can only run an older one.
PY_CANDIDATES="${PY_CANDIDATES:-$PY_FLOOR 3.13 3.12}"

INSTALLED=(); SKIPPED=(); FAILED=()

log()  { echo "[setup-ci-deps] $*"; }
skip() { SKIPPED+=("$1");   log "SKIP    $1 (already installed)"; }
ok()   { INSTALLED+=("$1"); log "OK      $1"; }
fail() { FAILED+=("$1");    log "FAILED  $1"; }

have() { command -v "$1" >/dev/null 2>&1; }


# --- Python: the project virtual environment ------------------------------
# Home Assistant sets a Python floor (see ci/check-ha-version.py) that the system
# interpreter is usually below. pip then goes back quietly to a Home Assistant
# that is months old, and that old release does not always run on a new Python.
# So make .venv, and try the candidate interpreters until the unit suite starts.
# .venv is in .gitignore.
VENV_PY=""
vpyhas() { [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import $1" >/dev/null 2>&1; }
vhas()   { [ -x "$VENV/bin/$1" ]; }
vpip() {
  if have uv; then
    uv pip install --quiet --python "$VENV/bin/python" "$@"
  else
    "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check \
      --timeout 120 --retries 5 "$@"
  fi
}
# A fast check that the Home Assistant test fixtures really work on this
# interpreter. An old Home Assistant on a new Python imports and then breaks at
# the first fixture, which a plain "import homeassistant" does not show.
venv_smoke() {
  "$VENV/bin/python" -m pytest "$SMOKE_TEST" -q -p no:cacheprovider >/dev/null 2>&1
}
SMOKE_TEST="${SMOKE_TEST:-tests/unit/test_coordinator_purge.py}"

make_venv() {
  local pyspec="$1"
  rm -rf "$VENV"
  log "Making .venv with Python $pyspec..."
  if have uv; then
    uv venv --quiet --python "$pyspec" "$VENV" >/dev/null 2>&1
  else
    "$pyspec" -m venv "$VENV" >/dev/null 2>&1
  fi
  [ -x "$VENV/bin/python" ] || return 1
  # ci/install-deps.sh installs these in two steps: the second one moves pytest
  # to the version the Home Assistant fixtures need.
  vpip -r requirements-test.txt >/dev/null 2>&1 || return 1
  vpip pytest-homeassistant-custom-component >/dev/null 2>&1 || return 1
  venv_smoke
}

if [ "$FORCE" = 1 ]; then rm -rf "$VENV"; fi
if [ -x "$VENV/bin/python" ] && venv_smoke; then
  VENV_PY="$("$VENV/bin/python" -V 2>&1)"
  skip ".venv ($VENV_PY)"
else
  for pyspec in $PY_CANDIDATES; do
    if have uv; then
      uv python install "$pyspec" >/dev/null 2>&1 || true
    elif ! have "python$pyspec"; then
      continue
    else
      pyspec="python$pyspec"
    fi
    if make_venv "$pyspec"; then
      VENV_PY="$("$VENV/bin/python" -V 2>&1)"
      ok ".venv ($VENV_PY) + requirements-test.txt + pytest-homeassistant-custom-component"
      break
    fi
    log "        Python $pyspec cannot run the Home Assistant fixtures. Trying the next one."
  done
  [ -n "$VENV_PY" ] || fail ".venv (no candidate Python ran the unit tests: $PY_CANDIDATES)"
fi

if [ -x "$VENV/bin/python" ]; then
  # lint.yml: ruff check, ruff format --check, then mypy with Home Assistant.
  for tool in ruff mypy; do
    if [ "$FORCE" = 0 ] && vhas "$tool"; then skip "$tool"; else
      log "Installing $tool..."
      vpip "$tool" && ok "$tool" || fail "$tool"
    fi
  done

  # mypy in lint.yml types against Home Assistant itself. The fixtures package
  # above normally brings it, so this only fills a gap.
  if [ "$FORCE" = 0 ] && vpyhas homeassistant; then
    skip "homeassistant"
  else
    log "Installing homeassistant..."
    vpip homeassistant && ok "homeassistant" || fail "homeassistant"
  fi

  # mutation.yml pins this version of mutmut. Keep the pin.
  if [ "$FORCE" = 0 ] && vhas mutmut && "$VENV/bin/python" -c \
     "import importlib.metadata as m,sys; sys.exit(0 if m.version('mutmut')=='$MUTMUT_VERSION' else 1)" \
     >/dev/null 2>&1; then
    skip "mutmut==$MUTMUT_VERSION"
  else
    log "Installing mutmut==$MUTMUT_VERSION..."
    vpip "mutmut==$MUTMUT_VERSION" && ok "mutmut==$MUTMUT_VERSION" || fail "mutmut==$MUTMUT_VERSION"
  fi

  # AGENTS.md: pip goes back quietly to an old Home Assistant when the
  # interpreter is below the floor. Report that. Do not let it pass unnoticed.
  if vpyhas homeassistant && ! "$VENV/bin/python" ci/check-ha-version.py >/dev/null 2>&1; then
    log "WARNING: the Home Assistant in .venv is older than the newest release,"
    log "         because no interpreter here meets the Home Assistant floor of"
    log "         $PY_FLOOR. mypy and the Home Assistant unit lane thus test an older"
    log "         API than CI does. Run '.venv/bin/python ci/check-ha-version.py'."
  fi
fi

# --- Node: one npm project for each lane -----------------------------------
# root = vitest and Stryker, frontend = the panel build, tests/e2e = Playwright,
# website = the Docusaurus docs site.
npm_project() {
  local dir="$1" label="$2"
  [ -f "$dir/package.json" ] || { log "SKIP    $label (no package.json)"; return; }
  if [ "$FORCE" = 0 ] && [ -d "$dir/node_modules" ]; then skip "$label"; return; fi
  log "Installing $label npm packages..."
  local cmd=(npm ci --no-audit --no-fund)
  [ -f "$dir/package-lock.json" ] || cmd=(npm install --no-audit --no-fund)
  (cd "$dir" && "${cmd[@]}") >/dev/null 2>&1 && ok "$label" || fail "$label"
}
if have npm; then
  npm_project "." "npm (root)"
  npm_project "custom_components/home_keeper/frontend" "npm (panel frontend)"
  npm_project "tests/e2e" "npm (e2e)"
  npm_project "website" "npm (docs site)"
else
  fail "npm (not on PATH)"
fi

# --- Vale: the prose lint --------------------------------------------------
# lint.yml runs the vale action. This is the local equivalent from AGENTS.md.
if [ "$FORCE" = 0 ] && have vale; then
  skip "vale"
else
  log "Installing vale $VALE_VERSION..."
  arch="$(uname -m)"
  case "$arch" in x86_64) varch="64-bit" ;; aarch64|arm64) varch="arm64" ;; *) varch="" ;; esac
  if [ -z "$varch" ]; then
    fail "vale (this script does not know the $arch package)"
  else
    mkdir -p "$BIN_DIR"
    url="https://github.com/errata-ai/vale/releases/download/v${VALE_VERSION}/vale_${VALE_VERSION}_Linux_${varch}.tar.gz"
    tmp="$(mktemp -d)"
    if curl -fsSL "$url" -o "$tmp/vale.tar.gz" && tar -xzf "$tmp/vale.tar.gz" -C "$tmp" vale; then
      install -m 0755 "$tmp/vale" "$BIN_DIR/vale" && ok "vale $VALE_VERSION" || fail "vale"
    else
      fail "vale (the download failed: $url)"
    fi
    rm -rf "$tmp"
  fi
fi
# The pinned ai-tells package that .vale.ini declares.
if have vale || [ -x "$BIN_DIR/vale" ]; then
  if [ "$FORCE" = 0 ] && [ -d styles/ai-tells ]; then
    skip "vale styles (ai-tells)"
  else
    log "Getting the vale styles..."
    PATH="$BIN_DIR:$PATH" vale sync >/dev/null 2>&1 \
      && ok "vale styles (ai-tells)" || fail "vale styles (ai-tells)"
  fi
fi

# --- ffmpeg: the walkthrough video capture ---------------------------------
# ci/capture-video.sh changes the Playwright recording to a gif and an mp4.
if [ "$FORCE" = 0 ] && have ffmpeg; then
  skip "ffmpeg"
else
  log "Installing ffmpeg..."
  SUDO=""
  if [ "$(id -u)" != 0 ] && have sudo && sudo -n true >/dev/null 2>&1; then SUDO="sudo -n"; fi
  if [ "$(id -u)" = 0 ] || [ -n "$SUDO" ]; then
    ( $SUDO apt-get update -qq \
      && DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq ffmpeg ) >/dev/null 2>&1 \
      && ok "ffmpeg" || fail "ffmpeg (apt-get)"
  else
    fail "ffmpeg (no root and no sudo without a password)"
  fi
fi

# --- Docker daemon and Playwright Chromium ---------------------------------
# integration.yml, e2e.yml and walkthrough-preview.yml need these. The browser
# script owns that setup and is also idempotent.
if [ "$SKIP_BROWSER" = 1 ]; then
  log "SKIP    Docker and Playwright Chromium (SKIP_BROWSER=1)"
elif [ -f ci/setup-browser-env.sh ]; then
  log "Starting ci/setup-browser-env.sh (Docker daemon and Playwright Chromium)..."
  bash ci/setup-browser-env.sh \
    && ok "Docker and Playwright Chromium" || fail "Docker and Playwright Chromium"
fi

# --- The summary -----------------------------------------------------------
echo
log "Installed: ${#INSTALLED[@]}  Skipped: ${#SKIPPED[@]}  Failed: ${#FAILED[@]}"
[ "${#INSTALLED[@]}" -gt 0 ] && log "  installed: ${INSTALLED[*]}"
[ "${#SKIPPED[@]}"   -gt 0 ] && log "  skipped:   ${SKIPPED[*]}"
if [ "${#FAILED[@]}" -gt 0 ]; then
  log "  failed:    ${FAILED[*]}"
  log "Start 'bash ci/setup-ci-deps.sh' again to try only the failed steps."
fi
if [ -x "$VENV/bin/python" ]; then
  log "Python tools are in $VENV. Use them with: source ${VENV#$ROOT/}/bin/activate"
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) log "NOTE: put $BIN_DIR in PATH to use the installed tools." ;;
esac
log "Done."
exit 0
