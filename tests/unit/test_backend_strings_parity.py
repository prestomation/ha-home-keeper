"""Quality guardrails for the backend_strings/<lang>.json bundle.

A handful of backend-generated strings (the problem-sensor sync's completion
prompt, a companion catalog suggestion's description, the inventory CSV headers)
have no home in strings.json — hassfest validates that tree against a fixed set of
categories and these aren't exceptions, so they're bundled as flat dotted-key
``backend_strings/<lang>.json`` files instead (the same convention
``notification_strings/`` and ``frontend/src/locales/*.json`` use), read directly
by ``backend_i18n.resolve_string``. These pure-Python checks mirror
``test_translations_parity.py``'s guarantees for that bundle.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_STRINGS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "custom_components"
    / "home_keeper"
    / "backend_strings"
)

_TOKEN_RE = re.compile(r"\{(\w+)\}")

# Per-locale cognates/loanwords genuinely identical to English (reviewed
# individually — same reasoning as strings.json's own translations, which already
# use these exact words for the same fields, e.g. add_asset.fields.model.name).
#
# ``declarative_preset.device_pulse.name`` is the product name of an upstream
# HA integration (studiobts/home-assistant-device-pulse) — brand names are not
# translated. Applies to every locale.
_BRAND_IDENTICAL: frozenset[str] = frozenset(
    {"declarative_preset.device_pulse.name"}
)
_COGNATE_IDENTICAL: dict[str, frozenset[str]] = {
    "ca": frozenset(
        {"inventory.csv.cost", "inventory.csv.model", "inventory.csv.total"}
    )
    | _BRAND_IDENTICAL,
    "cs": frozenset({"inventory.csv.model"}) | _BRAND_IDENTICAL,
    "da": frozenset({"inventory.csv.model"}) | _BRAND_IDENTICAL,
    "de": frozenset({"inventory.csv.details", "inventory.csv.name"}) | _BRAND_IDENTICAL,
    "es": frozenset({"inventory.csv.total"}) | _BRAND_IDENTICAL,
    "fr": frozenset({"inventory.csv.total"}) | _BRAND_IDENTICAL,
    "it": frozenset({"inventory.csv.area"}) | _BRAND_IDENTICAL,
    "nl": frozenset({"inventory.csv.details", "inventory.csv.model"})
    | _BRAND_IDENTICAL,
    "pl": frozenset({"inventory.csv.model"}) | _BRAND_IDENTICAL,
    "pt-BR": frozenset({"inventory.csv.total"}) | _BRAND_IDENTICAL,
    "fi": _BRAND_IDENTICAL,
    "nb": _BRAND_IDENTICAL,
    "ru": _BRAND_IDENTICAL,
    "sv": _BRAND_IDENTICAL,
    "zh-Hans": _BRAND_IDENTICAL,
}


def _load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tokens(value: str) -> list[str]:
    return sorted(_TOKEN_RE.findall(value))


def _locale_files() -> list[Path]:
    return sorted(_STRINGS_DIR.glob("*.json"))


_NON_EN = [p for p in _locale_files() if p.name != "en.json"]


def test_translation_files_exist() -> None:
    files = {p.name for p in _locale_files()}
    assert "en.json" in files, "backend_strings/en.json is required"
    for required in ("de.json", "fr.json", "es.json", "zh-Hans.json"):
        assert required in files, f"missing backend_strings/{required}"


@pytest.mark.parametrize("path", _NON_EN, ids=lambda p: p.name)
def test_locale_key_parity(path: Path) -> None:
    """Every locale must share en.json's exact key set."""
    en_keys = set(_load(_STRINGS_DIR / "en.json"))
    locale_keys = set(_load(path))
    assert locale_keys == en_keys, {
        "locale": path.name,
        "missing": sorted(en_keys - locale_keys),
        "extra": sorted(locale_keys - en_keys),
    }


@pytest.mark.parametrize("path", _NON_EN, ids=lambda p: p.name)
def test_placeholder_parity(path: Path) -> None:
    """Each locale value must carry the same ``{token}`` set as English."""
    en = _load(_STRINGS_DIR / "en.json")
    loc = _load(path)
    mismatches = {
        key: {"en": _tokens(en[key]), "locale": _tokens(value)}
        for key, value in loc.items()
        if key in en and _tokens(value) != _tokens(en[key])
    }
    assert not mismatches, {"locale": path.name, "placeholder_mismatch": mismatches}


@pytest.mark.parametrize("path", _NON_EN, ids=lambda p: p.name)
def test_no_brace_balance_errors(path: Path) -> None:
    """Every value must have balanced, non-nested ``{`` / ``}`` braces."""
    bad = {}
    for key, value in _load(path).items():
        depth = 0
        ok = True
        for ch in value:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            if depth not in (0, 1):
                ok = False
                break
        if not ok or depth != 0:
            bad[key] = value
    assert not bad, {"locale": path.name, "brace_errors": bad}


_ANY_BRACE_RE = re.compile(r"\{([^}]*)\}")
_IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


@pytest.mark.parametrize("path", _locale_files(), ids=lambda p: p.name)
def test_placeholders_are_valid_identifiers(path: Path) -> None:
    """Every ``{token}`` must be a valid ``str.format`` identifier."""
    bad = {
        key: value
        for key, value in _load(path).items()
        for tok in _ANY_BRACE_RE.findall(value)
        if not _IDENT_RE.fullmatch(tok)
    }
    assert not bad, {"file": path.name, "invalid_placeholders": bad}


@pytest.mark.parametrize("path", _NON_EN, ids=lambda p: p.name)
def test_no_untranslated_strings(path: Path) -> None:
    """No string may be shipped identical to its English source."""
    allowed = _COGNATE_IDENTICAL.get(path.stem, frozenset())
    en = _load(_STRINGS_DIR / "en.json")
    loc = _load(path)
    leaks = sorted(
        key
        for key, value in loc.items()
        if key in en and value == en[key] and key not in allowed
    )
    assert not leaks, {"locale": path.name, "untranslated_strings": leaks}
