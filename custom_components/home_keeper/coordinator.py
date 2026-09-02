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
from .device_compat import resolve_device
from .options import current_options
from .reconcile import buy_source
from .store import HomeKeeperStore

if TYPE_CHECKING:
    from .problem_sync import ProblemSensorSync
    from .sensor_watcher import SensorTaskWatcher
    from .shopping_sync import ShoppingListSync
    from .todo_list_sync import TodoListSync

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)

# hass.data namespace holding the transition edge-state map per config entry, so it
# survives a config-entry *reload* (add/delete task, options save) even though the
# coordinator object is recreated. A genuine HA *restart* starts with an empty
# hass.data, which is how we still baseline silently on restart (no overdue storm).
_EDGE_STATE_STORE = f"{DOMAIN}_edge_state"


def _edge_state_store(hass: HomeAssistant) -> dict[str, transitions.StateMap]:
    """The process-lifetime edge-state map keyed by config-entry id."""
    return hass.data.setdefault(_EDGE_STATE_STORE, {})


def discard_edge_state(hass: HomeAssistant, entry_id: str) -> None:
    """Drop an entry's persisted edge state (called when the entry is removed)."""
    _edge_state_store(hass).pop(entry_id, None)


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


def task_has_entities(task: dict[str, Any] | None) -> bool:
    """True when a task owns per-task entities (button/sensor/binary_sensor).

    Those exist only for an enabled, device-attached task. Adding or deleting a task
    that owns none needs no entry reload — a plain coordinator refresh suffices, which
    avoids flapping every entity unavailable when e.g. a companion seeds many
    device-less tasks.

    NOTE: ``store._task_owns_entities`` inlines this same rule (to avoid a
    store→coordinator import cycle). Keep the two in sync if the rule ever changes.
    """
    return bool(task and task.get("device_id") and task.get("enabled", True))


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
            # Pass the entry explicitly — HA deprecated inferring it from a ContextVar
            # (removal 2025.11). The base stores it as ``self.config_entry``; ``entry``
            # is a read-only alias so existing call sites don't churn.
            config_entry=entry,
        )
        self.store = store
        # The problem-sensor sync helper, attached during async_setup_entry.
        self.problem_sync: ProblemSensorSync | None = None
        # The declarative-companion reconciler, attached during async_setup_entry.
        # Kept as an ``Any`` on the coordinator to avoid a coordinator↔sync
        # import cycle at type-check time (the sync imports the coordinator's type).
        self.declarative_sync: Any | None = None
        # The sensor-based-task watcher, attached during async_setup_entry (after its
        # edge state / usage baselines are seeded, so the periodic tick below only ever
        # reacts to genuine transitions).
        self.sensor_watcher: SensorTaskWatcher | None = None
        # The shopping-list mirror, attached during async_setup_entry.
        self.shopping_sync: ShoppingListSync | None = None
        # The to-do list syncs (profile-filtered tasks on external to-do lists),
        # attached during async_setup_entry.
        self.todo_list_sync: TodoListSync | None = None
        # Edge state for the time-based task events (overdue / due-soon). Carried
        # across refreshes so each is fired at most once per ``next_due``; see
        # transitions.detect_transitions. Seeded from the process-lifetime store so it
        # survives a config-entry reload — otherwise a reload (triggered by any
        # add/delete task or options save) would recreate the coordinator with an
        # empty map and silently baseline any transition that happened since the last
        # refresh, losing the overdue/due-soon event forever.
        prior = _edge_state_store(hass).get(entry.entry_id)
        self._had_prior_edge_state = prior is not None
        self._edge_state: transitions.StateMap = dict(prior) if prior else {}
        # Firing is gated until setup finishes (enable_transition_events) so the
        # several refreshes during async_setup_entry silently *baseline* current state
        # — an HA restart never replays an "overdue" storm for tasks already overdue.
        self._events_enabled = False
        # Guards against piling up entry reloads when several buy-task syncs land close
        # together (mirrors ProblemSensorSync._reload_scheduled).
        self._buy_reload_scheduled = False

    @property
    def entry(self) -> ConfigEntry:
        """The config entry (alias for the base coordinator's ``config_entry``)."""
        entry = self.config_entry
        assert entry is not None  # always set: we pass config_entry= in __init__
        return entry

    def enable_transition_events(self) -> None:
        """Start firing overdue/due-soon events (called once setup is complete).

        Until this is called, refreshes still update the edge state but fire nothing,
        so the post-restart steady state is baselined silently and only genuine
        transitions observed while running are announced.
        """
        self._events_enabled = True

    def _persist_edge_state(self) -> None:
        """Save the edge state to the process-lifetime store so it survives a reload."""
        _edge_state_store(self.hass)[self.entry.entry_id] = self._edge_state

    async def async_settle_buy_tasks(self) -> None:
        """Reconcile auto-buy tasks after a stock/completion change, then settle state.

        The single decision point for the buy-task lifecycle at the HA boundary: any
        surface that can change a part's low/enabled state (stock adjust, task
        completion) calls this instead of a bare refresh. If a buy task that owns
        per-task device entities was created or removed, a full entry reload is needed
        to (un)register those entities — deferred via ``async_create_task`` so it never
        tears down the calling entity/handler mid-call, and guarded so several changes
        at once don't stack reloads. Otherwise a plain refresh suffices.

        The shopping-list mirror runs on **both** sides of the reconcile, and both
        before the reload is scheduled. Before, because a reminder that was just
        completed still exists for exactly this moment — the mirror can tick its
        shopping-list line off, instead of watching the reconcile delete the
        reminder and then having to guess why the line is stale. After, for
        whatever the reconcile created or retired. Neither pass reads a to-do list
        unless something actually drifted, so a settle that changes nothing is
        free.
        """
        if self.shopping_sync is not None:
            await self.shopping_sync.async_sync()
        entity_set_changed = await self.store.reconcile_buy_tasks()
        if self.shopping_sync is not None:
            await self.shopping_sync.async_sync()
        if entity_set_changed:
            if not self._buy_reload_scheduled:
                self._buy_reload_scheduled = True
                self.hass.async_create_task(self._async_reload_for_buy_tasks())
        else:
            await self.async_request_refresh()

    async def _async_reload_for_buy_tasks(self) -> None:
        try:
            await self.hass.config_entries.async_reload(self.entry.entry_id)
        finally:
            self._buy_reload_scheduled = False

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        await self._purge_expired_one_offs()
        # Re-evaluate sensor-based tasks against their bound readings before reading the
        # task map, so a freshly-armed task surfaces as overdue/due-soon in this same
        # cycle. No refresh request here — the transition detection below runs next.
        if self.sensor_watcher is not None:
            await self.sensor_watcher.async_evaluate(refresh=False)
        tasks = self.store.get_tasks()
        fired, next_state = transitions.detect_transitions(
            self._edge_state, tasks, now=dt_util.now()
        )
        if self._events_enabled:
            self._edge_state = next_state
            self._persist_edge_state()
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
        elif not self._had_prior_edge_state:
            # Fresh start (HA restart / first setup): adopt the detected state as the
            # silent baseline so a task already overdue at startup doesn't replay.
            self._edge_state = next_state
            self._persist_edge_state()
        # else: this is a config-entry *reload* still inside setup (events not yet
        # enabled). Preserve the prior edge state instead of baselining over it, so a
        # transition that occurred during the reload fires on the first refresh after
        # enable_transition_events rather than being silently swallowed.
        # Re-detect companions on the same cadence so a popular upstream installed at
        # runtime (e.g. Battery Notes) surfaces a suggestion, and an
        # installed/removed glue updates — edge-triggered + silently baselined inside
        # the registry (a no-op until it's live).
        companions.async_reconcile(self.hass)
        # Sweep the mirrored shopping list on the same cadence. The list's state is
        # only its outstanding-item count, so one item ticked off while another is
        # added produces no state change for the listener to catch; this is the
        # backstop. A no-op until something is actually mirrored.
        if self.shopping_sync is not None:
            self.shopping_sync.async_schedule_sweep()
        # And sweep the to-do list syncs on the same cadence, for the same blind
        # spot — plus one of their own: a task *falling due* mutates nothing, so no
        # task event fires for it and only this periodic tick notices that a chore
        # now belongs on a synced list. A no-op until a sync is configured or
        # something has been put on a list.
        if self.todo_list_sync is not None:
            self.todo_list_sync.async_schedule_sweep()
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
            task
            for task in self.store.get_tasks().values()
            # Skip auto-buy reminders: they're one-offs but reconciler-owned, so purging
            # a completed-but-still-low one would just respawn it (and delete_task would
            # reject it anyway). The reconciler removes them when the part restocks.
            if buy_source(task) is None
            and recurrence.one_off_expired(task, retention, now=now)
        ]
        reload_needed = False
        for task in expired:
            tid = task["id"]
            try:
                await self.store.delete_task(tid)
            except models.TaskValidationError as err:  # pragma: no cover - defensive
                _LOGGER.debug("Skipping auto-delete of one-off %s: %s", tid, err)
                continue
            # store.delete_task only mutates the store; the entity registry is cleaned
            # by reloading the config entry (as the service delete path does). Track
            # whether any purged task owned per-task entities so we reload once.
            if task_has_entities(task):
                reload_needed = True
        if reload_needed:
            # Reload to remove the now-orphaned per-task entities. This runs inside
            # _async_update_data (the coordinator's own refresh), so awaiting the
            # reload inline would tear down and recreate this coordinator mid-refresh.
            # Defer it so the current refresh completes first. The purged task's
            # entities therefore linger (as unavailable) until this reload lands on
            # the loop — a brief, harmless window on the next refresh tick.
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.entry.entry_id)
            )

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
        return resolve_device(dr.async_get(self.hass), device_id)

    def task_uses_existing_device(self, task: dict[str, Any]) -> bool:
        """True when the task's per-task entities merge onto an existing device.

        In that case several tasks can share one device page, so each entity's
        name is prefixed with the task name to disambiguate. Self-owned task
        devices (no ``device_id`` or an unknown one) need no prefix because the
        device itself is already named after the task.
        """
        return self._existing_device(task.get("device_id")) is not None

    def device_entry_for_device_id(
        self, device_id: str | None
    ) -> dr.DeviceEntry | None:
        """The registry device an entity should be linked to, or ``None`` to skip it.

        Entities attach to a device they don't own by setting ``entity.device_entry``
        (with no ``device_info``) — see :meth:`device_link_for_task` for why copying
        identifiers no longer works.
        """
        return self._existing_device(device_id)

    def virtual_asset_parts(
        self, predicate: Callable[[dict[str, Any]], bool]
    ) -> list[tuple[dict[str, Any], dict[str, Any], dr.DeviceEntry]]:
        """``(asset, part, device_entry)`` for virtual-asset parts matching *predicate*.

        The shared source for the per-part stock entities (the stock ``number`` and the
        low-stock ``binary_sensor``). Limited to **owned** (virtual) appliances with a
        resolvable device — we don't add stock entities onto a foreign/guest device — so
        both platforms agree on which parts get entities. ``predicate`` selects the part
        kind (tracks-stock vs has-reorder).
        """
        out: list[tuple[dict[str, Any], dict[str, Any], dr.DeviceEntry]] = []
        for asset in self.store.list_assets():
            if asset.get("kind") != ASSET_KIND_VIRTUAL:
                continue
            device = self.device_entry_for_device_id(asset.get("device_id"))
            if device is None:
                continue
            for part in asset.get("parts", []) or []:
                if predicate(part):
                    out.append((asset, part, device))
        return out

    def device_link_for_task(
        self, task: dict[str, Any]
    ) -> tuple[DeviceInfo | None, dr.DeviceEntry | None]:
        """``(device_info, device_entry)`` for a per-task entity — set both verbatim.

        Exactly one is ever non-``None``:

        * **Attached to a device that resolves** → ``(None, device)``. The entity is
          linked by assigning ``entity.device_entry``, which puts it on that device's
          page without claiming the device.
        * **Otherwise** → ``(DeviceInfo(...), None)``, a self-owned device named after
          the task, so its entities still group under Home Keeper.

        This used to copy the target device's ``identifiers``/``connections`` into a
        ``DeviceInfo``, which is how Home Assistant merged entities onto a device
        another integration owned. **HA 2026.8 made identifiers unique per config
        entry**, so that copy stopped merging and instead forked a duplicate device —
        one owned by us, carrying no ``name``, which is why affected users saw a raw
        GUID where a device name belonged (#183). Entity-level linking is the
        supported replacement; ``async_device_info_to_link_from_device_id`` is
        deprecated upstream and now returns ``None``.

        The trade-off, recorded here because it is invisible from the code: our config
        entry is no longer attached to that device, and Home Assistant sources device
        triggers and per-device diagnostics from ``device.config_entries``. So
        ``device_trigger.py`` and ``async_get_device_diagnostics`` are no longer
        offered on a device we merely link to. Tasks on Home Keeper's own appliance
        devices keep both. See ``docs/DEVICE_REGISTRY_2026_8_PLAN.md``.
        """
        device_id = task.get("device_id")
        device = self._existing_device(device_id)
        if device is not None:
            return None, device
        if device_id:
            _LOGGER.warning(
                "Home Keeper task %s references unknown device_id %s; "
                "falling back to a self-owned device",
                task.get("id"),
                device_id,
            )
        return (
            DeviceInfo(
                identifiers={(DOMAIN, task["id"])},
                name=task["name"],
                manufacturer="Home Keeper",
                model="Maintenance task",
            ),
            None,
        )


def find_coordinator(hass: HomeAssistant) -> HomeKeeperCoordinator | None:
    """The loaded Home Keeper coordinator, or None while no entry is loaded.

    The coordinator hangs off the config entry's ``runtime_data``, so everything
    outside the entry's own setup — websocket commands, services, device triggers,
    the document views — starts by finding it here. Returning None rather than
    raising is deliberate: an entry is momentarily unloaded during every reload, and
    each caller has its own way of saying so.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, HomeKeeperCoordinator):
            return coord
    return None
