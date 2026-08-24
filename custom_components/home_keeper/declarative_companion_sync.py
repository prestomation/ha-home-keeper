"""Home-Assistant-aware orchestration for declarative companions.

Builds a plain-dict projection of the entity registry, feeds it to the pure
selection pass in :mod:`declarative_companions`, renders each match's Jinja
name/notes templates against live entity state, and drives the store reconciler
that materializes managed sensor tasks. Live state watching on the materialized
tasks is delegated to :class:`SensorTaskWatcher` — this module never touches
state events; it re-reconciles on registry-shaped changes (adds/renames/removes,
device/area edits) and on the store's own spec-changed dispatcher signal.

Mirrors the shape of ``problem_sync.ProblemSensorSync``: single initial pass on
setup, listeners registered via ``entry.async_on_unload`` so teardown is
automatic, entity-set changes trigger a debounced entry reload (needed because
each managed task owns per-task device-page entities).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.template import Template, TemplateError

from . import declarative_companions
from .const import (
    DOMAIN,
    SIGNAL_DECLARATIVE_SPECS_CHANGED,
)

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)


class DeclarativeCompanionSync:
    """Materializes managed sensor tasks for every declarative-companion spec."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: HomeKeeperCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._unsub_registry: CALLBACK_TYPE | None = None
        self._unsub_device_registry: CALLBACK_TYPE | None = None
        self._unsub_area_registry: CALLBACK_TYPE | None = None
        self._unsub_specs: CALLBACK_TYPE | None = None
        self._reload_scheduled = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_initial_reconcile(self) -> None:
        """Reconcile every spec once during setup (before platforms forward).

        Runs before the coordinator publishes its first refresh so entities for
        newly-materialized tasks are registered by the time platforms fetch the
        task list. Never reloads — the entry is still setting up.
        """
        await self._reconcile_all()

    @callback
    def async_start_listeners(self) -> None:
        """Begin reacting to registry updates and spec-change signals.

        Registered via ``entry.async_on_unload`` so teardown is automatic on
        unload/reload — no explicit stop needed.
        """
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_event
            )
        )
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED,
                self._handle_registry_event,
            )
        )
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                ar.EVENT_AREA_REGISTRY_UPDATED, self._handle_registry_event
            )
        )
        self._unsub_specs = async_dispatcher_connect(
            self._hass,
            SIGNAL_DECLARATIVE_SPECS_CHANGED,
            self._handle_specs_changed,
        )
        self._entry.async_on_unload(self._unsub_specs)

    # ── snapshot builders ────────────────────────────────────────────────────
    def _registry_snapshot(self) -> dict[str, Any]:
        """Project the entity registry into the plain-dict shape ``expand_spec`` reads.

        Everything the pure selection pass needs sits in this snapshot; no
        further HA access is made inside :func:`declarative_companions.expand_spec`.
        Labels come from the entity registry entry's own set (device labels are
        NOT unioned — a device-level filter would reach into per-device labels,
        which the current filter shape doesn't expose).
        """
        ent_reg = er.async_get(self._hass)
        entries: list[dict[str, Any]] = []
        for entry in ent_reg.entities.values():
            entries.append(
                {
                    "entity_registry_id": entry.id,
                    "entity_id": entry.entity_id,
                    "platform": entry.platform,
                    "domain": entry.domain,
                    "device_class": entry.device_class,
                    "original_device_class": entry.original_device_class,
                    "device_id": entry.device_id,
                    "area_id": entry.area_id,
                    "labels": set(entry.labels or []),
                    "disabled": bool(entry.disabled),
                    "name": entry.name,
                    "original_name": entry.original_name,
                }
            )
        return {"entities": entries}

    # ── rendering ────────────────────────────────────────────────────────────
    def _template_variables(
        self, entry: dict[str, Any]
    ) -> dict[str, Any]:
        """Assemble the Jinja render context for a single matched entity.

        The context flattens registry + state + device + area lookups so a
        template writer only ever sees ``{{ device_name }}`` — never
        ``{{ device.name_by_user or device.name }}``. Attribute access on the
        entity's state is exposed as ``attributes.<key>`` so a Firmware Update
        template can say ``{{ attributes.latest_version }}``.
        """
        entity_id = entry["entity_id"]
        state = self._hass.states.get(entity_id)
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
            dev_reg = dr.async_get(self._hass)
            device = dev_reg.async_get(entry["device_id"])
            if device:
                device_name = device.name_by_user or device.name
        area_name = None
        if entry.get("area_id"):
            area_reg = ar.async_get(self._hass)
            area = area_reg.async_get_area(entry["area_id"])
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

    def _render_one(self, source: str, variables: dict[str, Any]) -> str:
        """Render one Jinja template, returning the source on any error.

        A broken template on one entity must not poison the whole reconcile pass
        — log the error, fall back to the raw source. The preview surface (see
        the WS ``preview_declarative_companion`` command) reports the template
        error explicitly so the user can fix it before saving.
        """
        if not source:
            return ""
        try:
            template = Template(source, self._hass)
            return str(template.async_render(variables, parse_result=False))
        except TemplateError as err:
            _LOGGER.warning(
                "Declarative-companion template render failed for %s: %s",
                variables.get("entity_id"),
                err,
            )
            return source

    def _render_match(
        self, spec: dict[str, Any], match: dict[str, Any]
    ) -> tuple[str, str]:
        """Return ``(rendered_name, rendered_notes)`` for one match."""
        variables = self._template_variables(match["entity"])
        template = spec.get("task_template") or {}
        name = self._render_one(template.get("name_template", ""), variables)
        notes = self._render_one(template.get("notes_template", ""), variables)
        return name, notes

    # ── reconcile ────────────────────────────────────────────────────────────
    async def _reconcile_all(self) -> bool:
        """Re-materialize every enabled spec against the current registry.

        Returns whether *any* spec's entity set changed (a task was created or
        removed) so the caller can decide between an entry reload and a plain
        coordinator refresh.
        """
        snapshot = self._registry_snapshot()
        entity_set_changed = False
        specs = self._coordinator.store.get_declarative_companions()
        for spec in list(specs.values()):
            if not spec.get("enabled", True):
                # A disabled spec's managed tasks are dropped (reconcile with empty
                # matches), so toggling enabled off cleans up without deleting the spec.
                changed = await self._coordinator.store.reconcile_declarative_companion_tasks(
                    spec, {}, {}, config_entry_id=self._entry.entry_id,
                )
                entity_set_changed = entity_set_changed or changed
                continue
            try:
                matches = declarative_companions.expand_spec(spec, snapshot)
            except Exception:
                _LOGGER.exception(
                    "expand_spec failed for %s (%s)", spec.get("id"), spec.get("name")
                )
                continue
            rendered = {
                key: self._render_match(spec, match) for key, match in matches.items()
            }
            changed = await self._coordinator.store.reconcile_declarative_companion_tasks(
                spec,
                matches,
                rendered,
                config_entry_id=self._entry.entry_id,
            )
            entity_set_changed = entity_set_changed or changed
        return entity_set_changed

    # ── event handlers ───────────────────────────────────────────────────────
    @callback
    def _handle_registry_event(self, event: Event) -> None:
        """Any registry change may add/remove/re-home a matched entity."""
        self._hass.async_create_task(self._async_reconcile_and_maybe_reload())

    @callback
    def _handle_specs_changed(self) -> None:
        """Store fired ``SIGNAL_DECLARATIVE_SPECS_CHANGED`` after a spec CRUD."""
        self._hass.async_create_task(self._async_reconcile_and_maybe_reload())

    async def _async_reconcile_and_maybe_reload(self) -> None:
        entity_set_changed = await self._reconcile_all()
        if entity_set_changed:
            if not self._reload_scheduled:
                self._reload_scheduled = True
                self._hass.async_create_task(self._async_reload())
        else:
            await self._coordinator.async_request_refresh()

    async def _async_reload(self) -> None:
        try:
            await self._hass.config_entries.async_reload(self._entry.entry_id)
        finally:
            self._reload_scheduled = False

    # ── preview (used by the panel's live-preview UX) ────────────────────────
    def preview(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Return the WS ``preview_declarative_companion`` payload for *spec*.

        Same expand + render passes as the reconcile path, but returns match
        detail (up to the first 10 entries) plus the total count so the panel can
        show "matches out of N" as the user edits. Never writes. Runs on a spec
        that has NOT been persisted — the caller normalizes first, this fails at
        the edge for malformed specs (raises the pure validator's error).
        """
        snapshot = self._registry_snapshot()
        warnings: list[str] = []
        try:
            matches = declarative_companions.expand_spec(spec, snapshot)
        except declarative_companions.DeclarativeCompanionValidationError as err:
            # Hard cap tripped — surface for the panel to show its red banner.
            return {
                "matched": [],
                "count": None,
                "warnings": [str(err)],
                "over_cap": True,
            }
        count = len(matches)
        if count > 50:
            warnings.append("too_many_matches")
        # Sample the first 10 for the preview panel (deterministic order — dicts
        # are insertion-ordered and expand_spec walks the registry in registry
        # order, which is stable across boots for the same HA config).
        sample: list[dict[str, Any]] = []
        for (spec_id_key, ent_reg_id), match in list(matches.items())[:10]:
            variables = self._template_variables(match["entity"])
            rendered_name = self._render_one(
                spec.get("task_template", {}).get("name_template", ""), variables
            )
            rendered_notes = self._render_one(
                spec.get("task_template", {}).get("notes_template", ""), variables
            )
            sample.append(
                {
                    "entity_id": match["entity"]["entity_id"],
                    "entity_registry_id": ent_reg_id,
                    "rendered_name": rendered_name,
                    "rendered_notes": rendered_notes,
                    "device_name": variables["device_name"],
                    "area_name": variables["area_name"],
                }
            )
        return {
            "matched": sample,
            "count": count,
            "warnings": warnings,
            "over_cap": False,
        }

    def installed_integrations(self) -> list[str]:
        """Distinct ``platform`` values in the entity registry, excluding Home Keeper.

        Used by the panel's integration picker so users can point a spec at an
        installed integration without typing the domain by hand. Excludes
        Home Keeper itself so the loop guard doesn't need to shadow it in the
        UI. Returns sorted for stable rendering.
        """
        ent_reg = er.async_get(self._hass)
        platforms = {
            entry.platform for entry in ent_reg.entities.values() if entry.platform
        }
        platforms.discard(DOMAIN)
        return sorted(platforms)
