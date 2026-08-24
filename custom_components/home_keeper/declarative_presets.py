"""Shipped declarative-companion presets.

A **preset** is a partial declarative-companion spec plus a bit of catalog
metadata (name/description i18n keys, icon, ``requires_integration`` gate). The
panel lists them under Settings → Companions → Declarative → *Add from preset*;
picking one seeds the Add dialog with the preset's ``default_spec``, the user
reviews, then Save persists a full spec (which the reconciler then materializes
into managed sensor tasks).

Three presets ship in v1:

* ``device_pulse`` — targets the standalone Device Pulse integration
  (studiobts/home-assistant-device-pulse) and watches its per-device
  ``sensor.*_total_failed_pings`` sensors via the existing ``threshold`` mode.
  Requires the Device Pulse integration to be installed.
* ``low_battery`` — watches every ``binary_sensor`` with device_class ``battery``
  reporting ``on`` (the HA-standard low-battery indicator). Works without a
  companion integration; coexists with the Battery Notes glue (users may end up
  with two tasks per battery if they run both, documented in the README).
* ``firmware_update_available`` — watches every ``update.*`` entity reporting
  ``on`` (HA's built-in firmware/software-update surface). Covers UniFi, ESPHome,
  HACS, Reolink, Bambu Lab firmware updates in one recipe.

None of the shipped presets use the ``availability`` sensor mode — that mode is
added in this PR as a general capability for user-authored companions ("watch my
MQTT devices go offline"), not as a preset the panel installs. See
``declarative_companions.py`` for spec shape and ``docs/EVENTS.md`` /
``docs/INTEGRATING.md`` for the surface.

Pure — no HA imports (the panel resolves ``name_key`` / ``description_key``
through ``backend_i18n.resolve_string`` at request time).
"""

from __future__ import annotations

from typing import Any, TypedDict


class PresetDefinition(TypedDict):
    """One shipped declarative-companion preset.

    ``requires_integration`` names the HA integration domain the panel should
    check for before enabling the preset card — ``None`` for presets that work
    without a specific upstream (Low Battery, Firmware Update). The panel greys
    out cards whose requirement isn't installed and shows a "Requires
    <integration>" tooltip.
    """

    id: str
    name_key: str
    description_key: str
    icon: str
    requires_integration: str | None
    default_spec: dict[str, Any]


CATALOG_PRESETS: list[PresetDefinition] = [
    {
        "id": "device_pulse",
        "name_key": "declarative_preset.device_pulse.name",
        "description_key": "declarative_preset.device_pulse.description",
        "icon": "mdi:heart-pulse",
        "requires_integration": "device_pulse",
        "default_spec": {
            "name": "Device Pulse",
            "description": "",
            "enabled": True,
            "preset_id": "device_pulse",
            "selection": {
                "target_integration": "device_pulse",
                "domain": "sensor",
                "entity_regex": r".*_total_failed_pings$",
                "area_ids": [],
                "label_ids": [],
                "exclude_entity_ids": [],
                "exclude_device_ids": [],
                "exclude_area_ids": [],
                "exclude_label_ids": [],
            },
            "trigger": {
                "mode": "threshold",
                "comparison": ">",
                "value": 0,
                "for_seconds": 3600,
                "clear_on_recover": True,
            },
            "task_template": {
                "name_template": "Check on {{ device_name or friendly_name }}",
                "notes_template": (
                    "Device Pulse reports {{ state }} failed pings "
                    "for {{ friendly_name }}."
                ),
                "labels": [],
            },
            "per_entity_overrides": {},
        },
    },
    {
        "id": "low_battery",
        "name_key": "declarative_preset.low_battery.name",
        "description_key": "declarative_preset.low_battery.description",
        "icon": "mdi:battery-alert",
        "requires_integration": None,
        "default_spec": {
            "name": "Low battery",
            "description": "",
            "enabled": True,
            "preset_id": "low_battery",
            "selection": {
                "domain": "binary_sensor",
                "device_class": "battery",
                "area_ids": [],
                "label_ids": [],
                "exclude_entity_ids": [],
                "exclude_device_ids": [],
                "exclude_area_ids": [],
                "exclude_label_ids": [],
            },
            "trigger": {
                "mode": "state",
                "state": "on",
                "clear_on_recover": True,
            },
            "task_template": {
                "name_template": "Replace {{ device_name or friendly_name }} battery",
                "notes_template": "",
                "labels": [],
            },
            "per_entity_overrides": {},
        },
    },
    {
        "id": "firmware_update_available",
        "name_key": "declarative_preset.firmware_update_available.name",
        "description_key": (
            "declarative_preset.firmware_update_available.description"
        ),
        "icon": "mdi:update",
        "requires_integration": None,
        "default_spec": {
            "name": "Firmware update available",
            "description": "",
            "enabled": True,
            "preset_id": "firmware_update_available",
            "selection": {
                "domain": "update",
                "area_ids": [],
                "label_ids": [],
                "exclude_entity_ids": [],
                "exclude_device_ids": [],
                "exclude_area_ids": [],
                "exclude_label_ids": [],
            },
            "trigger": {
                "mode": "state",
                "state": "on",
                "clear_on_recover": True,
            },
            "task_template": {
                "name_template": "Update {{ friendly_name }}",
                "notes_template": (
                    "Latest version: "
                    "{{ attributes.latest_version or 'unknown' }}"
                ),
                "labels": [],
            },
            "per_entity_overrides": {},
        },
    },
]


def preset_by_id(preset_id: str) -> PresetDefinition | None:
    """Return the shipped preset with *preset_id*, or ``None`` if unknown.

    Used by the panel WS endpoint to hand a preset's default spec back to the
    frontend when the user picks a preset card; also used by the store to check
    an incoming spec's ``preset_id`` against the catalog for badge rendering.
    """
    for preset in CATALOG_PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None
