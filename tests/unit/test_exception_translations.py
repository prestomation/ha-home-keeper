"""Drift guard for the ``exception-translations`` quality-scale rule (no HA).

Platinum integrations raise *localizable* exceptions: every user-facing
``ServiceValidationError`` / ``HomeAssistantError`` must be constructed with a
``translation_key`` (plus ``translation_domain``) rather than a bare English
string, and that key must exist under ``exceptions`` in ``strings.json``.

This pure-AST check fails the build if someone adds a bare-string raise or a
``translation_key`` with no matching strings.json entry — so the rule cannot
silently regress (the exception messages themselves are seeded English-first and
translated incrementally; see quality_scale.yaml).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
# Exception types that surface to the user and therefore must be translatable.
_TRANSLATABLE = {"ServiceValidationError", "HomeAssistantError"}


def _raise_calls() -> list[tuple[str, int, ast.Call]]:
    """Every ``raise <TranslatableError>(...)`` call in the component source."""
    found: list[tuple[str, int, ast.Call]] = []
    for path in sorted(_COMPONENT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in _TRANSLATABLE:
                found.append((path.name, node.lineno, node.exc))
    return found


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def test_user_facing_raises_use_translation_keys() -> None:
    """No bare-string raises: each must pass translation_domain + translation_key."""
    offenders = [
        f"{file}:{line}"
        for file, line, call in _raise_calls()
        if _kwarg(call, "translation_key") is None
        or _kwarg(call, "translation_domain") is None
    ]
    assert not offenders, (
        "User-facing exceptions must use translation_domain + translation_key "
        f"(exception-translations rule); offenders: {offenders}"
    )


def test_translation_keys_exist_in_strings() -> None:
    """Every translation_key raised must have an entry under strings.json exceptions."""
    strings = json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))
    defined = set(strings.get("exceptions", {}))
    missing = sorted(
        {
            key.value
            for _, _, call in _raise_calls()
            if isinstance((key := _kwarg(call, "translation_key")), ast.Constant)
            and key.value not in defined
        }
    )
    assert not missing, (
        f"translation_key(s) missing from strings.json exceptions: {missing}"
    )
