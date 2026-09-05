"""Unit tests for the pure declarative-companion surface.

Covers the recipe-shape module (spec normalization, entity selection,
reconciler diff, dedupe key) and the shipped presets (round-tripping every
preset through the normalizer to guarantee they stay valid). The HA-bound
reconciler (``declarative_companion_sync.py``) — with its entity-registry
snapshot builder and Jinja rendering — is exercised by the integration suite.
"""

from datetime import datetime, timedelta, timezone

import hk_declarative_companions as dc
import hk_declarative_presets as presets
import pytest
from asserts import raises_exactly
from hk_models import TaskValidationError

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 19, 9, tzinfo=TZ)
ENTRY = "cfg_entry_1"


# --- Fixtures ---------------------------------------------------------------


def _spec(**over):
    """Minimum viable spec dict, one field overridable at a time."""
    base = {
        "name": "Test spec",
        "selection": {
            "target_integration": "device_pulse",
            "entity_regex": r".*_total_failed_pings$",
        },
        "trigger": {
            "mode": "threshold",
            "comparison": ">",
            "value": 0,
            "for_seconds": 3600,
            "clear_on_recover": True,
        },
        "task_template": {
            "name_template": "Check on {{ friendly_name }}",
            "notes_template": "",
        },
    }
    base.update(over)
    return base


def _entity(entity_id, *, platform="device_pulse", domain="sensor", **over):
    """A registry-snapshot entry."""
    entry = {
        "entity_registry_id": f"reg_{entity_id.split('.')[-1]}",
        "entity_id": entity_id,
        "platform": platform,
        "domain": domain,
        "device_class": None,
        "original_device_class": None,
        "device_id": over.get("device_id"),
        "area_id": over.get("area_id"),
        "labels": over.get("labels", set()),
        "disabled": over.get("disabled", False),
        "name": over.get("name"),
        "original_name": over.get("original_name"),
    }
    entry.update({k: v for k, v in over.items() if k in entry})
    return entry


def _snapshot(*entities):
    return {"entities": list(entities)}


# --- Spec normalization -----------------------------------------------------


def test_normalize_assigns_id_if_missing():
    spec = dc.normalize_declarative_companion(_spec())
    assert spec["id"]  # uuid4 hex assigned


def test_normalize_preserves_explicit_id():
    spec = dc.normalize_declarative_companion(_spec(id="explicit-id"))
    assert spec["id"] == "explicit-id"


def test_normalize_carries_defaults():
    spec = dc.normalize_declarative_companion(_spec())
    assert spec["enabled"] is True
    assert spec["description"] == ""
    assert spec["preset_id"] is None
    assert spec["per_entity_overrides"] == {}


def test_normalize_carries_created_updated_when_present():
    spec = dc.normalize_declarative_companion(
        _spec(created="2026-01-01T00:00:00Z", updated="2026-06-01T00:00:00Z")
    )
    assert spec["created"] == "2026-01-01T00:00:00Z"
    assert spec["updated"] == "2026-06-01T00:00:00Z"


@pytest.mark.parametrize(
    "over",
    [
        {"name": ""},  # empty name
        {"name": "x" * 101},  # too long
        {"description": "y" * 501},  # description too long
        {"selection": {"entity_regex": "["}},  # invalid regex
        {"selection": {"entity_regex": "x" * 201}},  # regex too long
        {"selection": "not-a-mapping"},  # bad selection type
        {"trigger": {"mode": "bogus"}},  # bad trigger mode
        {"trigger": {}},  # missing mode fields
        {"task_template": {"name_template": ""}},  # missing name_template
        {"task_template": {"name_template": "x" * 201}},  # name_template too long
        {"task_template": {"name_template": "x", "notes_template": "y" * 2001}},
        {"per_entity_overrides": [1, 2, 3]},  # bad type
    ],
)
def test_normalize_rejects_malformed(over):
    with pytest.raises(TaskValidationError):
        dc.normalize_declarative_companion(_spec(**over))


def test_normalize_trigger_allows_missing_entity_id():
    """Spec triggers never carry entity_id — the reconciler stamps it per match."""
    spec = dc.normalize_declarative_companion(_spec())
    assert "entity_id" not in spec["trigger"]


# ── validation-error exact messages ────────────────────────────────────────
# Every message the panel echoes back to the user is asserted verbatim so a
# mutation that swaps the string for ``None`` / ``XX...XX`` / uppercase is
# caught. Each of the ``_clean_str`` call-site tests below also pins the
# field-name argument (``"id"`` / ``"name"`` / ``"description"`` /
# ``"preset_id"``) that gets mutated independently.


def test_normalize_rejects_non_mapping_input_exact_message():
    with raises_exactly(
        TaskValidationError, "a declarative companion requires a mapping"
    ):
        dc.normalize_declarative_companion("not-a-mapping")


def test_normalize_id_non_string_names_id_field():
    with raises_exactly(TaskValidationError, "id must be a string"):
        dc.normalize_declarative_companion(_spec(id=42))


def test_normalize_id_boundary_max_100_chars():
    # ``_clean_str(..., "id", 100)`` — a mutant that shifts the max to 101
    # would accept a 101-char id; the exact-message boundary catches it.
    spec = dc.normalize_declarative_companion(_spec(id="i" * 100))
    assert spec["id"] == "i" * 100
    with raises_exactly(TaskValidationError, "id must be <= 100 characters"):
        dc.normalize_declarative_companion(_spec(id="i" * 101))


def test_normalize_name_non_string_names_name_field():
    with raises_exactly(TaskValidationError, "name must be a string"):
        dc.normalize_declarative_companion(_spec(name=42))


def test_normalize_description_non_string_names_description_field():
    with raises_exactly(TaskValidationError, "description must be a string"):
        dc.normalize_declarative_companion(_spec(description=42))


def test_normalize_preset_id_non_string_names_preset_id_field():
    with raises_exactly(TaskValidationError, "preset_id must be a string"):
        dc.normalize_declarative_companion(_spec(preset_id=42))


def test_normalize_preset_id_boundary_max_100_chars():
    spec = dc.normalize_declarative_companion(_spec(preset_id="p" * 100))
    assert spec["preset_id"] == "p" * 100
    with raises_exactly(TaskValidationError, "preset_id must be <= 100 characters"):
        dc.normalize_declarative_companion(_spec(preset_id="p" * 101))


def test_normalize_per_entity_overrides_empty_string_normalizes_to_empty_dict():
    # ``overrides in (None, "", {})`` — a mutant that swaps ``""`` for
    # ``"XXXX"`` sends a real empty string through the ``isinstance(...,
    # dict)`` gate and raises instead of the None/""/dict short-circuit.
    spec = dc.normalize_declarative_companion(_spec(per_entity_overrides=""))
    assert spec["per_entity_overrides"] == {}


def test_normalize_per_entity_overrides_non_mapping_exact_message():
    with raises_exactly(TaskValidationError, "per_entity_overrides must be a mapping"):
        dc.normalize_declarative_companion(_spec(per_entity_overrides="not-a-mapping"))


def test_normalize_created_must_be_string_exact_message():
    with raises_exactly(TaskValidationError, "created must be an ISO timestamp string"):
        dc.normalize_declarative_companion(_spec(created=1234567890))


def test_normalize_updated_must_be_string_exact_message():
    with raises_exactly(TaskValidationError, "updated must be an ISO timestamp string"):
        dc.normalize_declarative_companion(_spec(updated=1234567890))


def test_normalize_deduplicates_id_lists():
    spec = dc.normalize_declarative_companion(
        _spec(
            selection={
                "target_integration": "device_pulse",
                "exclude_entity_ids": ["a", "b", "a", "  b  ", ""],
            }
        )
    )
    assert spec["selection"]["exclude_entity_ids"] == ["a", "b"]


def test_normalize_id_list_rejects_non_strings():
    with pytest.raises(TaskValidationError):
        dc.normalize_declarative_companion(
            _spec(selection={"exclude_entity_ids": [1, 2]})
        )


def test_normalize_task_template_priority_coerces_to_int():
    spec = dc.normalize_declarative_companion(
        _spec(
            task_template={
                "name_template": "Fix {{ friendly_name }}",
                "priority": "3",
            }
        )
    )
    assert spec["task_template"]["priority"] == 3


def test_normalize_task_template_rejects_non_int_priority():
    with pytest.raises(TaskValidationError):
        dc.normalize_declarative_companion(
            _spec(
                task_template={
                    "name_template": "Fix {{ friendly_name }}",
                    "priority": "not-a-number",
                }
            )
        )


def test_normalize_enabled_coerces_bool():
    assert dc.normalize_declarative_companion(_spec(enabled=0))["enabled"] is False
    assert dc.normalize_declarative_companion(_spec(enabled=1))["enabled"] is True


# --- Selection --------------------------------------------------------------


def _normalized_spec(**over):
    return dc.normalize_declarative_companion(_spec(**over))


def test_expand_matches_target_integration_and_regex():
    spec = _normalized_spec()
    entities = _snapshot(
        _entity("sensor.hub_total_failed_pings"),
        _entity("sensor.router_temperature"),  # regex miss
        _entity("sensor.other_total_failed_pings", platform="mqtt"),  # platform miss
    )
    matches = dc.expand_spec(spec, entities)
    assert len(matches) == 1
    (spec_id, ent_reg_id), match = next(iter(matches.items()))
    assert spec_id == spec["id"]
    assert ent_reg_id == "reg_hub_total_failed_pings"
    assert match["sensor"]["entity_id"] == "sensor.hub_total_failed_pings"
    # Sensor block carries the trigger template + stamped entity_id.
    assert match["sensor"]["mode"] == "threshold"


def test_expand_filters_by_device_class():
    spec = _normalized_spec(
        selection={
            "domain": "binary_sensor",
            "device_class": "battery",
        }
    )
    entities = _snapshot(
        _entity(
            "binary_sensor.motion_battery",
            platform="zha",
            domain="binary_sensor",
            device_class="battery",
        ),
        _entity(
            "binary_sensor.door_motion",
            platform="zha",
            domain="binary_sensor",
            device_class="motion",
        ),
    )
    matches = dc.expand_spec(spec, entities)
    assert len(matches) == 1
    key = next(iter(matches))
    assert matches[key]["entity"]["entity_id"] == "binary_sensor.motion_battery"


def test_expand_filters_by_original_device_class_fallback():
    """A user-overridden entity keeps the platform's original device_class."""
    spec = _normalized_spec(
        selection={"domain": "binary_sensor", "device_class": "battery"}
    )
    entities = _snapshot(
        _entity(
            "binary_sensor.foo",
            platform="mqtt",
            domain="binary_sensor",
            device_class=None,
            original_device_class="battery",
        )
    )
    matches = dc.expand_spec(spec, entities)
    assert len(matches) == 1


def test_expand_skips_disabled_entities():
    spec = _normalized_spec(selection={"target_integration": "device_pulse"})
    entities = _snapshot(
        _entity("sensor.on"),
        _entity("sensor.off", disabled=True),
    )
    matches = dc.expand_spec(spec, entities)
    assert len(matches) == 1


def test_expand_never_matches_home_keeper_own_entities():
    """Loop guard: broad regex would fan out over per-task device entities."""
    spec = _normalized_spec(selection={"entity_regex": ".*"})
    entities = _snapshot(
        _entity("sensor.hub_total_failed_pings"),
        _entity("sensor.some_task_status", platform="home_keeper"),
    )
    matches = dc.expand_spec(spec, entities)
    assert all(m["entity"]["platform"] != "home_keeper" for m in matches.values())


def test_expand_applies_exclude_lists():
    spec = _normalized_spec(
        selection={
            "target_integration": "device_pulse",
            "exclude_entity_ids": ["sensor.excluded_total_failed_pings"],
            "exclude_device_ids": ["dev_bad"],
            "exclude_area_ids": ["area_bad"],
        }
    )
    entities = _snapshot(
        _entity("sensor.kept_total_failed_pings"),
        _entity("sensor.excluded_total_failed_pings"),
        _entity("sensor.on_bad_device_total_failed_pings", device_id="dev_bad"),
        _entity("sensor.on_bad_area_total_failed_pings", area_id="area_bad"),
    )
    matches = dc.expand_spec(spec, entities)
    kept = [m["entity"]["entity_id"] for m in matches.values()]
    assert kept == ["sensor.kept_total_failed_pings"]


def test_expand_applies_area_and_label_include_filters():
    spec = _normalized_spec(
        selection={
            "target_integration": "device_pulse",
            "area_ids": ["office"],
            "label_ids": ["monitored"],
        }
    )
    entities = _snapshot(
        _entity(
            "sensor.office_total_failed_pings",
            area_id="office",
            labels={"monitored"},
        ),
        _entity(
            "sensor.bedroom_total_failed_pings",
            area_id="bedroom",
            labels={"monitored"},
        ),
        _entity(
            "sensor.office_unmonitored_total_failed_pings",
            area_id="office",
            labels={"other"},
        ),
    )
    matches = dc.expand_spec(spec, entities)
    kept = [m["entity"]["entity_id"] for m in matches.values()]
    assert kept == ["sensor.office_total_failed_pings"]


def test_expand_hard_caps_matches():
    spec = _normalized_spec(selection={"entity_regex": ".*"})
    # Well over MAX_DECLARATIVE_MATCH_HARD (500).
    entities = _snapshot(
        *(
            _entity(f"sensor.x_{i}_total_failed_pings", platform="device_pulse")
            for i in range(600)
        )
    )
    with pytest.raises(TaskValidationError):
        dc.expand_spec(spec, entities)


def test_expand_at_hard_cap_still_accepts():
    # ``if len(matches) > MAX`` — a mutant that shifts to ``>= MAX`` would
    # reject at exactly the cap. Pin that the cap itself is inclusive.
    spec = _normalized_spec(selection={"entity_regex": ".*"})
    entities = _snapshot(
        *(
            _entity(f"sensor.x_{i}_total_failed_pings", platform="device_pulse")
            for i in range(dc.MAX_DECLARATIVE_MATCH_HARD)
        )
    )
    matches = dc.expand_spec(spec, entities)
    assert len(matches) == dc.MAX_DECLARATIVE_MATCH_HARD


def test_expand_hard_cap_error_names_spec_and_hint():
    spec = _normalized_spec(name="My spec")
    entities = _snapshot(
        *(
            _entity(f"sensor.x_{i}_total_failed_pings", platform="device_pulse")
            for i in range(dc.MAX_DECLARATIVE_MATCH_HARD + 1)
        )
    )
    with raises_exactly(
        TaskValidationError,
        f"spec 'My spec' matches more than "
        f"{dc.MAX_DECLARATIVE_MATCH_HARD} entities; narrow the selection",
    ):
        dc.expand_spec(spec, entities)


def test_expand_continues_past_non_matching_entities():
    # The skip on a non-matching entity is ``continue``, not ``break`` — a
    # broken loop would drop every match after the first miss.
    spec = _normalized_spec()
    entities = _snapshot(
        _entity("sensor.other_state", platform="mqtt"),  # non-match first
        _entity("sensor.hub_total_failed_pings"),  # match second
    )
    matches = dc.expand_spec(spec, entities)
    assert len(matches) == 1
    (_spec_id, ent_reg_id), _ = next(iter(matches.items()))
    assert ent_reg_id == "reg_hub_total_failed_pings"


def test_expand_falls_back_to_entity_id_when_registry_id_missing():
    # ``entry.get("entity_registry_id") or entry.get("entity_id")`` — a mutant
    # that mangles the second key (``None`` / ``XX...XX`` / ``ENTITY_ID``)
    # loses the fallback path.
    spec = _normalized_spec()
    entry = _entity("sensor.hub_total_failed_pings")
    entry["entity_registry_id"] = None
    matches = dc.expand_spec(spec, _snapshot(entry))
    assert len(matches) == 1
    (((_spec_id, ent_reg_id), match),) = matches.items()
    assert ent_reg_id == "sensor.hub_total_failed_pings"
    # The dict key ``"entity_registry_id"`` on the returned meta must survive
    # (mutants 41/42 rename it).
    assert "entity_registry_id" in match
    assert match["entity_registry_id"] == "sensor.hub_total_failed_pings"


# --- Reconcile diff ---------------------------------------------------------


def _match(entity_id, spec_id):
    entry = _entity(entity_id)
    return (spec_id, entry["entity_registry_id"]), {
        "entity_registry_id": entry["entity_registry_id"],
        "entity": entry,
        "sensor": {"entity_id": entity_id, "mode": "state", "state": "on"},
    }


def _rendered(key):
    return {key: (f"Rendered {key[1]}", f"Notes for {key[1]}")}


def test_reconcile_creates_missing_tasks():
    spec = _normalized_spec()
    key, m = _match("sensor.hub_total_failed_pings", spec["id"])
    matches = {key: m}
    _new_tasks, ops, changed = dc.reconcile_declarative_tasks(
        spec,
        matches,
        tasks={},
        rendered_by_key=_rendered(key),
        config_entry_id=ENTRY,
        now=NOW,
    )
    assert changed is True
    assert len(ops) == 1
    assert ops[0][0] == "created"
    created = ops[0][1]
    assert created["name"] == "Rendered reg_hub_total_failed_pings"
    assert created["notes"] == "Notes for reg_hub_total_failed_pings"
    assert created["next_due"] is None
    assert created["source"]["declarative_companion"]["spec_id"] == spec["id"]
    assert created["managed_by"]["deletion_protected"] is True
    assert created["managed_by"]["completion_blocked"] is False


def test_reconcile_deletes_orphaned_tasks():
    spec = _normalized_spec()
    key, m = _match("sensor.hub_total_failed_pings", spec["id"])
    # Round-trip: create a task, then reconcile against zero matches.
    stored, _ops, _ = dc.reconcile_declarative_tasks(
        spec,
        {key: m},
        {},
        _rendered(key),
        config_entry_id=ENTRY,
        now=NOW,
    )
    new_tasks, ops, changed = dc.reconcile_declarative_tasks(
        spec,
        matches={},
        tasks=stored,
        rendered_by_key={},
        config_entry_id=ENTRY,
        now=NOW,
    )
    assert changed is True
    assert len(ops) == 1
    assert ops[0][0] == "deleted"
    assert not any(dc.task_key(t) is not None for t in new_tasks.values())


def test_reconcile_survives_entity_rename():
    """entity_id change + registry_id stable: task stays, source echoes new id."""
    spec = _normalized_spec()
    key, m = _match("sensor.old_total_failed_pings", spec["id"])
    stored, _, _ = dc.reconcile_declarative_tasks(
        spec,
        {key: m},
        {},
        _rendered(key),
        config_entry_id=ENTRY,
        now=NOW,
    )
    original_ids = list(stored.keys())

    # Same registry_id, different entity_id
    renamed_entry = _entity("sensor.new_total_failed_pings")
    renamed_entry["entity_registry_id"] = m["entity_registry_id"]
    renamed_match = {
        (spec["id"], m["entity_registry_id"]): {
            "entity_registry_id": m["entity_registry_id"],
            "entity": renamed_entry,
            "sensor": {
                "entity_id": "sensor.new_total_failed_pings",
                "mode": "state",
                "state": "on",
            },
        }
    }
    new_tasks, ops, changed = dc.reconcile_declarative_tasks(
        spec,
        renamed_match,
        stored,
        rendered_by_key={
            (spec["id"], m["entity_registry_id"]): (
                "Rendered new",
                "Notes for new",
            )
        },
        config_entry_id=ENTRY,
        now=NOW,
    )
    # Task list length unchanged, task id preserved.
    assert list(new_tasks.keys()) == original_ids
    assert ops[0][0] == "updated"
    surviving = new_tasks[original_ids[0]]
    assert surviving["sensor"]["entity_id"] == "sensor.new_total_failed_pings"
    assert (
        surviving["source"]["declarative_companion"]["entity_id"]
        == "sensor.new_total_failed_pings"
    )
    assert changed is True


def test_reconcile_created_task_has_full_source_and_managed_by_shape():
    # Structural equality on the ``source`` / ``managed_by`` blocks: a mutant
    # that renames a key (``spec_id`` → ``SPEC_ID`` / ``XXspec_idXX``,
    # ``entity_registry_id`` → ``ENTITY_REGISTRY_ID`` / …) breaks the dict
    # equality even without a direct key read.
    spec = _normalized_spec()
    key, m = _match("sensor.hub_total_failed_pings", spec["id"])
    _new, ops, _ = dc.reconcile_declarative_tasks(
        spec,
        {key: m},
        tasks={},
        rendered_by_key=_rendered(key),
        config_entry_id=ENTRY,
        now=NOW,
    )
    created = ops[0][1]
    assert created["source"]["declarative_companion"] == {
        "spec_id": spec["id"],
        "entity_registry_id": m["entity_registry_id"],
        "entity_id": "sensor.hub_total_failed_pings",
    }
    assert created["managed_by"] == {
        "integration": "home_keeper",
        "display_name": spec["name"],
        "config_entry_id": ENTRY,
        "deletion_protected": True,
        "locked_fields": ["name", "recurrence_type", "device_id", "area_id", "sensor"],
        "completion_blocked": False,
    }


def test_reconcile_rerun_with_same_inputs_reports_no_change():
    # After a first pass creates the task, a second identical pass must
    # detect zero drift: the field loop's ``if task.get(field) != value``
    # gates ``task_changed``. Mutants that shift ``task_changed=False``
    # start-state to ``True`` (mutant 83) or ``None`` (82), or that mangle
    # the field-name key read (mutant 106), all flip this test red.
    spec = _normalized_spec()
    key, m = _match("sensor.hub_total_failed_pings", spec["id"])
    stored, _, _ = dc.reconcile_declarative_tasks(
        spec,
        {key: m},
        tasks={},
        rendered_by_key=_rendered(key),
        config_entry_id=ENTRY,
        now=NOW,
    )
    _new, ops, changed = dc.reconcile_declarative_tasks(
        spec,
        {key: m},
        tasks=stored,
        rendered_by_key=_rendered(key),
        config_entry_id=ENTRY,
        now=NOW,
    )
    assert changed is False
    assert ops == []


def test_reconcile_carries_through_unrelated_tasks():
    spec = _normalized_spec()
    unrelated = {
        "abc": {
            "id": "abc",
            "name": "Unrelated",
            "recurrence_type": "floating",
            "source": {"user": True},
        }
    }
    new_tasks, _ops, changed = dc.reconcile_declarative_tasks(
        spec,
        matches={},
        tasks=unrelated,
        rendered_by_key={},
        config_entry_id=ENTRY,
        now=NOW,
    )
    assert changed is False
    assert new_tasks == unrelated


def test_task_key_returns_none_when_only_spec_id_is_missing():
    # ``if not spec_id or not ent_reg_id: return None`` — a mutant that swaps
    # ``or`` for ``and`` returns the tuple when only one half is missing.
    task = {
        "source": {
            "declarative_companion": {
                "spec_id": "",
                "entity_registry_id": "reg_x",
                "entity_id": "sensor.x",
            }
        }
    }
    assert dc.task_key(task) is None


def test_task_key_returns_none_when_only_entity_registry_id_is_missing():
    task = {
        "source": {
            "declarative_companion": {
                "spec_id": "spec-1",
                "entity_registry_id": "",
                "entity_id": "sensor.x",
            }
        }
    }
    assert dc.task_key(task) is None


def test_collect_orphans_leaves_non_declarative_tasks_alone():
    # ``if key is not None and key[0] == removed_spec_id`` — a mutant that
    # swaps ``and`` for ``or`` deletes every task whose key check is None
    # (i.e. every non-declarative task), which is what this proves does not
    # happen.
    non_declarative = {
        "user-task": {
            "id": "user-task",
            "name": "Change bulb",
            "recurrence_type": "floating",
        }
    }
    new_tasks, ops = dc.collect_orphans_for_removed_spec(
        "some-spec-id", non_declarative
    )
    assert ops == []
    assert new_tasks == non_declarative


def test_collect_orphans_deletes_all_specs_tasks():
    spec = _normalized_spec()
    key, m = _match("sensor.hub_total_failed_pings", spec["id"])
    stored, _, _ = dc.reconcile_declarative_tasks(
        spec,
        {key: m},
        {},
        _rendered(key),
        config_entry_id=ENTRY,
        now=NOW,
    )
    new_tasks, ops = dc.collect_orphans_for_removed_spec(spec["id"], stored)
    assert len(ops) == 1
    assert ops[0][0] == "deleted"
    assert new_tasks == {}


# --- Presets ----------------------------------------------------------------


def test_every_preset_normalizes():
    """Every shipped preset default_spec must round-trip validation."""
    for preset in presets.CATALOG_PRESETS:
        spec = dc.normalize_declarative_companion(preset["default_spec"])
        assert spec["preset_id"] == preset["id"]
        assert spec["enabled"] is True


def test_preset_by_id_lookup():
    device_pulse = presets.preset_by_id("device_pulse")
    assert device_pulse is not None
    assert device_pulse["requires_integration"] == "device_pulse"
    assert presets.preset_by_id("nonexistent") is None


def test_device_pulse_preset_uses_threshold_mode():
    """Device Pulse rides on the existing threshold mode, not availability."""
    preset = presets.preset_by_id("device_pulse")
    assert preset["default_spec"]["trigger"]["mode"] == "threshold"


def test_firmware_has_no_integration_gate():
    assert (
        presets.preset_by_id("firmware_update_available")["requires_integration"]
        is None
    )
