"""Which options changes reload the entry, and what a live change must do (#467).

A reload makes Home Assistant write ``unavailable`` for each Home Keeper entity, and
then the state again, so each reload puts many rows in the logbook. An options change
reloads only when it adds, removes or renames an entity. Every other change is applied
to the running entry. ``options.py`` decides which, so the rules are pure and the
mutation gate checks them.
"""

from __future__ import annotations

from typing import Any

import hk_const as const  # type: ignore[import-not-found]
import hk_options as opts  # type: ignore[import-not-found]
import pytest


def _doc(**updates: Any) -> dict[str, Any]:
    """A normalized options document with *updates* applied."""
    return opts._normalize(updates, opts._empty_options())


_P1 = {"id": "p1", "name": "Chores", "filter": {"status": "overdue"}}
_P2 = {"id": "p2", "name": "Garden", "filter": {"status": "all"}}


# ------------------------------------------------------------------ reload_needed


def test_the_same_options_need_no_reload() -> None:
    assert opts.reload_needed(_doc(), _doc()) is False


# Each option key, a changed value, and whether that change reloads the entry. Only
# the cost windows and the (id, name) of a profile name an entity. A new option fails
# ``test_every_option_key_has_a_reload_row`` until it has a row here.
_RELOAD_TABLE: dict[str, tuple[Any, bool]] = {
    const.OPTION_SYNC_PROBLEM_SENSORS: (True, False),
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: (["binary_sensor.a"], False),
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: (["dev1"], False),
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: (["kitchen"], False),
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS: (["lbl"], False),
    const.OPTION_ALLOW_SNOOZE: (False, False),
    const.OPTION_ALLOW_SKIP: (False, False),
    const.OPTION_ALLOW_DUE_TODAY: (False, False),
    const.OPTION_DUE_TIME_MODE: (const.DUE_TIME_MODE_SET_TIME, False),
    const.OPTION_DUE_TIME: ("09:30", False),
    const.OPTION_ONE_OFF_RETENTION_DAYS: (30, False),
    const.OPTION_SHOPPING_LIST_ENTITY: ("todo.shopping", False),
    const.OPTION_SHOPPING_LINE_STYLE: ("product_only", False),
    const.OPTION_COST_SUMMARY_PANEL: (False, False),
    const.OPTION_TASK_DEVICE_ENTITIES: (False, False),
    const.OPTION_DISMISSED_COMPANIONS: (["hue"], False),
    const.OPTION_HIDDEN_PANEL_TABS: (["spend"], False),
    const.OPTION_NOTIFICATIONS: (
        [{"id": "n1", "name": "Walk", "profile_id": None, "targets": []}],
        False,
    ),
    # 1 spend sensor for each window.
    const.OPTION_COST_WINDOWS: ([30, 60, 90], True),
    # 1 count sensor for each profile, with the profile name in its name.
    const.OPTION_PROFILES: ([_P1], True),
}


def test_every_option_key_has_a_reload_row() -> None:
    """A new option fails here until its row says if a change to it reloads."""
    assert set(_RELOAD_TABLE) == set(opts.ALL_OPTIONS)


@pytest.mark.parametrize(
    ("key", "value", "reloads"),
    [(key, value, reloads) for key, (value, reloads) in _RELOAD_TABLE.items()],
)
def test_a_change_of_each_option_reloads_as_the_table_says(
    key: str, value: Any, reloads: bool
) -> None:
    new = _doc(**{key: value})
    assert new != _doc()  # the value really changed
    assert opts.reload_needed(_doc(), new) is reloads
    assert opts.reload_needed(new, _doc()) is reloads


def test_cost_windows_in_another_order_do_not_reload() -> None:
    old = _doc(cost_windows=[30, 60])
    assert opts.reload_needed(old, _doc(cost_windows=[60, 30])) is False


def test_a_removed_profile_reloads() -> None:
    assert opts.reload_needed(_doc(profiles=[_P1, _P2]), _doc(profiles=[_P1])) is True


def test_a_renamed_profile_reloads() -> None:
    """The profile name is in the count sensor's name."""
    renamed = {**_P1, "name": "House"}
    assert opts.reload_needed(_doc(profiles=[_P1]), _doc(profiles=[renamed])) is True


def test_a_profile_filter_edit_does_not_reload() -> None:
    """The count sensor reads its filter live."""
    edited = {**_P1, "filter": {"status": "all"}}
    old, new = _doc(profiles=[_P1]), _doc(profiles=[edited])
    assert old != new
    assert opts.reload_needed(old, new) is False


def test_profiles_in_another_order_do_not_reload() -> None:
    old = _doc(profiles=[_P1, _P2])
    assert opts.reload_needed(old, _doc(profiles=[_P2, _P1])) is False


def test_the_entity_key_names_the_windows_and_the_profiles() -> None:
    key = opts.options_entity_key(_doc(cost_windows=[60, 30], profiles=[_P1, _P2]))
    assert key == (
        frozenset({30, 60}),
        frozenset({("p1", "Chores"), ("p2", "Garden")}),
    )


# ------------------------------------------------------------------ apply_steps


def test_no_change_has_no_steps() -> None:
    assert opts.apply_steps(_doc(), _doc()) == frozenset()


@pytest.mark.parametrize(
    ("key", "value", "step"),
    [
        (const.OPTION_SYNC_PROBLEM_SENSORS, True, opts.APPLY_PROBLEM_SYNC),
        (
            const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
            ["binary_sensor.a"],
            opts.APPLY_PROBLEM_SYNC,
        ),
        (const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES, ["d"], opts.APPLY_PROBLEM_SYNC),
        (const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS, ["a"], opts.APPLY_PROBLEM_SYNC),
        (const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS, ["l"], opts.APPLY_PROBLEM_SYNC),
        (const.OPTION_DUE_TIME_MODE, const.DUE_TIME_MODE_SET_TIME, opts.APPLY_DUE_TIME),
        (const.OPTION_DUE_TIME, "09:30", opts.APPLY_DUE_TIME),
        (const.OPTION_SHOPPING_LIST_ENTITY, "todo.shopping", opts.APPLY_SHOPPING),
        (const.OPTION_SHOPPING_LINE_STYLE, "product_only", opts.APPLY_SHOPPING),
        (const.OPTION_PROFILES, [_P1], opts.APPLY_TODO_LISTS),
        (const.OPTION_TASK_DEVICE_ENTITIES, False, opts.APPLY_TASK_ENTITIES),
        (
            const.OPTION_NOTIFICATIONS,
            [{"id": "n1", "name": "Walk", "profile_id": None, "targets": []}],
            opts.APPLY_NOTIFICATIONS,
        ),
    ],
)
def test_a_pushed_option_asks_for_its_step(key: str, value: Any, step: str) -> None:
    assert opts.apply_steps(_doc(), _doc(**{key: value})) == frozenset({step})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (const.OPTION_ALLOW_SNOOZE, False),
        (const.OPTION_ALLOW_SKIP, False),
        (const.OPTION_ALLOW_DUE_TODAY, False),
        (const.OPTION_ONE_OFF_RETENTION_DAYS, 30),
        (const.OPTION_COST_WINDOWS, [7]),
        (const.OPTION_COST_SUMMARY_PANEL, False),
        (const.OPTION_DISMISSED_COMPANIONS, ["hue"]),
        (const.OPTION_HIDDEN_PANEL_TABS, ["spend"]),
    ],
)
def test_an_option_read_live_asks_for_no_step(key: str, value: Any) -> None:
    """Its readers read ``entry.options`` each time, so the refresh is enough."""
    assert opts.apply_steps(_doc(), _doc(**{key: value})) == frozenset()


def test_steps_of_several_changes_are_joined() -> None:
    new = _doc(due_time="09:30", shopping_list_entity="todo.shopping")
    assert opts.apply_steps(_doc(), new) == frozenset(
        {opts.APPLY_DUE_TIME, opts.APPLY_SHOPPING}
    )


def test_every_option_key_is_classified() -> None:
    """A new option fails here until someone says how a change to it applies.

    An option that a reader reads only at setup, and that is in no step, would go
    stale after a live change: the entry no longer reloads to read it again.
    """
    assert set(opts._APPLY_STEPS) == set(opts.ALL_OPTIONS)
    known = {
        opts.APPLY_DUE_TIME,
        opts.APPLY_NOTIFICATIONS,
        opts.APPLY_PROBLEM_SYNC,
        opts.APPLY_SHOPPING,
        opts.APPLY_TODO_LISTS,
        opts.APPLY_TASK_ENTITIES,
    }
    for steps in opts._APPLY_STEPS.values():
        assert set(steps) <= known
