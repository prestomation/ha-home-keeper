"""Shared construction of the cross-integration completion event payload.

Both the real store (``store.complete_task``) and the test fake (``testing.py``)
build the ``home_keeper_task_completed`` payload here, so the documented contract
(see docs/INTEGRATING.md) can't drift between what ships and what integrators test
against. Pure — imports nothing from Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    EVENT_TASK_COMPLETED,
    EVENT_TASK_DUE_SOON,
    EVENT_TASK_DUE_TODAY_SET,
    EVENT_TASK_OCCURRENCE_MOVED,
    EVENT_TASK_OVERDUE,
    EVENT_TASK_SKIPPED,
    EVENT_TASK_SNOOZED,
    EVENT_TASK_TRIGGERED,
    EVENT_TASK_UNCOMPLETED,
    ORIGIN_PROBLEM_SENSOR_SYNC,
    ORIGIN_SENSOR_RECOVER,
    ORIGIN_TAG_SCAN,
)


def task_event_data(
    task: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Return the common "spine" payload shared by every task event.

    One template works across `home_keeper_task_created` / `_updated` / `_deleted` /
    `_completed` / `_uncompleted` / `_triggered` / `_overdue` / `_due_soon`: the same
    identity (``task_id``/``name``), attachment (``device_id``/``area_id``/``labels``),
    schedule state (``recurrence_type``/``next_due``/``enabled``), and the opaque
    ``source`` / well-known ``managed_by`` blocks Home Keeper echoes verbatim, plus
    the linked NFC/RFID ``tag_id`` (``None`` when no tag is bound).
    ``device_id`` is the task's stored registry device id (already a registry id;
    echoed as-is, or ``None`` when the task isn't attached to a device — its per-task
    entities then live on a self-owned device keyed on ``task_id``). Per-event extras
    (``changed_fields``,
    ``days_overdue``, ``due_in_hours``) are merged in via *extra*.

    ``entity_id`` is the Home Keeper to-do list entity, or ``None`` before it is
    registered. The logbook matches an event to an entity by this key, so the rows
    that ``logbook.py`` writes show on the to-do list.
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
        "task_chips": task.get("task_chips", []),
        "tag_id": task.get("tag_id"),
        "active_season": task.get("active_season"),
        "entity_id": entity_id,
    }
    if extra:
        data.update(extra)
    return data


def occurrence_moved_extra(
    occurrence: str, to: str, previous_to: str | None, *, origin: str | None
) -> dict[str, Any]:
    """The keys ``home_keeper_task_occurrence_moved`` adds to the task spine.

    ``occurrence`` is the date on the rule, ``to`` where it is now (the same value
    when the move was undone) and ``previous_to`` where it was before, or ``None``.
    """
    return {
        "occurrence": occurrence,
        "to": to,
        "previous_to": previous_to,
        "origin": origin,
    }


def completion_event_data(
    task: dict[str, Any],
    when: Any,
    origin: str | None,
    *,
    metadata: dict[str, Any] | None = None,
    entity_id: str | None = None,
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
    return task_event_data(task, extra=extra, entity_id=entity_id)


def asset_event_data(
    asset: dict[str, Any], *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the common payload for `home_keeper_asset_*` lifecycle events.

    Carries the appliance identity and its registry ``device_id`` (``None`` until a
    virtual asset's device is provisioned), plus the opaque ``source`` and the
    well-known ``managed_by`` block, echoed verbatim like a task's — an integration
    that owns an appliance reads its own namespace back off the event rather than
    calling ``list_assets`` to find out whether the appliance is still its own.
    Per-event extras (``changed_fields`` for an update) merge in via *extra*.
    """
    data: dict[str, Any] = {
        "asset_id": asset.get("id"),
        "asset_name": asset.get("name") or "",
        "device_id": asset.get("device_id"),
        "source": asset.get("source"),
        "managed_by": asset.get("managed_by"),
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
    quantities. Those quantities can be fractional, and ``unit`` is the label they are
    counted in (``""`` for plain whole spares) so an automation can say "250 ml left"
    without looking the part up. ``source`` and ``managed_by`` are the appliance's,
    echoed verbatim.
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
        "unit": part.get("stock_unit") or "",
        # The owner of the appliance, as on the asset events, so an integration that
        # manages an appliance can tell its own stock events from the rest.
        "source": asset.get("source"),
        "managed_by": asset.get("managed_by"),
    }


# Back-compat alias: the low-stock event predates the generalised stock events and is
# the documented name integrators built against (docs/INTEGRATING.md).
low_stock_event_data = stock_event_data


def companion_event_data(companion: dict[str, Any]) -> dict[str, Any]:
    """Return the payload for `home_keeper_companion_connected` / `_suggested`.

    A *companion* row (see companions_catalog.build_companion_list) carries enough
    for an automation to react to ecosystem changes — "notify me when a compatible
    integration is detected" — without re-querying: which integration, whether it's
    connected or merely suggested, and (for a connected companion) the config entry
    whose options page configures it.
    """
    return {
        "domain": companion.get("domain"),
        "name": companion.get("name"),
        "status": companion.get("status"),
        "config_entry_id": companion.get("config_entry_id"),
        "upstream_domain": companion.get("upstream_domain"),
    }


def declarative_companion_event_data(
    spec: dict[str, Any], *, match_count: int | None = None
) -> dict[str, Any]:
    """Return the payload for `home_keeper_declarative_companion_added` / `_updated` /
    `_removed`.

    A *spec* row is a declarative-companion configuration; the payload carries
    enough for an automation to react to CRUD without re-querying — spec id,
    display name, whether it's enabled, whether it came from a shipped preset,
    and (when the reconciler has run) the current match count. The managed sensor
    tasks the spec expands into emit the ordinary `home_keeper_task_*` events on
    their own, so automations that want per-task detail filter those via
    ``managed_by.integration == "home_keeper"`` +
    ``source.declarative_companion.spec_id``.
    """
    data: dict[str, Any] = {
        "spec_id": spec.get("id"),
        "name": spec.get("name"),
        "enabled": bool(spec.get("enabled", True)),
        "preset_id": spec.get("preset_id"),
    }
    if match_count is not None:
        data["match_count"] = int(match_count)
    return data


def data_transfer_event_data(
    kind: str, sections: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the payload for `home_keeper_data_exported` / `_imported`.

    *kind* is ``data`` for a YAML document and ``bundle`` for a zip file. *sections*
    maps each section of the document to its counts. A Home Keeper section of an
    export has the number of records. A Home Keeper section of an import has
    ``created`` and ``updated``. A companion section has the ``counts`` that the
    companion returned, as is. The payload holds counts only, never a record.
    """
    return {
        "kind": kind,
        "sections": {str(name): count for name, count in (sections or {}).items()},
    }


# The task events that ``logbook.py`` writes a row for. The created, updated and
# deleted events get no row: an edit is not part of the history of a task.
LOGBOOK_EVENTS: tuple[str, ...] = (
    EVENT_TASK_COMPLETED,
    EVENT_TASK_UNCOMPLETED,
    EVENT_TASK_SKIPPED,
    EVENT_TASK_SNOOZED,
    EVENT_TASK_OVERDUE,
    EVENT_TASK_DUE_SOON,
    EVENT_TASK_TRIGGERED,
    EVENT_TASK_DUE_TODAY_SET,
    EVENT_TASK_OCCURRENCE_MOVED,
)

# The icon of the logbook row for each event in ``LOGBOOK_EVENTS``.
LOGBOOK_ICONS: dict[str, str] = {
    EVENT_TASK_COMPLETED: "mdi:check-circle-outline",
    EVENT_TASK_UNCOMPLETED: "mdi:undo",
    EVENT_TASK_SKIPPED: "mdi:debug-step-over",
    EVENT_TASK_SNOOZED: "mdi:alarm-snooze",
    EVENT_TASK_OVERDUE: "mdi:alert-circle-outline",
    EVENT_TASK_DUE_SOON: "mdi:clock-alert-outline",
    EVENT_TASK_TRIGGERED: "mdi:bell-ring-outline",
    EVENT_TASK_DUE_TODAY_SET: "mdi:calendar-today",
    EVENT_TASK_OCCURRENCE_MOVED: "mdi:calendar-arrow-right",
}

_SENSOR_ORIGINS = (ORIGIN_PROBLEM_SENSOR_SYNC, ORIGIN_SENSOR_RECOVER)


def _day(value: Any) -> str:
    """The date part of an ISO date or datetime string, as stored."""
    return str(value)[:10] if value else "?"


def _completed_message(data: Mapping[str, Any]) -> str:
    origin = data.get("origin")
    if origin in _SENSOR_ORIGINS:
        return "was completed by its sensor"
    message = "was completed"
    if who := data.get("who"):
        message += f" by {who}"
    if origin == ORIGIN_TAG_SCAN:
        message += " with a tag scan"
    return message


def logbook_message(event_type: str, data: Mapping[str, Any]) -> str:
    """The logbook text for a task event. The logbook shows it after the task name.

    The text is English: Home Assistant shows the logbook text of an integration as
    it is.
    """
    if event_type == EVENT_TASK_COMPLETED:
        return _completed_message(data)
    if event_type == EVENT_TASK_UNCOMPLETED:
        return "had a completion removed"
    if event_type == EVENT_TASK_SKIPPED:
        return "was skipped"
    if event_type == EVENT_TASK_SNOOZED:
        return f"was snoozed until {_day(data.get('snoozed_until'))}"
    if event_type == EVENT_TASK_OVERDUE:
        return "became overdue"
    if event_type == EVENT_TASK_DUE_SOON:
        return f"is due in {data.get('due_in_hours', 0):g} hours"
    if event_type == EVENT_TASK_TRIGGERED:
        return "became due"
    if event_type == EVENT_TASK_DUE_TODAY_SET:
        return "was set to due today"
    if event_type == EVENT_TASK_OCCURRENCE_MOVED:
        occurrence, to = _day(data.get("occurrence")), _day(data.get("to"))
        if occurrence == to:
            return f"has its occurrence on {occurrence} back on its date"
        return f"has its occurrence on {occurrence} moved to {to}"
    return event_type
