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


def low_stock_event_data(
    asset: dict[str, Any], part: dict[str, Any]
) -> dict[str, Any]:
    """Return the ``home_keeper_part_low_stock`` event data for a low spare part.

    Carries enough to drive an automation (notify, add to a shopping list,
    reorder) without re-querying: which appliance and part, the part/vendor
    identifiers needed to rebuy, and the current vs. threshold counts.
    """
    return {
        "asset_id": asset.get("id"),
        "asset_name": asset.get("name") or "",
        "device_id": asset.get("device_id"),
        "part_id": part.get("id"),
        "part_name": part.get("name") or "",
        "part_number": part.get("part_number") or "",
        "vendor": part.get("vendor") or "",
        "stock": part.get("stock"),
        "reorder_at": part.get("reorder_at"),
    }
