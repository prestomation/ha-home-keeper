"""The gate that keeps a newly added field travelling.

``transfer.py`` exports the fields it does *not* exclude, rather than a list of the
ones it does — so a field added to ``models.build_task`` or ``assets.build_asset``
rides along for free. This file is what makes that claim enforceable: build a maximal
record, send it out and back, and compare field for field. A field that fails to
survive shows up as a dict diff naming the key, with no enumeration to keep in step
and no source parsing to fool.

If you add a field and this goes red, the fix is one of two things: make it travel, or
name it in ``EXCLUDED_TASK_KEYS`` / ``EXCLUDED_ASSET_KEYS`` with a reason.
"""

from datetime import datetime, timedelta, timezone

import hk_transfer as tr

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)

AREA_NAMES = {"area_base": "Basement", "area_kitchen": "Kitchen"}
AREA_IDS = {"Basement": "area_base", "Kitchen": "area_kitchen"}


def _maximal_asset() -> dict:
    """An appliance with every optional field, every nested collection populated."""
    return {
        "name": "Furnace",
        "external_id": "centriq-4711",
        "kind": "virtual",
        "area_id": "area_base",
        "manufacturer": "Carrier",
        "model": "59TP6A",
        "serial_number": "1234-5678",
        "notes": "Installed by ABC Heating.",
        "icon": "mdi:fire",
        "cost": 4200.0,
        "metadata": [
            {
                "type": "date",
                "label": "Installed",
                "value": "2019-11-02",
                "track": True,
            },
            {"type": "link", "label": "Vendor", "value": "https://example.com"},
            {"type": "text", "label": "Breaker", "value": "Panel B, 14"},
        ],
        "documents": [
            {"kind": "link", "name": "Manual", "url": "https://example.com/m.pdf"}
        ],
        "parts": [
            {
                "name": "Filter",
                "part_number": "FILXXFCC0021",
                "type": "consumable",
                "vendor": "Acme",
                "cost": 24.5,
                "url": "https://example.com/filter",
                "notes": "MERV 13 only.",
                "replace_interval": 3,
                "replace_unit": "months",
                "last_replaced": "2026-03-04",
                "stock": 2.0,
                "reorder_at": 1.0,
                "stock_unit": "ea",
                "consume_quantity": 1.0,
                "create_buy_task": True,
                "restock_quantity": 4.0,
            }
        ],
        "related_device_ids": ["dev_thermostat"],
    }


def _maximal_task(**overrides) -> dict:
    """A task with every recurrence-independent field set."""
    task = {
        "name": "Replace furnace filter",
        "external_id": "furnace-filter",
        "notes": "MERV 13 only.",
        "recurrence_type": "floating",
        "interval": 3,
        "unit": "months",
        "area_id": "area_base",
        "enabled": True,
        "labels": ["label_hvac", "label_seasonal"],
        "card_links": [{"asset_id": "asset_1", "entry_id": "doc_1"}],
        "task_chips": [{"label": "HVAC", "icon": "mdi:fire"}],
        "tag_id": "tag_furnace",
        "require_tag_scan": False,
        "completion_detail": "optional",
        "completion_required_fields": [],
        "active_season": [{"start": "10-01", "end": "04-30"}],
    }
    task.update(overrides)
    return task


# Every recurrence type, so the schedule fields that only exist for one of them
# (``freq``/``anchor``, ``due``, ``sensor``) are all exercised.
_BY_TYPE = {
    "floating": {},
    "fixed": {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "MONTHLY",
        "anchor": "2026-01-15T09:00:00-04:00",
        "unit": None,
    },
    "one-off": {
        "recurrence_type": "one-off",
        "due": "2026-08-01T09:00:00-04:00",
        "interval": None,
        "unit": None,
        "active_season": None,
    },
    "triggered": {
        "recurrence_type": "triggered",
        "interval": None,
        "unit": None,
        "active_season": None,
    },
    "sensor": {
        "recurrence_type": "sensor",
        "interval": None,
        "unit": None,
        "active_season": None,
        "sensor": {
            "entity_id": "sensor.furnace_hours",
            "mode": "usage",
            "target": 1500.0,
            "unit": "h",
            "also_every": {"interval": 6, "unit": "months"},
            "combinator": "any",
        },
    },
}


def _built(spec: dict) -> dict:
    """One stored task, built the way the store builds it."""
    return tr.models.build_task(
        {k: v for k, v in _maximal_task(**spec).items() if v is not None}, now=NOW
    )


def _roundtrip(tasks: list[dict], assets: list[dict]) -> tr.ImportPlan:
    """Export then plan an import back onto an *empty* store."""
    document = tr.build_document(tasks, assets, area_names=AREA_NAMES, now=NOW)
    return tr.plan_import(
        document,
        tasks={},
        assets={},
        area_ids=AREA_IDS,
        # A fresh install: no devices yet, so a device id copied out of the document
        # must be re-resolved rather than trusted.
        device_ids=frozenset(),
        now=NOW,
    )


def _compare(before: dict, after: dict, excluded: tuple) -> None:
    """Every key that is not deliberately excluded came back unchanged."""
    drop = {key for key, _reason in excluded}
    expected = {k: v for k, v in before.items() if k not in drop}
    actual = {k: after.get(k) for k in expected}
    assert actual == expected


def test_every_recurrence_type_survives_the_round_trip():
    for rec_type, spec in _BY_TYPE.items():
        task = _built(spec)
        plan = _roundtrip([task], [])
        assert plan.ok, (rec_type, [p.as_dict() for p in plan.problems])
        (record,) = plan.records
        _compare(task, record.payload, tr.EXCLUDED_TASK_KEYS)


def test_an_appliance_survives_the_round_trip():
    asset = tr.assets_model.build_asset(_maximal_asset(), now=NOW)
    plan = _roundtrip([], [asset])
    assert plan.ok, [p.as_dict() for p in plan.problems]
    (record,) = plan.records
    _compare(asset, record.payload, tr.EXCLUDED_ASSET_KEYS)


def test_the_round_trip_keeps_the_ids_so_entities_survive_a_restore():
    # Entity unique_ids are anchored to the task/appliance id. A restore that minted
    # new ones would hand every task new entities and orphan every automation and
    # dashboard pointing at the old ones.
    task = _built({})
    asset = tr.assets_model.build_asset(_maximal_asset(), now=NOW)
    plan = _roundtrip([task], [asset])
    by_section = {r.section: r for r in plan.records}
    assert by_section["tasks"].record_id == task["id"]
    assert by_section["appliances"].record_id == asset["id"]


def test_history_and_skips_survive_the_round_trip():
    task = _built({})
    tr.recurrence.apply_completion(
        task,
        datetime(2025, 12, 1, 9, tzinfo=TZ),
        now=NOW,
        metadata={"note": "Old one", "cost": 19.0},
    )
    tr.recurrence.apply_completion(
        task,
        datetime(2026, 3, 4, 9, tzinfo=TZ),
        now=NOW,
        metadata={"note": "Used a MERV 13", "cost": 24.5, "who": "person.chris"},
    )
    tr.recurrence.record_skip(
        task, datetime(2026, 5, 1, 9, tzinfo=TZ), metadata={"note": "Away"}
    )
    plan = _roundtrip([task], [])
    (record,) = plan.records
    assert record.payload["completions"] == task["completions"]
    assert record.payload["skips"] == task["skips"]
    assert record.payload["last_completed"] == task["last_completed"]
    assert plan.completions == 2
    assert plan.skips == 1


def test_a_tasks_appliance_link_survives_the_round_trip():
    # The link is stored as a device id, which is meaningless on the other install —
    # so it travels as the appliance's own key and is re-resolved on the way in.
    asset = tr.assets_model.build_asset(_maximal_asset(), now=NOW)
    asset["device_id"] = "dev_furnace"
    task = _built({})
    task["device_id"] = "dev_furnace"

    document = tr.build_document([task], [asset], area_names=AREA_NAMES, now=NOW)
    assert document["tasks"][0]["appliance"] == "centriq-4711"

    plan = tr.plan_import(
        document,
        tasks={},
        assets={},
        area_ids=AREA_IDS,
        device_ids=frozenset(),
        now=NOW,
    )
    task_record = next(r for r in plan.records if r.section == "tasks")
    asset_record = next(r for r in plan.records if r.section == "appliances")
    # The appliance is only planned, so its device does not exist yet: the link is a
    # placeholder the applier resolves once provisioning has run.
    assert (
        tr.planned_asset_id(task_record.payload["device_id"]) == asset_record.record_id
    )


def test_areas_travel_by_name_so_the_file_reads_on_another_install():
    task = _built({})
    document = tr.build_document([task], [], area_names=AREA_NAMES, now=NOW)
    assert document["tasks"][0]["area"] == "Basement"
    # The id is authoritative when both are present...
    assert document["tasks"][0]["area_id"] == "area_base"
    # ...and stripping it out still resolves, which is what makes a hand-written or
    # generated file work.
    del document["tasks"][0]["area_id"]
    plan = tr.plan_import(document, tasks={}, assets={}, area_ids=AREA_IDS, now=NOW)
    assert plan.records[0].payload["area_id"] == "area_base"


def test_re_importing_an_export_updates_rather_than_duplicating():
    task = _built({})
    asset = tr.assets_model.build_asset(_maximal_asset(), now=NOW)
    document = tr.build_document([task], [asset], area_names=AREA_NAMES, now=NOW)
    plan = tr.plan_import(
        document,
        tasks={task["id"]: task},
        assets={asset["id"]: asset},
        area_ids=AREA_IDS,
        now=NOW,
    )
    assert plan.ok
    assert [r.action for r in plan.records] == ["update", "update"]
    assert {r.matched_by for r in plan.records} == {"id"}
