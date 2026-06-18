"""Quality guardrails for Home Assistant translations.

``strings.json`` is the source of truth for the integration's translatable
strings (config flow, services, entity names). Home Assistant localizes by
loading a matching ``translations/<lang>.json`` with the *same* key structure.
These pure-Python checks (no HA runtime) guard against drift and low-quality
translations:

* ``translations/en.json`` must be an exact structural copy of ``strings.json``.
* every ``translations/<lang>.json`` must have the identical key structure
  (keys, not values) — no missing or extra keys in any locale.
* placeholder tokens (``{task_name}`` …) must match the English source per key,
  with no balance errors and no foreign/renamed tokens.
* no string may be left identical to English (an untranslated leak). A curated
  allowlist covers the handful of strings that are identical by design.

Together these catch the easy mistakes of adding a service/field/entity to
``strings.json`` and forgetting to mirror it into the locale files, and of
shipping a feature's strings copied verbatim from English.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "custom_components"
    / "home_keeper"
)
_STRINGS = _COMPONENT_DIR / "strings.json"
_TRANSLATIONS = _COMPONENT_DIR / "translations"

# Strings that are identical to English by design in (essentially) every
# language: brand names, symbols, etc. Dotted key paths. Keep this list tiny and
# justified — everything else identical to English is treated as untranslated.
_INTENTIONALLY_IDENTICAL: frozenset[str] = frozenset(
    {
        "config.step.user.title",  # "Home Keeper" — product name
    }
)

# Per-locale cognates / loanwords whose translation is genuinely identical to
# English in that language (reviewed individually). These are intentional, not
# untranslated leaks — but they are locale-specific, so the guard stays strict
# for every other locale. Examples: German "Name", French "Notes", Catalan
# "Cost", and technical loanwords "Delta"/"Model"/"Metadata"/"Interval".
_COGNATE_IDENTICAL: dict[str, frozenset[str]] = {
    "ca": frozenset({"services.add_asset.fields.cost.name", "services.add_asset.fields.model.name", "services.add_task.fields.interval.name", "services.add_task.fields.notes.name", "services.adjust_part_stock.fields.delta.name", "services.update_asset.fields.cost.name", "services.update_asset.fields.model.name", "services.update_task.fields.interval.name", "services.update_task.fields.notes.name"}),
    "cs": frozenset({"services.add_asset.fields.metadata.name", "services.add_asset.fields.model.name", "services.add_task.fields.interval.name", "services.adjust_part_stock.fields.delta.name", "services.update_asset.fields.metadata.name", "services.update_asset.fields.model.name", "services.update_task.fields.interval.name"}),
    "da": frozenset({"services.add_asset.fields.metadata.name", "services.add_asset.fields.model.name", "services.add_task.fields.interval.name", "services.update_asset.fields.metadata.name", "services.update_asset.fields.model.name", "services.update_task.fields.interval.name"}),
    "de": frozenset({"services.add_asset.fields.name.name", "services.add_task.fields.name.name", "services.update_asset.fields.name.name", "services.update_task.fields.name.name"}),
    "es": frozenset({"services.adjust_part_stock.fields.delta.name"}),
    "fr": frozenset({"services.add_task.fields.notes.name", "services.update_task.fields.notes.name"}),
    "it": frozenset({"services.add_asset.fields.area_id.name", "services.add_task.fields.area_id.name", "services.adjust_part_stock.fields.delta.name", "services.update_asset.fields.area_id.name", "services.update_task.fields.area_id.name"}),
    "nb": frozenset({"services.add_asset.fields.metadata.name", "services.update_asset.fields.metadata.name"}),
    "nl": frozenset({"services.add_asset.fields.metadata.name", "services.add_asset.fields.model.name", "services.add_task.fields.interval.name", "services.update_asset.fields.metadata.name", "services.update_asset.fields.model.name", "services.update_task.fields.interval.name"}),
    "pl": frozenset({"services.add_asset.fields.model.name", "services.adjust_part_stock.fields.delta.name", "services.update_asset.fields.model.name"}),
    "pt-BR": frozenset({"services.adjust_part_stock.fields.delta.name"}),
    "sv": frozenset({"services.add_asset.fields.metadata.name", "services.update_asset.fields.metadata.name"}),
}

# Token of the form ``{name}`` used by HA/Python ``str.format`` placeholders.
_TOKEN_RE = re.compile(r"\{(\w+)\}")


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


def _strings(obj, prefix: str = "") -> dict[str, str]:
    """Flatten to a {dotted_key: str_value} map (leaf strings only)."""
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, str):
                out[path] = value
            else:
                out.update(_strings(value, path))
    return out


def _tokens(value: str) -> list[str]:
    return sorted(_TOKEN_RE.findall(value))


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


# Non-English locale files, used for value-level quality checks.
_NON_EN = [p for p in _locale_files() if p.name != "en.json"]


@pytest.mark.parametrize("path", _NON_EN, ids=lambda p: p.name)
def test_placeholder_parity(path: Path) -> None:
    """Each locale value must carry the same ``{token}`` set as English.

    A locale that drops a placeholder (``{task_name}`` vanishes) or renames it
    (``{nom}``) would silently break entity names / messages without failing
    key parity. Compare token *sets* per key against the English source.
    """
    en = _strings(_load(_TRANSLATIONS / "en.json"))
    loc = _strings(_load(path))
    mismatches = {
        key: {"en": _tokens(en[key]), "locale": _tokens(value)}
        for key, value in loc.items()
        if key in en and _tokens(value) != _tokens(en[key])
    }
    assert not mismatches, {"locale": path.name, "placeholder_mismatch": mismatches}


@pytest.mark.parametrize("path", _NON_EN, ids=lambda p: p.name)
def test_no_brace_balance_errors(path: Path) -> None:
    """Every value must have balanced, non-nested ``{`` / ``}`` braces.

    Catches a stray brace from a hand-edited translation that would raise at
    ``str.format`` time or render a literal ``{`` in the UI.
    """
    bad = {}
    for key, value in _strings(_load(path)).items():
        depth = 0
        ok = True
        for ch in value:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            if depth not in (0, 1):  # no nesting, never negative
                ok = False
                break
        if not ok or depth != 0:
            bad[key] = value
    assert not bad, {"locale": path.name, "brace_errors": bad}


@pytest.mark.parametrize("path", _NON_EN, ids=lambda p: p.name)
def test_no_untranslated_strings(path: Path) -> None:
    """No string may be shipped identical to its English source.

    A string equal to English is almost always an untranslated leak (a feature's
    strings copied verbatim to satisfy key parity). Escape hatches:
    ``_INTENTIONALLY_IDENTICAL`` (identical by design in every language) and the
    per-locale ``_COGNATE_IDENTICAL`` (reviewed cognates/loanwords).
    """
    allowed = _INTENTIONALLY_IDENTICAL | _COGNATE_IDENTICAL.get(path.stem, frozenset())
    en = _strings(_load(_TRANSLATIONS / "en.json"))
    loc = _strings(_load(path))

    leaks = sorted(
        key
        for key, value in loc.items()
        if key in en and value == en[key] and key not in allowed
    )
    # Translate these, or (if identical by design) add to the allowlist above.
    assert not leaks, {"locale": path.name, "untranslated_strings": leaks}
