#!/usr/bin/env bash
set -euo pipefail

# Assumes Docker Home Assistant is already running.
# Integration tests need real HTTP to the Docker HA container, so the pytest-socket
# plugin has to be off. It is pulled in by pytest-homeassistant-custom-component,
# which `requirements-test.txt` deliberately leaves out of this lane — so on CI the
# plugin is absent and these flags are inert.
#
# Both spellings, because the plugin's *registered* name is `socket` (its pytest11
# entry point), not `pytest_socket`. A local environment that has the plugin — the
# .venv `ci/setup-ci-deps.sh` builds, which installs everything — ran every one of
# these 210 tests into SocketBlockedError with only the wrong name here, so running
# the integration tier the way AGENTS.md prescribes was impossible. `-p no:` for a
# plugin that is not installed is a no-op, so naming both is free.
#
# Turning pytest-socket off is still not enough on its own. The block is applied by
# an autouse fixture in `pytest_homeassistant_custom_component.plugins`, which calls
# `pytest_socket.disable_socket` itself, so the whole tier stayed red locally with
# only the 2 names above. That plugin's pytest11 entry point is `homeassistant`, and
# this lane wants none of it — it drives a real container over HTTP rather than an
# in-process Home Assistant.
# Arguments are passed through, so a targeted run is possible: this tier takes ~9
# minutes whole, and re-running it to see one file made a debugging loop that long.
# With none, pytest takes the `.` below and runs everything, which is what CI does.
cd tests/integration
python -m pytest . -v --tb=short --override-ini="asyncio_mode=auto" \
  -p no:socket -p no:pytest_socket -p no:homeassistant "$@"
