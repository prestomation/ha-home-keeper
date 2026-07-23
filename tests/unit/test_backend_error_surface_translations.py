"""Drift guards for two user-facing error surfaces that ``test_exception_translations``
doesn't cover (no HA runtime needed).

``ServiceValidationError``/``HomeAssistantError`` raises are guarded by
``test_exception_translations.py`` (every one must carry a ``translation_key``, lazily
resolved by the frontend). Two other surfaces send the *final string* to the user
immediately and have no such lazy path:

* ``connection.send_error(id, code, message)`` in ``websocket_api.py`` — the panel
  shows ``message`` verbatim.
* ``<HomeAssistantView>.json_message(message, status)`` in ``manuals.py`` — the
  document-upload views' JSON error body, which ``frontend/src/api.ts`` throws
  directly.

Both must resolve ``message`` via ``backend_i18n.resolve_exception(...)`` (see that
module's docstring) rather than pass a literal string — these pure-AST checks fail
the build on a bare-string call so the rule can't silently regress, the same way
``test_exception_translations.py`` guards ``raise``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"


def _literal_arg_calls(path: Path, *, attr: str, arg_index: int) -> list[int]:
    """Line numbers of ``<anything>.<attr>(...)`` calls whose *arg_index*-th
    positional argument is a literal string constant."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == attr):
            continue
        args = node.args
        if len(args) > arg_index:
            candidate = args[arg_index]
            if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                offenders.append(node.lineno)
    return offenders


def test_websocket_send_error_has_no_bare_string_message() -> None:
    """Every ``connection.send_error(id, code, message)`` message must be resolved
    via ``backend_i18n.resolve_exception``, not a literal string (websocket_api.py)."""
    path = _COMPONENT / "websocket_api.py"
    offenders = _literal_arg_calls(path, attr="send_error", arg_index=2)
    assert not offenders, (
        "connection.send_error(...) with a bare-string message in websocket_api.py "
        f"(resolve it via backend_i18n.resolve_exception instead): lines {offenders}"
    )


def test_manuals_json_message_has_no_bare_string() -> None:
    """Every ``view.json_message(message, status)`` message must be resolved via
    ``backend_i18n.resolve_exception``, not a literal string (manuals.py)."""
    path = _COMPONENT / "manuals.py"
    offenders = _literal_arg_calls(path, attr="json_message", arg_index=0)
    assert not offenders, (
        "json_message(...) with a bare-string message in manuals.py (resolve it via "
        f"backend_i18n.resolve_exception instead): lines {offenders}"
    )
