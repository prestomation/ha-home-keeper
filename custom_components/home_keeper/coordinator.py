"""DataUpdateCoordinator for Home Keeper.

Reads tasks from the local :class:`HomeKeeperStore` (no network). A periodic
refresh keeps time-based state (overdue / due-soon) current even when no
mutations occur; every mutation also triggers an immediate refresh.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

try:
    from homeassistant.helpers.device_registry import DeviceInfo
except ImportError:  # pragma: no cover - older HA fallback
    from homeassistant.helpers.entity import DeviceInfo  # type: ignore[no-redef]
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import companions, models, notifier, recurrence, transitions
from .const import (
    ASSET_KIND_VIRTUAL,
    DOMAIN,
    EVENT_TASK_DUE_SOON,
    EVENT_TASK_OVERDUE,
    OPTION_ONE_OFF_RETENTION_DAYS,
)
from .options import current_options
from .store import HomeKeeperStore

if TYPE_CHECKING:
    from .problem_sync import ProblemSensorSync
    from .sensor_watcher import SensorTaskWatcher

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)


def entity_set_key(task: dict[str, Any] | None) -> tuple:
    """Identity of a task's per-task entity set.

    Per-task entities (button/sensor/binary_sensor) exist only for an enabled,
    device-attached task, and their display name embeds the task name (so several
    tasks on one device page stay distinguishable). When this key changes between
    an update's before/after, the entry must be reloaded so entities are
    created/removed/renamed; otherwise a plain coordinator refresh is enough.

    ``name`` is part of the key because HA caches an entity's computed ``name``;
    recreating the entity on reload is how a rename takes effect on the device
    page (and how a self-owned task device picks up its new name).
    """
    if not task:
        return (None, False, None)
    return (task.get("device_id"), bool(task.get("enabled", True)), task.get("name"))


class HomeKeeperCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator exposing the current task map to all entities."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, store: HomeKeeperStore
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Home Keeper",
            update_interval=SCAN_INTERVAL,
        )
        self.store = store
        self.entry = entry
        # The problem-sensor sync helper, attached during async_setup_entry.
        self.problem_sync: ProblemSensorSync | None = None
        # The sensor-based-task watcher, attached during async_setup_entry (after its
        # edge state / usage baselines are seeded, so the periodic tick below only ever
        # reacts to genuine transitions).
        self.sensor_watcher: SensorTaskWatcher | None = None
        # Edge state for the time-based task events (overdue / due-soon). Carried
        # across refreshes so each is fired at most once per ``next_due``; see
        # transitions.detect_transitions.
        self._edge_state: transitions.StateMap = {}
        # Firing is gated until setup finishes (enable_transition_events) so the
        # several refreshes during async_setup_entry silently *baseline* current state
        # — an HA restart never replays an "overdue" storm for tasks already overdue.
        self._events_enabled = False

    def enable_transition_events(self) -> None:
        """Start firing overdue/due-soon events (called once setup is complete).

        Until this is called, refreshes still update the edge state but fire nothing,
        so the post-restart steady state is baselined silently and only genuine
        transitions observed while running are announced.
        """
        self._events_enabled = True

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        await self._purge_expired_one_offs()
        # Re-evaluate sensor-based tasks against their bound readings before reading the
        # task map, so a freshly-armed task surfaces as overdue/due-soon in this same
        # cycle. No refresh request here — the transition detection below runs next.
        if self.sensor_watcher is not None:
            await self.sensor_watcher.async_evaluate(refresh=False)
        tasks = self.store.get_tasks()
        fired, self._edge_state = transitions.detect_transitions(
            self._edge_state, tasks, now=dt_util.now()
        )
        if self._events_enabled:
            for event_name, payload in fired:
                self.hass.bus.async_fire(event_name, payload)
            # Automatic notification source: send to any profile whose auto trigger
            # matches a transition that fired this cycle (once per profile, deduped).
            kinds = {
                EVENT_TASK_OVERDUE: "overdue",
                EVENT_TASK_DUE_SOON: "due_soon",
            }
            fired_kinds = {kinds[name] for name, _ in fired if name in kinds}
            if fired_kinds:
                await notifier.async_send_auto(self.hass, self, fired_kinds)
        # Re-detect companions on the same cadence so a popular upstream installed at
        # runtime (e.g. Battery Notes) surfaces a suggestion, and an
        # installed/removed glue updates — edge-triggered + silently baselined inside
        # the registry (a no-op until it's live).
        companions.async_reconcile(self.hass)
        return tasks

    async def _purge_expired_one_offs(self) -> None:
        """Auto-delete completed one-off tasks past the configured retention window.

        Runs on every periodic refresh (the single time-based chokepoint). The
        retention is a config-entry option in days; ``0`` (the default) keeps
        completed one-offs forever, so this is a no-op until the user opts in.
        """
        retention = int(
            current_options(self.entry).get(OPTION_ONE_OFF_RETENTION_DAYS, 0)
        )
        if retention <= 0:
            return
        now = dt_util.now()
        expired = [
            tid
            for tid, task in self.store.get_tasks().items()
            if recurrence.one_off_expired(task, retention, now=now)
        ]
        for tid in expired:
            try:
                await self.store.delete_task(tid)
            except models.TaskValidationError as err:  # pragma: no cover - defensive
                _LOGGER.debug("Skipping auto-delete of one-off %s: %s", tid, err)

    def device_attached_task_ids(self) -> list[str]:
        """Enabled task ids attached to a device (so get per-task entities)."""
        return [
            tid
            for tid, task in self.data.items()
            if task.get("device_id") and task.get("enabled", True)
        ]

    def _existing_device(self, device_id: str | None) -> dr.DeviceEntry | None:
        """Resolve ``device_id`` to a registry device, or ``None``.

        Single source of truth for "is this an existing device we can merge onto?"
        so the DeviceInfo and name-prefix decisions can't drift apart.
        """
        if not device_id:
            return None
        return dr.async_get(self.hass).async_get(device_id)

    def task_uses_existing_device(self, task: dict[str, Any]) -> bool:
        """True when the task's per-task entities merge onto an existing device.

        In that case several tasks can share one device page, so each entity's
        name is prefixed with the task name to disambiguate. Self-owned task
        devices (no ``device_id`` or an unknown one) need no prefix because the
        device itself is already named after the task.
        """
        return self._existing_device(task.get("device_id")) is not None

    def device_info_for_device_id(self, device_id: str | None) -> DeviceInfo | None:
        """DeviceInfo that merges entities onto an existing registry device.

        Reuses the device's own identifiers/connections so HA attaches our entities
        to that device page rather than creating a new device. Returns ``None`` when
        the device cannot be resolved (the entity should then be skipped).
        """
        device = self._existing_device(device_id)
        if device is None:
            return None
        return DeviceInfo(
            identifiers=device.identifiers,
            connections=device.connections,
        )

    def virtual_asset_parts(
        self, predicate: Callable[[dict[str, Any]], bool]
    ) -> list[tuple[dict[str, Any], dict[str, Any], DeviceInfo]]:
        """``(asset, part, device_info)`` for virtual-asset parts matching *predicate*.

        The shared source for the per-part stock entities (the stock ``number`` and the
        low-stock ``binary_sensor``). Limited to **owned** (virtual) appliances with a
        resolvable device — we don't add stock entities onto a foreign/guest device — so
        both platforms agree on which parts get entities. ``predicate`` selects the part
        kind (tracks-stock vs has-reorder).
        """
        out: list[tuple[dict[str, Any], dict[str, Any], DeviceInfo]] = []
        for asset in self.store.list_assets():
            if asset.get("kind") != ASSET_KIND_VIRTUAL:
                continue
            device_info = self.device_info_for_device_id(asset.get("device_id"))
            if device_info is None:
                continue
            for part in asset.get("parts", []) or []:
                if predicate(part):
                    out.append((asset, part, device_info))
        return out

    def device_info_for_task(self, task: dict[str, Any]) -> DeviceInfo:
        """Return the DeviceInfo a per-task entity should use.

        * If the task is attached to an existing device (``device_id``), reuse that
          device's own identifiers/connections so HA merges our entities onto the
          existing device page (the Battery-Notes-style attachment) rather than
          creating a new device.
        * Otherwise, create a self-owned device per task so its entities group
          together under the Home Keeper integration.
        """
        device_id = task.get("device_id")
        device = self._existing_device(device_id)
        if device is not None:
            return DeviceInfo(
                identifiers=device.identifiers,
                connections=device.connections,
            )
        if device_id:
            _LOGGER.warning(
                "Home Keeper task %s references unknown device_id %s; "
                "falling back to a self-owned device",
                task.get("id"),
                device_id,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, task["id"])},
            name=task["name"],
            manufacturer="Home Keeper",
            model="Maintenance task",
        )
