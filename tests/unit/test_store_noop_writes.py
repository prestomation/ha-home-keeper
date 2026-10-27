"""An edit that changes no field writes nothing (#467 audit, S3 and R2).

Each save writes the whole storage document. An automation that sends the same
``update_task`` or ``update_asset`` on a schedule must not write the store, and must
not fire an event. The harness is ``test_store_consumable.py``'s: a fake ``Store``
and a fake ``hass``.
"""

from __future__ import annotations

from test_store_consumable import _asset, _run, _task, store  # noqa: F401

EVENT_TASK_UPDATED = "home_keeper_task_updated"
EVENT_ASSET_UPDATED = "home_keeper_asset_updated"


# ── S3: update_task ─────────────────────────────────────────────────────────────
def test_an_update_task_with_the_stored_values_does_not_save(store):  # noqa: F811
    task = _task(store, notes="Check the seal.")
    saves = store._store.saves

    result = _run(store.update_task(task["id"], {"notes": "Check the seal."}))

    assert store._store.saves == saves
    assert store._hass.bus.fired == []
    assert result == task
    assert store._tasks[task["id"]] == task


def test_an_empty_update_task_does_not_save(store):  # noqa: F811
    task = _task(store)
    saves = store._store.saves
    _run(store.update_task(task["id"], {}))
    assert store._store.saves == saves
    assert store._hass.bus.fired == []


def test_an_update_task_that_changes_a_field_saves_once(store):  # noqa: F811
    task = _task(store, notes="Check the seal.")
    saves = store._store.saves

    result = _run(store.update_task(task["id"], {"notes": "Check the hose."}))

    assert store._store.saves == saves + 1
    assert result["notes"] == "Check the hose."
    assert store._tasks[task["id"]]["notes"] == "Check the hose."
    [event] = store._hass.bus.of(EVENT_TASK_UPDATED)
    assert event["changed_fields"] == ["notes"]


def test_a_problem_note_that_is_not_mirrored_yet_still_saves(store):  # noqa: F811
    """The note mirror is part of the document, so a new mirror entry is a change."""
    task = _task(store, notes="Call the plumber.")
    task["source"] = {"problem_sensor": {"entity_id": "binary_sensor.leak"}}
    store._problem_notes.pop("binary_sensor.leak", None)
    saves = store._store.saves

    _run(store.update_task(task["id"], {"notes": "Call the plumber."}))

    assert store._problem_notes["binary_sensor.leak"] == "Call the plumber."
    assert store._store.saves == saves + 1
    assert store._hass.bus.fired == []


# ── R2: update_asset ────────────────────────────────────────────────────────────
def test_an_update_asset_with_the_stored_values_does_not_save(store):  # noqa: F811
    asset = _asset(store, notes="Noise notes")
    saves = store._store.saves

    result = _run(store.update_asset(asset["id"], {"notes": "Noise notes"}))

    assert store._store.saves == saves
    assert store._hass.bus.fired == []
    assert result == asset
    assert store._assets[asset["id"]] == asset


def test_an_update_asset_that_changes_a_field_saves_once(store):  # noqa: F811
    asset = _asset(store, notes="Noise notes")
    saves = store._store.saves

    result = _run(store.update_asset(asset["id"], {"notes": "New notes"}))

    assert store._store.saves == saves + 1
    assert result["notes"] == "New notes"
    [event] = store._hass.bus.of(EVENT_ASSET_UPDATED)
    assert event["changed_fields"] == ["notes"]
