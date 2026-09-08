#!/usr/bin/env bash
set -euo pipefail

# Property-based tests draw their inputs rather than stating them, so on a shared
# runner they must be reproducible: the `ci` profile derandomizes the draw and turns
# the example database off. See tests/unit/conftest.py.
export HK_HYPOTHESIS_PROFILE="${HK_HYPOTHESIS_PROFILE:-ci}"

find custom_components -name "*.py" -exec python -m py_compile {} +
# tests/integration and tests/upgrade both drive a real Home Assistant container:
# the first needs one running, the second needs `bash ci/fetch-glues.sh` staged and
# boots two of its own. Neither belongs in the unit lane.
python -m pytest tests/ -v --ignore=tests/integration --ignore=tests/upgrade
