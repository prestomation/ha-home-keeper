"""Who can complete or skip a ``completion_blocked`` task.

The integration that owns the task (``origin`` equal to ``managed_by.integration``)
and the 2 system origins can. A user, an automation with no origin, and a different
integration cannot. Home Keeper's own tasks accept only the system origins.

The harness is ``test_store_consumable.py``'s: a fake ``Store`` and a fake ``hass``.
"""

from __future__ import annotations

import pytest
from asserts import raises_exactly
from test_store_consumable import (  # noqa: F401
    TaskValidationError,
    _run,
    _task,
    store,
)

GLUE = "home_keeper_bambu_lab"
SENSOR_RECOVER = "home_keeper_sensor_recover"
PROBLEM_SYNC = "home_keeper_problem_sensor_sync"
REFUSAL = (
    "Home Keeper completes this task when the watched condition recovers, so it "
    "can't be marked done by hand."
)
EVENT_TASK_COMPLETED = "home_keeper_task_completed"
EVENT_TASK_SKIPPED = "home_keeper_task_skipped"


def _blocked(store, integration=GLUE):  # noqa: F811
    """An armed triggered task whose owner withholds Done."""
    return _task(
        store,
        name="Update firmware",
        interval=None,
        unit=None,
        recurrence_type="triggered",
        managed_by={
            "integration": integration,
            "display_name": "Bambu Lab",
            "completion_blocked": True,
        },
    )


def _complete(store, task_id, origin):  # noqa: F811
    return _run(store.complete_task(task_id, origin=origin))


def _skip(store, task_id, origin):  # noqa: F811
    return _run(store.skip_task(task_id, origin=origin))


@pytest.mark.parametrize("act", [_complete, _skip])
def test_the_owner_clears_its_own_blocked_task(store, act):  # noqa: F811
    task = _blocked(store)
    assert task["next_due"] is not None
    updated = act(store, task["id"], GLUE)
    assert updated["next_due"] is None


def test_the_owner_completion_is_recorded_with_its_origin(store):  # noqa: F811
    task = _blocked(store)
    _complete(store, task["id"], GLUE)
    assert len(store._tasks[task["id"]]["completions"]) == 1
    fired = store._hass.bus.of(EVENT_TASK_COMPLETED)
    assert [event["origin"] for event in fired] == [GLUE]


@pytest.mark.parametrize("act", [_complete, _skip])
@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "home_keeper_battery_notes",
        "home_keeper_bambu_lab_x",
        "home_keeper",
        "home_keeper_notification_action",
        "home_keeper_todo_sync",
    ],
)
def test_any_other_origin_is_refused(store, act, origin):  # noqa: F811
    task = _blocked(store)
    saves = store._store.saves
    with raises_exactly(TaskValidationError, REFUSAL):
        act(store, task["id"], origin)
    assert store._tasks[task["id"]]["next_due"] is not None
    assert store._store.saves == saves
    assert store._hass.bus.of(EVENT_TASK_COMPLETED) == []
    assert store._hass.bus.of(EVENT_TASK_SKIPPED) == []


@pytest.mark.parametrize("act", [_complete, _skip])
@pytest.mark.parametrize("origin", [SENSOR_RECOVER, PROBLEM_SYNC])
def test_the_system_origins_still_clear_a_blocked_task(store, act, origin):  # noqa: F811
    task = _blocked(store)
    assert act(store, task["id"], origin)["next_due"] is None


@pytest.mark.parametrize("act", [_complete, _skip])
def test_home_keeper_cannot_claim_its_own_blocked_task_as_owner(store, act):  # noqa: F811
    task = _blocked(store, integration="home_keeper")
    with raises_exactly(TaskValidationError, REFUSAL):
        act(store, task["id"], "home_keeper")
    assert act(store, task["id"], SENSOR_RECOVER)["next_due"] is None


@pytest.mark.parametrize("integration", [None, "", 7])
def test_a_block_with_no_owner_name_accepts_no_owner(store, integration):  # noqa: F811
    task = _task(store, recurrence_type="triggered", interval=None, unit=None)
    store._tasks[task["id"]]["managed_by"] = {
        "integration": integration,
        "completion_blocked": True,
    }
    for origin in (None, "", "7"):
        with raises_exactly(TaskValidationError, REFUSAL):
            _complete(store, task["id"], origin)
