"""Shared construction of the cross-integration completion event payload.

Both the real store (``store.complete_task``) and the test fake (``testing.py``)
build the ``home_keeper_task_completed`` payload here, so the documented contract
(see docs/INTEGRATING.md) can't drift between what ships and what integrators test
against. Pure — imports nothing from Home Assistant.
"""

from __future__ import annotations

from typing import Any


def completion_event_data(
    task: dict[str, Any], when: Any, origin: str | None
) -> dict[str, Any]:
    """Return the ``home_keeper_task_completed`` event data for a completed task.

    ``when`` is the completion datetime (or an ISO string); ``origin`` is the opaque
    caller marker. ``source`` is echoed verbatim from the task.
    """
    return {
        "task_id": task.get("id"),
        "name": task.get("name"),
        "source": task.get("source"),
        "completed_at": when.isoformat() if hasattr(when, "isoformat") else when,
        "origin": origin,
    }
