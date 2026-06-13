#!/usr/bin/env bash
set -euo pipefail

cd custom_components/home_keeper
zip -r ../../home_keeper.zip . \
  -x "*/__pycache__/*" \
  -x "*/__pycache__" \
  -x "__pycache__/*" \
  -x "__pycache__" \
  -x "*.pyc" \
  -x "*/node_modules/*" \
  -x "*/node_modules" \
  -x "*/src/*" \
  -x "*/test/*" \
  -x "rollup.config.mjs" \
  -x "tsconfig.json" \
  -x "package.json" \
  -x "package-lock.json"
