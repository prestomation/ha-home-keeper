"""Names and identity of a task's per-task device-page entities. Pure, no HA imports.

A task attached to an existing device gets three entities on that device's page
(mark-done button, next-due sensor, overdue binary sensor). Several tasks can share
one device page, so each entity name starts with a short label for its task. Home
Assistant then puts the device name in front of the whole name, and makes the
``entity_id`` from the result the first time the entity registers.

:func:`entity_name_prefix` picks that label. :func:`entity_set_key` says when the
entities must be made again (an entry reload), because Home Assistant caches an
entity's name.
"""

from __future__ import annotations

import re
from typing import Any

from .declarative_companions import declarative_source
from .notifications import is_completion_blocked

# Separators left over when the device name is cut off the start or end of a task
# name: "Kitchen Sensor: Check battery" -> ": Check battery" -> "Check battery".
_TRIM = " \t:-\u2013\u2014,"


def companion_name(task: dict[str, Any]) -> str | None:
    """The name of the declarative companion that owns *task*, else ``None``.

    ``build_managed_by`` stamps the companion name as ``managed_by.display_name``. A
    problem-sensor task stamps a display name too, so the companion source is what
    decides, not the display name alone.
    """
    if declarative_source(task) is None:
        return None
    managed_by = task.get("managed_by")
    if not isinstance(managed_by, dict):
        return None
    name = managed_by.get("display_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _strip_device_name(name: str, device_name: str) -> str:
    """*name* with *device_name* cut off its start or end, as a whole word."""
    escaped = re.escape(device_name.strip())
    for pattern in (rf"^{escaped}(?!\w)", rf"(?<!\w){escaped}$"):
        name = re.sub(pattern, "", name, count=1, flags=re.IGNORECASE)
    return name.strip(_TRIM)


def entity_name_prefix(task: dict[str, Any], device_name: str | None) -> str:
    """The label for *task* in front of its entity names on *device_name*'s page.

    A declarative companion task uses the companion name: it is short, the user chose
    it, and it says which rule opened the task. The rendered task name usually holds the
    device name, which Home Assistant adds again, so it made long, repeated names and
    entity_ids (#377). Any other task uses its name without the device name at its start
    or end, or its whole name when nothing else is left. The caller adds the ``": "``.
    """
    companion = companion_name(task)
    if companion is not None:
        return companion
    name = str(task.get("name") or "").strip()
    if not name or not device_name or not device_name.strip():
        return name
    return _strip_device_name(name, device_name) or name


def entity_set_key(task: dict[str, Any] | None) -> tuple[Any, ...]:
    """Identity of a task's per-task entity set.

    Per-task entities (button/sensor/binary_sensor) exist only for an enabled,
    device-attached task. When this key changes between an update's before and after,
    the entry must be reloaded so entities are created, removed or renamed; otherwise
    a plain coordinator refresh is enough.

    * ``name`` and the companion name are in the key because Home Assistant caches an
      entity's computed ``name``. Making the entity again on reload is how a rename
      reaches the device page (and how a self-owned task device gets its new name).
    * ``completion_blocked`` is in the key because it decides whether the task has a
      mark-done button at all.
    """
    if not task:
        return (None, False, None, None, False)
    return (
        task.get("device_id"),
        bool(task.get("enabled", True)),
        task.get("name"),
        companion_name(task),
        is_completion_blocked(task),
    )
