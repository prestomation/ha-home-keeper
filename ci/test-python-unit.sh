#!/usr/bin/env bash
set -euo pipefail

find custom_components -name "*.py" -exec python -m py_compile {} +
python -m pytest tests/ -v --ignore=tests/integration
