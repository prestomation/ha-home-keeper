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
#
# Each part can be left alone on its own:
#   SKIP_PYTHON=1  SKIP_NPM=1  SKIP_VALE=1  SKIP_FFMPEG=1  SKIP_BROWSER=1
#
# The Python packages go in .venv (git ignores it). Activate it before you run the
# Python lanes: source .venv/bin/activate
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

FORCE="${FORCE:-0}"
SKIP_PYTHON="${SKIP_PYTHON:-0}"
SKIP_NPM="${SKIP_NPM:-0}"
SKIP_VALE="${SKIP_VALE:-0}"
SKIP_FFMPEG="${SKIP_FFMPEG:-0}"
SKIP_BROWSER="${SKIP_BROWSER:-0}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
# The lock lives in the repository, so two checkouts of it do not share one.
LOCK_DIR="${LOCK_DIR:-$ROOT/.setup-ci-deps.lock}"

# CI pins the vale binary in its own action, and AGENTS.md says a local vale can
# miss what CI reports. So this version is the local one, and there is no CI pin
# to read it from. The ai-tells style package needs no pin here: .vale.ini holds
# the release URL, and "vale sync" reads it.
VALE_VERSION="${VALE_VERSION:-3.9.1}"

# Read the pins that CI already holds, so this script cannot go stale on its own.
# sed and awk only: grep -oP is GNU, and this script also runs on macOS.
# These run in a command substitution, which is a subshell, so a note goes to
# stderr rather than to an array the parent would never see.
pin_note() { echo "[setup-ci-deps] NOTE: $1" >&2; }

# mutation.yml holds the mutmut pin, as "pip install mutmut==3.7.0".
read_mutmut_pin() {
  local f=".github/workflows/mutation.yml" v=""
  [ -f "$f" ] && v="$(sed -n 's/.*[^#]*mutmut==\([0-9][0-9.]*\).*/\1/p' "$f" | head -1)"
  if [ -z "$v" ]; then
    pin_note "no mutmut pin found in $f. Using $1."
    v="$1"
  fi
  echo "$v"
}
# pyproject.toml holds the Python floor, as python_version under [tool.mypy].
# Read it from that table only: another table can carry the same key.
read_py_floor() {
  local f="pyproject.toml" v=""
  [ -f "$f" ] && v="$(awk '
    /^\[/ { in_mypy = ($0 ~ /^\[tool\.mypy\]/); next }
    in_mypy && /^[[:space:]]*python_version[[:space:]]*=/ {
      gsub(/.*=[[:space:]]*"?|"[[:space:]]*$|[[:space:]]*$/, ""); print; exit
    }' "$f")"
  if [ -z "$v" ]; then
    pin_note "no python_version under [tool.mypy] in $f. Using $1."
    v="$1"
  fi
  echo "$v"
}
MUTMUT_VERSION="${MUTMUT_VERSION:-$(read_mutmut_pin 3.7.0)}"
PY_FLOOR="${PY_FLOOR:-$(read_py_floor 3.14)}"

# rm -rf runs on this path, so resolve it first and then refuse anything that is
# not inside the repository. A text test alone passes $ROOT/../elsewhere.
VENV_RAW="${VENV:-$ROOT/.venv}"
case "$VENV_RAW" in /*) ;; *) VENV_RAW="$ROOT/$VENV_RAW" ;; esac
have_cmd() { command -v "$1" >/dev/null 2>&1; }
abs_path() {  # resolve . .. and symlinks, whether or not the path exists yet
  if have_cmd realpath; then
    realpath -m "$1" 2>/dev/null && return
  fi
  python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1" 2>/dev/null
}
VENV="$(abs_path "$VENV_RAW")"
ROOT_REAL="$(abs_path "$ROOT")"
case "${VENV%/}/" in
  "$ROOT_REAL"/?*/) ;;
  *) echo "[setup-ci-deps] VENV must resolve to a path inside $ROOT_REAL. Got: '$VENV'" >&2
     exit 2 ;;
esac
VENV="${VENV%/}"

# Newest first. CI runs the floor; this machine often can only run an older one.
if [ -n "${PY_CANDIDATES:-}" ]; then
  read -r -a PY_CANDIDATES <<<"$PY_CANDIDATES"
else
  PY_CANDIDATES=("$PY_FLOOR" 3.13 3.12)
fi

INSTALLED=(); SKIPPED=(); FAILED=(); WARNINGS=()

log()  { echo "[setup-ci-deps] $*"; }
skip() { SKIPPED+=("$1");   log "SKIP    $1 (already installed)"; }
ok()   { INSTALLED+=("$1"); log "OK      $1"; }
fail() { FAILED+=("$1");    log "FAILED  $1"; }

have() { command -v "$1" >/dev/null 2>&1; }

# One run at a time. The SessionStart hook starts this in the background, so two
# sessions can open together and fight over .venv, node_modules and $BIN_DIR.
# mkdir is atomic, which is what makes it a lock.
take_lock() { mkdir "$LOCK_DIR" 2>/dev/null && echo $$ >"$LOCK_DIR/pid"; }
if ! take_lock; then
  # A kill -9 or a container restart leaves the directory behind. Without this
  # the next session would skip the setup quietly and for good.
  holder="$(cat "$LOCK_DIR/pid" 2>/dev/null)"
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    log "Run $holder holds $LOCK_DIR. Stopping."
    exit 0
  fi
  log "Taking the lock at $LOCK_DIR from run ${holder:-unknown}, which is gone."
  rm -rf "$LOCK_DIR"
  if ! take_lock; then
    log "Could not take $LOCK_DIR. Stopping."
    exit 0
  fi
fi
trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM


if [ "$SKIP_PYTHON" = 1 ]; then log "SKIP    the Python packages (SKIP_PYTHON=1)"; else
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
# A renamed or deleted file would fail every candidate and leave no .venv at all.
if [ ! -f "$SMOKE_TEST" ]; then
  fallback="$(ls tests/unit/test_*.py 2>/dev/null | head -1)"
  if [ -n "$fallback" ]; then
    log "NOTE: $SMOKE_TEST is gone. Using $fallback to test the interpreter."
    SMOKE_TEST="$fallback"
  fi
fi

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
  for pyspec in "${PY_CANDIDATES[@]}"; do
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
  [ -n "$VENV_PY" ] || fail ".venv (no candidate Python ran the unit tests: ${PY_CANDIDATES[*]})"
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
    WARNINGS+=("The Home Assistant in .venv is older than the newest release. No interpreter here meets the floor of $PY_FLOOR, so mypy and the Home Assistant unit lane test an older API than CI does.")
    log "WARNING: the Home Assistant in .venv is older than the newest release,"
    log "         because no interpreter here meets the Home Assistant floor of"
    log "         $PY_FLOOR. mypy and the Home Assistant unit lane thus test an older"
    log "         API than CI does. Run '.venv/bin/python ci/check-ha-version.py'."
  fi
fi

fi  # SKIP_PYTHON

# --- Node: one npm project for each lane -----------------------------------
# root = vitest and Stryker, frontend = the panel build, tests/e2e = Playwright,
# website = the Docusaurus docs site.
npm_project() {
  local dir="$1" label="$2"
  [ -f "$dir/package.json" ] || { log "SKIP    $label (no package.json)"; return; }
  if [ "$FORCE" = 0 ] && [ -d "$dir/node_modules" ]; then
    # A lock file newer than the install means node_modules is behind it.
    # npm writes node_modules/.package-lock.json on each install, so it is the
    # mtime that tracks the install rather than the directory's own.
    local marker="$dir/node_modules/.package-lock.json"
    [ -f "$marker" ] || marker="$dir/node_modules"
    if [ -f "$dir/package-lock.json" ] && [ "$dir/package-lock.json" -nt "$marker" ]; then
      log "        $label is behind $dir/package-lock.json. Installing again."
    else
      skip "$label"; return
    fi
  fi
  log "Installing $label npm packages..."
  local cmd=(npm ci --no-audit --no-fund)
  [ -f "$dir/package-lock.json" ] || cmd=(npm install --no-audit --no-fund)
  (cd "$dir" && "${cmd[@]}") >/dev/null 2>&1 && ok "$label" || fail "$label"
}
if [ "$SKIP_NPM" = 1 ]; then
  log "SKIP    the npm packages (SKIP_NPM=1)"
elif have npm; then
  npm_project "." "npm (root)"
  npm_project "custom_components/home_keeper/frontend" "npm (panel frontend)"
  npm_project "tests/e2e" "npm (e2e)"
  npm_project "website" "npm (docs site)"
else
  fail "npm (not on PATH)"
fi

# --- Vale: the prose lint --------------------------------------------------
# lint.yml runs the vale action. This is the local equivalent from AGENTS.md.
vale_is_pinned() {
  have vale && vale --version 2>/dev/null | grep -qE "(^| )$(printf %s "$VALE_VERSION" | sed 's/\./\\./g')( |$)"
}
if [ "$SKIP_VALE" = 1 ]; then
  log "SKIP    vale (SKIP_VALE=1)"
elif [ "$FORCE" = 0 ] && vale_is_pinned; then
  skip "vale $VALE_VERSION"
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
      rm -rf "$tmp"
    else
      fail "vale (the download failed: $url)"
      log "        The partial download stays in $tmp for you to look at."
    fi
  fi
fi
# The ai-tells package that .vale.ini declares.
if [ "$SKIP_VALE" != 1 ] && { have vale || [ -x "$BIN_DIR/vale" ]; }; then
  # A directory alone is not proof: an interrupted sync leaves an empty one.
  if [ "$FORCE" = 0 ] && [ -n "$(ls -A styles/ai-tells 2>/dev/null)" ]; then
    skip "vale styles (ai-tells)"
  else
    log "Getting the vale styles..."
    PATH="$BIN_DIR:$PATH" vale sync >/dev/null 2>&1 \
      && ok "vale styles (ai-tells)" || fail "vale styles (ai-tells)"
  fi
fi

# --- ffmpeg: the walkthrough video capture ---------------------------------
# ci/capture-video.sh changes the Playwright recording to a gif and an mp4.
if [ "$SKIP_FFMPEG" = 1 ]; then
  log "SKIP    ffmpeg (SKIP_FFMPEG=1)"
elif [ "$FORCE" = 0 ] && have ffmpeg; then
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
for note in ${WARNINGS[@]+"${WARNINGS[@]}"}; do log "WARNING: $note"; done
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
# No step stops the run, but the exit status still says whether one failed, so a
# caller that wants to know does not have to read the log.
[ "${#FAILED[@]}" -eq 0 ] || exit 1
exit 0
