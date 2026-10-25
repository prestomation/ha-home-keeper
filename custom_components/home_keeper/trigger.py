"""Home Keeper triggers for the automation editor.

Home Assistant's "Add trigger" dialog shows an integration's own triggers under
"By target", under "By type" and in its search. This platform gives 1 trigger for
each Home Keeper bus event that has a payload (``trigger: home_keeper.task_overdue``),
from :data:`api_surface.TRIGGERS`. A new bus event therefore gets a trigger with no
change here. ``triggers.yaml`` describes them for the editor, and
``tests/unit/test_triggers_yaml.py`` keeps it equal to the model.

A task, part or appliance trigger takes a target: entities, devices, areas, floors
or labels. The target is resolved when the event fires, so it follows a task that
moves to another device, and a removed device or task makes it match no event.
:mod:`trigger_targets` holds the rules. A companion, declarative companion or data
transfer trigger takes no target.

The trigger listens on the bus, so it does not depend on an entity and does not miss
an event while the config entry reloads. The trigger variables hold the bus event as
``trigger.event``, as a ``platform: event`` trigger and the device triggers do.
"""

from __future__ import annotations

from typing import Any, ClassVar

import voluptuous as vol
from homeassistant.const import CONF_OPTIONS, CONF_TARGET
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import target as target_helpers
from homeassistant.helpers.trigger import (
    Trigger,
    TriggerActionRunner,
    TriggerConfig,
)
from homeassistant.helpers.typing import ConfigType

from . import trigger_targets
from .api_surface import TRIGGERS, TriggerSpec
from .const import DOMAIN, SERVICE_DEVICE_IDENTIFIER
from .device_compat import find_devices

_TARGETED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Optional(CONF_OPTIONS, default={}): {},
    }
)
_UNTARGETED_SCHEMA = vol.Schema({vol.Optional(CONF_OPTIONS, default={}): {}})


def _service_device_id(hass: HomeAssistant) -> str | None:
    devices = find_devices(
        dr.async_get(hass), identifiers={(DOMAIN, SERVICE_DEVICE_IDENTIFIER)}
    )
    return devices[0].id if devices else None


@callback
def resolve_target(
    hass: HomeAssistant, target: ConfigType
) -> trigger_targets.TargetRefs:
    """The tasks, parts and appliances that *target* holds now."""
    selection = target_helpers.TargetSelection(target)
    selected = target_helpers.async_extract_referenced_entity_ids(
        hass, selection, expand_group=False
    )
    registry = er.async_get(hass)
    entities: list[tuple[str, str | None]] = []
    for entity_id in selected.referenced | selected.indirectly_referenced:
        entry = registry.async_get(entity_id)
        if entry is not None and entry.platform == DOMAIN:
            entities.append((entry.unique_id, entry.device_id))
    return trigger_targets.target_refs(
        entities,
        device_ids=selected.referenced_devices,
        area_ids=selected.referenced_areas,
        label_ids=selection.label_ids,
        service_device_id=_service_device_id(hass),
    )


class HomeKeeperTrigger(Trigger):
    """Fires on 1 Home Keeper bus event, filtered by the target."""

    spec: ClassVar[TriggerSpec]

    @classmethod
    async def async_validate_config(
        cls, hass: HomeAssistant, config: ConfigType
    ) -> ConfigType:
        """Require a target only where the payload names a task, part or appliance."""
        schema = _TARGETED_SCHEMA if cls.spec.targeted else _UNTARGETED_SCHEMA
        validated: ConfigType = schema(config)
        return validated

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        """Keep the target. It is resolved again for each event."""
        super().__init__(hass, config)
        self._target: ConfigType = dict(config.target or {})

    def wants(self, data: dict[str, Any]) -> bool:
        """True when the event with this payload is in the target."""
        if not self.spec.targeted:
            return True
        refs = resolve_target(self._hass, self._target)
        return trigger_targets.matches(self.spec.payload, data, refs)

    async def async_attach_runner(
        self, run_action: TriggerActionRunner, *args: Any, **kwargs: Any
    ) -> CALLBACK_TYPE:
        """Listen on the bus.

        Home Assistant 2026.10 also passes a ``did_not_trigger`` reporter, which
        2026.1 does not. This trigger does not use it.
        """

        @callback
        def _handle(event: Event) -> None:
            if self.wants(dict(event.data)):
                run_action(
                    {"event": event},
                    f"event '{event.event_type}'",
                    event.context,
                )

        return self._hass.bus.async_listen(self.spec.event, _handle)


def _trigger_class(spec: TriggerSpec) -> type[Trigger]:
    name = "".join(part.title() for part in spec.key.split("_")) + "Trigger"
    return type(name, (HomeKeeperTrigger,), {"spec": spec})


TRIGGER_CLASSES: dict[str, type[Trigger]] = {
    spec.key: _trigger_class(spec) for spec in TRIGGERS
}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return the Home Keeper triggers."""
    return TRIGGER_CLASSES
