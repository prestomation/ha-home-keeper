#!/usr/bin/env bash
# EXPLORATION TOOL (not product code). Boot Home Assistant on a generated config with N tasks.
#
#   bash tools/explore-many-tasks/run_stack.sh N [WORKDIR]
#
# Builds the config with gen_config.py, starts the container on port 8123, waits for the
# Home Keeper to-do entity and prints the start-up time. Then it runs the Playwright
# global setup once (onboarding and token), so tests/e2e/.auth/token.json exists.
# Stop with: (cd tests/integration && HA_CONFIG=... docker compose down -v)
set -uo pipefail
N="${1:?N tasks}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${2:-${TMPDIR:-/tmp}/hk-explore}"
CFG="$WORK/cfg$N"
mkdir -p "$WORK"
cd "$ROOT/tests/integration"
HA_CONFIG="$CFG" docker compose down -v >/dev/null 2>&1
python3 "$ROOT/tools/explore-many-tasks/gen_config.py" "$N" "$CFG" || exit 1
rm -rf "$ROOT/tests/e2e/.auth"
T0=$(date +%s.%N)
HA_CONFIG="$CFG" docker compose up -d || exit 1
READY=""
for i in $(seq 1 400); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8123/api/ 2>/dev/null || true)
  if [ "$code" = "200" ] || [ "$code" = "401" ]; then READY=${READY:-$(date +%s.%N)}; break; fi
  sleep 1
done
echo "HA_HTTP_UP_SECONDS=$(echo "$READY - $T0" | bc 2>/dev/null)"
cd "$ROOT/tests/e2e"
cat > /tmp/hk-noop.spec.ts <<'S'
import { test } from '@playwright/test';
test('noop', async () => {});
S
mkdir -p tests && cp /tmp/hk-noop.spec.ts tests/zz-noop.spec.ts
npx playwright test tests/zz-noop.spec.ts --project=desktop --reporter=line
RC=$?
rm -f tests/zz-noop.spec.ts
T1=$(date +%s.%N)
echo "SETUP_DONE_SECONDS=$(echo "$T1 - $T0" | bc) playwright_exit=$RC"
exit $RC
