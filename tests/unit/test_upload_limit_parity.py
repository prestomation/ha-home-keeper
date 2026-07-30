"""Drift guard: the panel's copy of the upload ceiling must match ``const.py``.

The panel refuses an oversized file *before* uploading it (so a 30 MB pick fails
instantly instead of after a long transfer), which means it needs the byte ceiling
client-side. TypeScript can't import a Python constant, so
``frontend/src/limits.ts`` mirrors ``MAX_DOCUMENT_BYTES`` — and this test fails the
build if the two ever disagree, which would otherwise show up as the panel happily
accepting a file the backend then rejects with a 413 (or vice versa).

Pure file reading: no Home Assistant, no frontend toolchain, runs under a bare
``pytest tests/unit``.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_COMPONENT = _ROOT / "custom_components" / "home_keeper"
_CONST_PY = _COMPONENT / "const.py"
_LIMITS_TS = _COMPONENT / "frontend" / "src" / "limits.ts"

# Only integer arithmetic is allowed on the right-hand side, so the values below can be
# evaluated without executing arbitrary code from either source file.
_ARITHMETIC_ONLY = re.compile(r"^[\d\s*+]+$")


def _eval_arithmetic(expr: str, *, source: str) -> int:
    """Evaluate a whitespace/digit/``*``/``+`` expression like ``25 * 1024 * 1024``.

    ``ast.literal_eval`` can't be used — that's a ``BinOp``, not a literal — so the
    expression is pattern-checked first and then evaluated in an empty namespace.
    """
    assert _ARITHMETIC_ONLY.match(expr), f"{source}: unexpected expression {expr!r}"
    value = eval(expr, {"__builtins__": {}}, {})
    assert isinstance(value, int), f"{source}: {expr!r} is not an int"
    return value


def _python_limit() -> int:
    match = re.search(
        r"^MAX_DOCUMENT_BYTES\s*=\s*(.+)$", _CONST_PY.read_text("utf-8"), re.M
    )
    assert match, "MAX_DOCUMENT_BYTES not found in const.py"
    return _eval_arithmetic(match.group(1).strip(), source="const.py")


def _typescript_limit() -> int:
    match = re.search(
        r"^export const MAX_DOCUMENT_BYTES\s*=\s*(.+);$",
        _LIMITS_TS.read_text("utf-8"),
        re.M,
    )
    assert match, "MAX_DOCUMENT_BYTES not exported from frontend/src/limits.ts"
    return _eval_arithmetic(match.group(1).strip(), source="limits.ts")


def test_panel_upload_limit_matches_backend() -> None:
    """limits.ts and const.py must agree, or the panel's pre-check lies to the user."""
    assert _typescript_limit() == _python_limit(), (
        "frontend/src/limits.ts MAX_DOCUMENT_BYTES has drifted from const.py — "
        "update both together."
    )


def test_upload_limit_is_a_whole_number_of_megabytes() -> None:
    """The limit is rendered as '{mb} MB' in both the backend error (strings.json
    ``file_too_large``) and the panel's pre-check message, so a fractional value would
    round to a number that doesn't match what's actually enforced."""
    assert _python_limit() % (1024 * 1024) == 0
