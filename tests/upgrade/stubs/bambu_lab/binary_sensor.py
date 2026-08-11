"""The firmware-update entity the Home Keeper glue watches.

Bambu Lab exposes firmware as a ``binary_sensor`` with ``device_class: update`` when
its "Firmware update" option is off, which is the default — so that is the shape
reproduced here. Starts ``on`` (update available) so the glue creates its firmware
task during phase 1.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DEVICE_IDENTIFIER, DEVICE_NAME, SERIAL


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([StubFirmwareUpdate()])


class StubFirmwareUpdate(BinarySensorEntity):
    """Firmware update available for the printer."""

    _attr_has_entity_name = True
    _attr_name = "Firmware update"
    # The `_firmware_update` suffix is load-bearing: the glue matches on it and
    # strips it to recover the serial.
    _attr_unique_id = f"{SERIAL}_firmware_update"
    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_is_on = True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={DEVICE_IDENTIFIER}, name=DEVICE_NAME)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"installed_version": "01.08.00.00", "latest_version": "01.09.00.00"}
