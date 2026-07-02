"""The Home Keeper integration.

Tracks home maintenance and chores. Administration happens in a dedicated sidebar
panel; usage (viewing/completing tasks) is surfaced through native HA entities
(todo, calendar) and per-task device-page entities (button/sensor/binary_sensor).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.start import async_at_started

from . import (
    card,
    companions,
    devices,
    manuals,
    notifier,
    options,
    panel,
    services,
    websocket_api,
)
from .const import DOMAIN, PLATFORMS
from .coordinator import HomeKeeperCoordinator, discard_edge_state
from .problem_sync import ProblemSensorSync
from .sensor_watcher import SensorTaskWatcher
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (config-entry only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Home Keeper from a config entry."""
    store = HomeKeeperStore(hass)
    await store.load()

    coordinator = HomeKeeperCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Provision/reconcile virtual asset devices and the tasks derived from wear
    # parts BEFORE forwarding platforms so the registry devices and per-task
    # entities exist when the platforms set up. The same applies to the tasks
    # mirroring ``device_class: problem`` binary sensors (when syncing is enabled).
    await devices.async_reconcile_assets(hass, entry, store)
    await store.reconcile_part_tasks()
    problem_sync = ProblemSensorSync(hass, entry, coordinator)
    await problem_sync.async_initial_reconcile()
    coordinator.problem_sync = problem_sync
    await coordinator.async_request_refresh()

    await panel.async_register_panel(hass)
    await card.async_register_card(hass)
    manuals.async_register_http(hass)
    websocket_api.async_register(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Platforms have removed entities for deleted/excluded tasks; drop Home Keeper
    # from any device that no longer carries one of our entities so disabling Problem
    # Sensor Sync (or an exclusion) leaves no empty device card behind.
    await devices.async_prune_orphaned_devices(hass, entry)

    services.async_register_services(hass)
    # Now that the register_companion service exists, ask companions to (re-)announce
    # themselves and run a catalog-detection pass. Companions that set up before Home
    # Keeper listen for this ping; those that set up after register at their own setup.
    companions.async_request_registration(hass)
    # React to options-flow changes (e.g. toggling problem-sensor syncing) by
    # reloading the entry, which re-runs this setup with the new options.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Relocalize reconciler-generated task names when the HA language changes. The
    # generated wear-part name is baked into storage in the configured language at
    # write time (see store.reconcile_part_tasks); reloading the entry re-runs setup,
    # which reconciles with the new language and recreates the per-task entities under
    # their new names. Captured at setup, so the reload re-baselines to the new value.
    setup_language = hass.config.language

    async def _relocalize_on_language_change(event: Event) -> None:
        if hass.config.language == setup_language:
            return  # some other core-config change (unit system, name, …) — ignore
        _LOGGER.debug(
            "HA language changed %s -> %s; reloading Home Keeper to relocalize "
            "generated task names",
            setup_language,
            hass.config.language,
        )
        await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _relocalize_on_language_change)
    )
    # Now that platforms are up, start the live problem-sensor listeners (these may
    # reload the entry when a synced task is created/removed, so they run last).
    problem_sync.async_start_listeners()
    # Sensor-based tasks: baseline the watcher's edge state / usage meters BEFORE
    # attaching it to the coordinator, so the first evaluation only reacts to genuine
    # transitions (an already-over-threshold sensor at boot does not arm). Then start
    # its live state listeners.
    sensor_watcher = SensorTaskWatcher(hass, entry, coordinator)
    await sensor_watcher.async_baseline()
    coordinator.sensor_watcher = sensor_watcher
    sensor_watcher.async_start_listeners()
    # Listen for actionable-notification taps (mobile_app_notification_action) so a
    # Mark done / Snooze / Skip button routes back into the store and advances a walk.
    entry.async_on_unload(notifier.async_setup_notifications(hass, entry, coordinator))
    # Setup is complete: the refreshes above have baselined current overdue/due-soon
    # state silently, so start firing those events only for transitions from here on.
    coordinator.enable_transition_events()
    # One evaluation pass now that everything is wired: arms any usage task whose meter
    # is already past target (e.g. it advanced while HA was down) and fires the genuine
    # overdue/due-soon events for it.
    await coordinator.async_request_refresh()
    # Flip the companion registry live only once HA has fully started, so companions
    # that self-register during startup (and catalog upstreams already installed) are
    # baselined silently — an HA restart never replays a companion_connected storm.
    entry.async_on_unload(async_at_started(hass, _async_companions_go_live))
    return True


@callback
def _async_companions_go_live(hass: HomeAssistant) -> None:
    """Baseline current companions silently, then start firing discovery events."""
    registry = companions.async_get_registry(hass)
    registry.reconcile()  # capture whatever registered during startup (still silent)
    registry.set_live()


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change.

    The options *flow* updates the entry directly, so this listener performs the
    reload. The service / panel path goes through ``options.async_set_options``,
    which awaits its own reload so the caller observes the reconciled task set — it
    flags the entry while doing so, so we don't fire a second, overlapping reload.
    """
    if options.caller_is_reloading(entry.entry_id):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Only tear down the panel/services when the last entry goes away. Gate on
    # *loaded* entries, not ``async_entries``: HA removes the entry from the registry
    # only *after* this unload returns (and a disabled entry stays registered), so
    # ``async_entries(DOMAIN)`` is never empty here and the teardown was dead code —
    # leaving the panel pointing at a dead backend and all services registered until
    # restart. ``async_loaded_entries`` excludes the entry currently unloading.
    if unloaded and not hass.config_entries.async_loaded_entries(DOMAIN):
        panel.async_unregister_panel(hass)
        services.async_unregister_services(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove all Home Keeper data when the integration is deleted.

    Virtual asset devices (and per-task self-owned devices) are tied to this config
    entry, so Home Assistant removes them automatically. Here we additionally drop
    our stored tasks/assets document and the uploaded-documents blob tree so no
    residue is left behind.
    """
    discard_edge_state(hass, entry.entry_id)
    store = HomeKeeperStore(hass)
    await store.async_remove()
    await manuals.async_delete_all_documents(hass)
