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

from datetime import datetime

import hk_transfer as tr
from transfer_records import (
    _BY_TYPE,
    AREA_IDS,
    AREA_NAMES,
    NOW,
    TZ,
    _maximal_asset,
    _maximal_task,
)


def _built(spec: dict) -> dict:
    """One stored task, built the way the store builds it."""
    return tr.models.build_task(
        {k: v for k, v in _maximal_task(**spec).items() if v is not None}, now=NOW
    )


def _roundtrip(tasks: list[dict], assets: list[dict]) -> tr.ImportPlan:
    """Export, **write the file, read it back**, then plan an import onto an empty
    store.

    Going through the text rather than the dict is the point. A field can survive
    ``build_document`` and still not survive being written and read — a value YAML
    resolves to a date, a bool or None on the way back is a lost field, and it would
    be invisible to a test that handed the mapping straight to ``plan_import``. So
    every assertion below covers the serializer as well as the exporter.
    """
    document = tr.build_document(tasks, assets, area_names=AREA_NAMES, now=NOW)
    return tr.plan_import(
        tr.document_to_yaml(document),
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
