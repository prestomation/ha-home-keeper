#!/usr/bin/env bash
set -euo pipefail

# Assumes Docker Home Assistant is already running.
# -p no:pytest_socket disables the pytest-socket plugin (pulled in by
# pytest-homeassistant-custom-component) which blocks real network access.
# Integration tests need real HTTP to the Docker HA container.
cd tests/integration
python -m pytest . -v --tb=short --override-ini="asyncio_mode=auto" -p no:pytest_socket
