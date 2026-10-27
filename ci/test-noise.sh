#!/usr/bin/env bash
# The noise-budget tier (tests/noise). It starts its own Home Assistant on a temporary
# copy of the integration fixture with the noise probe added, runs the scenarios, and
# stops it again. The scenarios add tasks, change options and the language, so they
# never run on the committed fixture, which the other tiers share.
#
#   bash ci/test-noise.sh                      # check against tests/noise/baseline.json
#   HK_NOISE_UPDATE=1 bash ci/test-noise.sh    # write the measured numbers as budgets
#   KEEP_UP=1 bash ci/test-noise.sh            # leave the container running after
#
# Arguments go to pytest. The scenarios share state and run in file order, so select
# a part with -k only to read its numbers, not to check it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$(mktemp -d "${TMPDIR:-/tmp}/hk-noise-config.XXXXXX")"
COMPOSE=(docker compose --project-name hk-noise -f "$ROOT/tests/integration/docker-compose.yml")
export HA_CONFIG="$CONFIG"

cleanup() {
  if [ "${KEEP_UP:-0}" != "1" ]; then
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
    rm -rf "$CONFIG"
  else
    echo "[noise] container left running; config in $CONFIG"
  fi
}
trap cleanup EXIT

# The fixture minus its runtime files, plus the probe as a custom integration.
cp -a "$ROOT/tests/integration/ha_config/." "$CONFIG/"
(cd "$ROOT/tests/integration/ha_config" && git ls-files --others --ignored --exclude-standard) \
  | while read -r f; do rm -rf "${CONFIG:?}/$f"; done
mkdir -p "$CONFIG/custom_components"
cp -a "$ROOT/tests/noise/hk_noise_probe" "$CONFIG/custom_components/"
printf '\nhk_noise_probe:\n' >> "$CONFIG/configuration.yaml"
# Debug logging from Home Keeper costs time and adds nothing here.
sed -i 's/custom_components.home_keeper: debug/custom_components.home_keeper: info/' \
  "$CONFIG/configuration.yaml"

"${COMPOSE[@]}" up -d
echo "[noise] Home Assistant ${HA_TAG:-stable} is starting on $CONFIG"

# Same plugin flags as ci/test-python-integration.sh: this lane drives a real
# container over HTTP, so pytest-socket and the in-process HA plugin must be off.
status=0
(cd "$ROOT/tests/noise" && python -m pytest . -v -rxX --tb=short \
  -p no:socket -p no:pytest_socket -p no:homeassistant "$@") || status=$?
if [ "$status" != "0" ]; then
  "${COMPOSE[@]}" logs homeassistant 2>&1 | grep -E "ERROR|Traceback" | tail -40 || true
fi
exit "$status"
