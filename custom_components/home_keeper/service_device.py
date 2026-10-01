"""The Home Keeper service device.

This module is small on purpose. The to-do list, the calendar and the count
sensors put their entities on this device, and a platform that imports
``devices`` also imports the store and the sensor watcher.
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PANEL_URL_PATH, SERVICE_DEVICE_IDENTIFIER


def service_device_info() -> dr.DeviceInfo:
    """The integration-level device the aggregate task-count sensors live on.

    Those sensors count across tasks, so they belong to no one task and no appliance.
    A ``SERVICE`` device gives them a home under **Settings, Devices and services,
    Home Keeper** without pretending to be hardware.

    Home Assistant creates the device from an entity's ``device_info`` when the
    platform adds it, so nothing here calls ``async_get_or_create``: Home Assistant
    owns the config-entry link and removes the device with the integration, and the
    device can never exist with no entities on it. ``async_prune_orphaned_devices``
    relies on that second property, since this device is not an asset device and is
    therefore *not* skipped by the prune.
    """
    return dr.DeviceInfo(
        identifiers={(DOMAIN, SERVICE_DEVICE_IDENTIFIER)},
        name="Home Keeper",
        manufacturer="Home Keeper",
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=f"homeassistant://{PANEL_URL_PATH}",
    )
