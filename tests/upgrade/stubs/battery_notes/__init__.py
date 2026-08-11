"""Test-only stand-in for the real Battery Notes integration.

The real integration needs discovered hardware and a device library to do anything,
which an upgrade test can't provide. What the *glue* actually consumes from it is
narrow and easy to reproduce faithfully:

* a ``binary_sensor`` registered by the ``battery_notes`` platform,
* with ``device_class: battery`` (``BN_BATTERY_LOW_DEVICE_CLASS``),
* carrying ``battery_type`` / ``battery_quantity`` / ``battery_level`` attributes,
* attached to the device whose battery is low.

Those are exactly the predicates in the glue's ``wiring.py``, so the **real** glue
logic runs unmodified against this stub. The domain must literally be
``battery_notes`` because the glue filters on ``entity.platform``.

Crucially this stub also reproduces the behaviour that #183 is about: it attaches its
entity to the **source device** by copying that device's identifiers into its own
``DeviceInfo``. Before HA 2026.8 that merged onto the source device; from 2026.8 it
forks a second device. That split is the thing the upgrade suite exists to observe,
so the stub must keep doing it — do not "fix" it to use ``device_entry`` linking.

**Fidelity scope — read this before drawing conclusions from the suite.** The
identifier copy models Battery Notes *as it was before 2026.8*, which is the correct
thing for phase 1: it is the world users are upgrading from, and the merged device it
produces is what Home Assistant then splits. Battery Notes itself confirms this was
its old shape — its own `common.py` notes that on older versions "devices sharing an
identifier or connection were merged into a single device".

It is **not** a model of current Battery Notes, which has already migrated: 3.0.0-dev
links via ``async_entity_id_to_device_id`` and no longer copies identifiers at all.
So results here support claims about *upgrading from a pre-2026.8 install* — which is
what #183 reports — and must not be read as claims about how Battery Notes behaves
today. Worth noting for the model decision in
``docs/DEVICE_REGISTRY_2026_8_PLAN.md``: upstream has moved to entity-level linking,
and Home Keeper has not.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "battery_notes"

PLATFORMS = ["binary_sensor"]

#: The source device this stub attaches its battery sensor to. Matches the
#: ``hk_upgrade_source`` stub's kitchen sensor.
SOURCE_IDENTIFIER = ("hk_upgrade_source", "kitchen_sensor")
SOURCE_NAME = "Kitchen Sensor"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
