"""Deprecated input forms: 1 warning per form per Home Assistant run.

Each entry of ``DEPRECATIONS`` is an input form that still works, with the text that
names the form that replaces it. A later release removes the old form. To remove one,
search for its key: the key names every place that still accepts the form.

The set of warned keys lives for the Python process. An entry reload does not import
this module again, so a form warns 1 time for each start of Home Assistant, however
often an automation calls it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final

_LOGGER = logging.getLogger(__package__)

# The 1-link fields of the consumable link (#493). The ``parts`` list replaces them.
SERVICE_SINGLE_CONSUMABLE_LINK: Final = "service_set_task_consumable_single_link"
WS_SINGLE_CONSUMABLE_LINK: Final = "ws_set_task_consumable_single_link"

DEPRECATIONS: Final[dict[str, str]] = {
    SERVICE_SINGLE_CONSUMABLE_LINK: (
        "The asset_id, part_id and quantity fields of home_keeper.set_task_consumable "
        "are deprecated and will be removed in a later release. Send the `parts` list "
        "instead, for 1 part or more. Send `parts: []` to clear the links."
    ),
    WS_SINGLE_CONSUMABLE_LINK: (
        "The asset_id, part_id and quantity fields of the home_keeper/"
        "set_task_consumable websocket command are deprecated and will be removed in "
        "a later release. Send the `parts` list instead. Send `parts: []` to clear "
        "the links."
    ),
}

_warned: set[str] = set()


def warn_once(key: str) -> bool:
    """Log the warning of the deprecated form *key*, the first time only.

    Returns True when this call logged it. Raises ``KeyError`` for a key that is not
    in ``DEPRECATIONS``, so a typo cannot pass in silence.
    """
    message = DEPRECATIONS[key]
    if key in _warned:
        return False
    _warned.add(key)
    _LOGGER.warning("%s", message)
    return True


def warn_single_consumable_link(data: Mapping[str, Any], key: str) -> bool:
    """Warn once when a consumable-link call does not send the ``parts`` list.

    Every call without ``parts`` uses the old form: ``asset_id`` and ``part_id`` set a
    list of 1, and a call with neither clears the links.
    """
    if "parts" in data:
        return False
    return warn_once(key)
