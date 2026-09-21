"""The Jinja render context Home Keeper hands every user-written template.

Two surfaces render user templates, and they must see the same names:

* a declarative companion's ``name_template`` / ``notes_template``, rendered per
  matched entity by :mod:`declarative_companion_sync`;
* a ``template``-mode sensor binding's trigger, rendered per evaluation pass by
  :mod:`sensor_watcher`.

The context lived in ``DeclarativeCompanionSync`` while only the first surface
existed. It moved here rather than growing a second copy, because
``declarative_companion_sync`` imports ``sensor_watcher`` (for
``async_mark_tasks_new``), so the watcher cannot import it back. A second copy is
worse than the import cycle it avoids: the two would drift, and a recipe's task name
would then read a different ``{{ state }}`` from the trigger that opened it.

HA-bound: it reads the entity, device and area registries. The pure side never calls
it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.template import Template
from homeassistant.util.hass_dict import HassKey

# Templates Home Keeper has already compiled, per config entry's Home Assistant.
#
# Home Assistant caches compiled template code on its shared environment, but
# ``TemplateEnvironment.template_cache`` is a **WeakValueDictionary**: the only strong
# reference to the compiled code is the ``Template`` object's own ``_compiled_code``.
# Build a fresh ``Template`` for each entity and the previous one is collected, the
# cache entry goes with it, and every render re-parses the Jinja source.
#
# That is 90x the cost of the render it precedes — ~500us to parse against ~6us to
# render — so a recipe at the 500-entity cap spent about a quarter of a second of
# event-loop time parsing one unchanged expression, on every pass. Holding the
# ``Template`` keeps Home Assistant's own cache warm and the parse happens once.
#
# Capped, because the recipe preview renders on every keystroke and each draft is a
# different source: without a bound, typing a template would grow this forever.
_TEMPLATE_CACHE: HassKey[dict[str, Template]] = HassKey("home_keeper_template_cache")
_TEMPLATE_CACHE_MAX = 64


def cached_template(hass: HomeAssistant, source: str) -> Template:
    """A ``Template`` for *source*, reused across entities and evaluation passes.

    Reuse is safe because rendering does not mutate the template: ``async_render``
    takes its variables per call, which is how Home Assistant drives its own
    config-defined templates. Callers must keep the render flags constant, though —
    ``Template`` asserts that ``limited`` and ``strict`` never change for one object.

    Kept on ``hass.data`` rather than in a module-level dict so the cache cannot
    outlive the Home Assistant it is bound to.
    """
    cache = hass.data.get(_TEMPLATE_CACHE)
    if cache is None:
        cache = hass.data[_TEMPLATE_CACHE] = {}
    template = cache.get(source)
    if template is None:
        if len(cache) >= _TEMPLATE_CACHE_MAX:
            # Plain FIFO rather than an LRU: the entries worth keeping are the handful
            # of saved recipes that render every pass, and they are re-added the next
            # time they render. The churn this bounds is a preview draft, which is
            # never rendered twice.
            cache.pop(next(iter(cache)))
        template = cache[source] = Template(source, hass)
    return template


def registry_projection(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """The registry fields :func:`template_variables` needs, for *entity_id*.

    Falls back to a projection carrying only the ``entity_id``. A managed task always
    names its entity, but the registry entry can already be gone (the entity was
    removed and the reconcile pass that drops the task has not run yet), and a
    template-mode task can be bound to an entity that has no registry entry at all.
    The templates that read ``{{ entity_id }}`` and the live state still render.
    """
    found = er.async_get(hass).async_get(entity_id)
    if found is None:
        return {"entity_id": entity_id}
    return {
        "entity_id": found.entity_id,
        "device_id": found.device_id,
        "area_id": found.area_id,
        "platform": found.platform,
        "name": found.name,
        "original_name": found.original_name,
    }


def template_variables(hass: HomeAssistant, entry: dict[str, Any]) -> dict[str, Any]:
    """Assemble the Jinja render context for one entity.

    *entry* is a registry projection — either the one a declarative companion's
    selection pass already built, or the one :func:`registry_projection` builds for a
    lone entity id. Only the keys listed below are read, so both shapes fit.

    The context flattens registry + state + device + area lookups so a template writer
    only ever sees ``{{ device_name }}`` — never ``{{ device.name_by_user or
    device.name }}``. Attribute access on the entity's state is exposed as
    ``attributes.<key>`` so a Firmware Update template can say
    ``{{ attributes.latest_version }}``.

    These names are a public contract: they appear in the panel's helper text, in the
    User Guide, and in every recipe a user has already saved. Add to them freely;
    never rename one.
    """
    entity_id = entry["entity_id"]
    state = hass.states.get(entity_id)
    friendly = None
    state_value: Any = None
    attributes: dict[str, Any] = {}
    if state is not None:
        state_value = state.state
        attributes = dict(state.attributes)
        friendly = attributes.get("friendly_name")
    friendly = friendly or entry.get("name") or entry.get("original_name") or entity_id
    device_name = None
    if entry.get("device_id"):
        device = dr.async_get(hass).async_get(entry["device_id"])
        if device:
            device_name = device.name_by_user or device.name
    area_name = None
    if entry.get("area_id"):
        area = ar.async_get(hass).async_get_area(entry["area_id"])
        if area:
            area_name = area.name
    return {
        "entity_id": entity_id,
        "friendly_name": friendly,
        "device_id": entry.get("device_id"),
        "device_name": device_name,
        "area_id": entry.get("area_id"),
        "area_name": area_name,
        "integration": entry.get("platform"),
        "state": state_value,
        "attributes": attributes,
    }
