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

from . import declarative_companions, sensor_tasks, sensor_watcher
from .const import (
    DOMAIN,
    SIGNAL_DECLARATIVE_SPECS_CHANGED,
)

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)


def _project_entry(entry: er.RegistryEntry) -> dict[str, Any]:
    """Project one entity-registry entry into the plain-dict shape the pure pass reads.

    Kept as a free function so the whole-registry snapshot and the single-entity
    lookup that re-renders one task's notes cannot describe an entity differently.
    """
    return {
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

        A task made here did not exist before setup, so the watcher's baseline pass
        (which runs later in the same setup) must leave its edge unset — the entity
        may have started matching while Home Assistant was down.
        """
        _entity_set_changed, created = await self._reconcile_all()
        sensor_watcher.async_mark_tasks_new(self._hass, self._entry.entry_id, created)

    @callback
    def async_start_listeners(self) -> None:
        """Begin reacting to registry updates and spec-change signals.

        Registered via ``entry.async_on_unload`` so teardown is automatic on
        unload/reload — no explicit stop needed.
        """
        # Three thin wrappers rather than one shared handler: HA's event bus is
        # strictly typed per event kind (entity vs device vs area registry each
        # carry a different data mapping), and a single ``Event[Mapping[str,Any]]``
        # signature fails mypy. Each wrapper is a per-event-kind adapter that
        # discards the payload and calls the shared reconcile trigger.
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._on_entity_registry_updated,
            )
        )
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED,
                self._on_device_registry_updated,
            )
        )
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                ar.EVENT_AREA_REGISTRY_UPDATED,
                self._on_area_registry_updated,
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
        entries = [_project_entry(entry) for entry in ent_reg.entities.values()]
        return {"entities": entries}

    def _entry_for_entity(self, entity_id: str) -> dict[str, Any]:
        """The snapshot projection of one entity, by entity id.

        Falls back to a projection carrying only the ``entity_id``. A managed task
        always names its entity, but the registry entry can already be gone (the
        entity was removed and the reconcile pass that drops the task has not run
        yet). The templates that read ``{{ entity_id }}`` and the live state still
        render from that.
        """
        ent_reg = er.async_get(self._hass)
        found = ent_reg.async_get(entity_id)
        return _project_entry(found) if found is not None else {"entity_id": entity_id}

    # ── rendering ────────────────────────────────────────────────────────────
    def _template_variables(self, entry: dict[str, Any]) -> dict[str, Any]:
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
        friendly = (
            friendly or entry.get("name") or entry.get("original_name") or entity_id
        )
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
    async def _reconcile_all(self) -> tuple[bool, list[str]]:
        """Re-materialize every enabled spec against the current registry.

        Returns ``(entity_set_changed, created_task_ids)``. The flag says whether
        *any* spec's entity set changed (a task was created or removed) so the caller
        can decide between an entry reload and a plain coordinator refresh. The ids
        name the tasks this pass made, which the sensor watcher needs so its next
        baseline pass leaves their edge unset (see
        :func:`sensor_watcher.async_mark_tasks_new`).

        Complexity: the snapshot is built once per pass, then each spec walks
        every entity to apply its filters (O(N specs x M entities)). For the
        expected load (~10 specs, ~500 entities) that's ~5,000 predicate
        evaluations per pass, which the dispatcher already debounces to at most
        one pass per burst of registry events. If users report slowness with
        many specs, index the snapshot by domain/platform/device_class once and
        filter the pre-indexed subset per spec.
        """
        snapshot = self._registry_snapshot()
        entity_set_changed = False
        created: list[str] = []
        specs = self._coordinator.store.get_declarative_companions()
        for spec in list(specs.values()):
            if not spec.get("enabled", True):
                # A disabled spec's managed tasks are dropped (reconcile with empty
                # matches), so toggling enabled off cleans up without deleting the spec.
                store = self._coordinator.store
                changed, made = await store.reconcile_declarative_companion_tasks(
                    spec,
                    {},
                    {},
                    config_entry_id=self._entry.entry_id,
                )
                entity_set_changed = entity_set_changed or changed
                created.extend(made)
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
            store = self._coordinator.store
            changed, made = await store.reconcile_declarative_companion_tasks(
                spec,
                matches,
                rendered,
                config_entry_id=self._entry.entry_id,
            )
            entity_set_changed = entity_set_changed or changed
            created.extend(made)
        return entity_set_changed, created

    # ── notes refresh (called by the sensor watcher on an arm) ───────────────
    async def async_refresh_task_notes(self, task_id: str) -> None:
        """Re-render one managed task's notes from the live entity.

        The sensor watcher calls this the moment it arms a declarative-companion
        task. Notes are otherwise rendered only by the reconcile pass — at creation,
        and on registry changes after that — so a template that quotes the reading
        ("{{ state }} hours left") describes the value from that moment. A brush that
        went from 145 hours to 3 arrived with a note reading 145. Rendering again
        here makes the note describe the reading that armed the task.

        Does nothing for a task no declarative companion manages, for a spec that has
        gone away, for a spec with no notes template, and when the render matches
        what is stored.

        A note edited by hand is overwritten. ``notes`` is not one of the task's
        ``managed_by.locked_fields``, but the reconcile pass already rewrites it from
        the template whenever the registry moves (see
        ``declarative_companions.reconcile_declarative_tasks``), so the field is
        owned by the recipe in practice. Keeping the hand-edit here would make the
        note survive an arm but not a rename of the device, which is a worse rule
        than the one it replaces.
        """
        store = self._coordinator.store
        task = store.get_tasks().get(task_id)
        if task is None:
            return
        source = declarative_companions.declarative_source(task)
        if source is None:
            return
        spec = store.get_declarative_companion(source.get("spec_id") or "")
        if spec is None:
            return
        template = (spec.get("task_template") or {}).get("notes_template") or ""
        if not template:
            return
        entity_id = sensor_tasks.bound_entity_id(task)
        if not entity_id:
            return
        variables = self._template_variables(self._entry_for_entity(entity_id))
        notes = self._render_one(template, variables)
        if notes == task.get("notes"):
            return
        await store.update_task(task_id, {"notes": notes})

    # ── event handlers ───────────────────────────────────────────────────────
    @callback
    def _on_entity_registry_updated(
        self, event: Event[er.EventEntityRegistryUpdatedData]
    ) -> None:
        """Entity added/removed/rehomed/relabeled may match a different spec now."""
        self._trigger_reconcile()

    @callback
    def _on_device_registry_updated(
        self, event: Event[dr.EventDeviceRegistryUpdatedData]
    ) -> None:
        """Device renamed/relabeled/rehomed rerenders templated names."""
        self._trigger_reconcile()

    @callback
    def _on_area_registry_updated(
        self, event: Event[ar.EventAreaRegistryUpdatedData]
    ) -> None:
        """Area renamed rerenders every task template that reads ``area_name``."""
        self._trigger_reconcile()

    @callback
    def _trigger_reconcile(self) -> None:
        """Schedule a reconcile pass (shared by every registry-event wrapper)."""
        self._hass.async_create_task(self._async_reconcile_and_maybe_reload())

    @callback
    def _handle_specs_changed(self) -> None:
        """Store fired ``SIGNAL_DECLARATIVE_SPECS_CHANGED`` after a spec CRUD."""
        self._hass.async_create_task(self._async_reconcile_and_maybe_reload())

    async def _async_reconcile_and_maybe_reload(self) -> None:
        entity_set_changed, created = await self._reconcile_all()
        if entity_set_changed:
            # The reload re-runs setup, which baselines the sensor watcher's edge
            # state and would record a task made a moment ago as already-met. Name
            # the new tasks first: the set lives on ``hass.data``, because the reload
            # destroys this object before the baseline reads it.
            sensor_watcher.async_mark_tasks_new(
                self._hass, self._entry.entry_id, created
            )
            if not self._reload_scheduled:
                self._reload_scheduled = True
                self._hass.async_create_task(self._async_reload())
        else:
            # No reload, so no baseline pass: the watcher has never seen these ids,
            # and its next evaluation already reads a standing condition as a fresh
            # crossing. Marking them would leave a set behind for a later, unrelated
            # reload to consume.
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
        for (_spec_id_key, ent_reg_id), match in list(matches.items())[:10]:
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
