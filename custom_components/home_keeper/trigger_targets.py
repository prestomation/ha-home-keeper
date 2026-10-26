"""What the target of a Home Keeper trigger means for 1 event.

``trigger.py`` resolves a trigger's target (entities, devices, areas, floors and
labels) with Home Assistant's own target helpers. It gives this module the
Home Keeper entities that the target holds, as ``(unique_id, device_id)`` pairs,
and the devices, areas and labels that it names. :func:`target_refs` turns them
into the tasks, parts and appliances that the target holds. :func:`matches` then
decides at fire time if 1 event payload is in the target.

The rules, for each payload:

* **task**: the task has an entity in the target, or its ``device_id``, its
  ``area_id`` or 1 of its ``labels`` is in the target. A task on a self-owned
  device carries a ``device_id`` that the registry does not know, so it matches
  through its entities. A standalone task has no entities, so it matches through
  its area or its labels.
* **stock**: the part has an entity in the target, or the appliance has a
  metadata entity in the target, or the event's ``device_id`` is in the target.
* **asset**: the appliance has an entity or a part entity in the target, or its
  ``device_id`` is in the target.

The Home Keeper service device, or an entity on it (the to-do list, for example),
means every event. Other payloads have no target rule and always match.

Pure: no Home Assistant import, so the unit tests and the mutation gate run it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .const import ASSET_IDENTIFIER_PREFIX, DOMAIN

# The unique id shapes of the per-task, part and appliance entities. The
# coordinator-entities design doc lists them as one-way doors.
_PART_UID = re.compile(
    rf"^{DOMAIN}_{ASSET_IDENTIFIER_PREFIX}_(?P<asset>.+?)_part_(?P<part>.+?)"
    r"_(?:low_stock|stock)$"
)
_META_UID = re.compile(rf"^{DOMAIN}_{ASSET_IDENTIFIER_PREFIX}_(?P<asset>.+?)_meta_.+$")
_TASK_UID = re.compile(rf"^{DOMAIN}_(?P<task>.+)_(?:done|next_due|overdue)$")


@dataclass(frozen=True, slots=True)
class TargetRefs:
    """The Home Keeper objects that 1 resolved trigger target holds."""

    everything: bool = False
    task_ids: frozenset[str] = field(default_factory=frozenset)
    part_keys: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    asset_ids: frozenset[str] = field(default_factory=frozenset)
    device_ids: frozenset[str] = field(default_factory=frozenset)
    area_ids: frozenset[str] = field(default_factory=frozenset)
    label_ids: frozenset[str] = field(default_factory=frozenset)


def target_refs(
    entities: Iterable[tuple[str, str | None]],
    *,
    device_ids: Iterable[str],
    area_ids: Iterable[str],
    label_ids: Iterable[str],
    service_device_id: str | None,
) -> TargetRefs:
    """Read a resolved target.

    ``entities`` holds the ``(unique_id, device_id)`` of each Home Keeper entity in
    the target, also the entities that a device, area or label adds. The other
    arguments are the devices, areas and labels that the target names.
    """
    devices = frozenset(device_ids)
    everything = service_device_id is not None and service_device_id in devices
    tasks: set[str] = set()
    parts: set[tuple[str, str]] = set()
    assets: set[str] = set()
    for unique_id, device_id in entities:
        if service_device_id is not None and device_id == service_device_id:
            everything = True
        if part := _PART_UID.match(unique_id):
            parts.add((part["asset"], part["part"]))
        elif meta := _META_UID.match(unique_id):
            assets.add(meta["asset"])
        elif task := _TASK_UID.match(unique_id):
            tasks.add(task["task"])
    return TargetRefs(
        everything=everything,
        task_ids=frozenset(tasks),
        part_keys=frozenset(parts),
        asset_ids=frozenset(assets),
        device_ids=devices,
        area_ids=frozenset(area_ids),
        label_ids=frozenset(label_ids),
    )


def _task_matches(data: Mapping[str, Any], refs: TargetRefs) -> bool:
    return (
        data.get("task_id") in refs.task_ids
        or data.get("device_id") in refs.device_ids
        or data.get("area_id") in refs.area_ids
        or not refs.label_ids.isdisjoint(data.get("labels") or ())
    )


def _stock_matches(data: Mapping[str, Any], refs: TargetRefs) -> bool:
    return (
        (data.get("asset_id"), data.get("part_id")) in refs.part_keys
        or data.get("asset_id") in refs.asset_ids
        or data.get("device_id") in refs.device_ids
    )


def _asset_matches(data: Mapping[str, Any], refs: TargetRefs) -> bool:
    asset_id = data.get("asset_id")
    return (
        asset_id in refs.asset_ids
        or any(asset_id == part_asset for part_asset, _ in refs.part_keys)
        or data.get("device_id") in refs.device_ids
    )


_RULES = {"task": _task_matches, "stock": _stock_matches, "asset": _asset_matches}


def matches(payload: str, data: Mapping[str, Any], refs: TargetRefs) -> bool:
    """True when an event with this payload spine and data is in the target."""
    rule = _RULES.get(payload)
    if rule is None or refs.everything:
        return True
    return rule(data, refs)
