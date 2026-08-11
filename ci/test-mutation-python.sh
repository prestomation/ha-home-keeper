#!/usr/bin/env bash
# Mutation testing for the pure Python core, via mutmut.
#
#   bash ci/test-mutation-python.sh            # only what changed vs the base branch
#   bash ci/test-mutation-python.sh --all      # the whole configured surface
#
# The surface is `only_mutate` in `[tool.mutmut]` (pyproject.toml) and the gate
# is `[tool.mutation-gate] break`. Mutants run against the pure unit tier only:
# it is the one tier fast enough to run thousands of times, and the tier whose
# assertions the score is actually measuring. Set MUTATION_BASE_REF to diff
# against something other than origin/main.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:---changed}"
BASE="${MUTATION_BASE_REF:-origin/main}"
MUTMUT=(python -m mutmut)

SCOPE_FILE="$(mktemp)"
trap 'rm -f "$SCOPE_FILE"' EXIT

if [ "$MODE" = "--all" ]; then
  echo "[mutation] mutating the full Python surface"
  : > "$SCOPE_FILE"
else
  echo "[mutation] scoping to Python changed against $BASE"
  python3 ci/mutation_scope.py --language python --base "$BASE" > "$SCOPE_FILE"
  if [ ! -s "$SCOPE_FILE" ]; then
    python3 - <<'PY'
import os

message = (
    "## Mutation testing (Python)\n\n"
    "No mutable Python changed in this pull request — nothing to test.\n"
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
fi

# mutmut exits 0 whether or not mutants survived, and non-zero on its own
# internal errors. Either way we want the report, so capture the status and
# let ci/mutation_report.py decide the outcome.
set +e
if [ "$MODE" = "--all" ]; then
  "${MUTMUT[@]}" run
else
  mapfile -t FILTERS < "$SCOPE_FILE"
  "${MUTMUT[@]}" run "${FILTERS[@]}"
fi
RUN_STATUS=$?
set -e

if [ "$RUN_STATUS" -ne 0 ]; then
  echo "[mutation] mutmut exited $RUN_STATUS" >&2
  exit "$RUN_STATUS"
fi

"${MUTMUT[@]}" results --all=1 | python3 ci/mutation_report.py \
  --format mutmut \
  --scope-file "$SCOPE_FILE" \
  --title "Mutation testing (Python)" \
  --gate \
  --require-mutants
