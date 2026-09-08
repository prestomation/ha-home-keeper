#!/usr/bin/env bash
# Install the converter the published JSON Schema is built with, at the version Home
# Assistant itself is built against.
#
# `ci/generate_schema.py` hands Home Assistant's own voluptuous schemas to
# `voluptuous_openapi.convert`. Which version of that library is not a free choice:
# Home Assistant pins it in `homeassistant/package_constraints.txt`, and the API is not
# stable across those pins. An unpinned `pip install voluptuous-openapi` took 0.4.1
# against a Home Assistant pinned to an earlier one, and `convert` died on
# `TypeError: unhashable type: 'Schema'` — a `vol.Schema` is unhashable in every
# version, and 0.4.1 tests `schema in TYPES_MAP` before it unwraps one.
#
# So: install under Home Assistant's constraints file and let it decide. That keeps the
# generator using the same converter Home Assistant's own code calls, and it stays
# right after the next Home Assistant bump with no edit here.
#
# Home Assistant must already be installed. Run `ci/check-ha-version.py` first, so a
# pip backtrack to an ancient Home Assistant is caught before it silently decides this.
set -euo pipefail

constraints=$(python -c 'import homeassistant, pathlib; print(pathlib.Path(homeassistant.__file__).parent / "package_constraints.txt")')
echo "[install-schema-deps] constraining against $constraints"
grep -E '^voluptuous' "$constraints" || echo "[install-schema-deps] no voluptuous pin found"
pip install -c "$constraints" voluptuous-openapi "$@"
