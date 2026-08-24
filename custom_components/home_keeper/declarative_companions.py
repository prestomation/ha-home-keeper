"""Pure logic for declarative companions.

A **declarative companion** is a Home-Keeper-owned recipe (target integration +
entity filters + sensor-task trigger + Jinja-templated task fields) that expands
into one managed sensor task per matching entity. Unlike a hand-coded glue
integration (Battery Notes, Pawsistant) it needs no separate repo — users create
them from the panel, or install one from a shipped preset (see
``declarative_presets.py``).

This module owns:

* :func:`normalize_declarative_companion` — spec validation, mirroring
  :func:`models.normalize_sensor`'s edge-fail contract.
* :func:`expand_spec` — the selection pass: which entities match the spec's
  filters, keyed by the survives-rename ``entity_registry_id``.
* :func:`reconcile_declarative_tasks` — the diff pass: creates / updates /
  removes managed tasks against the current set of matched entities. Same
  ``(new_tasks, ops, changed)`` return shape as
  :func:`problem_tasks.reconcile_problem_tasks`.
* :func:`build_managed_by` — the ownership block stamped on every managed task.

The reconciler (``declarative_companion_sync.py``) handles the HA-bound bits:
enumerating the entity registry, rendering Jinja templates for name/notes, and
firing the store hook that persists the diff. State watching is delegated:
expanded tasks look like normal sensor tasks (``recurrence_type = "sensor"`` with
a full ``sensor`` block), so the existing ``SensorTaskWatcher`` handles arm/clear.

No HA imports here — every branch is unit-testable with plain dicts (see
``tests/unit/test_declarative_companions.py``). The renderer that needs
``hass.helpers.template.Template`` lives on the HA-bound side.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from . import models
from .const import (
    DOMAIN,
    MAX_DECLARATIVE_ENTITY_REGEX_LEN,
    MAX_DECLARATIVE_MATCH_HARD,
    MAX_DECLARATIVE_NAME_TEMPLATE_LEN,
    MAX_DECLARATIVE_NOTES_TEMPLATE_LEN,
    MAX_DECLARATIVE_SPEC_DESCRIPTION_LEN,
    MAX_DECLARATIVE_SPEC_NAME_LEN,
    REC_SENSOR,
    TASK_SOURCE_DECLARATIVE_COMPANION,
)
from .models import TaskValidationError

# Fields the reconciler owns and rewrites from the spec on every pass; user edits
# through the update_task service are stripped by ``models.merge_update``. The
# panel additionally hides edit/delete for source-owned tasks.
_LOCKED_FIELDS = ["name", "recurrence_type", "device_id", "area_id", "sensor"]


class DeclarativeCompanionValidationError(TaskValidationError):
    """Raised when a declarative-companion spec fails validation.

    Subclasses :class:`TaskValidationError` so callers already trapping the
    parent (the ``add_task`` service edge, ``store.async_add_task``) still catch
    it, but a caller wanting a spec-specific message can distinguish it.
    """


def _clean_str(value: Any, field: str, max_len: int, *, required: bool = False) -> str:
    """Trim *value* to a string; enforce ``max_len``; empty allowed unless *required*.

    Wrapped so every string field on a spec fails the same way and the caller
    doesn't build strings.strip() + length checks by hand at each field.
    """
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise DeclarativeCompanionValidationError(f"{field} must be a string")
    if required and not text:
        raise DeclarativeCompanionValidationError(f"{field} is required")
    if len(text) > max_len:
        raise DeclarativeCompanionValidationError(
            f"{field} must be <= {max_len} characters"
        )
    return text


def _clean_id_list(value: Any, field: str) -> list[str]:
    """Normalize a filter-list-of-ids to a de-duplicated list of stripped strings.

    Accepts a list/tuple of strings or a single string; ``None``/``""``/``[]`` -> ``[]``.
    Same shape as :func:`models.normalize_labels` but reused here rather than imported
    so ``TaskValidationError`` from that helper doesn't leak through with a labels
    message on an area-id list.
    """
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise DeclarativeCompanionValidationError(f"{field} must be a list")
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise DeclarativeCompanionValidationError(f"{field} entries must be strings")
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _normalize_selection(data: Any) -> dict[str, Any]:
    """Validate the entity-selection block on a spec.

    Every field is optional individually; an empty selection would match every entity
    in the HA config, which is guarded downstream by ``MAX_DECLARATIVE_MATCH_HARD``.
    The regex is only *compiled* (validated) here; the reconciler recompiles under a
    ``functools.lru_cache`` to avoid re-parsing on every reconcile pass.
    """
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise DeclarativeCompanionValidationError("selection must be a mapping")
    result: dict[str, Any] = {}
    target_integration = _clean_str(
        data.get("target_integration"), "selection.target_integration", 100
    )
    if target_integration:
        result["target_integration"] = target_integration
    domain = _clean_str(data.get("domain"), "selection.domain", 100)
    if domain:
        result["domain"] = domain
    device_class = _clean_str(
        data.get("device_class"), "selection.device_class", 100
    )
    if device_class:
        result["device_class"] = device_class
    entity_regex = _clean_str(
        data.get("entity_regex"),
        "selection.entity_regex",
        MAX_DECLARATIVE_ENTITY_REGEX_LEN,
    )
    if entity_regex:
        try:
            re.compile(entity_regex)
        except re.error as err:
            raise DeclarativeCompanionValidationError(
                f"selection.entity_regex is not a valid regex: {err}"
            ) from err
        result["entity_regex"] = entity_regex
    for field in (
        "area_ids",
        "label_ids",
        "exclude_entity_ids",
        "exclude_device_ids",
        "exclude_area_ids",
        "exclude_label_ids",
    ):
        result[field] = _clean_id_list(data.get(field), f"selection.{field}")
    return result


def _normalize_task_template(data: Any) -> dict[str, Any]:
    """Validate the task-template block on a spec.

    Jinja source strings are validated for length and non-emptiness (``name_template``
    only) — actual template compilation happens on the HA-bound side where a
    ``hass`` object is in scope. ``category``/``priority``/``labels`` pass through
    with light shape checks and are stamped verbatim onto the materialized task.
    """
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise DeclarativeCompanionValidationError("task_template must be a mapping")
    result: dict[str, Any] = {}
    result["name_template"] = _clean_str(
        data.get("name_template"),
        "task_template.name_template",
        MAX_DECLARATIVE_NAME_TEMPLATE_LEN,
        required=True,
    )
    notes_template = _clean_str(
        data.get("notes_template"),
        "task_template.notes_template",
        MAX_DECLARATIVE_NOTES_TEMPLATE_LEN,
    )
    result["notes_template"] = notes_template
    category = _clean_str(data.get("category"), "task_template.category", 100)
    if category:
        result["category"] = category
    priority = data.get("priority")
    if priority is not None:
        try:
            priority_int = int(priority)
        except (TypeError, ValueError) as err:
            raise DeclarativeCompanionValidationError(
                "task_template.priority must be an integer"
            ) from err
        result["priority"] = priority_int
    labels_raw = data.get("labels")
    if labels_raw in (None, "", []):
        result["labels"] = []
    else:
        result["labels"] = _clean_id_list(labels_raw, "task_template.labels")
    return result


def normalize_declarative_companion(data: Any) -> dict[str, Any]:
    """Validate and normalize a declarative-companion spec.

    Assigns a UUID if missing (letting a caller pre-set an ``id`` for updates).
    Mirrors :func:`models.normalize_sensor`'s edge-fail contract — raises
    :class:`DeclarativeCompanionValidationError` on any malformed field so bad
    input fails at the service edge rather than persisting.

    The trigger block is delegated to
    ``models.normalize_sensor(..., allow_missing_entity=True)`` — the spec's trigger
    is a **template** for the sensor binding stamped onto each materialized task,
    with the real ``entity_id`` filled in per matching entity by the reconciler.
    Pure — no HA imports.
    """
    if not isinstance(data, dict):
        raise DeclarativeCompanionValidationError(
            "a declarative companion requires a mapping"
        )
    spec_id = _clean_str(data.get("id"), "id", 100) or uuid.uuid4().hex
    name = _clean_str(data.get("name"), "name", MAX_DECLARATIVE_SPEC_NAME_LEN, required=True)
    description = _clean_str(
        data.get("description"), "description", MAX_DECLARATIVE_SPEC_DESCRIPTION_LEN
    )
    preset_id = _clean_str(data.get("preset_id"), "preset_id", 100) or None
    enabled = data.get("enabled")
    enabled = True if enabled is None else bool(enabled)
    selection = _normalize_selection(data.get("selection"))
    trigger = models.normalize_sensor(
        data.get("trigger"), allow_missing_entity=True
    )
    task_template = _normalize_task_template(data.get("task_template"))
    # ``per_entity_overrides`` is a reserved v1 field — the panel UI is deferred, but
    # the slot exists on-disk so a follow-up doesn't need a storage migration.
    overrides = data.get("per_entity_overrides")
    if overrides in (None, "", {}):
        overrides = {}
    if not isinstance(overrides, dict):
        raise DeclarativeCompanionValidationError(
            "per_entity_overrides must be a mapping"
        )
    result: dict[str, Any] = {
        "id": spec_id,
        "name": name,
        "description": description,
        "enabled": enabled,
        "preset_id": preset_id,
        "selection": selection,
        "trigger": trigger,
        "task_template": task_template,
        "per_entity_overrides": overrides,
    }
    for ts_field in ("created", "updated"):
        raw = data.get(ts_field)
        if raw is not None:
            if not isinstance(raw, str):
                raise DeclarativeCompanionValidationError(
                    f"{ts_field} must be an ISO timestamp string"
                )
            result[ts_field] = raw
    return result


# --- Selection (pure) --------------------------------------------------------


def _labels_intersect(entity_labels: Any, wanted: list[str]) -> bool:
    """Whether *entity_labels* contains any of *wanted*.

    Empty *wanted* returns ``False`` — "no labels to check for" cannot intersect
    with anything. Callers that mean "no filter" (an empty include list =
    everything matches) guard the call with ``if wanted`` before delegating here;
    the exclude branch simply gets its natural "empty exclude list = nothing
    excluded" semantic.
    """
    if not wanted or not entity_labels:
        return False
    return any(label in entity_labels for label in wanted)


def _entity_matches(entry: dict[str, Any], selection: dict[str, Any], regex: re.Pattern[str] | None) -> bool:
    """Whether *entry* (a registry-snapshot dict) satisfies *selection*.

    Applies each filter as an AND. Empty filters match everything. See
    :func:`expand_spec` for how the snapshot is shaped.
    """
    if entry.get("disabled"):
        return False
    # Loop guard: never match Home Keeper's own entities. Otherwise a broad regex
    # would fan out over per-task device entities and create tasks about tasks.
    if entry.get("platform") == DOMAIN:
        return False
    target = selection.get("target_integration")
    if target and entry.get("platform") != target:
        return False
    domain = selection.get("domain")
    if domain and entry.get("domain") != domain:
        return False
    device_class = selection.get("device_class")
    if device_class:
        entry_class = entry.get("device_class") or entry.get("original_device_class")
        if entry_class != device_class:
            return False
    if regex is not None and not regex.fullmatch(entry["entity_id"]):
        return False
    entity_id = entry["entity_id"]
    if entity_id in selection.get("exclude_entity_ids", []):
        return False
    if entry.get("device_id") and entry["device_id"] in selection.get(
        "exclude_device_ids", []
    ):
        return False
    if entry.get("area_id") and entry["area_id"] in selection.get(
        "exclude_area_ids", []
    ):
        return False
    if _labels_intersect(entry.get("labels"), selection.get("exclude_label_ids", [])):
        return False
    area_ids = selection.get("area_ids") or []
    if area_ids and entry.get("area_id") not in area_ids:
        return False
    label_ids = selection.get("label_ids") or []
    if label_ids and not _labels_intersect(entry.get("labels"), label_ids):
        return False
    return True


def expand_spec(
    spec: dict[str, Any], registry_snapshot: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return every ``(spec_id, entity_registry_id) -> match_meta`` the spec picks.

    *registry_snapshot* is a plain-dict projection of the HA entity registry (built
    by the HA-bound reconciler) shaped as::

        {
          "entities": [
            {"entity_registry_id": ..., "entity_id": ..., "platform": ...,
             "domain": ..., "device_class": ..., "original_device_class": ...,
             "device_id": ..., "area_id": ..., "labels": {...}, "disabled": bool,
             "name": ..., "original_name": ...},
            ...
          ]
        }

    Each *match_meta* carries the fields the reconciler needs to build the sensor
    binding + templated name/notes: the registry entry dict itself plus the trigger
    block. Enforces ``MAX_DECLARATIVE_MATCH_HARD`` as a runaway-regex guard — raises
    :class:`DeclarativeCompanionValidationError` past the cap so a spec matching 800
    entities is rejected loudly rather than fanning out.
    """
    entities = registry_snapshot.get("entities") or []
    selection = spec.get("selection") or {}
    entity_regex_str = selection.get("entity_regex")
    regex = re.compile(entity_regex_str) if entity_regex_str else None
    spec_id = spec["id"]
    trigger = spec["trigger"]
    matches: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entities:
        if not _entity_matches(entry, selection, regex):
            continue
        ent_reg_id = entry.get("entity_registry_id") or entry.get("entity_id")
        matches[(spec_id, ent_reg_id)] = {
            "entity_registry_id": ent_reg_id,
            "entity": entry,
            "sensor": {**trigger, "entity_id": entry["entity_id"]},
        }
        if len(matches) > MAX_DECLARATIVE_MATCH_HARD:
            raise DeclarativeCompanionValidationError(
                f"spec {spec.get('name')!r} matches more than "
                f"{MAX_DECLARATIVE_MATCH_HARD} entities; narrow the selection"
            )
    return matches


# --- Managed-by + reconcile -------------------------------------------------


def build_managed_by(
    spec: dict[str, Any], config_entry_id: str
) -> dict[str, Any]:
    """Ownership block stamped on a task materialized from *spec*.

    ``deletion_protected`` requires ``config_entry_id`` (see
    :func:`models.validate_managed_by`) so the task stays cleanable if Home Keeper
    is removed. ``completion_blocked`` is **False** — a declarative-companion task
    is real work a person will complete; ``clear_on_recover`` (per the spec's
    trigger) still auto-completes when the signal recovers. ``locked_fields`` reflect
    that the reconciler owns name/device/area/sensor from the spec's template.
    """
    return {
        "integration": DOMAIN,
        "display_name": spec["name"],
        "config_entry_id": config_entry_id,
        "deletion_protected": True,
        "locked_fields": list(_LOCKED_FIELDS),
        "completion_blocked": False,
    }


def declarative_source(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``{spec_id, entity_registry_id, entity_id}`` provenance, or ``None``."""
    source = task.get("source")
    if isinstance(source, dict) and isinstance(
        source.get(TASK_SOURCE_DECLARATIVE_COMPANION), dict
    ):
        return source[TASK_SOURCE_DECLARATIVE_COMPANION]
    return None


def task_key(task: dict[str, Any]) -> tuple[str, str] | None:
    """The ``(spec_id, entity_registry_id)`` dedupe key for a materialized task.

    Survives entity renames — the entity's registry id is stable across an
    ``entity_id`` rename, which is why the reconciler keys on it rather than the
    entity id echoed into ``source`` for observability.
    """
    src = declarative_source(task)
    if not src:
        return None
    spec_id = src.get("spec_id")
    ent_reg_id = src.get("entity_registry_id")
    if not spec_id or not ent_reg_id:
        return None
    return (spec_id, ent_reg_id)


def _build_task(
    spec: dict[str, Any],
    match: dict[str, Any],
    *,
    rendered_name: str,
    rendered_notes: str,
    config_entry_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Create a fresh managed sensor task for *match* under *spec*.

    Name/notes come pre-rendered (the HA-bound reconciler runs Jinja); this stays
    pure. The materialized task carries a full ``sensor`` binding, so the existing
    :class:`SensorTaskWatcher` handles arm/clear like any other sensor task.
    Baseline stance: a fresh task starts dormant (``next_due = None``) — the
    watcher's per-mode baseline pass will arm on the first genuine live crossing,
    not on an already-true condition at boot.
    """
    entry = match["entity"]
    template = spec.get("task_template") or {}
    task_input: dict[str, Any] = {
        "name": rendered_name,
        "notes": rendered_notes,
        "recurrence_type": REC_SENSOR,
        "sensor": match["sensor"],
        "device_id": entry.get("device_id"),
        "area_id": entry.get("area_id"),
        "source": {
            TASK_SOURCE_DECLARATIVE_COMPANION: {
                "spec_id": spec["id"],
                "entity_registry_id": match["entity_registry_id"],
                "entity_id": entry["entity_id"],
            }
        },
        "managed_by": build_managed_by(spec, config_entry_id),
    }
    if labels := template.get("labels"):
        task_input["labels"] = labels
    task = models.build_task(task_input, now=now)
    # ``build_task`` for a sensor task computes next_due=None (dormant). Keep it
    # dormant explicitly so a future default change doesn't quietly arm every fresh
    # declarative task.
    task["next_due"] = None
    return task


def reconcile_declarative_tasks(
    spec: dict[str, Any],
    matches: dict[tuple[str, str], dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    rendered_by_key: dict[tuple[str, str], tuple[str, str]],
    *,
    config_entry_id: str,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, dict[str, Any]]], bool]:
    """Diff *spec*'s current match set against *tasks* and return the update plan.

    *matches* is the output of :func:`expand_spec`. *rendered_by_key* maps each
    match key to ``(rendered_name, rendered_notes)`` — pre-rendered because Jinja
    needs ``hass``, which this pure module doesn't have.

    Returns ``(new_tasks, ops, changed)`` — same shape as
    :func:`problem_tasks.reconcile_problem_tasks`:

    * ``new_tasks`` — a fresh task map (non-declarative tasks and tasks from other
      specs are carried through untouched).
    * ``ops`` — ordered ``(kind, task)`` events the store must fire:
      ``"created"`` / ``"deleted"`` / ``"updated"``. Arm/clear transitions are not
      handled here — the sensor watcher owns those on the materialized tasks.
    * ``changed`` — whether ``new_tasks`` differs from ``tasks`` (persist if true).

    Handles four cases per match: new (create), still-there (drift-update
    name/notes/device/area from template + entity registry), rename (task's
    ``sensor.entity_id`` follows the current entity_id under the same registry id,
    ``source`` echoes the fresh id), orphaned (delete).
    """
    result = dict(tasks)
    ops: list[tuple[str, dict[str, Any]]] = []
    changed = False

    # Index existing tasks belonging to THIS spec by dedupe key.
    existing_by_key: dict[tuple[str, str], str] = {}
    for tid, task in result.items():
        key = task_key(task)
        if key is None or key[0] != spec["id"]:
            continue
        existing_by_key[key] = tid

    # Orphan pass: registered entity vanished, was excluded, or the spec narrowed.
    for key, tid in list(existing_by_key.items()):
        if key not in matches:
            ops.append(("deleted", result.pop(tid)))
            existing_by_key.pop(key, None)
            changed = True

    # Create / update pass.
    for key, match in matches.items():
        rendered_name, rendered_notes = rendered_by_key.get(key, ("", ""))
        existing_tid = existing_by_key.get(key)
        if existing_tid is None:
            task = _build_task(
                spec,
                match,
                rendered_name=rendered_name,
                rendered_notes=rendered_notes,
                config_entry_id=config_entry_id,
                now=now,
            )
            result[task["id"]] = task
            ops.append(("created", task))
            changed = True
            continue

        task = result[existing_tid]
        # Recompute reconciler-owned metadata from the spec + current entity, so
        # renames / device rehoming / spec-name edits flow through.
        entry = match["entity"]
        managed_by = build_managed_by(spec, config_entry_id)
        new_source = {
            TASK_SOURCE_DECLARATIVE_COMPANION: {
                "spec_id": spec["id"],
                "entity_registry_id": match["entity_registry_id"],
                "entity_id": entry["entity_id"],
            }
        }
        task_changed = False
        for field, value in (
            ("name", rendered_name),
            ("notes", rendered_notes),
            ("device_id", entry.get("device_id")),
            ("area_id", entry.get("area_id")),
            ("sensor", match["sensor"]),
            ("managed_by", managed_by),
            ("source", new_source),
        ):
            if task.get(field) != value:
                task[field] = value
                task_changed = True
        if task_changed:
            ops.append(("updated", task))
            changed = True

    return result, ops, changed


def collect_orphans_for_removed_spec(
    removed_spec_id: str, tasks: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    """Drop every task belonging to *removed_spec_id* and return the plan.

    Called by the store when a spec is deleted — the reconciler would otherwise
    need to be told to run for a spec that no longer exists. Same op shape as
    :func:`reconcile_declarative_tasks`, always ``("deleted", ...)``.
    """
    result = dict(tasks)
    ops: list[tuple[str, dict[str, Any]]] = []
    for tid, task in list(result.items()):
        key = task_key(task)
        if key is not None and key[0] == removed_spec_id:
            ops.append(("deleted", result.pop(tid)))
    return result, ops
