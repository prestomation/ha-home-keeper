#!/usr/bin/env bash
# Mutation testing for the frontend TypeScript, via Stryker.
#
#   bash ci/test-mutation-frontend.sh          # only what changed vs the base branch
#   bash ci/test-mutation-frontend.sh --all    # the whole configured surface
#
# The surface and the gate both live in `stryker.conf.json` (`mutate` and
# `thresholds.break`); Stryker owns the exit code. Set MUTATION_BASE_REF to diff
# against something other than origin/main.
#
# Stryker runs from the repo root against `vitest.stryker.config.js` — the root
# is where vitest and jsdom are installed, and the tests import `src/*.ts`
# directly, so no panel build is needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:---changed}"
BASE="${MUTATION_BASE_REF:-origin/main}"
REPORT="reports/mutation/mutation.json"

STRYKER_ARGS=()

if [ "$MODE" = "--all" ]; then
  echo "[mutation] mutating the full TypeScript surface"
else
  echo "[mutation] scoping to TypeScript changed against $BASE"
  SCOPE_FILE="$(mktemp)"
  trap 'rm -f "$SCOPE_FILE"' EXIT
  python3 ci/mutation_scope.py --language typescript --base "$BASE" > "$SCOPE_FILE"
  if [ ! -s "$SCOPE_FILE" ]; then
    python3 - <<'PY'
import os

message = (
    "## Mutation testing (TypeScript)\n\n"
    "No mutable TypeScript changed in this pull request — nothing to test.\n"
)
print(message)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write(message + "\n")
PY
    exit 0
  fi
  echo "[mutation] scope:"
  sed 's/^/    /' "$SCOPE_FILE"
  mapfile -t RANGES < "$SCOPE_FILE"
  STRYKER_ARGS=(--mutate "$(IFS=,; echo "${RANGES[*]}")")
fi

rm -f "$REPORT"

set +e
npx stryker run "${STRYKER_ARGS[@]}"
RUN_STATUS=$?
set -e

# Summarise regardless of outcome, then hand Stryker's verdict back to the
# caller — `thresholds.break` in stryker.conf.json is the gate. A Stryker crash
# that never wrote a report still fails here, because RUN_STATUS carries it.
python3 ci/mutation_report.py \
  --format stryker \
  --input "$REPORT" \
  --title "Mutation testing (TypeScript)" \
  --require-mutants

exit "$RUN_STATUS"
