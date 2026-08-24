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


def test_normalize_rejects_non_string_field_with_field_name_in_error():
    # ``_clean_str`` reports which field carried the non-string, so a bad
    # payload from the panel points to what to fix. The ``match=`` catches a
    # mutation that swaps the message body for ``None``.
    with pytest.raises(TaskValidationError, match="name must be a string"):
        dc.normalize_declarative_companion(_spec(name=42))


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


def test_low_battery_and_firmware_have_no_integration_gate():
    assert presets.preset_by_id("low_battery")["requires_integration"] is None
    assert (
        presets.preset_by_id("firmware_update_available")["requires_integration"]
        is None
    )
