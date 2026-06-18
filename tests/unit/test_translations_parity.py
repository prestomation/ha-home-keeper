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
* no *new* string may be left identical to English (an untranslated leak). A
  curated allowlist covers strings that are identical by design; the current
  backlog of known-untranslated strings is frozen in
  ``translations_untranslated_baseline.json`` and must only ever shrink.

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
_BASELINE = Path(__file__).resolve().parent / "translations_untranslated_baseline.json"

# Strings that are identical to English by design in (essentially) every
# language: brand names, symbols, etc. Dotted key paths. Keep this list tiny and
# justified — everything else identical to English is treated as untranslated.
_INTENTIONALLY_IDENTICAL: frozenset[str] = frozenset(
    {
        "config.step.user.title",  # "Home Keeper" — product name
    }
)

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


def _baseline() -> dict[str, set[str]]:
    raw = json.loads(_BASELINE.read_text(encoding="utf-8"))
    return {lang: set(keys) for lang, keys in raw.items()}


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
    """No *new* string may be shipped identical to its English source.

    A string equal to English is almost always an untranslated leak (a feature's
    strings copied verbatim to satisfy key parity). Two escape hatches:

    * ``_INTENTIONALLY_IDENTICAL`` — identical by design in every language.
    * the per-locale backlog in ``translations_untranslated_baseline.json`` —
      the debt that existed when this guard was introduced. It may only shrink:
      a baselined key that is now translated must be removed from the baseline,
      and a baselined key that no longer exists is likewise stale.
    """
    lang = path.stem
    baseline = _baseline().get(lang, set())
    en = _strings(_load(_TRANSLATIONS / "en.json"))
    loc = _strings(_load(path))

    identical = {
        key
        for key, value in loc.items()
        if key in en and value == en[key] and key not in _INTENTIONALLY_IDENTICAL
    }
    new_leaks = sorted(identical - baseline)
    stale = sorted(baseline - identical)
    assert not new_leaks and not stale, {
        "locale": path.name,
        # Translate these, or (if identical by design) add to allowlist.
        "new_untranslated_strings": new_leaks,
        # These are translated now (or gone) — remove them from the baseline.
        "stale_baseline_entries": stale,
    }
