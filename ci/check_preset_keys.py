#!/usr/bin/env python3
"""Check that each integration preset's entity keys still exist upstream.

An integration preset selects entities by their ``translation_key``. An integration
can rename or remove a key in a new release, and a preset that names that key then
matches nothing, with no error. This script reads the English translation file of
each integration in ``declarative_presets_catalog.INTEGRATIONS`` (its ``source``) and
reports every key that is no longer in the ``entity`` section for its platform.

Standard library only, so it runs on a bare runner. Exit status: 0 when every key is
found, 1 when a key is missing or a source cannot be read. It is not a pull request
gate: a change in another project must not stop a merge here. See
docs/INTEGRATION_PRESET_GAPS_PLAN.md, "Weekly check of the preset keys".

Usage:
    python ci/check_preset_keys.py            # every integration
    python ci/check_preset_keys.py roborock   # only the named domains
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_CATALOG = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "home_keeper"
    / "declarative_presets_catalog.py"
)
_TIMEOUT = 30
_HEADERS = {"User-Agent": "home-keeper-preset-key-check"}


def _integrations() -> list[dict[str, Any]]:
    """The catalog, loaded by path: it imports nothing from Home Assistant."""
    spec = importlib.util.spec_from_file_location("preset_catalog", _CATALOG)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.INTEGRATIONS)


def _fetch(url: str) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        print(f"  FETCH FAILED: {url} ({err})")
        return None


def missing_keys(
    entry: dict[str, Any], translations: dict[str, Any]
) -> list[tuple[str, str]]:
    """The ``(platform, key)`` pairs of *entry* not in *translations*."""
    entities = translations.get("entity") or {}
    missing = []
    for duty in entry["duties"]:
        platform = duty.get("platform", "sensor")
        known = entities.get(platform) or {}
        missing += [(platform, key) for key in duty["keys"] if key not in known]
    return missing


def main(argv: list[str]) -> int:
    entries = _integrations()
    if argv:
        entries = [e for e in entries if e["domain"] in argv]
    with ThreadPoolExecutor(max_workers=8) as pool:
        sources = list(pool.map(lambda e: _fetch(e["source"]), entries))
    problems = 0
    for entry, translations in zip(entries, sources, strict=True):
        if translations is None:
            print(f"[FAIL] {entry['domain']}: cannot read {entry['source']}")
            problems += 1
            continue
        missing = missing_keys(entry, translations)
        if missing:
            listed = ", ".join(f"{platform}.{key}" for platform, key in missing)
            print(f"[DRIFT] {entry['domain']}: {listed} not found upstream")
            problems += 1
        else:
            print(f"[OK] {entry['domain']}")
    print(f"\n{len(entries)} integrations checked, {problems} with a problem.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
