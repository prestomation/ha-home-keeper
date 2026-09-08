"""Running the portable document against a live Home Assistant.

``transfer.py`` decides *what* an import does, with no Home Assistant in sight so the
whole decision is unit-testable. This module is the half that needs the running
system: the registries a document's names resolve against, the device provisioning a
new appliance triggers, and the entry reload that rebuilds the entity set afterwards.

It lives apart from ``__init__.py`` for one reason: the service and its websocket twin
must run the *same* code, and ``websocket_api`` cannot import ``__init__`` — the same
split, and the same reason, as ``notifications.py`` (pure) and ``notifier.py``.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from . import devices, transfer
from .const import PANEL_VERSION
from .coordinator import HomeKeeperCoordinator


async def async_export_document(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, data: dict[str, Any]
) -> dict[str, Any]:
    """Build the portable document. Shared by the service and its websocket twin."""
    document = transfer.build_document(
        coord.store.list_tasks(),
        coord.store.list_assets(),
        area_names=devices.area_names(hass),
        version=PANEL_VERSION,
        now=dt_util.now(),
        include=data.get("include"),
    )
    return {"document": document, "yaml": transfer.document_to_yaml(document)}


async def async_import_document(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, data: dict[str, Any]
) -> dict[str, Any]:
    """Plan an import, then apply it unless this is a dry run.

    Two passes, and the split is the whole safety story. ``transfer.plan_import`` is
    pure and touches nothing: it decides every record's fate against the live store
    and reports *every* problem at once, each with a path. Only a plan with no error
    is applied — so a document that is wrong anywhere writes nothing, which is what
    makes a plain (non-dry-run) import safe to point at a generated file and gives
    whoever generated it a clean fix-and-retry loop.

    The applying pass is ordered by a dependency the panel never has to think about:
    a task attaches to an appliance's *device*, and a virtual appliance has no device
    until it is provisioned. So appliances are written first, ``async_reconcile_assets``
    runs once for the whole batch (it writes each new device id back onto its asset),
    and only then are the tasks written with their placeholder device references
    resolved. One reconcile and one reload for the batch, not one per record.
    """
    registry = dr.async_get(hass)
    plan = transfer.plan_import(
        data["document"],
        tasks=coord.store.get_tasks(),
        assets=coord.store.get_assets(),
        area_ids={area.name: area.id for area in ar.async_get(hass).async_list_areas()},
        # The registry's ids, not its entries: a stated device_id is only kept
        # when the device really is on this install. ``devices`` iterates entries,
        # so take each one's id rather than reaching for a mapping view that its
        # ``Collection`` type does not promise.
        device_ids=frozenset(device.id for device in registry.devices),
        match=data.get("match", "auto"),
        now=dt_util.now(),
    )
    dry_run = bool(data.get("dry_run"))
    if dry_run or not plan.ok:
        return plan.as_report(dry_run=dry_run)

    planned_assets = plan.for_section("appliances")
    if planned_assets:
        await coord.store.async_import_records(
            assets_to_write=[
                (r.record_id, r.payload, r.action == "create") for r in planned_assets
            ],
            tasks_to_write=[],
        )
        # Provisions a device for every virtual appliance and writes its id back onto
        # the asset — the only moment those ids come into existence.
        await devices.async_reconcile_assets(hass, coord.entry, coord.store)

    planned_tasks = plan.for_section("tasks")
    unattached: list[transfer.Problem] = []
    if planned_tasks:
        # Build the write list rather than editing the plan. `PlannedRecord` is
        # frozen, and a frozen record whose dict gets rewritten underneath it is a
        # half-promise: the plan should stay the record of what was *planned*, so
        # anything that reads it back — a report, a log, a future retry — sees the
        # same thing the preview showed.
        tasks_to_write: list[tuple[str, dict[str, Any], bool]] = []
        for record in planned_tasks:
            payload = record.payload
            asset_id = transfer.planned_asset_id(payload.get("device_id"))
            if asset_id is not None:
                device_id = (coord.store.get_asset(asset_id) or {}).get("device_id")
                payload = {**payload, "device_id": device_id}
                if not device_id:
                    # Provisioning is the one step that can still fail after
                    # validation passed, and the appliances are already written by
                    # now, so there is nothing to roll back to. Import the task
                    # standalone and *say so*: a task that quietly lost its
                    # appliance is the kind of thing a migration notices months late.
                    unattached.append(
                        transfer.Problem(
                            section="tasks",
                            index=record.index,
                            path=f"tasks[{record.index}].appliance",
                            message=(
                                f'"{record.name}" was imported without its appliance: '
                                "Home Assistant did not give that appliance a device. "
                                "Open the appliance, then set the task's appliance "
                                "again."
                            ),
                            severity="warning",
                        )
                    )
            tasks_to_write.append(
                (record.record_id, payload, record.action == "create")
            )
        await coord.store.async_import_records(
            assets_to_write=[], tasks_to_write=tasks_to_write
        )

    if plan.records:
        # Imported parts may imply derived tasks, and the entity set has to be rebuilt
        # for everything that arrived — the same finish an asset mutation does.
        await coord.store.reconcile_part_tasks()
        await coord.store.reconcile_buy_tasks()
        await hass.config_entries.async_reload(coord.entry.entry_id)
    report = plan.as_report(dry_run=False)
    report["problems"].extend(problem.as_dict() for problem in unattached)
    return report
