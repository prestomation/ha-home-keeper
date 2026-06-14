"""Parity checks for Home Assistant translations.

``strings.json`` is the source of truth for the integration's translatable
strings (config flow, services, entity names). Home Assistant localizes by
loading a matching ``translations/<lang>.json`` with the *same* key structure.
These pure-Python checks (no HA runtime) guard against drift:

* ``translations/en.json`` must be an exact structural copy of ``strings.json``.
* every ``translations/<lang>.json`` must have the identical key structure
  (keys, not values) — no missing or extra keys in any locale.

This catches the easy mistake of adding a service/field/entity to
``strings.json`` and forgetting to mirror it into the locale files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "custom_components"
    / "home_keeper"
)
_STRINGS = _COMPONENT_DIR / "strings.json"
_TRANSLATIONS = _COMPONENT_DIR / "translations"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _keys(obj, prefix: str = "") -> set[str]:
    """Recursive set of dotted key paths in a nested mapping."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            out.add(path)
            out |= _keys(value, path)
    return out


def _locale_files() -> list[Path]:
    return sorted(_TRANSLATIONS.glob("*.json"))


def test_translation_files_exist() -> None:
    files = {p.name for p in _locale_files()}
    assert "en.json" in files, "translations/en.json is required"
    # The integration ships a common set of locales; guard a representative few
    # so an accidental deletion is caught.
    for required in ("de.json", "fr.json", "es.json", "zh-Hans.json"):
        assert required in files, f"missing translations/{required}"


def test_en_matches_strings() -> None:
    """translations/en.json must be a structural copy of strings.json."""
    strings_keys = _keys(_load(_STRINGS))
    en_keys = _keys(_load(_TRANSLATIONS / "en.json"))
    assert en_keys == strings_keys, {
        "missing_in_en": sorted(strings_keys - en_keys),
        "extra_in_en": sorted(en_keys - strings_keys),
    }


@pytest.mark.parametrize("path", _locale_files(), ids=lambda p: p.name)
def test_locale_key_parity(path: Path) -> None:
    """Every locale must share strings.json's exact key structure."""
    strings_keys = _keys(_load(_STRINGS))
    locale_keys = _keys(_load(path))
    assert locale_keys == strings_keys, {
        "locale": path.name,
        "missing": sorted(strings_keys - locale_keys),
        "extra": sorted(locale_keys - strings_keys),
    }
