"""Test-only stand-in for the Bambu Lab integration.

The real integration needs an actual printer (LAN credentials or the vendor cloud),
so the upgrade suite substitutes this. As with the ``battery_notes`` stub, the
contract the **real** glue consumes is narrow and reproduced exactly — see
``home_keeper_bambu_lab``'s ``wiring.is_firmware_entity``:

* platform ``bambu_lab`` (hence this domain name — the glue filters on it),
* an ``update`` entity or a ``binary_sensor`` with ``device_class: update``,
* ``unique_id`` ending ``_firmware_update``,

plus the optional cumulative usage-hours sensor keyed ``{serial}_total_usage_hours``.

Unlike Battery Notes, the real Bambu Lab integration **owns** its printer device
rather than merging onto someone else's, so this stub does the same. That makes it
the interesting counter-case: the printer device itself survives the 2026.8 split
intact, and any Home Keeper breakage comes from Home Keeper's own attachment, not
from the device being renumbered.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

DOMAIN = "bambu_lab"

PLATFORMS = ["binary_sensor", "sensor"]

#: The glue derives the printer serial from the firmware entity's unique_id by
#: stripping ``_firmware_update``, and keys its maintenance options on that serial.
SERIAL = "AC12309BH109"
DEVICE_IDENTIFIER = (DOMAIN, SERIAL)
DEVICE_NAME = "X1 Carbon"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={DEVICE_IDENTIFIER},
        name=DEVICE_NAME,
        manufacturer="Bambu Lab",
        # The glue feeds device.model to its catalog as the detected printer family.
        model="X1C",
        serial_number=SERIAL,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
