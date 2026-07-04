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
    assert (
        task["next_due"]
        == r.compute_floating_next_due(anchor, 12, "months", now=NOW).isoformat()
    )


def test_creates_task_due_now_when_no_last_replaced():
    asset = _asset(parts=[_wear_part()])
    tasks, _ = _reconcile({"a1": asset})
    task = _only(tasks)
    # No recorded replacement → due now (not "assumed fresh" a full interval out).
    # An unknown replacement history is surfaced now; the user can backdate the
    # replacement or mark it done.
    assert task["last_completed"] is None
    assert task["next_due"] == NOW.isoformat()


def test_uses_appliance_fallback_when_asset_name_blank():
    asset = _asset(name="", parts=[_wear_part()])
    task = _only(_reconcile({"a1": asset})[0])
    # Default (English) fallback word; mirrors the panel's appliance.fallbackName.
    assert task["name"] == "Replace Anode (Appliance)"


# ── localized generated name (hass.config.language, resolved by the store) ─────
def test_localized_name_template_is_applied_on_create():
    # The store passes the language-resolved template + fallback in; the reconciler
    # formats the name with them (this is how a Polish household gets a Polish name).
    asset = _asset(parts=[_wear_part()])
    tasks, _ = rc.reconcile_part_tasks(
        {"a1": asset},
        {},
        name_template="Wymień {part} ({asset})",
        appliance_fallback="Urządzenie",
        now=NOW,
    )
    assert _only(tasks)["name"] == "Wymień Anode (Heater)"


def test_localized_appliance_fallback_is_applied_when_asset_name_blank():
    asset = _asset(name="", parts=[_wear_part()])
    tasks, _ = rc.reconcile_part_tasks(
        {"a1": asset},
        {},
        name_template="Wymień {part} ({asset})",
        appliance_fallback="Urządzenie",
        now=NOW,
    )
    assert _only(tasks)["name"] == "Wymień Anode (Urządzenie)"


def test_language_change_rewrites_generated_name_as_drift():
    # A task created in English is re-reconciled with a Polish template: the name
    # differs, so the existing drift branch updates it (this is what an entry reload
    # after a language change triggers — no bespoke migration needed).
    asset = _asset(parts=[_wear_part()])
    english, _ = _reconcile({"a1": asset})
    assert _only(english)["name"] == "Replace Anode (Heater)"
    tid = _only(english)["id"]
    polish, changed = rc.reconcile_part_tasks(
        {"a1": asset},
        english,
        name_template="Wymień {part} ({asset})",
        appliance_fallback="Urządzenie",
        now=NOW,
    )
    assert changed is True
    assert polish[tid]["name"] == "Wymień Anode (Heater)"


# ── what does NOT create a task ───────────────────────────────────────────────
def test_consumable_part_creates_no_task():
    asset = _asset(parts=[{"id": "p1", "name": "Filter", "type": "consumable"}])
    tasks, changed = _reconcile({"a1": asset})
    assert tasks == {} and changed is False


def test_wear_part_without_interval_creates_no_task():
    asset = _asset(
        parts=[{"id": "p1", "name": "Belt", "type": "wear", "replace_interval": None}]
    )
    tasks, changed = _reconcile({"a1": asset})
    assert tasks == {} and changed is False


def test_non_part_tasks_are_carried_through_untouched():
    standalone = {"id": "t9", "name": "Standalone", "source": None}
    tasks, changed = _reconcile({}, {"t9": standalone})
    assert changed is False
    assert tasks["t9"] is standalone


def test_malformed_part_source_does_not_crash_reconcile():
    # Regression: a task carrying a reserved-but-malformed part source (dict without
    # asset_id/part_id) must be ignored, not reach the bracket access that would raise
    # KeyError inside async_setup_entry and brick the entry on every restart.
    bad = {"id": "tbad", "name": "Bogus", "source": {"part": {"foo": 1}}}
    tasks, changed = _reconcile({}, {"tbad": bad})
    assert changed is False
    assert tasks["tbad"] is bad  # carried through untouched, no crash


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
    assert (
        _only(tasks)["next_due"]
        == r.compute_floating_next_due(anchor, 24, "months", now=NOW).isoformat()
    )


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


def test_updating_one_of_several_part_tasks_writes_to_the_right_task():
    # Regression: the update branch wrote ``result[tid]`` using a stale loop variable
    # left over from the orphan/index loops instead of ``existing_tid``. With two or
    # more part-tasks present, renaming a non-last one corrupted a *different* task's
    # slot (the rename landed on the wrong id, dropping a task entirely).
    a1 = _asset(aid="a1", name="Heater", parts=[_wear_part(pid="p1")])
    a2 = _asset(aid="a2", name="Boiler", parts=[_wear_part(pid="p2")])
    created, _ = _reconcile({"a1": a1, "a2": a2})
    assert len(created) == 2

    # Rename only the first asset; the second is untouched.
    a1_renamed = _asset(aid="a1", name="HeaterRENAMED", parts=[_wear_part(pid="p1")])
    tasks, changed = _reconcile({"a1": a1_renamed, "a2": a2}, created)

    assert changed is True
    # Both tasks survive, each still keyed to its own part, with names applied to the
    # correct task (no cross-contamination).
    by_asset = {t["source"]["part"]["asset_id"]: t for t in tasks.values()}
    assert set(by_asset) == {"a1", "a2"}
    assert by_asset["a1"]["name"] == "Replace Anode (HeaterRENAMED)"
    assert by_asset["a2"]["name"] == "Replace Anode (Boiler)"


# ── timezone healing vs. real completions ─────────────────────────────────────
def test_heals_legacy_naive_last_completed():
    # Simulate a task persisted by an older build: naive last_completed/next_due.
    created, _ = _reconcile(
        {"a1": _asset(parts=[_wear_part(last_replaced="2025-05-01")])}
    )
    task = _only(created)
    tid = task["id"]
    task["last_completed"] = "2025-05-01T00:00:00"  # naive (no tz)
    task["next_due"] = "2026-05-01T00:00:00"  # naive
    tasks, changed = _reconcile(
        {"a1": _asset(parts=[_wear_part(last_replaced="2025-05-01")])}, created
    )
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


# ── manual consumable links ───────────────────────────────────────────────────
def _manual_link_task(tid="m1", aid="a1", pid="p1"):
    """A user-owned task manually linked to a consumable (note ``manual: True``)."""
    return {
        "id": tid,
        "name": "Replace fridge filter",
        "recurrence_type": "sensor",
        "source": {"part": {"asset_id": aid, "part_id": pid, "manual": True}},
    }


def test_is_manual_part_link_discriminates():
    assert rc.is_manual_part_link(_manual_link_task()) is True
    # A reconciler-derived task (no manual flag) is not a manual link.
    derived = {"source": {"part": {"asset_id": "a1", "part_id": "p1"}}}
    assert rc.is_manual_part_link(derived) is False
    assert rc.is_manual_part_link({"source": None}) is False


def test_manual_link_is_not_orphan_deleted():
    # A manual link to a *consumable* (no wear cadence -> not in ``desired``) must
    # survive reconcile; the pre-fix bug deleted it as an orphan.
    asset = _asset(parts=[{"id": "p1", "name": "Filter", "type": "consumable"}])
    link = _manual_link_task()
    tasks, changed = _reconcile({"a1": asset}, {"m1": link})
    assert changed is False
    assert tasks["m1"] is link


def test_manual_link_is_not_updated_by_reconcile():
    # Even when the linked part IS a wear part with a cadence, the manual link is
    # left untouched (the reconciler owns only its own derived task, if any).
    asset = _asset(device_id="dev1", parts=[_wear_part(pid="p1", name="Anode")])
    link = _manual_link_task(pid="p1")
    tasks, changed = _reconcile({"a1": asset}, {"m1": dict(link)})
    # The manual link is carried through verbatim...
    assert tasks["m1"] == link
    # ...and a separate reconciler-derived task is created for the wear part.
    derived = [
        t for t in tasks.values() if rc.part_source(t) and not rc.is_manual_part_link(t)
    ]
    assert len(derived) == 1
    assert changed is True


def test_manual_link_cleared_when_part_removed():
    # The consumable the task is linked to is removed while the appliance survives →
    # the manual link is cleared (task lives on as a standalone task) rather than left
    # dangling to silently no-op on completion.
    asset = _asset(parts=[{"id": "p1", "name": "Filter", "type": "consumable"}])
    link = _manual_link_task(pid="p1")
    _reconcile({"a1": asset}, {"m1": dict(link)})  # part present → kept (sanity)
    empty = _asset(parts=[])
    tasks, changed = _reconcile({"a1": empty}, {"m1": link})
    assert changed is True
    assert tasks["m1"]["source"] is None
    # Idempotent: a second pass over the now-cleared task changes nothing.
    _again, changed2 = _reconcile({"a1": empty}, tasks)
    assert changed2 is False


def test_manual_link_cleared_when_whole_asset_gone():
    # The linked asset no longer exists at all (e.g. mid-reconcile) → link cleared.
    link = _manual_link_task(aid="ghost", pid="p1")
    tasks, changed = _reconcile({}, {"m1": link})
    assert changed is True
    assert tasks["m1"]["source"] is None


def test_qualify_iso():
    assert rc.qualify_iso("2025-05-01", TZ) == "2025-05-01T00:00:00-04:00"
    # Already-aware values are returned unchanged.
    assert (
        rc.qualify_iso("2025-05-01T12:00:00-04:00", TZ) == "2025-05-01T12:00:00-04:00"
    )
    assert rc.qualify_iso(None, TZ) is None
    assert rc.qualify_iso("", TZ) is None
    assert rc.qualify_iso("not-a-date", TZ) is None


# ── auto-buy tasks (reconcile_buy_tasks) ───────────────────────────────────────
def _consumable(
    pid="p1", name="Filter", stock=0, reorder_at=1, create_buy_task=True, **extra
):
    return {
        "id": pid,
        "name": name,
        "type": "consumable",
        "stock": stock,
        "reorder_at": reorder_at,
        "create_buy_task": create_buy_task,
        **extra,
    }


def _buy_reconcile(assets, tasks=None):
    return rc.reconcile_buy_tasks(assets, tasks or {}, now=NOW)


def test_creates_buy_task_when_low():
    asset = _asset(device_id="dev1", parts=[_consumable(stock=0, reorder_at=2)])
    tasks, changed = _buy_reconcile({"a1": asset})
    assert changed is True
    task = _only(tasks)
    assert task["name"] == "Buy Filter"
    assert task["recurrence_type"] == "one-off"
    assert task["device_id"] == "dev1"
    assert task["source"]["buy"] == {"asset_id": "a1", "part_id": "p1"}
    assert rc.buy_source(task) == {"asset_id": "a1", "part_id": "p1"}


def test_no_buy_task_when_not_low():
    asset = _asset(parts=[_consumable(stock=5, reorder_at=2)])
    tasks, changed = _buy_reconcile({"a1": asset})
    assert changed is False
    assert tasks == {}


def test_no_buy_task_when_option_off():
    asset = _asset(parts=[_consumable(stock=0, reorder_at=1, create_buy_task=False)])
    tasks, changed = _buy_reconcile({"a1": asset})
    assert changed is False
    assert tasks == {}


def test_no_buy_task_without_reorder_threshold():
    # Low is undefined without a reorder threshold, so nothing is desired.
    asset = _asset(parts=[_consumable(stock=0, reorder_at=None)])
    tasks, changed = _buy_reconcile({"a1": asset})
    assert changed is False
    assert tasks == {}


def test_removes_buy_task_when_restocked():
    asset = _asset(parts=[_consumable(stock=0, reorder_at=1)])
    tasks, _ = _buy_reconcile({"a1": asset})
    assert len(tasks) == 1
    # Restock above the threshold → the reminder is orphan-removed.
    asset["parts"][0]["stock"] = 5
    tasks2, changed = _buy_reconcile({"a1": asset}, tasks)
    assert changed is True
    assert tasks2 == {}


def test_idempotent_while_still_low():
    asset = _asset(parts=[_consumable(stock=0, reorder_at=1)])
    tasks, _ = _buy_reconcile({"a1": asset})
    # A second pass while still low creates no duplicate.
    tasks2, changed = _buy_reconcile({"a1": asset}, tasks)
    assert changed is False
    assert len(tasks2) == 1


def test_no_respawn_when_completed_task_present_and_still_low():
    asset = _asset(parts=[_consumable(stock=0, reorder_at=1)])
    tasks, _ = _buy_reconcile({"a1": asset})
    task = _only(tasks)
    # Simulate the user completing the reminder (still low, stock not yet updated):
    # a completed buy task still "occupies" the episode and blocks a duplicate.
    task["last_completed"] = NOW.isoformat()
    tasks2, changed = _buy_reconcile({"a1": asset}, {task["id"]: task})
    assert changed is False
    assert len(tasks2) == 1


def test_removes_buy_task_when_part_gone():
    asset = _asset(parts=[_consumable(stock=0, reorder_at=1)])
    tasks, _ = _buy_reconcile({"a1": asset})
    empty = _asset(parts=[])
    tasks2, changed = _buy_reconcile({"a1": empty}, tasks)
    assert changed is True
    assert tasks2 == {}


def test_buy_task_carries_area_from_asset():
    asset = _asset(area_id="garage", parts=[_consumable()])
    task = _only(_buy_reconcile({"a1": asset})[0])
    assert task["area_id"] == "garage"
