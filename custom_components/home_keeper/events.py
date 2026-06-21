"""Shared construction of the cross-integration completion event payload.

Both the real store (``store.complete_task``) and the test fake (``testing.py``)
build the ``home_keeper_task_completed`` payload here, so the documented contract
(see docs/INTEGRATING.md) can't drift between what ships and what integrators test
against. Pure — imports nothing from Home Assistant.
"""

from __future__ import annotations

from typing import Any


def task_event_data(
    task: dict[str, Any], *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the common "spine" payload shared by every task event.

    One template works across `home_keeper_task_created` / `_updated` / `_deleted` /
    `_completed` / `_uncompleted` / `_triggered` / `_overdue` / `_due_soon`: the same
    identity (``task_id``/``name``), attachment (``device_id``/``area_id``/``labels``),
    schedule state (``recurrence_type``/``next_due``/``enabled``), and the opaque
    ``source`` / well-known ``managed_by`` blocks Home Keeper echoes verbatim.
    ``device_id`` is the task's stored registry device id (already a registry id;
    echoed as-is, or ``None`` when the task isn't attached to a device — its per-task
    entities then live on a self-owned device keyed on ``task_id``). Per-event extras
    (``changed_fields``,
    ``days_overdue``, ``due_in_hours``) are merged in via *extra*.
    """
    data: dict[str, Any] = {
        "task_id": task.get("id"),
        "name": task.get("name"),
        "device_id": task.get("device_id"),
        "area_id": task.get("area_id"),
        "recurrence_type": task.get("recurrence_type"),
        "next_due": task.get("next_due"),
        "enabled": task.get("enabled", True),
        "labels": task.get("labels", []),
        "source": task.get("source"),
        "managed_by": task.get("managed_by"),
    }
    if extra:
        data.update(extra)
    return data


def completion_event_data(
    task: dict[str, Any],
    when: Any,
    origin: str | None,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the ``home_keeper_task_completed`` event data for a completed task.

    The common task spine plus the completion-specific ``completed_at`` and ``origin``.
    ``when`` is the completion datetime (or an ISO string); ``origin`` is the opaque
    caller marker. The task passed in is the *post-completion* task, so ``next_due`` is
    already the next occurrence (``None`` for a now-dormant triggered task).

    *metadata* is the cleaned per-completion context that was recorded
    (``note``/``cost``/``photo``/``who``); only the keys that carried a value are
    merged in, so a plain one-click completion adds nothing beyond the spine.
    """
    extra: dict[str, Any] = {
        "completed_at": when.isoformat() if hasattr(when, "isoformat") else when,
        "origin": origin,
    }
    if metadata:
        extra.update(metadata)
    return task_event_data(task, extra=extra)


def asset_event_data(
    asset: dict[str, Any], *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the common payload for `home_keeper_asset_*` lifecycle events.

    Carries the appliance identity and its registry ``device_id`` (``None`` until a
    virtual asset's device is provisioned). Per-event extras (``changed_fields`` for an
    update) merge in via *extra*.
    """
    data: dict[str, Any] = {
        "asset_id": asset.get("id"),
        "asset_name": asset.get("name") or "",
        "device_id": asset.get("device_id"),
    }
    if extra:
        data.update(extra)
    return data


def stock_event_data(asset: dict[str, Any], part: dict[str, Any]) -> dict[str, Any]:
    """Return the shared payload for the three `home_keeper_part_*` stock events.

    Low-stock, out-of-stock and restocked all carry the same shape so an automation
    template is interchangeable across them. Carries enough to drive an automation
    (notify, add to a shopping list, reorder) without re-querying: which appliance and
    part, the part/vendor identifiers needed to rebuy, and the current vs. threshold
    counts.
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


# Back-compat alias: the low-stock event predates the generalised stock events and is
# the documented name integrators built against (docs/INTEGRATING.md).
low_stock_event_data = stock_event_data
