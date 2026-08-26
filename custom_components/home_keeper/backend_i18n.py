"""Eager, server-side string resolution for surfaces that can't use HA's lazy
``translation_key`` mechanism.

HA's own ``ServiceValidationError``/``HomeAssistantError`` translation is *lazy*:
the exception carries a ``translation_key`` and the frontend resolves it to text
only when it renders the error, in the viewer's own language. That works great for
service calls, but two surfaces in this integration need the *final string*
immediately, server-side, because nothing downstream will localize it later:

- The websocket API (``websocket_api.py``) sends ``connection.send_error(id, code,
  message)`` — the frontend displays ``message`` verbatim; it has no lazy-lookup
  path for a websocket error the way it does for a service-call exception.
- The document-upload HTTP views (``manuals.py``) return a JSON ``{"message": ...}``
  body that ``frontend/src/api.ts`` throws directly as the shown error.

Both read the *same* ``exceptions`` category already used for service exceptions in
``strings.json``/``translations/<lang>.json`` — no new category, so hassfest and
``test_translations_parity.py`` keep validating it unchanged — just resolved here
directly by reading the file, instead of waiting on the frontend to look it up.

Separately, a handful of backend-generated (not exception) strings — the
problem-sensor sync's completion prompt, a companion catalog suggestion's
description, the inventory CSV column headers — have no home in strings.json at all
(hassfest rejects unknown top-level categories there, and they aren't exceptions).
Those live in their own flat-dotted-key bundle, ``backend_strings/<lang>.json``,
mirroring the convention ``frontend/src/locales/*.json`` uses for the panel.

Every helper here is a plain file read + ``str.format``-style interpolation — no
Home Assistant import, so any module that needs a translated string (even a "pure"
one like ``problem_tasks.py``/``inventory.py``) can use this without giving up its
own unit-testability; callers thread the caller's ``hass.config.language`` in as a
plain string.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

_DEFAULT_LANG = "en"
_COMPONENT_DIR = Path(__file__).parent
_TRANSLATIONS_DIR = _COMPONENT_DIR / "translations"
_BACKEND_STRINGS_DIR = _COMPONENT_DIR / "backend_strings"
_TOKEN_RE = re.compile(r"\{(\w+)\}")


def _interpolate(template: str, params: dict[str, Any]) -> str:
    return _TOKEN_RE.sub(
        lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0),
        template,
    )


@functools.cache
def _exceptions(lang: str) -> dict[str, str]:
    """The ``exceptions.<key>.message`` templates for *lang*, flattened."""
    path = _TRANSLATIONS_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    exceptions = data.get("exceptions")
    if not isinstance(exceptions, dict):
        return {}
    return {
        key: value["message"]
        for key, value in exceptions.items()
        if isinstance(value, dict) and isinstance(value.get("message"), str)
    }


def resolve_exception(lang: str, key: str, **params: Any) -> str:
    """Resolve ``exceptions.<key>.message`` for *lang*, English-then-key fallback."""
    template = _exceptions(lang).get(key) or _exceptions(_DEFAULT_LANG).get(key, key)
    return _interpolate(template, params)


@functools.cache
def _backend_strings(lang: str) -> dict[str, str]:
    """The flat ``backend_strings/<lang>.json`` table for *lang*."""
    path = _BACKEND_STRINGS_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_string(lang: str, key: str, **params: Any) -> str:
    """Resolve a ``backend_strings/<lang>.json`` key, English-then-key fallback."""
    template = _backend_strings(lang).get(key) or _backend_strings(_DEFAULT_LANG).get(
        key, key
    )
    return _interpolate(template, params)


def preload(lang: str) -> None:
    """Read every string table for *lang* into cache. **Blocking** — call from an
    executor, never from the event loop.

    Each table above is read from disk exactly once per language and memoized, so
    the cost is a one-off — but it lands on whichever caller happens to get there
    first, and every one of those callers is on Home Assistant's event loop: the
    problem-sensor reconcile during setup, a websocket error reply, an inventory
    export. Home Assistant's blocking-call detector catches it and logs a
    ``Detected blocking call to read_text ... inside the event loop`` warning
    naming this file, which is what issue #247's reporter pasted. (``notifier.py``
    had the same problem in #150 and solved it the other way — dispatching each
    lookup through ``hass.async_add_executor_job`` — but that is not available
    here, because the callers are the pure modules and this module has no Home
    Assistant import to hand them one.)

    So the loop-bound callers never do the reading: ``async_setup_entry`` runs this
    once in the executor before anything can ask for a string, and every later
    ``resolve_*`` is a cache hit. English is always included — it is the fallback
    both resolvers reach for when a key is missing from the caller's language, so
    warming only that language would leave the second read on the loop.

    Idempotent: a second call (an entry reload, a second entry) hits the caches.
    """
    for wanted in dict.fromkeys((lang, _DEFAULT_LANG)):
        _exceptions(wanted)
        _backend_strings(wanted)
