"""Unit tests for the pure wear-part → task reconciler (``reconcile.py``).

These exercise the create/anchor/heal/orphan/update branches directly, without a
Home Assistant runtime. The store wraps this with persistence (integration tests).
"""

from datetime import datetime, timedelta, timezone

import hk_reconcile as rc
import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _asset(aid="a1", name="Heater", parts=None, **extra):
    return {"id": aid, "name": name, "parts": parts or [], **extra}


def _wear_part(pid="p1", name="Anode", interval=12, unit="months", **extra):
    return {
        "id": pid,
        "name": name,
        "type": "wear",
        "replace_interval": interval,
        "replace_unit": unit,
        **extra,
    }


def _reconcile(assets, tasks=None):
    return rc.reconcile_part_tasks(assets, tasks or {}, now=NOW)


def _only(tasks):
    assert len(tasks) == 1, tasks
    return next(iter(tasks.values()))


# ── creation / anchoring ──────────────────────────────────────────────────────
def test_creates_task_anchored_on_last_replaced():
    asset = _asset(device_id="dev1", parts=[_wear_part(last_replaced="2025-05-01")])
    tasks, changed = _reconcile({"a1": asset})
    assert changed is True
    task = _only(tasks)
    assert task["name"] == "Replace Anode (Heater)"
    assert task["device_id"] == "dev1"
    assert task["source"]["part"] == {"asset_id": "a1", "part_id": "p1"}
    anchor = datetime.fromisoformat("2025-05-01").replace(tzinfo=TZ)
    assert task["last_completed"] == anchor.isoformat()
    assert task["next_due"] == r.compute_floating_next_due(
        anchor, 12, "months", now=NOW
    ).isoformat()


def test_creates_task_anchored_on_creation_when_no_last_replaced():
    asset = _asset(parts=[_wear_part()])
    tasks, _ = _reconcile({"a1": asset})
    task = _only(tasks)
    # No recorded replacement → "assumed fresh" at creation.
    assert task["last_completed"] == task["created"] == NOW.isoformat()
    assert task["next_due"] == r.compute_floating_next_due(NOW, 12, "months", now=NOW).isoformat()


def test_uses_appliance_fallback_when_asset_name_blank():
    asset = _asset(name="", parts=[_wear_part()])
    task = _only(_reconcile({"a1": asset})[0])
    assert task["name"] == "Replace Anode (appliance)"


# ── what does NOT create a task ───────────────────────────────────────────────
def test_consumable_part_creates_no_task():
    asset = _asset(parts=[{"id": "p1", "name": "Filter", "type": "consumable"}])
    tasks, changed = _reconcile({"a1": asset})
    assert tasks == {} and changed is False


def test_wear_part_without_interval_creates_no_task():
    asset = _asset(parts=[{"id": "p1", "name": "Belt", "type": "wear", "replace_interval": None}])
    tasks, changed = _reconcile({"a1": asset})
    assert tasks == {} and changed is False


def test_non_part_tasks_are_carried_through_untouched():
    standalone = {"id": "t9", "name": "Standalone", "source": None}
    tasks, changed = _reconcile({}, {"t9": standalone})
    assert changed is False
    assert tasks["t9"] is standalone


# ── idempotency ───────────────────────────────────────────────────────────────
def test_second_reconcile_is_idempotent():
    asset = _asset(device_id="dev1", parts=[_wear_part(last_replaced="2025-05-01")])
    first, _ = _reconcile({"a1": asset})
    second, changed = _reconcile({"a1": asset}, first)
    assert changed is False
    assert second == first


# ── orphan removal ────────────────────────────────────────────────────────────
def test_removes_task_when_part_disappears():
    asset = _asset(parts=[_wear_part()])
    created, _ = _reconcile({"a1": asset})
    # Part removed from the asset entirely.
    empty_asset = _asset(parts=[])
    tasks, changed = _reconcile({"a1": empty_asset}, created)
    assert changed is True and tasks == {}


def test_removes_task_when_wear_cadence_cleared():
    asset = _asset(parts=[_wear_part()])
    created, _ = _reconcile({"a1": asset})
    cleared = _asset(parts=[_wear_part(interval=None)])
    tasks, changed = _reconcile({"a1": cleared}, created)
    assert changed is True and tasks == {}


# ── updates ───────────────────────────────────────────────────────────────────
def test_renaming_asset_updates_task_name():
    created, _ = _reconcile({"a1": _asset(parts=[_wear_part()])})
    renamed = _asset(name="Boiler", parts=[_wear_part()])
    tasks, changed = _reconcile({"a1": renamed}, created)
    assert changed is True
    assert _only(tasks)["name"] == "Replace Anode (Boiler)"


def test_changing_interval_rebases_off_anchor_not_now():
    # A task anchored on last_replaced=2025-05-01; bumping 12→24 months should
    # extend from the anchor (2027-05-01), not restart from now.
    asset = _asset(parts=[_wear_part(interval=12, last_replaced="2025-05-01")])
    created, _ = _reconcile({"a1": asset})
    bumped = _asset(parts=[_wear_part(interval=24, last_replaced="2025-05-01")])
    tasks, changed = _reconcile({"a1": bumped}, created)
    assert changed is True
    anchor = datetime.fromisoformat("2025-05-01").replace(tzinfo=TZ)
    assert _only(tasks)["next_due"] == r.compute_floating_next_due(
        anchor, 24, "months", now=NOW
    ).isoformat()


def test_changing_device_id_updates_task():
    created, _ = _reconcile({"a1": _asset(device_id="dev1", parts=[_wear_part()])})
    moved = _asset(device_id="dev2", parts=[_wear_part()])
    tasks, changed = _reconcile({"a1": moved}, created)
    assert changed is True and _only(tasks)["device_id"] == "dev2"


def test_changing_area_id_updates_task():
    created, _ = _reconcile({"a1": _asset(area_id="area1", parts=[_wear_part()])})
    moved = _asset(area_id="area2", parts=[_wear_part()])
    tasks, changed = _reconcile({"a1": moved}, created)
    assert changed is True and _only(tasks)["area_id"] == "area2"


def test_changing_replace_unit_updates_task():
    created, _ = _reconcile({"a1": _asset(parts=[_wear_part(unit="months")])})
    changed_unit = _asset(parts=[_wear_part(unit="weeks")])
    tasks, changed = _reconcile({"a1": changed_unit}, created)
    assert changed is True and _only(tasks)["unit"] == "weeks"


# ── timezone healing vs. real completions ─────────────────────────────────────
def test_heals_legacy_naive_last_completed():
    # Simulate a task persisted by an older build: naive last_completed/next_due.
    created, _ = _reconcile({"a1": _asset(parts=[_wear_part(last_replaced="2025-05-01")])})
    task = _only(created)
    tid = task["id"]
    task["last_completed"] = "2025-05-01T00:00:00"  # naive (no tz)
    task["next_due"] = "2026-05-01T00:00:00"  # naive
    tasks, changed = _reconcile({"a1": _asset(parts=[_wear_part(last_replaced="2025-05-01")])}, created)
    assert changed is True
    healed = tasks[tid]
    assert healed["last_completed"].endswith("-04:00")  # now aware
    assert datetime.fromisoformat(healed["next_due"]).tzinfo is not None


def test_real_aware_completion_is_not_reverted():
    # A real completion (aware, later than the part's last_replaced anchor) must
    # survive reconcile untouched — the regression that prompted this extraction.
    asset = _asset(parts=[_wear_part(last_replaced="2025-05-01")])
    created, _ = _reconcile({"a1": asset})
    task = _only(created)
    tid = task["id"]
    completion = datetime(2026, 6, 1, 9, tzinfo=TZ).isoformat()
    task["last_completed"] = completion
    task["next_due"] = r.compute_floating_next_due(
        datetime(2026, 6, 1, 9, tzinfo=TZ), 12, "months", now=NOW
    ).isoformat()
    tasks, changed = _reconcile({"a1": asset}, created)
    assert changed is False
    assert tasks[tid]["last_completed"] == completion


# ── helpers ───────────────────────────────────────────────────────────────────
def test_part_source_extracts_provenance():
    assert rc.part_source({"source": {"part": {"asset_id": "a", "part_id": "p"}}}) == {
        "asset_id": "a",
        "part_id": "p",
    }
    assert rc.part_source({"source": None}) is None
    assert rc.part_source({}) is None
    assert rc.part_source({"source": {"part": "notadict"}}) is None


def test_qualify_iso():
    assert rc.qualify_iso("2025-05-01", TZ) == "2025-05-01T00:00:00-04:00"
    # Already-aware values are returned unchanged.
    assert rc.qualify_iso("2025-05-01T12:00:00-04:00", TZ) == "2025-05-01T12:00:00-04:00"
    assert rc.qualify_iso(None, TZ) is None
    assert rc.qualify_iso("", TZ) is None
    assert rc.qualify_iso("not-a-date", TZ) is None
