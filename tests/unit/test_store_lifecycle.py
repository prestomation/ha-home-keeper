"""Store gates of the task life cycle, with the fake ``Store`` and ``hass``.

The harness is ``test_store_consumable.py``'s. The pure rules are in
``test_task_lifecycle_stateful.py`` and ``test_transitions_stateful.py``. This file
holds the sequences that need the store itself.
"""

from __future__ import annotations

import sys
import types
from datetime import timedelta

import hk_transitions as t
import pytest
from hk_const import EVENT_TASK_OVERDUE, EVENT_TASK_TRIGGERED
from test_store_consumable import NOW, _run, store, store_mod  # noqa: F401


def _clock(when):
    store_mod.dt_util = types.SimpleNamespace(
        **{**vars(store_mod.dt_util), "now": lambda: when}
    )


@pytest.fixture
def clock():
    prior = store_mod.dt_util
    yield _clock
    store_mod.dt_util = prior


def _triggered(store):  # noqa: F811
    models = sys.modules["hk.models"]
    task = models.build_task(
        {"name": "Filter", "recurrence_type": "triggered"}, now=NOW
    )
    store._tasks[task["id"]] = task
    return task


def test_a_second_trigger_keeps_the_due_date_and_announces_no_overdue(store, clock):  # noqa: F811
    task = _triggered(store)
    tasks = store._tasks

    _run(store.trigger_task(task["id"]))
    armed_at = tasks[task["id"]]["next_due"]
    fired, state = t.detect_transitions({}, tasks, now=NOW + timedelta(hours=1))
    assert [name for name, _ in fired] == [EVENT_TASK_OVERDUE]

    clock(NOW + timedelta(hours=2))
    _run(store.trigger_task(task["id"]))
    fired, _ = t.detect_transitions(state, tasks, now=NOW + timedelta(hours=2))

    assert tasks[task["id"]]["next_due"] == armed_at
    assert fired == []
    # The owner still sees each trigger on the bus.
    assert len(store._hass.bus.of(EVENT_TASK_TRIGGERED)) == 2
